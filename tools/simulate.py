#!/usr/bin/env python3
"""Replay Claude Code usage traces and price what-if policies.

Generic: it reads two CSV files (no message text in them) and prints/writes
markdown tables. Nothing in here knows about a particular person or workflow.

  llamadas.csv(.gz): ts, proyecto, sesion, archivo, subagente, modelo,
                     input, cache_read, cache_5m, cache_1h, cache_creation_total, output
  eventos.csv(.gz):  ts, sesion, tipo, pre_tokens
                     tipo in {humano, mensaje_otra_sesion, cron, cierre_tarea, compactacion}

Usage:
  python3 tools/simulate.py --calls PATH --events PATH --out DIR [--prices official|report]
  python3 tools/simulate.py --selftest

Standard library only.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import statistics as st
import sys
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------
# Prices, USD per million tokens: (input, write 5m, write 1h, cache read, output).
# "official": https://platform.claude.com/docs/en/about-claude/pricing (read 4 nov 2026).
# "report": the table the weekly usage report used (cached 6 oct 2026); it differs only in
# the Sonnet 5.5 cache read (0.20 instead of the official 0.10). Kept so the report's
# $1,310 and its $13.2-per-quota-point calibration can be reproduced.
# --------------------------------------------------------------------------------------
OFFICIAL = {
    'claude-fable-5-1': (10, 12.5, 20, 0.25, 50),
    'claude-fable-5': (10, 12.5, 20, 1.0, 50),
    'claude-opus-5-5': (4, 5, 8, 0.20, 20),
    'claude-opus-5': (5, 6.25, 10, 0.50, 25),
    'claude-opus-4-8': (5, 6.25, 10, 0.50, 25),
    'claude-opus-4-7': (5, 6.25, 10, 0.50, 25),
    'claude-opus-4-6': (5, 6.25, 10, 0.50, 25),
    'claude-sonnet-5-5': (2, 2.5, 4, 0.10, 10),
    'claude-sonnet-5': (2, 2.5, 4, 0.20, 10),
    'claude-sonnet-4-6': (3, 3.75, 6, 0.30, 15),
    'claude-haiku-5-5': (0.10, 0.125, 0.20, 0.01, 0.50),
    'claude-haiku-4-5': (1, 1.25, 2, 0.10, 5),
}
HAIKU55_LONG = (0.50, 0.625, 1.0, 0.05, 2.50)  # prompt over 100k tokens
REPORT = dict(OFFICIAL)
REPORT['claude-sonnet-5-5'] = (2, 2.5, 4, 0.20, 10)
PRICE_TABLES = {'official': OFFICIAL, 'report': REPORT}

HOUR = 3600.0
MAIN_TTL = HOUR          # main conversation on a subscription: 1 h
SUB_TTL = 300.0          # subagents, compaction: 5 min by default
MISS_MIN_WRITE = 20_000  # a "miss": wrote >= 20k and >= 50 % of the context
MISS_SHARE = 0.5
IDLE_COMPACT_GAP = 1800.0  # a compaction this long after the last request is the app's idle compaction
APP_IDLE_MIN = 200_000     # the app compacts idle conversations from this context (its documented default)


def price_of(model: str, table: dict, prompt_tokens: int = 0):
    m = model
    if m.startswith('claude-haiku-4-5'):
        m = 'claude-haiku-4-5'
    if m == 'claude-haiku-5-5' and prompt_tokens > 100_000:
        return HAIKU55_LONG
    return table.get(m)


def ts_of(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def opener(path):
    return gzip.open(path, 'rt', newline='') if path.endswith('.gz') else open(path, newline='')


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
@dataclass
class Call:
    t: float
    session: str
    thread: str
    sub: bool
    model: str
    inp: int
    read: int
    w5: int
    w1: int
    out: int

    @property
    def ctx(self) -> int:
        return self.inp + self.read + self.w5 + self.w1

    @property
    def write(self) -> int:
        return self.w5 + self.w1

    @property
    def miss(self) -> bool:
        return self.write >= MISS_MIN_WRITE and self.write >= MISS_SHARE * max(1, self.ctx)


@dataclass
class Event:
    t: float
    session: str
    kind: str
    pre: int


def load(calls_path, events_path):
    calls = []
    with opener(calls_path) as f:
        for r in csv.DictReader(f):
            if r['modelo'] == '<synthetic>':
                calls.append(Call(ts_of(r['ts']), r['sesion'], r['archivo'], r['subagente'] == '1', '<synthetic>', 0, 0, 0, 0, 0))
                continue
            calls.append(Call(ts_of(r['ts']), r['sesion'], r['archivo'], r['subagente'] == '1', r['modelo'],
                              int(r['input']), int(r['cache_read']), int(r['cache_5m']), int(r['cache_1h']), int(r['output'])))
    # tiny zero-output main-thread requests (aborted attempts) sit right before some compactions and hide the drop
    calls = [c for c in calls if c.sub or c.model == '<synthetic>' or not (c.ctx < 5000 and c.out == 0)]
    calls.sort(key=lambda c: c.t)
    events = []
    with opener(events_path) as f:
        for r in csv.DictReader(f):
            events.append(Event(ts_of(r['ts']), r['sesion'], r['tipo'], int(r['pre_tokens'] or 0)))
    events.sort(key=lambda e: e.t)
    return calls, events


def cost_parts(model, inp, read, w5, w1, out, table):
    p = price_of(model, table, inp + read + w5 + w1)
    if p is None:
        return (0.0, 0.0, 0.0, 0.0)
    i, p5, p1, pr, po = p
    return (inp * i / 1e6, read * pr / 1e6, (w5 * p5 + w1 * p1) / 1e6, out * po / 1e6)


def call_cost(c: Call, table) -> float:
    return sum(cost_parts(c.model, c.inp, c.read, c.w5, c.w1, c.out, table))


# --------------------------------------------------------------------------------------
# Weeks: Wednesday 00:00 UTC (01:00 in Madrid in winter), as the usage report counts them
# --------------------------------------------------------------------------------------
def week_start(t: float) -> float:
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    day = d.replace(hour=0, minute=0, second=0, microsecond=0)
    back = (day.weekday() - 2) % 7  # Wednesday = 2
    return (day - dt.timedelta(days=back)).timestamp()


def wlabel(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%d %b').lstrip('0')


# --------------------------------------------------------------------------------------
# Model parameters of what the traces do not show
# --------------------------------------------------------------------------------------
@dataclass
class Params:
    post_ctx: int = 128_000        # context of the first call after a compaction (base + summary)
    post_prefix: int = 45_000      # part of it still cached after a compaction (shared system prefix)
    summary_out: int = 33_000      # output tokens of the compaction call itself (not in the traces)
    reread_share: float = 0.27     # rereads after a compaction: growth is ~27 % higher in the 30 calls after a real one (measured)
    reread_calls: int = 30
    safety_ctx: int = 950_000      # the app's own auto-compaction (~97 % of 1M)
    first_growth: int = 2_000      # growth of the first call after a skipped compaction


# --------------------------------------------------------------------------------------
# Thread index: main threads per session, with turn ends and close points
# --------------------------------------------------------------------------------------
@dataclass
class Thread:
    session: str
    calls: list
    sub: bool
    turn_end: list = field(default_factory=list)    # bool per call: a message arrives before the next call (or last)
    close: list = field(default_factory=list)       # bool per call: a task-closed signal right after this call
    act_comp: list = field(default_factory=list)    # bool per call: an actual compaction happens right after
    act_comp_t: list = field(default_factory=list)  # its time
    act_idle: list = field(default_factory=list)    # bool per call: the app compacted while idle after it (exogenous)
    act_idle_t: list = field(default_factory=list)
    msg_after: list = field(default_factory=list)   # first message kind after this call and before next call


def build_threads(calls, events):
    by_thread = collections.defaultdict(list)
    for c in calls:
        if c.model == '<synthetic>':
            continue
        by_thread[c.thread].append(c)
    ev_by_s = collections.defaultdict(list)
    for e in events:
        ev_by_s[e.session].append(e)
    threads = []
    for key, cs in by_thread.items():
        th = Thread(cs[0].session, cs, cs[0].sub)
        n = len(cs)
        th.turn_end = [False] * n
        th.close = [False] * n
        th.act_comp = [False] * n
        th.act_comp_t = [0.0] * n
        th.act_idle = [False] * n
        th.act_idle_t = [0.0] * n
        th.msg_after = [None] * n
        if not th.sub:
            evs = ev_by_s.get(th.session, [])
            ts = [c.t for c in cs]
            for e in evs:
                # the call just before the event
                i = bisect.bisect_right(ts, e.t) - 1
                if i < 0:
                    continue
                if e.kind in ('humano', 'mensaje_otra_sesion', 'cron'):
                    th.turn_end[i] = True
                    if th.msg_after[i] is None:
                        th.msg_after[i] = e.kind
                elif e.kind == 'cierre_tarea':
                    th.close[i] = True
                elif e.kind == 'compactacion':
                    # only if the context really dropped on the next call
                    if i + 1 < n and cs[i + 1].ctx < 0.7 * cs[i].ctx:
                        if e.t - cs[i].t > IDLE_COMPACT_GAP:
                            # long after the last request: the app's own idle compaction, not a closed task
                            th.act_idle[i] = True
                            th.act_idle_t[i] = e.t
                        else:
                            th.act_comp[i] = True
                            th.act_comp_t[i] = e.t
                            th.close[i] = True
                        th.turn_end[i] = True
            th.turn_end[-1] = True
        threads.append(th)
    return threads


# --------------------------------------------------------------------------------------
# Measured cost (what the traces say) per week
# --------------------------------------------------------------------------------------
def measured_by_week(calls, table):
    out = collections.defaultdict(float)
    for c in calls:
        out[week_start(c.t)] += call_cost(c, table)
    return out


# --------------------------------------------------------------------------------------
# Predictive check: rebuild every call's cost from context, gaps and output only
# (miss when the gap is past the TTL, or after a compaction), and compare with measured
# --------------------------------------------------------------------------------------
def predictive_by_week(threads, table, p: Params):
    out = collections.defaultdict(float)
    for th in threads:
        ttl = SUB_TTL if th.sub else MAIN_TTL
        prev = None
        for i, c in enumerate(th.calls):
            ctx = c.ctx
            dropped = prev is not None and ctx < 0.7 * prev.ctx
            cold = prev is None or (c.t - prev.t) > ttl or dropped
            if cold:
                read = min(ctx, p.post_prefix if not th.sub else 0)
                if prev is None and th.sub:
                    read = min(ctx, c.read)  # subagent's first call: system prefix may be cached
                w = ctx - read - c.inp
            else:
                w = max(0, ctx - prev.ctx - c.inp)
                read = ctx - w - c.inp
            w1 = w if (c.w1 >= c.w5 and c.write > 0) or (c.write == 0 and not th.sub) else 0
            w5 = w - w1
            out[week_start(c.t)] += sum(cost_parts(c.model, c.inp, read, w5, w1, c.out, table))
            prev = c
    return out


# --------------------------------------------------------------------------------------
# Counterfactual replay of main threads under a compaction policy
# --------------------------------------------------------------------------------------
@dataclass
class Result:
    cost: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(float))
    comp_cost: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(float))
    n_comp: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(int))
    n_wasted: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(int))
    wasted_cost: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(float))
    cold_returns: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(int))
    cold_cost: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(float))
    ctx_tokens: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(float))
    ncalls: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(int))
    n_app_idle: collections.defaultdict = field(default_factory=lambda: collections.defaultdict(int))

    def total(self, weeks=None):
        ws = self.cost.keys() if weeks is None else weeks
        return sum(self.cost[w] + self.comp_cost[w] for w in ws)


def compaction_call_cost(model, ctx, warm, table, p: Params):
    """The /compact request itself: it reads the whole conversation (from cache if warm,
    otherwise it writes it to the 5-minute cache) and writes the summary as output."""
    if warm:
        return sum(cost_parts(model, 0, ctx, 0, 0, p.summary_out, table))
    return sum(cost_parts(model, 0, 0, ctx, 0, p.summary_out, table))


def replay(threads, table, p: Params, policy, leave=None):
    """policy(ctx, closed, turn_end, act_comp) -> True to compact after this call.
    leave: None or (idle_s, min_ctx, need_close): compact while idle, cache still alive,
    if no message arrives within idle_s of the last call."""
    R = Result()
    for th in threads:
        if th.sub:
            continue
        cs = th.calls
        n = len(cs)
        off = 0.0              # actual ctx - simulated ctx
        sim_prev = None        # simulated ctx of the previous call
        miss_next = False      # the next call rebuilds (after a simulated compaction)
        reread_left = 0
        last_close = False     # a task-closed signal since the last message
        just = False           # compacted and no call since
        unread_left = 0
        comped_prev = False
        for i, c in enumerate(cs):
            w = week_start(c.t)
            prev = cs[i - 1] if i else None
            # actual growth of this call
            if prev is None:
                g = c.ctx
            elif c.ctx < 0.7 * prev.ctx and not (th.act_comp[i - 1] or th.act_idle[i - 1]):
                g = sim_prev * (c.ctx / prev.ctx - 1)   # exogenous drop with no compaction event: keep it
            elif c.ctx < 0.7 * prev.ctx:          # an actual compaction just before
                g = p.first_growth
                if not comped_prev:
                    unread_left = p.reread_calls
            else:
                g = c.ctx - prev.ctx
                if (g < 0 or c.model != prev.model) and sim_prev is not None:
                    g = sim_prev * (c.ctx / max(1, prev.ctx) - 1)
            if unread_left > 0 and g > 0 and not (prev is not None and c.ctx < 0.7 * prev.ctx):
                g = g / (1 + p.reread_share)
                unread_left -= 1
            comped_prev = False
            if reread_left > 0 and g > 0:
                g = g * (1 + p.reread_share)
                reread_left -= 1
            sim = g if sim_prev is None else sim_prev + g
            gap = (c.t - prev.t) if prev else None
            cold_ttl = gap is not None and gap > MAIN_TTL
            # was this call a miss in reality for a reason other than TTL or compaction (prefix change)?
            other_miss = c.miss and not cold_ttl and not (prev is not None and c.ctx < 0.7 * prev.ctx) and prev is not None
            is_miss = prev is None or cold_ttl or miss_next or other_miss
            if is_miss:
                read = min(sim, c.read if prev is None else p.post_prefix)
                wr = max(0, sim - read - c.inp)
            else:
                # a warm call writes what it adds; when it was warm in reality too, that is its own write
                wr = c.write if (prev is not None and not c.miss) else max(0, g - c.inp)
                wr = min(wr, max(0, sim - c.inp))
                read = max(0, sim - wr - c.inp)
            w1 = wr if (c.w1 >= c.w5) else 0
            w5 = wr - w1
            cc = sum(cost_parts(c.model, c.inp, read, w5, w1, c.out, table))
            R.cost[w] += cc
            R.ctx_tokens[w] += sim
            R.ncalls[w] += 1
            if cold_ttl and not just:
                R.cold_returns[w] += 1
                R.cold_cost[w] += sum(cost_parts(c.model, 0, 0, 0, wr, 0, table)) - sum(cost_parts(c.model, 0, wr, 0, 0, 0, table))
            miss_next = False
            just = False
            sim_prev = sim
            if th.close[i]:
                last_close = True
            # decide after this call
            nxt = cs[i + 1] if i + 1 < n else None
            do = False
            if th.turn_end[i] or th.close[i]:
                do = policy(sim, th.close[i], th.turn_end[i], th.act_comp[i], c.model)
            if sim >= p.safety_ctx:
                do = True   # the app auto-compacts mid-turn too
            t_comp = c.t
            if not do and leave is not None and th.turn_end[i]:
                idle_s, min_ctx, need_close = leave
                gap_next = (nxt.t - c.t) if nxt else float('inf')
                if gap_next > idle_s and sim >= min_ctx and (last_close or not need_close) and idle_s < MAIN_TTL:
                    do = True
                    t_comp = c.t + idle_s
                    if not last_close:
                        # the idle question: one warm turn in which the model wraps up (about 5 requests)
                        R.comp_cost[w] += sum(cost_parts(c.model, 0, 5 * sim, 0, 5 * 3_000, 4_000, table))
            if not do and th.act_idle[i] and sim >= APP_IDLE_MIN:
                # the app's idle compaction happens whatever the policy, if the context still qualifies
                do = True
                t_comp = th.act_idle_t[i]
                R.n_app_idle[w] += 1
            if do:
                warm = (t_comp - c.t) < MAIN_TTL
                k = compaction_call_cost(c.model, sim, warm, table, p)
                R.comp_cost[w] += k
                R.n_comp[w] += 1
                if nxt is None:
                    R.n_wasted[w] += 1
                    R.wasted_cost[w] += k
                sim_prev = p.post_ctx - (nxt.ctx - c.ctx if (nxt and nxt.ctx >= 0.7 * c.ctx) else p.first_growth)
                sim_prev = max(p.post_prefix, sim_prev)
                miss_next = True
                reread_left = 0 if (nxt is not None and nxt.ctx < 0.7 * c.ctx) else p.reread_calls
                last_close = False
                just = True
                comped_prev = True
                unread_left = 0
            if th.msg_after[i] is not None and not th.close[i]:
                last_close = False
    return R


# --------------------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------------------
def pol_actual(sim, closed, turn_end, act_comp, model=None):
    return act_comp


def pol_never(sim, closed, turn_end, act_comp, model=None):
    return False


def pol_close_at(T):
    def f(sim, closed, turn_end, act_comp, model=None):
        return closed and sim >= T
    return f


def pol_any_turn_at(T):
    def f(sim, closed, turn_end, act_comp, model=None):
        return turn_end and sim >= T
    return f


def plugin_economics(ctx, model, table, p: Params, calls=50, cold=2):
    """The same sums as plugin/hooks/policy.ts (economics): cost now, expected saving later."""
    pr = price_of(model, table, int(ctx)) or price_of('claude-opus-5-5', table)
    r, w1, o = pr[3] / 1e6, pr[2] / 1e6, pr[4] / 1e6
    d = max(0.0, ctx - p.post_ctx)
    cost = ctx * r + p.summary_out * o + max(0, p.post_ctx - p.post_prefix) * (w1 - r)
    saving = calls * d * r + cold * d * (w1 - r)
    return cost, saving


def pol_plugin(table, p: Params, floor=100_000, hard_cap=850_000, calls=50, cold=2):
    """plugin/hooks/policy.ts at a turn end: a closed task compacts when it pays; any turn end
    compacts when the window is nearly full."""
    def f(sim, closed, turn_end, act_comp, model=None):
        if sim >= hard_cap:
            return True
        if not closed or sim < floor:
            return False
        cost, saving = plugin_economics(sim, model, table, p, calls, cold)
        return saving >= cost
    return f


# --------------------------------------------------------------------------------------
# Remaining life after a close point: calls until the next actual compaction or the end,
# and cold returns among them (for the break-even table)
# --------------------------------------------------------------------------------------
def remaining_after_close(threads):
    rows = []
    for th in threads:
        if th.sub:
            continue
        cs = th.calls
        n = len(cs)
        nxt_comp = [n] * (n + 1)
        nc = n
        for i in range(n - 1, -1, -1):
            if th.act_comp[i] or th.act_idle[i]:
                nc = i + 1
            nxt_comp[i] = nc
        for i in range(n):
            if not th.close[i]:
                continue
            end = n if th.act_comp[i] else nxt_comp[i + 1] if i + 1 < n else n
            # if the close was itself compacted in reality, its "life" is until the next compaction after it
            j0 = i + 1
            N = max(0, min(end, n) - j0)
            M = sum(1 for j in range(j0, min(end, n)) if j > 0 and cs[j].t - cs[j - 1].t > MAIN_TTL)
            rows.append((cs[i].ctx, N, M, cs[i].model, week_start(cs[i].t)))
    return rows


# --------------------------------------------------------------------------------------
# Break-even
# --------------------------------------------------------------------------------------
def breakeven(model, C, table, p: Params, M=0):
    i, w5, w1, r, o = price_of(model, table, C)
    r, w1, o = r / 1e6, w1 / 1e6, o / 1e6
    P, pi = p.post_ctx, p.post_prefix
    D = C - P
    if D <= 0:
        return None, None
    fixed = C * r + p.summary_out * o + (P - pi) * (w1 - r)
    per_turn = D * r
    cold = D * (w1 - r)
    return fixed, per_turn, cold


# --------------------------------------------------------------------------------------
# Subagent cache TTL: replay subagent threads with 5 min (as measured) and with 1 h
# --------------------------------------------------------------------------------------
def subagent_ttl(threads, table):
    res = {}
    for ttl_name, ttl, wkey in (('5 min', SUB_TTL, 'w5'), ('1 h', MAIN_TTL, 'w1')):
        tot = collections.defaultdict(float)
        gaps = collections.Counter()
        for th in threads:
            if not th.sub:
                continue
            prev = None
            for c in th.calls:
                ctx = c.ctx
                if prev is None:
                    read = c.read
                    wr = max(0, ctx - read - c.inp)
                else:
                    gap = c.t - prev.t
                    if gap > SUB_TTL:
                        gaps['>5m'] += 1
                        if gap <= MAIN_TTL:
                            gaps['5-60m'] += 1
                    else:
                        gaps['<=5m'] += 1
                    if gap > ttl or ctx < 0.7 * prev.ctx:
                        read = min(ctx, c.read)
                        read = min(read, ctx)
                        wr = max(0, ctx - read - c.inp)
                    else:
                        wr = max(0, ctx - prev.ctx - c.inp)
                        read = ctx - wr - c.inp
                kw = {'w5': (wr, 0), 'w1': (0, wr)}[wkey]
                tot[week_start(c.t)] += sum(cost_parts(c.model, c.inp, read, kw[0], kw[1], c.out, table))
                prev = c
        res[ttl_name] = (tot, gaps)
    return res


# --------------------------------------------------------------------------------------
# Cross-session messages to a cold session: hold and batch
# --------------------------------------------------------------------------------------
def peer_batching(threads, events, table, holds):
    """A peer message that reaches a session whose cache is cold pays a rebuild. If it waits
    (up to `hold` seconds) for the next wake of that session that would be cold anyway
    (another message, a person), the two share one rebuild. People's messages never wait."""
    by_s = {th.session: th for th in threads if not th.sub}
    ev_by_s = collections.defaultdict(list)
    for e in events:
        if e.kind in ('humano', 'mensaje_otra_sesion', 'cron'):
            ev_by_s[e.session].append(e)
    out = {}
    for hold in holds:
        saved = collections.defaultdict(float)
        n_cold = collections.defaultdict(int)
        n_merged = collections.defaultdict(int)
        delays = []
        for s, evs in ev_by_s.items():
            th = by_s.get(s)
            if th is None:
                continue
            ts = [c.t for c in th.calls]
            for k, e in enumerate(evs):
                if e.kind != 'mensaje_otra_sesion':
                    continue
                i = bisect.bisect_right(ts, e.t) - 1
                j = i + 1
                if i < 0 or j >= len(th.calls):
                    continue
                if e.t - th.calls[i].t <= MAIN_TTL:
                    continue  # warm: nothing to save
                c = th.calls[j]
                if not c.miss:
                    continue
                w = week_start(e.t)
                n_cold[w] += 1
                # the chain this message started ends at the next message; find the next wake after it
                nxt = None
                for e2 in evs[k + 1:]:
                    if e2.t > e.t:
                        nxt = e2
                        break
                if nxt is None:
                    continue
                if nxt.t - e.t > hold:
                    continue
                # would that next wake be cold too (more than the TTL after the chain's last call)?
                i2 = bisect.bisect_right(ts, nxt.t) - 1
                if i2 < 0 or nxt.t - th.calls[i2].t <= MAIN_TTL:
                    continue
                j2 = i2 + 1
                if j2 >= len(th.calls) or not th.calls[j2].miss:
                    continue
                c2 = th.calls[j2]
                # one rebuild saved: the later one (now it is warm behind the batched delivery)
                wr = c2.write
                saved[w] += sum(cost_parts(c2.model, 0, 0, 0, wr, 0, table)) - sum(cost_parts(c2.model, 0, wr, 0, 0, 0, table))
                n_merged[w] += 1
                delays.append(nxt.t - e.t)
        out[hold] = (saved, n_cold, n_merged, delays)
    return out


