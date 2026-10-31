#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_context.py: how much carrying context costs you in Claude Code.

Reads the local Claude Code transcripts (~/.claude/projects/**/*.jsonl), read-only, and
works out: how much of your usage is re-reading old context, how much the high-context
turns weigh, what reopening a session after a long pause costs, and when you compact.

It never prints or stores the text of any conversation. Session titles only appear with
--titles; by default each session is identified by the first 8 characters of its id.

Usage:
    python measure_context.py                      # last 7 days
    python measure_context.py --days 14 --top 20
    python measure_context.py --until 2026-10-31T12:00:00Z --json out.json
    python measure_context.py --prices my_prices.json

(The old Spanish flags --dias, --hasta, --titulos and --precios still work.)

Definitions:
    turn      one API call (one assistant message, deduplicated by message.id)
    context   input_tokens + cache_creation + cache_read of that call (what the model "sees")
    cost      API list-price equivalent, in USD. It is NOT your bill or your subscription
              quota: use it as a relative measure of load (what weighs more than what).
    carry     cache reads + rewriting of old context (cache expired or invalidated)

Requires Python 3.9 or newer. No external dependencies.
"""
import argparse
import glob
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ----------------------------------------------------------------------------------------------
# List prices (USD per million tokens): (input, output, cache read).
# Source: the Claude API pricing documentation, checked on 2026-10-31
# (https://platform.claude.com/docs/en/about-claude/pricing). Check them before trusting the
# dollar amounts, and override them with --prices if they change. Entries marked "assumed" have
# no published cache-read price in that source: the read price is assumed to be 0.1x the input.
# Cache write: 1.25x the input price (5 min) and 2x (1 h).
# ----------------------------------------------------------------------------------------------
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),        # read price assumed
    "claude-opus-4-8": (5.0, 25.0, 0.50),      # read price assumed
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),    # tier up to 100k; read price assumed
}
DEFAULT_PRICE = PRICES["claude-opus-5-5"]
W5, W1 = 1.25, 2.0

BANDS = [(0, 50e3, "0-50k"), (50e3, 100e3, "50-100k"), (100e3, 200e3, "100-200k"),
         (200e3, 300e3, "200-300k"), (300e3, 400e3, "300-400k"), (400e3, 600e3, "400-600k"),
         (600e3, float("inf"), ">600k")]
GAPS = [("<5 min", 0, 300), ("5-60 min", 300, 3600), (">60 min", 3600, float("inf"))]


def price(model):
    return PRICES.get(model, DEFAULT_PRICE)


def cost_parts(t):
    """Cost of one turn in four parts: input, cache write, cache read, output."""
    p_in, p_out, p_read = price(t["model"])
    return (t["in"] * p_in / 1e6,
            (t["cw5"] * W5 + t["cw1"] * W1) * p_in / 1e6,
            t["cr"] * p_read / 1e6,
            t["out"] * p_out / 1e6)


def to_epoch(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def band(ctx):
    for lo, hi, name in BANDS:
        if lo <= ctx < hi:
            return name
    return BANDS[-1][2]


# ----------------------------------------------------------------------------------------------
# 1. Reading
# ----------------------------------------------------------------------------------------------
def read_file(path):
    """Turns (deduplicated within the file), compactions and title of one .jsonl file."""
    parts = path.replace("\\", "/").split("/")
    is_sub = "subagents" in parts
    parent = parts[parts.index("subagents") - 1] if is_sub else None
    key = os.path.basename(path)[:-len(".jsonl")]
    turns, by_id, compactions = [], {}, []
    title, pending_compact = None, None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if '"type":"assistant"' in line:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                m = d.get("message") or {}
                u = m.get("usage") if isinstance(m, dict) else None
                if d.get("type") != "assistant" or not u or m.get("model") == "<synthetic>":
                    continue
                ts = to_epoch(d.get("timestamp", ""))
                if ts is None:
                    continue
                mid = m.get("id") or d.get("uuid")
                cwt = u.get("cache_creation_input_tokens", 0) or 0
                cw1 = min((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0) or 0, cwt)
                data = {"in": u.get("input_tokens", 0) or 0, "cw5": cwt - cw1, "cw1": cw1,
                        "cr": u.get("cache_read_input_tokens", 0) or 0,
                        "out": u.get("output_tokens", 0) or 0}
                t = by_id.get(mid)
                if t is None:
                    t = {"id": mid, "model": m.get("model") or "?", "t0": ts, "t1": ts,
                         "after_compact": pending_compact is not None, **data}
                    pending_compact = None
                    by_id[mid] = t
                    turns.append(t)
                else:
                    # The same message can arrive on several lines (streaming): keep the maximum
                    t["t1"] = max(t["t1"], ts)
                    for field, value in data.items():
                        t[field] = max(t[field], value)
            elif '"subtype":"compact_boundary"' in line:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("subtype") != "compact_boundary":
                    continue
                cm = d.get("compactMetadata") or {}
                c = {"uuid": d.get("uuid"), "t": to_epoch(d.get("timestamp", "")),
                     "trigger": cm.get("trigger") or "?", "before": cm.get("preTokens"),
                     "summary": cm.get("postTokens"), "after": None}
                compactions.append(c)
                pending_compact = c
            elif line.startswith('{"type":"custom-title"'):
                try:
                    title = json.loads(line).get("customTitle") or title
                except Exception:
                    pass
            elif title is None and line.startswith('{"type":"agent-name"'):
                try:
                    title = json.loads(line).get("agentName") or title
                except Exception:
                    pass
    # Context after each compaction: that of the first turn that follows it
    for c in compactions:
        if c["t"] is None:
            continue
        following = next((t for t in turns if t["t0"] >= c["t"]), None)
        if following is not None:
            c["after"] = following["in"] + following["cw5"] + following["cw1"] + following["cr"]
    return {"path": path, "key": key, "is_sub": is_sub, "parent": parent, "title": title,
            "turns": turns, "compactions": compactions,
            "t_start": turns[0]["t0"] if turns else None}


def load(base, w0):
    files = []
    for f in glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(f) >= w0:
                files.append(f)
        except OSError:
            continue
    print(f"Reading {len(files)} .jsonl files with activity in the window...", file=sys.stderr)
    return [read_file(f) for f in files]


def prepare(data, w0, w1):
    """Drop duplicates across files (forked sessions copy history) and mark the window."""
    data.sort(key=lambda d: (d["t_start"] or float("inf"), d["path"]))
    seen, seen_compactions = set(), set()
    for d in data:
        d["turns"] = [t for t in d["turns"] if t["in"] + t["cw5"] + t["cw1"] + t["cr"] > 0]
        for t in d["turns"]:
            t["ctx"] = t["in"] + t["cw5"] + t["cw1"] + t["cr"]
            t["counts"] = t["id"] not in seen and w0 <= t["t0"] <= w1
            seen.add(t["id"])
        comp = []
        for c in d["compactions"]:
            if c["uuid"] in seen_compactions:
                continue
            seen_compactions.add(c["uuid"])
            if c["t"] is not None and w0 <= c["t"] <= w1:
                comp.append(c)
        d["window_compactions"] = comp
    return data


# ----------------------------------------------------------------------------------------------
# 2. Metrics
# ----------------------------------------------------------------------------------------------
def rewrite(t, prev):
    """Fraction of a turn's new context that is really old context written again
    (the cache had expired or was invalidated). 0 if the turn follows a compaction."""
    if prev is None or t["after_compact"] or t["ctx"] < 0.7 * prev["ctx"]:
        return 0, 0
    new = t["in"] + t["cw5"] + t["cw1"]
    growth = max(t["ctx"] - prev["ctx"], 0)
    extra = max(new - growth, 0)
    return extra, (extra / new if new else 0)


def measure(data):
    total = {"output": 0.0, "new": 0.0, "rewrite": 0.0, "read": 0.0}
    tokens = {"in": 0, "cw": 0, "cr": 0, "out": 0}
    by_band = {n: {"turns": 0, "cost": 0.0, "carry": 0.0} for _, _, n in BANDS}
    gaps = {n: {"turns": 0, "misses": 0, "tokens": 0, "extra_cost": 0.0} for n, _, _ in GAPS}
    sessions = defaultdict(lambda: {"turns": 0, "cost": 0.0, "sub_cost": 0.0, "ctx": [],
                                    "compact": 0, "title": None})
    contexts, turn_costs = [], []
    n_main = n_sub = 0
    compactions = []
    # The same split for the main threads alone: compacting acts there, subagents are not touched
    total_main = {"output": 0.0, "new": 0.0, "rewrite": 0.0, "read": 0.0}
    contexts_main, out_main = [], 0
    by_model = defaultdict(float)

    for d in data:
        key = d["parent"] if d["is_sub"] else d["key"]
        s = sessions[key]
        if not d["is_sub"]:
            s["title"] = d["title"] or s["title"]
            s["compact"] += len(d["window_compactions"])
            compactions.extend(d["window_compactions"])
        prev = None
        for t in d["turns"]:
            if t["counts"]:
                c_in, c_write, c_read, c_out = cost_parts(t)
                extra, frac = rewrite(t, prev)
                cost = c_in + c_write + c_read + c_out
                total["output"] += c_out
                total["read"] += c_read
                total["rewrite"] += (c_in + c_write) * frac
                total["new"] += (c_in + c_write) * (1 - frac)
                tokens["in"] += t["in"]; tokens["cw"] += t["cw5"] + t["cw1"]
                tokens["cr"] += t["cr"]; tokens["out"] += t["out"]
                b = by_band[band(t["ctx"])]
                b["turns"] += 1
                b["cost"] += cost
                b["carry"] += c_read + (c_in + c_write) * frac
                contexts.append(t["ctx"])
                turn_costs.append((t["ctx"], cost))
                by_model[t["model"]] += cost
                if d["is_sub"]:
                    n_sub += 1
                    s["sub_cost"] += cost
                else:
                    n_main += 1
                    s["turns"] += 1
                    s["cost"] += cost
                    s["ctx"].append(t["ctx"])
                    total_main["output"] += c_out
                    total_main["read"] += c_read
                    total_main["rewrite"] += (c_in + c_write) * frac
                    total_main["new"] += (c_in + c_write) * (1 - frac)
                    contexts_main.append(t["ctx"])
                    out_main += t["out"]
                # Cache misses by the pause since the previous turn
                if prev is not None and not t["after_compact"] and t["ctx"] >= 0.7 * prev["ctx"]:
                    prev_context = t["ctx"] - max(t["ctx"] - prev["ctx"], 0)
                    if prev_context >= 100e3:
                        pause = t["t0"] - prev["t1"]
                        name = next(n for n, lo, hi in GAPS if lo <= pause < hi)
                        h = gaps[name]
                        h["turns"] += 1
                        if extra > 0.2 * prev_context and extra > 20e3:
                            p_in, _, p_read = price(t["model"])
                            cwt = t["cw5"] + t["cw1"]
                            mult = (t["cw5"] * W5 + t["cw1"] * W1) / cwt if cwt else W1
                            h["misses"] += 1
                            h["tokens"] += extra
                            h["extra_cost"] += extra * (p_in * mult - p_read) / 1e6
            prev = t
    return {"total": total, "tokens": tokens, "by_band": by_band, "gaps": gaps,
            "sessions": sessions, "contexts": contexts, "turn_costs": turn_costs,
            "n_main": n_main, "n_sub": n_sub, "compactions": compactions,
            "total_main": total_main, "contexts_main": contexts_main, "out_main": out_main,
            "by_model": dict(by_model)}


# ----------------------------------------------------------------------------------------------
# 2b. Before and after: two windows side by side
# ----------------------------------------------------------------------------------------------
def read_mod_log(paths, w0, w1):
    """Compactions the mod logged in [w0, w1): by trigger, with the context before and after.
    Reads the public log (time, context_before, context_after, trigger) and the older Spanish
    one (fecha, contexto_antes, contexto_despues, disparador)."""
    rows = []
    for path in paths or []:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        j = json.loads(line)
                    except Exception:
                        continue
                    t = to_epoch(j.get("time") or j.get("fecha") or "")
                    if t is None or not (w0 <= t < w1):
                        continue
                    trig = j.get("trigger") or j.get("disparador") or "?"
                    trig = {"fin_de_tarea": "task_done"}.get(trig, trig)
                    rows.append({"trigger": trig, "t": t,
                                 "session_id": j.get("session_id") or j.get("id_sesion") or "",
                                 "before": j.get("context_before", j.get("contexto_antes")),
                                 "after": j.get("context_after", j.get("contexto_despues"))})
        except OSError:
            print(f"Mod log not found: {path}", file=sys.stderr)
    return rows


def avoided_by_mod(data, rows, w0, w1, window_cap=950_000):
    """A direct estimate of what the mod's own compactions saved, from the week they happened in.

    For each compaction in the mod's log, find it in its session's transcript: the context before
    it, and the context on the turn after. Every later turn of that session (until its next
    compaction or the end of the window) would have re-read that difference from the cache. Stop
    counting once the counterfactual context passes 95% of a 1M window, where Claude Code's own
    auto-compact would have fired anyway. Then take off the compaction's own request.

    It is a lower bound for the carrying it removed (it ignores the larger cache rewrites after long
    pauses) and assumes the session would have gone on the same way. It cannot see a session you
    would have closed by hand instead."""
    by_key = {d["key"]: d for d in data if not d["is_sub"]}
    p_in, p_out, p_read = DEFAULT_PRICE
    found, avoided, turns, req_lo, req_hi, dropped = 0, 0.0, 0, 0.0, 0.0, []
    for row in rows:
        d = by_key.get(row["session_id"])
        if d is None:
            continue
        near = [c for c in d["compactions"] if c["t"] is not None and abs(c["t"] - row["t"]) <= 300]
        if not near:
            continue
        c = min(near, key=lambda x: abs(x["t"] - row["t"]))
        before, after = c["before"] or row["before"], c["after"] or row["after"]
        if not before or not after or before <= after:
            continue
        delta = before - after
        found += 1
        dropped.append(delta)
        nxt = min([x["t"] for x in d["compactions"] if x["t"] is not None and x["t"] > c["t"]] + [w1])
        for t in d["turns"]:
            if t["t0"] <= c["t"] or t["t0"] >= nxt or t["t0"] < w0:
                continue
            if t["ctx"] + delta > window_cap:
                break
            avoided += delta * price(t["model"])[2] / 1e6
            turns += 1
        req_lo += (before * p_read + (c["summary"] or 0) * p_out) / 1e6
        req_hi += (before * p_in * W1 + (c["summary"] or 0) * p_out) / 1e6
    return {"mod_compactions_matched": found, "avoided_carry": avoided, "later_turns": turns,
            "requests_low": req_lo, "requests_high": req_hi,
            "net_low": avoided - req_hi, "net_high": avoided - req_lo,
            "avg_dropped": statistics.mean(dropped) if dropped else 0}


def summarize(r, w0, w1, log_rows, avoided=None):
    """The figures that say whether carrying context got cheaper, for one window."""
    days = (w1 - w0) / 86400
    tot, tm = r["total"], r["total_main"]
    cost, cost_m = sum(tot.values()), sum(tm.values())
    ctx, ctx_m = r["contexts"], r["contexts_main"]
    comp = r["compactions"]
    p_in, p_out, p_read = DEFAULT_PRICE
    # A compaction's own request is not in the transcripts: estimate it from its size. Low: the
    # conversation read from the cache. High: written again at the 1 h price. Plus the summary as output.
    over_lo = sum(((c["before"] or 0) * p_read + (c["summary"] or 0) * p_out) / 1e6 for c in comp)
    over_hi = sum(((c["before"] or 0) * p_in * W1 + (c["summary"] or 0) * p_out) / 1e6 for c in comp)
    share = lambda part, whole: 100 * part / whole if whole else 0.0  # noqa: E731
    triggers = defaultdict(int)
    for c in comp:
        triggers[c["trigger"]] += 1
    mod_triggers = defaultdict(int)
    for row in log_rows:
        mod_triggers[row["trigger"]] += 1
    befores = [c["before"] for c in comp if c["before"]]
    afters = [c["after"] for c in comp if c["after"]]
    top_models = sorted(r["by_model"].items(), key=lambda kv: -kv[1])[:4]
    return {
        "days": days,
        "turns_main": r["n_main"], "turns_sub": r["n_sub"],
        "turns_main_per_day": r["n_main"] / days if days else 0,
        "cost": cost, "cost_per_day": cost / days if days else 0,
        "cost_main": cost_m, "cost_main_per_day": cost_m / days if days else 0,
        "carry_pct": share(tot["read"] + tot["rewrite"], cost),
        "reads_pct": share(tot["read"], cost), "rewrites_pct": share(tot["rewrite"], cost),
        "output_pct": share(tot["output"], cost), "new_pct": share(tot["new"], cost),
        "carry_main_pct": share(tm["read"] + tm["rewrite"], cost_m),
        "ctx_median": statistics.median(ctx) if ctx else 0, "ctx_mean": statistics.mean(ctx) if ctx else 0,
        "ctx_main_median": statistics.median(ctx_m) if ctx_m else 0,
        "ctx_main_mean": statistics.mean(ctx_m) if ctx_m else 0,
        "main_over_200k_pct": share(sum(1 for x in ctx_m if x > 200e3), len(ctx_m)),
        "main_over_400k_pct": share(sum(1 for x in ctx_m if x > 400e3), len(ctx_m)),
        "cost_per_main_turn": cost_m / r["n_main"] if r["n_main"] else 0,
        "cost_main_per_1k_output": cost_m / (r["out_main"] / 1e3) if r["out_main"] else 0,
        "context_read_per_output_main": (sum(ctx_m) / r["out_main"]) if r["out_main"] else 0,
        "compactions": len(comp), "compactions_per_day": len(comp) / days if days else 0,
        "compactions_by_trigger": dict(triggers),
        "compact_before_avg": statistics.mean(befores) if befores else 0,
        "compact_first_turn_after_avg": statistics.mean(afters) if afters else 0,
        "compaction_requests_cost_low": over_lo, "compaction_requests_cost_high": over_hi,
        "mod_compactions": len(log_rows), "mod_compactions_by_trigger": dict(mod_triggers),
        "reopen_over_60min_pct": share(r["gaps"][">60 min"]["extra_cost"], cost),
        "top_models": [(m, share(c, cost)) for m, c in top_models],
        "mod_effect": avoided,
    }


def compare_report(a, b, wa, wb):
    """Markdown: the two windows side by side, and what can and cannot be read from them."""
    fmt_t = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    rows = [
        ("Days in the window", "days", "{:.2f}", False),
        ("Main-thread turns per day", "turns_main_per_day", "{:.0f}", False),
        ("Equivalent cost per day, all", "cost_per_day", "${:,.2f}", True),
        ("Equivalent cost per day, main threads", "cost_main_per_day", "${:,.2f}", True),
        ("Carrying context, share of cost (all)", "carry_pct", "{:.1f}%", True),
        ("Carrying context, share of cost (main threads)", "carry_main_pct", "{:.1f}%", True),
        ("  cache reads", "reads_pct", "{:.1f}%", True),
        ("  rewrites of old context", "rewrites_pct", "{:.1f}%", True),
        ("Median context per main-thread turn", "ctx_main_median", "{:,.0f}", True),
        ("Mean context per main-thread turn", "ctx_main_mean", "{:,.0f}", True),
        ("Main-thread turns above 200k", "main_over_200k_pct", "{:.1f}%", True),
        ("Main-thread turns above 400k", "main_over_400k_pct", "{:.1f}%", True),
        ("Cost per main-thread turn", "cost_per_main_turn", "${:.4f}", True),
        ("Main-thread cost per 1k output tokens", "cost_main_per_1k_output", "${:.3f}", True),
        ("Context read per output token (main)", "context_read_per_output_main", "{:,.0f}", True),
        ("Compactions per day", "compactions_per_day", "{:.1f}", False),
        ("Average context when compacting", "compact_before_avg", "{:,.0f}", False),
        ("Average context on the turn after", "compact_first_turn_after_avg", "{:,.0f}", False),
        ("Reopening after >60 min, share of cost", "reopen_over_60min_pct", "{:.1f}%", True),
    ]
    out = ["# Before and after: context cost in Claude Code\n",
           f"Before: {fmt_t(wa[0])} to {fmt_t(wa[1])} UTC. After: {fmt_t(wb[0])} to {fmt_t(wb[1])} UTC.\n",
           "| Figure | Before | After | Change |", "|---|---:|---:|---:|"]
    for label, key, f, rel in rows:
        va, vb = a[key], b[key]
        if rel and va:
            change = f"{100 * (vb - va) / va:+.0f}%" if not f.endswith("%") else f"{vb - va:+.1f} pts"
        else:
            change = ""
        out.append(f"| {label} | {f.format(va)} | {f.format(vb)} | {change} |")
    out.append("")
    for name, s in (("Before", a), ("After", b)):
        trig = ", ".join(f"{k} {v}" for k, v in sorted(s["compactions_by_trigger"].items())) or "none"
        mod = ", ".join(f"{k} {v}" for k, v in sorted(s["mod_compactions_by_trigger"].items())) or "none in the log"
        models = ", ".join(f"{m} {p:.0f}%" for m, p in s["top_models"])
        out.append(f"- **{name}:** {s['compactions']} compactions in the transcripts ({trig}); "
                   f"the mod's log: {mod}. Their own requests, estimated: "
                   f"${s['compaction_requests_cost_low']:,.2f} to ${s['compaction_requests_cost_high']:,.2f}. "
                   f"Cost by model: {models}.")
    m = b.get("mod_effect")
    if m and m["mod_compactions_matched"]:
        cm = b["cost_main"] or 1
        out.append("")
        out.append("## What the mod's own compactions saved (direct estimate)\n")
        out.append(f"{m['mod_compactions_matched']} compactions from the mod's log were found in the transcripts. "
                   f"Each dropped {m['avg_dropped']:,.0f} tokens on average. The {m['later_turns']} later turns of those "
                   f"sessions would have re-read that from the cache: **${m['avoided_carry']:,.2f}** at list price. "
                   f"The compaction requests themselves: ${m['requests_low']:,.2f} to ${m['requests_high']:,.2f}. "
                   f"Net: **${m['net_low']:,.2f} to ${m['net_high']:,.2f}**, that is "
                   f"{100 * m['net_low'] / cm:.1f}% to {100 * m['net_high'] / cm:.1f}% of the main threads' cost in the window.")
        out.append("")
        out.append("It is a lower bound on the carrying removed (it leaves out the larger cache rewrites after long "
                   "pauses) and it assumes each session would have gone on the same way. It stops counting where "
                   "Claude Code's own auto-compact would have fired.")
    elif b["mod_compactions"] == 0:
        out.append("")
        out.append("No compactions from the mod's log fall in the after window (pass the log with --log).")
    out.append("")
    out.append("How to read it:")
    out.append("- The figure that answers \"does it save usage\" is the share of cost spent carrying context, and the "
               "cost per 1k output tokens of the main threads (it divides out how much work there was). Per-day totals "
               "move with how much you worked, so on their own they say little.")
    out.append("- Subagents are not compacted by the mod: the main-thread rows are where a change should show.")
    out.append("- A compaction's own request is not in the transcripts. The estimate above is a range, from reading "
               "the conversation from the cache to writing it again at the 1 h price.")
    out.append("- Two different weeks are not a controlled test: different tasks, models and hours. Read a change "
               "of a few points as noise, and a large one as a hint, not a proof.")
    out.append("- Amounts are API list-price equivalents, not a bill or a subscription quota.")
    return "\n".join(out)


def figures_for_chart(a, b):
    """The JSON that assets/make_assets.py --figures reads for before-after.svg. The first bar is the
    week before; the saving is the direct estimate for the mod's own compactions, not week against
    week (two weeks of different work differ by more than any plugin)."""
    r = lambda x: int(round(x))  # noqa: E731
    m = b.get("mod_effect") or {}
    cm = b["cost_main"] or 1
    return {
        "mode": "measured",
        "before": {"carry": r(a["carry_pct"]), "reads": r(a["reads_pct"]), "rewrites": r(a["rewrites_pct"]),
                   "output": r(a["output_pct"]), "new": r(a["new_pct"])},
        "saving_low": max(r(100 * m.get("net_low", 0) / cm), 0),
        "saving_high": max(r(100 * m.get("net_high", 0) / cm), 0),
        "mod_compactions": m.get("mod_compactions_matched", 0),
        "days": r(b["days"]),
        "note1": "Token cost at API list prices, one user. First bar: the week before. Second: the week with the plugin,",
        "note2": "estimated from its own compactions (what later turns no longer re-read, minus the compactions). docs/MEASUREMENT.md.",
    }


# ----------------------------------------------------------------------------------------------
# 3. Report
# ----------------------------------------------------------------------------------------------
def k(x):
    return f"{x / 1e6:.2f}M" if x >= 1e6 else f"{x / 1e3:.0f}k"


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def usd(x):
    return f"${x:,.2f}"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join(["---"] + ["---:"] * (len(header) - 1)) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def report(r, w0, w1, top, titles):
    tot = r["total"]
    cost = sum(tot.values())
    carry = tot["read"] + tot["rewrite"]
    ctx = r["contexts"]
    out = []
    start = datetime.fromtimestamp(w0, timezone.utc).strftime("%Y-%m-%d %H:%M")
    end = datetime.fromtimestamp(w1, timezone.utc).strftime("%Y-%m-%d %H:%M")
    out.append(f"# Context cost in Claude Code\n\nWindow: {start} to {end} (UTC). "
               f"Turns: {r['n_main']} in main sessions and {r['n_sub']} in subagents.\n")
    if not ctx:
        out.append("No turns in the window.")
        return "\n".join(out)

    c200 = sum(c for x, c in r["turn_costs"] if x > 200e3)
    n200 = sum(1 for x in ctx if x > 200e3)
    out.append("## Summary\n")
    out.append(f"- **Carrying context is {pct(carry, cost)} of the cost** "
               f"(cache reads {pct(tot['read'], cost)}, rewriting old context "
               f"{pct(tot['rewrite'], cost)}). Output is {pct(tot['output'], cost)} and "
               f"the new context that gets added is {pct(tot['new'], cost)}.")
    out.append(f"- Context per turn: median {k(statistics.median(ctx))}, mean "
               f"{k(statistics.mean(ctx))}, max {k(max(ctx))}.")
    out.append(f"- {pct(n200, len(ctx))} of turns run above 200k and account for "
               f"{pct(c200, cost)} of the cost.")
    h60 = r["gaps"][">60 min"]
    out.append(f"- Reopening a large session after more than 60 minutes rewrote {k(h60['tokens'])} "
               f"tokens in {h60['misses']} turns: {pct(h60['extra_cost'], cost)} of the cost.")
    comp = r["compactions"]
    if comp:
        before = [c["before"] for c in comp if c["before"]]
        avg = f", averaging {k(statistics.mean(before))} when compacting" if before else ""
        out.append(f"- {len(comp)} compactions{avg}.")
    out.append(f"- Total equivalent cost: {usd(cost)} at list price (relative measure, not a bill).\n")

    out.append("## Cost by context size\n")
    rows = []
    for _, _, n in BANDS:
        b = r["by_band"][n]
        rows.append([n, b["turns"], pct(b["turns"], len(ctx)), pct(b["cost"], cost),
                     usd(b["cost"] / b["turns"]) if b["turns"] else "-",
                     pct(b["carry"], b["cost"])])
    out.append(table(["Turn context", "Turns", "% of turns", "% of cost", "Cost per turn",
                      "% of it that is carry"], rows) + "\n")

    out.append("## Cache misses by pause length\n")
    out.append("Turns that already had 100k or more of context, grouped by the time since the "
               "previous turn. A miss is a turn that rewrites more than 20% of the previous "
               "context (and more than 20k tokens).\n")
    rows = [[n, h["turns"], f"{h['misses']} ({pct(h['misses'], h['turns'])})", k(h["tokens"]),
             usd(h["extra_cost"])] for n, h in ((n, r["gaps"][n]) for n, _, _ in GAPS)]
    out.append(table(["Pause", "Turns", "Misses", "Tokens rewritten", "Extra cost"], rows) + "\n")

    if comp:
        out.append("## Compactions\n")
        by_trigger = defaultdict(list)
        for c in comp:
            by_trigger[c["trigger"]].append(c)
        rows = []
        for trigger, items in sorted(by_trigger.items()):
            before = [c["before"] for c in items if c["before"]]
            summary = [c["summary"] for c in items if c["summary"]]
            after = [c["after"] for c in items if c["after"]]
            avg = lambda xs: k(statistics.mean(xs)) if xs else "-"
            rows.append([trigger, len(items), avg(before), k(max(before)) if before else "-",
                         avg(summary), avg(after)])
        out.append(table(["Trigger", "Compactions", "Avg context before", "Max before",
                          "Avg summary", "First turn after"], rows) + "\n")
        out.append("\"Summary\" is the size of the compacted conversation. \"First turn after\" is "
                   "everything the model reads on the next call: summary, system prompt, tools, "
                   "CLAUDE.md, memory and whatever the hooks reinject.\n")

    out.append(f"## Most expensive main sessions (top {top})\n")
    rows = []
    ranked = sorted(r["sessions"].items(), key=lambda kv: -(kv[1]["cost"] + kv[1]["sub_cost"]))
    for key, s in ranked[:top]:
        if not s["turns"] and not s["sub_cost"]:
            continue
        name = key[:8]
        if titles and s["title"]:
            name = f"{s['title']} ({key[:6]})"
        rows.append([name, s["turns"], k(statistics.mean(s["ctx"])) if s["ctx"] else "-",
                     k(max(s["ctx"])) if s["ctx"] else "-", s["compact"], usd(s["cost"]),
                     usd(s["sub_cost"]), pct(s["cost"] + s["sub_cost"], cost)])
    out.append(table(["Session", "Turns", "Avg ctx", "Max ctx", "Compactions", "Cost",
                      "Its subagents", "% of total"], rows) + "\n")
    out.append("Amounts are API list-price equivalents. If you use a subscription, look at the "
               "percentages and the order of magnitude, not the dollars.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Measure how much carrying context costs in Claude Code.")
    ap.add_argument("--days", "--dias", type=float, default=7, help="length of the window in days (default 7)")
    ap.add_argument("--until", "--hasta", default=None, help="end of the window, ISO UTC (default: now)")
    ap.add_argument("--base", default=os.path.join(os.path.expanduser("~"), ".claude", "projects"),
                    help="transcripts folder (default ~/.claude/projects)")
    ap.add_argument("--top", type=int, default=15, help="sessions in the final table")
    ap.add_argument("--titles", "--titulos", action="store_true",
                    help="show each session's title (by default only its id, so the report can be shared without conversation data)")
    ap.add_argument("--prices", "--precios", default=None,
                    help='JSON file with your own prices: {"model": [input, output, cache_read]}')
    ap.add_argument("--json", default=None, help="also save the figures to this JSON file")
    ap.add_argument("--compare", nargs=4, metavar=("BEFORE_FROM", "BEFORE_UNTIL", "AFTER_FROM", "AFTER_UNTIL"),
                    help="compare two windows (ISO dates with a time zone, e.g. 2026-11-01T00:00:00+01:00)")
    ap.add_argument("--log", action="append", default=[],
                    help="with --compare: the mod's compactions.jsonl, to count what it compacted (repeatable)")
    ap.add_argument("--figures", default=None,
                    help="with --compare: write the JSON that assets/make_assets.py --figures reads")
    a = ap.parse_args()

    if a.prices:
        with open(a.prices, encoding="utf-8") as f:
            for model, values in json.load(f).items():
                PRICES[model] = tuple(float(v) for v in values)

    if a.compare:
        wins = [to_epoch(x) for x in a.compare]
        if None in wins:
            sys.exit("--compare takes four ISO dates, e.g. 2026-10-25T00:00:00+02:00")
        wa, wb = (wins[0], wins[1]), (wins[2], wins[3])
        if not (wa[0] < wa[1] and wb[0] < wb[1]):
            sys.exit("--compare: each window has to start before it ends")
        if not os.path.isdir(a.base):
            sys.exit(f"Transcripts folder not found: {a.base}")
        data = load(a.base, min(wa[0], wb[0]))
        log_a, log_b = read_mod_log(a.log, *wa), read_mod_log(a.log, *wb)
        ra = measure(prepare(data, *wa))
        sa = summarize(ra, *wa, log_a, avoided_by_mod(data, log_a, *wa))
        rb = measure(prepare(data, *wb))
        sb = summarize(rb, *wb, log_b, avoided_by_mod(data, log_b, *wb))
        print(compare_report(sa, sb, wa, wb))
        if a.json:
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump({"before": {"window": wa, **sa}, "after": {"window": wb, **sb}}, f, ensure_ascii=False, indent=2)
            print(f"\nFigures saved to {a.json}", file=sys.stderr)
        if a.figures:
            with open(a.figures, "w", encoding="utf-8") as f:
                json.dump(figures_for_chart(sa, sb), f, ensure_ascii=False, indent=2)
            print(f"Chart figures saved to {a.figures}", file=sys.stderr)
        return

    end = to_epoch(a.until) if a.until else datetime.now(timezone.utc).timestamp()
    if end is None:
        sys.exit("--until is not a valid ISO date (example: 2026-10-31T12:00:00Z)")
    start = end - timedelta(days=a.days).total_seconds()
    if not os.path.isdir(a.base):
        sys.exit(f"Transcripts folder not found: {a.base}")

    data = prepare(load(a.base, start), start, end)
    r = measure(data)
    print(report(r, start, end, a.top, a.titles))

    if a.json:
        cost = sum(r["total"].values())
        result = {
            "window": {"from": start, "until": end},
            "turns": {"main": r["n_main"], "subagents": r["n_sub"]},
            "tokens": r["tokens"],
            "cost_usd": {**r["total"], "total": cost},
            "by_band": r["by_band"],
            "misses_by_pause": r["gaps"],
            "compactions": [{"trigger": c["trigger"], "before": c["before"], "summary": c["summary"],
                             "first_turn_after": c["after"]} for c in r["compactions"]],
            "sessions": [{"id": key[:8], "title": (s["title"] if a.titles else None),
                          "turns": s["turns"], "cost": s["cost"], "subagent_cost": s["sub_cost"],
                          "compactions": s["compact"]}
                         for key, s in r["sessions"].items() if s["turns"] or s["sub_cost"]],
        }
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nFigures saved to {a.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
