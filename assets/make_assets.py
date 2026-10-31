#!/usr/bin/env python3
"""Draws the README images by hand, as SVG, in a light and a dark version.

    python assets/make_assets.py                    writes the SVGs next to this script
    python assets/make_assets.py --png              also renders social-preview.png and the plugin icon
                                                    (with Playwright, or a Chrome/Edge given with --browser)
    python assets/make_assets.py --figures f.json   takes the measured figures from a JSON file

The idea: the context has a tide. Every turn re-reads everything under the line, so the area under
the line is what you pay for. Left alone it rises until the window is full; with cc-autocompact it
goes out at the end of every task. So the images are a tide record: chart paper, a graduated border,
a pen trace, the water under it, and the lettering written with the same pen (lettering.py).

Colours: a day chart (light) and a night chart (dark), with chart magenta for the one thing that
matters, the moment the model says "Ready to compact.". No image models and no fonts to load: shapes,
paths, and the viewer's system fonts only for the small notes and the code.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from xml.etree import ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lettering as L  # noqa: E402

PALETTES = {
    "light": {  # a day chart: cool paper, navy ink, shallow-water blue, pencil, chart magenta
        "paper": "#F4F7F7", "grid": "#E2EBED", "grid2": "#D0DEE2", "ink": "#102A43", "soft": "#4A6176",
        "water": "#CBE3EF", "water2": "#A9D0E3", "pencil": "#8D99A3", "hatch": "#AEB9C1", "magenta": "#B8157A",
        "card": "#FFFFFF", "line": "#C9D6DB", "band": "#102A43",
    },
    "dark": {  # a night chart: the same roles, dimmed for a dark room
        "paper": "#0B1620", "grid": "#13212C", "grid2": "#1A2C3A", "ink": "#DCE6EE", "soft": "#8FA3B4",
        "water": "#123247", "water2": "#1A4560", "pencil": "#61717E", "hatch": "#3F4E5A", "magenta": "#EF5FAE",
        "card": "#101F2B", "line": "#24394A", "band": "#6F8597",
    },
}

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

# The figures in before-after.svg. Until a real week with the plugin is measured, the second bar is
# the simulation from docs/MEASUREMENT.md. tools/measure_context.py --compare ... --figures f.json
# writes a file with the same keys, "mode": "measured" and the estimate from the plugin's own compactions.
FIGURES = {
    "mode": "simulated",
    "before": {"carry": 67, "reads": 46, "rewrites": 21, "output": 16, "new": 17},
    "saving_low": 28, "saving_high": 37,
    "note1": "Token cost at API list prices, one user, one week of heavy use (October 2026).",
    "note2": "The second bar is a simulation, not a measured saving. Method and every number: docs/MEASUREMENT.md.",
}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def sans(x, y, s, size, fill, anchor="start", weight=400, extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{SANS}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{extra}>{esc(s)}</text>')


def mono(x, y, s, size, fill, anchor="start", weight=400, extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{extra}>{esc(s)}</text>')


def pts(points):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def sheet(w, h, p, body, title, frame=True, defs=""):
    """Chart paper: a fine grid and, with frame, a neatline with a graduated border."""
    m, band = 18, 7
    grid = []
    for gx in range(m + band, w - m - band, 16):
        major = (gx - m - band) % 80 == 0
        grid.append(f'<line x1="{gx}" y1="{m + band}" x2="{gx}" y2="{h - m - band}" stroke="{p["grid2" if major else "grid"]}" stroke-width="1"/>')
    for gy in range(m + band, h - m - band, 16):
        major = (gy - m - band) % 80 == 0
        grid.append(f'<line x1="{m + band}" y1="{gy}" x2="{w - m - band}" y2="{gy}" stroke="{p["grid2" if major else "grid"]}" stroke-width="1"/>')
    border = []
    if frame:
        o, i = m, m + band
        border.append(f'<rect x="{o}" y="{o}" width="{w - 2 * o}" height="{h - 2 * o}" fill="none" stroke="{p["band"]}" stroke-width="1.4"/>')
        border.append(f'<rect x="{i}" y="{i}" width="{w - 2 * i}" height="{h - 2 * i}" fill="none" stroke="{p["band"]}" stroke-width="0.8"/>')
        seg = 40
        for k, x in enumerate(range(i, w - i, seg)):
            if k % 2 == 0:
                x2 = min(x + seg, w - i)
                border.append(f'<rect x="{x}" y="{o}" width="{x2 - x}" height="{band}" fill="{p["band"]}"/>')
                border.append(f'<rect x="{x}" y="{h - i}" width="{x2 - x}" height="{band}" fill="{p["band"]}"/>')
        for k, y in enumerate(range(i, h - i, seg)):
            if k % 2 == 1:
                y2 = min(y + seg, h - i)
                border.append(f'<rect x="{o}" y="{y}" width="{band}" height="{y2 - y}" fill="{p["band"]}"/>')
                border.append(f'<rect x="{w - i}" y="{y}" width="{band}" height="{y2 - y}" fill="{p["band"]}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
            f'<title>{esc(title)}</title><defs>{defs}</defs>'
            f'<rect width="{w}" height="{h}" fill="{p["paper"]}"/>{"".join(grid)}{"".join(border)}{body}</svg>\n')


def hatch_def(p, pid="hatch"):
    return (f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">'
            f'<line x1="0" y1="0" x2="0" y2="7" stroke="{p["hatch"]}" stroke-width="1.3"/></pattern>')


# --- the tide record: the same work, carried two ways --------------------------------------------

STEPS = [7, 11, 6, 12, 9, 5, 8]          # new context per turn (relative), the same in both lines
RISES = [0.25, 0.19, 0.27, 0.22, 0.2]     # how much context each task adds, as a share of the window
BASE = 0.13                               # what is left after a compaction (summary + what reloads)


def tide(x0, x1, y_top, y_base, tasks=4):
    """Points of the two traces. Returns (old, new, drops, auto_x) in px."""
    span = y_base - y_top
    lvl = lambda v: y_base - v * span  # noqa: E731
    turn_w = (x1 - x0) / (tasks * len(STEPS) + 6)
    old, new, drops = [(x0, lvl(BASE))], [(x0, lvl(BASE))], []
    vo = vn = BASE
    x = x0
    auto_x = None
    for t in range(tasks):
        unit = RISES[t] / sum(STEPS)
        for s in STEPS:
            x += turn_w
            vn += s * unit
            vo += s * unit
            if vo >= 0.985 and auto_x is None:   # the window is full: Claude Code's auto-compact
                old.append((x - turn_w * 0.35, lvl(0.985)))
                old.append((x - turn_w * 0.35, lvl(BASE + 0.03)))
                auto_x = x - turn_w * 0.35
                vo = BASE + 0.03 + s * unit * 0.6
            old.append((x, lvl(vo)))
            new.append((x, lvl(vn)))
        vn = BASE
        new.append((x, lvl(vn)))
        drops.append((x, lvl(vn), lvl(BASE + RISES[t])))
    for s in STEPS[:6]:
        x += turn_w
        vn += s * RISES[tasks] / sum(STEPS)
        vo += s * RISES[tasks] / sum(STEPS)
        new.append((x, lvl(vn)))
        old.append((x, lvl(vo)))
    return old, new, drops, auto_x


def tide_chart(p, x0, x1, y_top, y_base, fs=12, marker=True, notes=True):
    old, new, drops, auto_x = tide(x0, x1, y_top, y_base)
    out = []
    ceiling = y_top
    # the water each line carries: hatched under the old line, water under the new one
    out.append(f'<polygon points="{pts(old + [(old[-1][0], y_base), (x0, y_base)])}" fill="url(#hatch)"/>')
    out.append(f'<polygon points="{pts(new + [(new[-1][0], y_base), (x0, y_base)])}" fill="{p["water"]}"/>')
    # the window
    out.append(f'<line x1="{x0}" y1="{ceiling}" x2="{x1}" y2="{ceiling}" stroke="{p["ink"]}" stroke-width="1.2" stroke-dasharray="2 5" stroke-linecap="round"/>')
    out.append(L.text("context window full", x1, ceiling - 10, fs * 0.92, p["soft"], weight=0.13, tracking=0.26, anchor="end"))
    # baseline and task ticks
    out.append(f'<line x1="{x0}" y1="{y_base}" x2="{x1}" y2="{y_base}" stroke="{p["ink"]}" stroke-width="1.4"/>')
    prev = x0
    for i, (dx, _, _) in enumerate(drops):
        out.append(f'<line x1="{dx:.1f}" y1="{y_base}" x2="{dx:.1f}" y2="{y_base + 7}" stroke="{p["ink"]}" stroke-width="1.4"/>')
        out.append(L.text(f"task {i + 1}", (prev + dx) / 2, y_base + 9 + fs * 1.25, fs * 0.9, p["soft"], weight=0.13, tracking=0.26, anchor="middle"))
        prev = dx
    # the traces
    out.append(f'<polyline points="{pts(old)}" fill="none" stroke="{p["pencil"]}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')
    out.append(f'<polyline points="{pts(new)}" fill="none" stroke="{p["ink"]}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
    # where the model said it was done
    for dx, dy, peak in drops:
        out.append(f'<line x1="{dx:.1f}" y1="{peak - 9:.1f}" x2="{dx:.1f}" y2="{peak - 22:.1f}" stroke="{p["magenta"]}" stroke-width="2" stroke-linecap="round"/>')
        out.append(f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="4.2" fill="{p["magenta"]}" stroke="{p["paper"]}" stroke-width="2"/>')
    if auto_x is not None:
        out.append(L.text("auto-compact", auto_x + 10, ceiling + fs * 2.1, fs * 0.82, p["pencil"], weight=0.15, tracking=0.26))
    if marker:
        dx, _, peak = drops[0]
        out.append(mono(dx + 10, peak - 13, "Ready to compact.", fs + 1, p["magenta"], weight=600))
    if notes:
        out.append(L.text("drops after", new[-1][0] + 12, new[-1][1] - 4, fs * 0.82, p["ink"], weight=0.15, tracking=0.26))
        out.append(L.text("every task", new[-1][0] + 12, new[-1][1] + fs * 1.2, fs * 0.82, p["ink"], weight=0.15, tracking=0.26))
        stop = auto_x if auto_x is not None else old[-1][0]
        px, py = min(old, key=lambda q: abs(q[0] - (x0 + 0.62 * (stop - x0))))
        out.append(L.text("left alone, it fills the window", px - 6, py - 14, fs * 0.82, p["pencil"], weight=0.15, tracking=0.26, anchor="end"))
    return "".join(out)


def legend(p, x, y, fs):
    """Two swatches that say what the areas mean."""
    return (f'<rect x="{x}" y="{y - fs * 1.05:.1f}" width="30" height="{fs * 1.15:.1f}" fill="{p["water"]}" stroke="{p["ink"]}" stroke-width="1"/>'
            + L.text("re-read on every turn", x + 42, y, fs, p["ink"], weight=0.14, tracking=0.26)
            + f'<rect x="{x}" y="{y + fs * 1.55:.1f}" width="30" height="{fs * 1.15:.1f}" fill="url(#hatch)" stroke="{p["pencil"]}" stroke-width="1"/>'
            + L.text("no longer re-read", x + 42, y + fs * 2.6, fs, p["ink"], weight=0.14, tracking=0.26))


# --- the images ----------------------------------------------------------------------------------

def banner(p):
    w, h = 1280, 536
    body = [
        L.text("cc-autocompact", 74, 152, 60, p["ink"], weight=0.105, tracking=0.2),
        L.text("auto-compact for claude code when the task ends,", 78, 214, 17, p["soft"], weight=0.13, tracking=0.24),
        L.text("not when the context window is full.", 78, 246, 17, p["soft"], weight=0.13, tracking=0.24),
        legend(p, 930, 200, 12),
        tide_chart(p, 78, 1060, 304, 476, fs=13),
    ]
    return sheet(w, h, p, "".join(body), "cc-autocompact: auto-compact for Claude Code when the task ends, not when the context window is full", defs=hatch_def(p))


def social(p):
    w, h = 1280, 640
    body = [
        L.text("cc-autocompact", 80, 176, 76, p["ink"], weight=0.1, tracking=0.2),
        L.text("auto-compact for claude code when the task ends,", 86, 252, 21, p["soft"], weight=0.13, tracking=0.24),
        L.text("not when the context window is full.", 86, 290, 21, p["soft"], weight=0.13, tracking=0.24),
        tide_chart(p, 86, 1080, 356, 560, fs=15, notes=True),
    ]
    return sheet(w, h, p, "".join(body), "cc-autocompact", defs=hatch_def(p))


def flow(p):
    w, h = 1280, 470
    xs = [150, 395, 640, 885, 1130]
    ly = 150
    stations = [
        ("task done", ["The model asks itself:", "does the next task need", "this context?"], None),
        ("wrap-up", ["Writes .claude/HANDOFF.md", "and checks it is on disk.", "Last line of the answer:"], "Ready to compact."),
        ("the mod", ["Sees the line at turn end.", "Waits 1.5 s: a message", "from you cancels it."], None),
        ("/compact", ["Runs as if you typed it.", "The summary is saved", "to disk as well."], None),
        ("next task", ["The handoff goes back", "into the fresh context.", "Same session, less weight."], None),
    ]
    out = [f'<line x1="{xs[0]}" y1="{ly}" x2="{xs[-1]}" y2="{ly}" stroke="{p["ink"]}" stroke-width="1.6"/>']
    for i, (x, (name, lines, code)) in enumerate(zip(xs, stations)):
        out.append(L.text(name, x, ly - 30, 19, p["ink"], weight=0.12, tracking=0.22, anchor="middle"))
        colour = p["magenta"] if i == 1 else p["ink"]
        out.append(f'<circle cx="{x}" cy="{ly}" r="7" fill="{colour}" stroke="{p["paper"]}" stroke-width="3"/>')
        for j, t in enumerate(lines):
            out.append(sans(x, ly + 42 + j * 23, t, 15, p["soft"], anchor="middle"))
        if code:
            y = ly + 42 + len(lines) * 23 + 6
            out.append(f'<rect x="{x - 92}" y="{y - 18}" width="184" height="30" fill="{p["card"]}" stroke="{p["magenta"]}" stroke-width="1.2"/>')
            out.append(mono(x, y + 2, code, 15, p["magenta"], anchor="middle", weight=600))
    # the branch that keeps the context
    bx = xs[0]
    out.append(f'<line x1="{bx}" y1="{ly + 118}" x2="{bx}" y2="{ly + 150}" stroke="{p["pencil"]}" stroke-width="1.4" stroke-dasharray="2 5" stroke-linecap="round"/>')
    out.append(sans(bx, ly + 172, "If it does, or it isn't sure:", 15, p["ink"], anchor="middle"))
    out.append(sans(bx, ly + 195, "it keeps working, up to 1M.", 15, p["soft"], anchor="middle"))
    # who does what
    spans = [(xs[0] - 85, xs[1] + 85, "the model decides"), (xs[2] - 85, xs[3] + 50, "the mod acts"), (xs[3] + 75, xs[4] + 90, "nothing is lost")]
    sy = 405
    for a, b, label in spans:
        out.append(f'<path d="M{a} {sy - 8} L{a} {sy} L{b} {sy} L{b} {sy - 8}" fill="none" stroke="{p["ink"]}" stroke-width="1.2"/>')
        out.append(L.text(label, (a + b) / 2, sy + 30, 15, p["ink"], weight=0.13, tracking=0.24, anchor="middle"))
    return sheet(w, h, p, "".join(out), "How it works: task done, wrap-up writes the handoff and ends with Ready to compact., the mod waits 1.5 s and queues /compact, the summary is saved, and the handoff goes back into the fresh context")


def before_after(p, fig):
    w, h = 1280, 446
    x0, full = 360, 840
    b = fig["before"]
    out = []

    def bar(y, carry, label_carry, label_new):
        cw = full * carry / 100
        nw = full - cw
        out.append(f'<rect x="{x0}" y="{y}" width="{cw:.1f}" height="54" fill="{p["water"]}" stroke="{p["ink"]}" stroke-width="1"/>')
        out.append(f'<rect x="{x0 + cw:.1f}" y="{y}" width="{nw:.1f}" height="54" fill="{p["ink"]}"/>')
        out.append(sans(x0 + 14, y + 33, label_carry, 16, p["ink"], weight=600))
        out.append(sans(x0 + cw + 14, y + 33, label_new, 16, p["paper"], weight=600))

    # first row: the week that was measured
    out.append(L.text(f"{b['carry']}%", 74, 128, 40, p["ink"], weight=0.1, tracking=0.16))
    out.append(sans(76, 160, "of a week's token cost was", 15, p["soft"]))
    out.append(sans(76, 181, "re-reading old context", 15, p["soft"]))
    bar(92, b["carry"], f"re-reading old context: {b['reads']}% cache reads, {b['rewrites']}% rewrites", f"new work {b['output'] + b['new']}%")
    # second row: the simulation, or (once a week with the plugin is measured) the direct estimate
    lo, hi = fig["saving_low"], fig["saving_high"]
    out.append(L.text(f"{lo} to {hi}%", 74, 278, 34, p["magenta"], weight=0.11, tracking=0.16))
    if fig["mode"] == "measured":
        n = fig.get('mod_compactions', 0)
        out.append(sans(76, 310, f"less with the plugin: {n} compaction{'' if n == 1 else 's'}", 15, p["soft"]))
        out.append(sans(76, 331, f"in {fig.get('days', 7)} days (estimated from them)", 15, p["soft"]))
    else:
        out.append(sans(76, 310, "less, if every task ended", 15, p["soft"]))
        out.append(sans(76, 331, "in a compaction (simulated)", 15, p["soft"]))
    scale = 1 - (lo + hi) / 200
    new_w = full * (b["output"] + b["new"]) / 100
    cw = full * scale - new_w
    out.append(f'<rect x="{x0}" y="242" width="{cw:.1f}" height="54" fill="{p["water"]}" stroke="{p["ink"]}" stroke-width="1"/>')
    out.append(f'<rect x="{x0 + cw:.1f}" y="242" width="{new_w:.1f}" height="54" fill="{p["ink"]}"/>')
    out.append(sans(x0 + 14, 275, "old context", 16, p["ink"], weight=600))
    out.append(sans(x0 + cw + 14, 275, "same new work", 16, p["paper"], weight=600))
    # what is no longer paid: the outline of the week as it was
    end = x0 + full * scale
    seg = x0 + full - end - 4
    if seg > 2:
        out.append(f'<rect x="{end + 4:.1f}" y="242" width="{seg:.1f}" height="54" fill="url(#hatch)" stroke="{p["pencil"]}" stroke-width="1.2"/>')
    if seg >= L.width("no longer re-read", 13, 0.26) + 24:
        out.append(L.text("no longer re-read", (end + x0 + full) / 2, 274, 13, p["ink"], weight=0.15, tracking=0.26, anchor="middle"))
    else:
        out.append(L.text("no longer re-read", x0 + full, 322, 13, p["ink"], weight=0.15, tracking=0.26, anchor="end"))
    out.append(sans(74, 376, fig["note1"], 13.5, p["soft"]))
    out.append(sans(74, 397, fig["note2"], 13.5, p["soft"]))
    title = (f"Measured: {b['carry']}% of a week's token cost was re-reading old context. "
             + (f"With the plugin, estimated from its own compactions: {lo} to {hi}% less." if fig["mode"] == "measured"
                else f"Simulated: compacting at task ends costs {lo} to {hi}% less."))
    return sheet(w, h, p, "".join(out), title, defs=hatch_def(p))


def demo(p):
    """The flow as an animated illustration (not a recording). One loop is 14 s."""
    w, h = 1280, 700
    T = 14.0
    css = []

    def pct(t):
        return f"{min(t, T) / T * 100:.2f}%"

    def show(cls, t_in, t_out=12.9, rise=8):
        """An element that appears at t_in (s) and stays until t_out, every loop."""
        css.append(f"@keyframes {cls}{{0%,{pct(t_in)}{{opacity:0;transform:translateY({rise}px)}}"
                   f"{pct(t_in + 0.32)},{pct(t_out)}{{opacity:1;transform:translateY(0)}}{pct(t_out + 0.4)},100%{{opacity:0;transform:translateY(0)}}}}"
                   f".{cls}{{animation:{cls} {T}s cubic-bezier(.23,1,.32,1) infinite;transform-box:fill-box}}")
        return cls

    out = []
    # --- left: the session -------------------------------------------------------------------
    px0, py0, pw = 64, 62, 700
    out.append(L.text("the session", px0, py0 + 4, 14, p["soft"], weight=0.13, tracking=0.26))
    out.append(f'<rect x="{px0}" y="{py0 + 18}" width="{pw}" height="532" fill="{p["card"]}" stroke="{p["line"]}" stroke-width="1.2"/>')
    out.append(f'<line x1="{px0}" y1="{py0 + 98}" x2="{px0 + pw}" y2="{py0 + 98}" stroke="{p["line"]}" stroke-width="1"/>')
    y = py0 + 138
    out.append(f'<g class="{show("m0", 0.2)}">{sans(px0 + 24, y, "you", 12.5, p["soft"], weight=600)}'
               f'{sans(px0 + 24, y + 22, "Move the billing tables to the new schema and merge it.", 15.5, p["ink"])}</g>')
    y += 60
    for i, (t, at) in enumerate([("Read 14 files, wrote the migration.", 1.0), ("212 tests pass.", 2.0), ("Merged into main.", 3.0)]):
        out.append(f'<g class="{show(f"m{i + 1}", at)}">{sans(px0 + 24, y, t, 15.5, p["soft"])}</g>')
        y += 28
    y += 14
    out.append(f'<g class="{show("m4", 4.0)}">{sans(px0 + 24, y, "claude", 12.5, p["soft"], weight=600)}'
               f'{sans(px0 + 24, y + 22, "Done: billing tables migrated, tests green, merged.", 15.5, p["ink"])}'
               f'{sans(px0 + 24, y + 46, "Handoff updated in .claude/HANDOFF.md.", 15.5, p["ink"])}</g>')
    y += 82
    out.append(f'<g class="{show("m5", 4.7)}">{mono(px0 + 24, y, "Ready to compact.", 16, p["magenta"], weight=600)}'
               f'<line x1="{px0 + 24}" y1="{y + 7}" x2="{px0 + 196}" y2="{y + 7}" stroke="{p["magenta"]}" stroke-width="1.6"/></g>')
    y += 46
    out.append(f'<g class="{show("m6", 6.5)}">{mono(px0 + 24, y, "/compact", 15.5, p["ink"], weight=600)}'
               f'{sans(px0 + 112, y, "queued by the mod, as if you typed it", 14, p["soft"])}</g>')
    # a progress line while the summary is written
    css.append(f"@keyframes prog{{0%,{pct(6.6)}{{transform:scaleX(0);opacity:1}}{pct(8.3)}{{transform:scaleX(1);opacity:1}}"
               f"{pct(8.6)},100%{{transform:scaleX(1);opacity:0}}}}"
               f".prog{{animation:prog {T}s linear infinite;transform-box:fill-box;transform-origin:0 50%}}")
    out.append(f'<rect class="prog" x="{px0 + 24}" y="{y + 12}" width="{pw - 48}" height="3" fill="{p["ink"]}"/>')
    y += 44
    out.append(f'<g class="{show("m7", 8.8)}"><rect x="{px0 + 24}" y="{y - 20}" width="{pw - 48}" height="56" fill="none" stroke="{p["line"]}" stroke-width="1.2" stroke-dasharray="3 4"/>'
               f'{sans(px0 + 40, y, "Task handoff (re-injected after compaction)", 14, p["ink"], weight=600)}'
               f'{sans(px0 + 40, y + 22, "Next step: drop the old billing columns once the backfill is checked.", 14, p["soft"])}</g>')
    # toasts, top right of the session
    tx, ty = px0 + pw - 16, py0 + 30
    for cls, t_in, t_out in (("t1", 4.95, 8.3), ("t2", 8.45, 12.9)):
        css.append(f"@keyframes {cls}{{0%,{pct(t_in)}{{opacity:0;transform:translateY(-8px)}}{pct(t_in + 0.3)},{pct(t_out)}{{opacity:1;transform:translateY(0)}}"
                   f"{pct(t_out + 0.25)},100%{{opacity:0;transform:translateY(0)}}}}.{cls}{{animation:{cls} {T}s cubic-bezier(.23,1,.32,1) infinite;transform-box:fill-box}}")

    def toast(cls, text, sub):
        tw = 330
        return (f'<g class="{cls}"><rect x="{tx - tw}" y="{ty}" width="{tw}" height="58" fill="{p["paper"]}" stroke="{p["ink"]}" stroke-width="1.2"/>'
                f'<rect x="{tx - tw}" y="{ty}" width="5" height="58" fill="{p["magenta"]}"/>'
                f'{sans(tx - tw + 20, ty + 24, text, 14.5, p["ink"], weight=600)}{sans(tx - tw + 20, ty + 45, sub, 13, p["soft"])}</g>')

    out.append(toast("t1", "Task wrapped up at 780k", "compacting in a moment (1.5 s to cancel)"))
    out.append(toast("t2", "Compacted: 780k to 123k", "summary saved, handoff back in"))

    # --- right: the tide staff -----------------------------------------------------------------
    sx, top, bot = 836, 100, 560
    out.append(L.text("context", sx - 20, py0 + 4, 14, p["soft"], weight=0.13, tracking=0.26))
    span = bot - top
    lvl = lambda v: bot - v * span  # noqa: E731  (v as a share of 1M)
    out.append(f'<rect x="{sx}" y="{top}" width="44" height="{span}" fill="none" stroke="{p["ink"]}" stroke-width="1.2"/>')
    for k in range(0, 11):
        yk = lvl(k / 10)
        out.append(f'<line x1="{sx + 44}" y1="{yk:.1f}" x2="{sx + (60 if k % 5 == 0 else 52)}" y2="{yk:.1f}" stroke="{p["ink"]}" stroke-width="1.2"/>')
        if k % 2 == 0:
            label = "1m" if k == 10 else f"{k * 100}k" if k else "0"
            out.append(L.text(label, sx + 68, yk + 6, 11.5, p["soft"], weight=0.14, tracking=0.24))
    # the water in the staff: rises with the task, goes out at the compaction
    levels = [(0.0, 0.123), (1.0, 0.31), (2.0, 0.52), (3.0, 0.69), (4.0, 0.76), (4.7, 0.78), (8.3, 0.78), (8.9, 0.123), (13.6, 0.123)]
    frames = "".join(f"{pct(t)}{{transform:scaleY({v / 0.78:.4f})}}" for t, v in levels)
    css.append(f"@keyframes lvl{{{frames}}}.lvl{{animation:lvl {T}s cubic-bezier(.77,0,.175,1) infinite;transform-box:fill-box;transform-origin:50% 100%}}")
    out.append(f'<rect class="lvl" x="{sx + 1}" y="{lvl(0.78):.1f}" width="42" height="{bot - lvl(0.78):.1f}" fill="{p["water2"]}"/>')
    out.append(f'<line x1="{sx - 14}" y1="{lvl(0.78):.1f}" x2="{sx + 44}" y2="{lvl(0.78):.1f}" stroke="{p["magenta"]}" stroke-width="1.4" stroke-dasharray="3 3"/>')
    # the readout, written with the pen; each value shows until the next one
    reads = [(0.0, "123k"), (1.0, "310k"), (2.0, "520k"), (3.0, "690k"), (4.0, "760k"), (4.7, "780k"), (8.9, "123k")]
    for i, (t0, label) in enumerate(reads):
        t1 = reads[i + 1][0] if i + 1 < len(reads) else T
        cls = f"r{i}"
        if t0 == 0:
            frames = f"0%,{pct(t1 - 0.01)}{{opacity:1}}{pct(t1)},100%{{opacity:0}}"
        else:
            frames = f"0%,{pct(t0 - 0.01)}{{opacity:0}}{pct(t0)},{pct(t1 - 0.01)}{{opacity:1}}{pct(t1)},100%{{opacity:0}}"
        css.append(f"@keyframes {cls}{{{frames}}}.{cls}{{animation:{cls} {T}s linear infinite}}")
        colour = p["magenta"] if label == "780k" else p["ink"]
        out.append(f'<g class="{cls}">{L.text(label, 972, 330, 46, colour, weight=0.1, tracking=0.16)}</g>')
    out.append(L.text("tokens of context", 974, 368, 11.5, p["soft"], weight=0.14, tracking=0.26))
    out.append(L.text("first live run: 779,856", 974, 404, 11.5, p["soft"], weight=0.14, tracking=0.26))
    out.append(L.text("before, 122,599 on the", 974, 426, 11.5, p["soft"], weight=0.14, tracking=0.26))
    out.append(L.text("turn after (31 oct 2026)", 974, 448, 11.5, p["soft"], weight=0.14, tracking=0.26))
    out.append(sans(64, 650, "Illustration of the flow, not a screen recording. The numbers are from the first live run, 31 Oct 2026.", 14, p["soft"]))
    style = "<style>" + "".join(css) + "@media (prefers-reduced-motion: reduce){*{animation:none!important}}</style>"
    return sheet(w, h, p, style + "".join(out), "Illustration: the model ends a task with Ready to compact., the mod queues /compact after 1.5 s, the context goes from 780k to 123k and the handoff is put back")


def icon(size=512):
    """The plugin icon: three teeth of the trace on navy, the drops in magenta."""
    p = PALETTES["light"]
    s = size / 512
    x0, x1, base, peak = 92 * s, 420 * s, 360 * s, 150 * s
    teeth = 3
    tw = (x1 - x0) / teeth
    line = [(x0, base)]
    dots = []
    for t in range(teeth):
        line.append((x0 + tw * (t + 1), peak + t * 18 * s))
        line.append((x0 + tw * (t + 1), base))
        dots.append((x0 + tw * (t + 1), base))
    body = (f'<rect width="{size}" height="{size}" rx="{96 * s:.0f}" fill="{p["ink"]}"/>'
            f'<line x1="{x0}" y1="{120 * s}" x2="{x1}" y2="{120 * s}" stroke="#5B7790" stroke-width="{6 * s}" stroke-dasharray="{4 * s} {16 * s}" stroke-linecap="round"/>'
            f'<polygon points="{pts(line + [(x1, base + 2 * s), (x0, base + 2 * s)])}" fill="#1F4A6B"/>'
            f'<polyline points="{pts(line)}" fill="none" stroke="#F4F7F7" stroke-width="{22 * s}" stroke-linejoin="round" stroke-linecap="round"/>'
            + "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{20 * s}" fill="{PALETTES["dark"]["magenta"]}" stroke="{p["ink"]}" stroke-width="{8 * s}"/>' for x, y in dots))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">{body}</svg>\n'


def render_png(svg_path, png_path, w, h, browser=None):
    """Renders an SVG to PNG at its own size, with Playwright or a headless Chrome/Edge."""
    url = "file:///" + svg_path.replace("\\", "/")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(**({"executable_path": browser} if browser else {}))
            page = b.new_page(viewport={"width": w, "height": h})
            page.goto(url)
            page.screenshot(path=png_path, omit_background=True)
            b.close()
        return
    except ImportError:
        pass
    exe = browser or shutil.which("chrome") or shutil.which("msedge") or shutil.which("chromium")
    if not exe:
        sys.exit("--png needs Playwright (pip install playwright) or a Chrome/Edge path in --browser")
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={w},{h}", f"--screenshot={png_path}", url], check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true", help="also render social-preview.png and the plugin icon")
    ap.add_argument("--browser", help="path to chrome.exe or msedge.exe, if Playwright's own browser is not installed")
    ap.add_argument("--figures", help="JSON with the figures for before-after.svg (see FIGURES)")
    a = ap.parse_args()
    fig = dict(FIGURES)
    if a.figures:
        with open(a.figures, encoding="utf-8") as f:
            fig.update(json.load(f))
    made = []

    def write(name, text):
        ElementTree.fromstring(text)  # GitHub shows nothing for an SVG that is not well-formed XML
        path = os.path.join(HERE, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        made.append(path)
        return path

    for mode, p in PALETTES.items():
        write(f"banner-{mode}.svg", banner(p))
        write(f"flow-{mode}.svg", flow(p))
        write(f"before-after-{mode}.svg", before_after(p, fig))
        write(f"demo-{mode}.svg", demo(p))
    social_svg = write("social-preview.svg", social(PALETTES["light"]))
    icon_svg = write("icon.svg", icon())
    if a.png:
        png = os.path.join(HERE, "social-preview.png")
        render_png(social_svg, png, 1280, 640, a.browser)
        made.append(png)
        icon_png = os.path.abspath(os.path.join(HERE, "..", "plugin", ".claude-plugin", "icon.png"))
        render_png(icon_svg, icon_png, 512, 512, a.browser)
        made.append(icon_png)
    print("\n".join(made))


if __name__ == "__main__":
    sys.exit(main())