# --------------------------------------------------------------------------------------
# Five-hour windows: proxy spend per rolling window and limit-like bursts
# --------------------------------------------------------------------------------------
def five_hour(calls, table):
    synth = [c for c in calls if c.model == '<synthetic>']
    # bursts: >= 3 distinct sessions with a synthetic message inside 15 min
    bursts = []
    i = 0
    synth.sort(key=lambda c: c.t)
    while i < len(synth):
        j = i
        while j + 1 < len(synth) and synth[j + 1].t - synth[i].t <= 900:
            j += 1
        sess = {c.session for c in synth[i:j + 1]}
        if len(sess) >= 3:
            bursts.append((synth[i].t, len(sess), j - i + 1))
            i = j + 1
        else:
            i += 1
    real = [c for c in calls if c.model != '<synthetic>']
    ts = [c.t for c in real]
    costs = [call_cost(c, table) for c in real]
    pref = [0.0]
    for x in costs:
        pref.append(pref[-1] + x)

    def spend(a, b):
        return pref[bisect.bisect_left(ts, b)] - pref[bisect.bisect_left(ts, a)]
    rows = []
    for (t, ns, nm) in bursts:
        rows.append((t, ns, nm, spend(t - 5 * HOUR, t)))
    # busiest 5 h windows starting at each call (sampled)
    top = []
    for k in range(0, len(real), 20):
        a = ts[k]
        top.append((spend(a, a + 5 * HOUR), a))
    top.sort(reverse=True)
    return rows, top[:15]


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------
def fmt(x, d=0):
    s = f'{x:,.{d}f}'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


def pct(a, b):
    return 100.0 * (a - b) / b if b else 0.0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--calls')
    ap.add_argument('--events')
    ap.add_argument('--out', default='.')
    ap.add_argument('--prices', default='official', choices=list(PRICE_TABLES))
    ap.add_argument('--validate-from', default='2026-10-21', help='weeks from this date are the out-of-sample check')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    calls, events = load(a.calls, a.events)
    run_all(calls, events, a.out, a.prices, ts_of(a.validate_from + 'T00:00:00Z'))
    return 0


def run_all(calls, events, outdir, price_name, t_val, quiet=False):
    os.makedirs(outdir, exist_ok=True)
    table = PRICE_TABLES[price_name]
    threads = build_threads(calls, events)
    res = {}
    weeks = sorted(set(week_start(c.t) for c in calls))
    last = max(c.t for c in calls)
    full = [w for w in weeks if w + 7 * 86400 <= last + 1]
    fit = [w for w in full if w < t_val]
    val = [w for w in full if w >= t_val]
    res['weeks'] = {'all': [wlabel(w) for w in weeks], 'fit': [wlabel(w) for w in fit], 'val': [wlabel(w) for w in val]}

    # 1. measured and predictive
    meas = measured_by_week(calls, table)
    p = fit_params(threads, fit)
    pred = predictive_by_week(threads, table, p)
    res['params'] = p.__dict__
    res['measured'] = {wlabel(w): meas[w] for w in weeks}
    res['predictive'] = {wlabel(w): pred[w] for w in weeks}
    # 2. baseline replay (actual compactions) and policies
    base = replay(threads, table, p, pol_actual)
    res['replay_base'] = {wlabel(w): base.cost[w] for w in weeks}
    pols = {'actual': base, 'never': replay(threads, table, p, pol_never)}
    for T in (150, 200, 300, 400, 500, 600):
        pols[f'close_{T}k'] = replay(threads, table, p, pol_close_at(T * 1000))
        pols[f'any_{T}k'] = replay(threads, table, p, pol_any_turn_at(T * 1000))
    pols['plugin'] = replay(threads, table, p, pol_plugin(table, p), leave=(50 * 60, 155_000, True))
    pols['plugin_idle_any'] = replay(threads, table, p, pol_plugin(table, p), leave=(45 * 60, 300_000, False))
    pols['plugin_no_idle'] = replay(threads, table, p, pol_plugin(table, p))
    res['policies'] = {}
    for k, R in pols.items():
        res['policies'][k] = {
            'by_week': {wlabel(w): R.cost[w] + R.comp_cost[w] for w in full},
            'comp_cost': {wlabel(w): R.comp_cost[w] for w in full},
            'n_comp': {wlabel(w): R.n_comp[w] for w in full},
            'n_app_idle': {wlabel(w): R.n_app_idle[w] for w in full},
            'mean_ctx': {wlabel(w): (R.ctx_tokens[w] / R.ncalls[w] if R.ncalls[w] else 0) for w in full},
            'fit': R.total(fit), 'val': R.total(val),
            'n_wasted': sum(R.n_wasted[w] for w in full), 'wasted_cost': sum(R.wasted_cost[w] for w in full),
            'cold_returns_val': sum(R.cold_returns[w] for w in val), 'cold_cost_val': sum(R.cold_cost[w] for w in val),
            'cold_returns_fit': sum(R.cold_returns[w] for w in fit), 'cold_cost_fit': sum(R.cold_cost[w] for w in fit),
        }
    # 3. leave-compaction on top of the best close policy and on top of actual
    leave = {}
    for base_name, bpol in (('actual', pol_actual),):
        for mins in (30, 45, 50, 55):
            for need_close in (True, False):
                for min_ctx in (200_000, 300_000):
                    R = replay(threads, table, p, bpol, leave=(mins * 60, min_ctx, need_close))
                    key = f'{base_name}+leave{mins}m_{"close" if need_close else "any"}_{min_ctx // 1000}k'
                    leave[key] = {
                        'fit': R.total(fit), 'val': R.total(val),
                        'by_week': {wlabel(w): R.cost[w] + R.comp_cost[w] for w in full},
                        'n_comp': sum(R.n_comp[w] for w in full), 'n_wasted': sum(R.n_wasted[w] for w in full),
                        'wasted_cost': sum(R.wasted_cost[w] for w in full),
                        'cold_returns': sum(R.cold_returns[w] for w in full),
                        'cold_cost': sum(R.cold_cost[w] for w in full),
                    }
    res['leave'] = leave
    res['cold_base'] = {'cold_returns': sum(base.cold_returns[w] for w in full), 'cold_cost': sum(base.cold_cost[w] for w in full),
                        'cold_returns_val': sum(base.cold_returns[w] for w in val), 'cold_cost_val': sum(base.cold_cost[w] for w in val)}
    # 4. break-even
    be = {}
    for model in ('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-fable-5-1'):
        for C in (150, 200, 300, 400, 500, 600):
            x = breakeven(model, C * 1000, table, p)
            if x[0] is None:
                continue
            fixed, per, cold = x
            be[f'{model}|{C}'] = {'fixed': fixed, 'per_turn': per, 'cold': cold, 'n_star': fixed / per}
    res['breakeven'] = be
    rem = remaining_after_close(threads)
    res['remaining'] = summarize_remaining(rem, fit, val)
    # 5. subagent TTL
    sub = subagent_ttl(threads, table)
    res['subagent_ttl'] = {k: {'fit': sum(v[0][w] for w in fit), 'val': sum(v[0][w] for w in val),
                               'by_week': {wlabel(w): v[0][w] for w in full}, 'gaps': dict(v[1])} for k, v in sub.items()}
    sub_meas = collections.defaultdict(float)
    for c in calls:
        if c.sub:
            sub_meas[week_start(c.t)] += call_cost(c, table)
    res['subagent_measured'] = {'fit': sum(sub_meas[w] for w in fit), 'val': sum(sub_meas[w] for w in val)}
    # 6. peer batching
    pb = peer_batching(threads, events, table, (HOUR, 2 * HOUR, 4 * HOUR, 12 * HOUR))
    res['peer'] = {}
    for hold, (saved, n_cold, n_merged, delays) in pb.items():
        res['peer'][f'{int(hold // 3600)}h'] = {
            'saved_fit': sum(saved[w] for w in fit), 'saved_val': sum(saved[w] for w in val),
            'cold_fit': sum(n_cold[w] for w in fit), 'cold_val': sum(n_cold[w] for w in val),
            'merged_fit': sum(n_merged[w] for w in fit), 'merged_val': sum(n_merged[w] for w in val),
            'delay_mean_min': (st.mean(delays) / 60 if delays else 0), 'delay_median_min': (st.median(delays) / 60 if delays else 0),
        }
    # 7. five-hour
    bursts, top = five_hour(calls, table)
    res['five_hour'] = {'bursts': [(dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(), ns, nm, sp) for t, ns, nm, sp in bursts],
                        'top_windows': [(dt.datetime.fromtimestamp(a, dt.timezone.utc).isoformat(), s) for s, a in top]}
    with open(os.path.join(outdir, f'sim_{price_name}.json'), 'w') as f:
        json.dump(res, f, indent=1, default=str)
    return res


def fit_params(threads, fit_weeks):
    """Post-compaction context and cached prefix, measured on the fitting weeks only."""
    fitset = set(fit_weeks)
    post, prefix = [], []
    for th in threads:
        if th.sub:
            continue
        cs = th.calls
        for i in range(len(cs) - 1):
            if (th.act_comp[i] or th.act_idle[i]) and week_start(cs[i].t) in fitset:
                # context after the first few calls (the "first turn")
                k = min(len(cs) - 1, i + 1)
                post.append(cs[k].ctx)
                prefix.append(cs[k].read)
    p = Params()
    if len(post) >= 5:
        p.post_ctx = int(st.median(post))
        p.post_prefix = int(st.median(prefix))
    p._n_post = len(post)  # type: ignore[attr-defined]
    return p


def summarize_remaining(rows, fit, val):
    out = {}
    bands = [(0, 150e3), (150e3, 200e3), (200e3, 300e3), (300e3, 400e3), (400e3, 500e3), (500e3, 600e3), (600e3, 2e6)]
    for name, ws in (('fit', set(fit)), ('val', set(val)), ('all', set(fit) | set(val))):
        d = {}
        for lo, hi in bands:
            sel = [(N, M) for (C, N, M, m, w) in rows if lo <= C < hi and w in ws]
            if not sel:
                continue
            Ns = [x[0] for x in sel]
            Ms = [x[1] for x in sel]
            d[f'{int(lo // 1000)}-{int(hi // 1000)}k'] = {'n': len(sel), 'N_median': st.median(Ns), 'N_mean': st.mean(Ns),
                                                          'M_mean': st.mean(Ms)}
        out[name] = d
    return out


# --------------------------------------------------------------------------------------
# Self-test on synthetic data
# --------------------------------------------------------------------------------------
def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(('ok  ' if cond else 'FAIL') + ' ' + name)
        ok = ok and cond
    # prices
    c = Call(0, 's', 'f', False, 'claude-opus-5-5', 0, 1_000_000, 0, 0, 0)
    check('opus 5.5 cache read is $0.20/M', abs(call_cost(c, OFFICIAL) - 0.20) < 1e-9)
    c = Call(0, 's', 'f', False, 'claude-sonnet-5-5', 0, 1_000_000, 0, 0, 0)
    check('sonnet 5.5 cache read official $0.10/M, report $0.20/M', abs(call_cost(c, OFFICIAL) - 0.10) < 1e-9 and abs(call_cost(c, REPORT) - 0.20) < 1e-9)
    c = Call(0, 's', 'f', False, 'claude-haiku-5-5', 0, 150_000, 0, 0, 0)
    check('haiku 5.5 over 100k uses the long price', abs(call_cost(c, OFFICIAL) - 150_000 * 0.05 / 1e6) < 1e-12)
    # week anchoring
    t = ts_of('2026-10-28T00:00:00Z')
    check('week starts on Wednesday 00:00 UTC', week_start(t + 3600) == t and week_start(t - 1) == t - 7 * 86400)
    # a synthetic thread: steady growth, one close at 400k, cold return after 3 h
    calls = []
    t0 = ts_of('2026-10-28T08:00:00Z')
    ctx = 100_000
    tt = t0
    for k in range(60):
        tt += 60
        ctx += 5_000
        calls.append(Call(tt, 'S', 'F', False, 'claude-opus-5-5', 1, ctx - 5_001, 0, 5_000, 500))
    close_t = tt + 1
    tt += 3 * HOUR
    for k in range(40):
        tt += 60
        ctx += 5_000
        w = ctx - 50_000 if k == 0 else 5_000
        calls.append(Call(tt, 'S', 'F', False, 'claude-opus-5-5', 1, ctx - w - 1, 0, w, 500))
    events = [Event(close_t, 'S', 'cierre_tarea', 0), Event(close_t + 2, 'S', 'humano', 0)]
    threads = build_threads(calls, events)
    p = Params()
    base = replay(threads, OFFICIAL, p, pol_never)
    meas = sum(call_cost(c, OFFICIAL) for c in calls)
    check('replay without compactions reproduces the measured cost (+-1%)', abs(pct(base.total(), meas)) < 1.0)
    comp = replay(threads, OFFICIAL, p, pol_close_at(300_000))
    check('compacting at the close before a 3 h pause and 40 more calls is cheaper', comp.total() < base.total())
    check('one compaction was made', sum(comp.n_comp.values()) == 1)
    hi = replay(threads, OFFICIAL, p, pol_close_at(900_000))
    check('a threshold above the context never compacts', sum(hi.n_comp.values()) == 0)
    lv = replay(threads, OFFICIAL, p, pol_never, leave=(50 * 60, 200_000, True))
    check('leave-compaction fires on the 3 h idle after a close', sum(lv.n_comp.values()) == 1 and lv.total() < base.total())
    lv2 = replay(threads, OFFICIAL, p, pol_never, leave=(50 * 60, 200_000, False))
    check('without the close condition it fires too', sum(lv2.n_comp.values()) >= 1)
    fixed, per, cold = breakeven('claude-opus-5-5', 600_000, OFFICIAL, p)
    check('break-even at 600k on Opus 5.5 is under 30 calls', fixed / per < 30)
    fixed2, per2, cold2 = breakeven('claude-opus-5-5', 200_000, OFFICIAL, p)
    check('break-even at 200k needs many more calls than at 600k', fixed2 / per2 > 3 * fixed / per)
    print('selftest', 'passed' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
