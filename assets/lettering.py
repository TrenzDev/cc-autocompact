"""A single-stroke lettering for the README images, drawn as pen paths.

The images are a tide record of the context: a pen trace on chart paper. The lettering is written
with the same pen, so the name, the figures and the labels belong to the drawing. It is geometric
and monoline (circles, arcs and straight strokes with round caps), like the lettering of a pen
plotter or a technical drawing, and it renders the same everywhere because it is paths, not a font.

Units: x-height = 1, baseline at y = 0, y grows upwards. Ascenders and figures reach 1.4.
Lowercase, figures and a little punctuation: that is all the images use.
"""
import math

ASC = 1.4   # ascender and figure height
DESC = -0.42


def arc(cx, cy, rx, ry, a0, a1, step=6.0):
    """Points along an elliptical arc from angle a0 to a1 (degrees, counter-clockwise positive)."""
    n = max(2, int(abs(a1 - a0) / step) + 1)
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / (n - 1))),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / (n - 1)))) for i in range(n)]


def circle(cx, cy, r, ry=None):
    return arc(cx, cy, r, ry if ry is not None else r, 90, 450)


def dot(x, y):
    return [(x, y), (x, y)]


# Each glyph: (advance, [stroke, ...]); a stroke is a list of points
G = {}

G["o"] = (1.0, [circle(0.5, 0.5, 0.5)])
G["c"] = (0.9, [arc(0.5, 0.5, 0.5, 0.5, 42, 318)])
G["e"] = (1.0, [[(0.02, 0.5), (1.0, 0.5)] + arc(0.5, 0.5, 0.5, 0.5, 0, 318)[1:]])
G["a"] = (1.0, [circle(0.5, 0.5, 0.5), [(1.0, 1.0), (1.0, 0.0)]])
G["d"] = (1.0, [circle(0.5, 0.5, 0.5), [(1.0, ASC), (1.0, 0.0)]])
G["b"] = (1.0, [[(0.0, ASC), (0.0, 0.0)], circle(0.5, 0.5, 0.5)])
G["p"] = (1.0, [[(0.0, 1.0), (0.0, DESC)], circle(0.5, 0.5, 0.5)])
G["q"] = (1.0, [circle(0.5, 0.5, 0.5), [(1.0, 1.0), (1.0, DESC)]])
G["g"] = (1.0, [circle(0.5, 0.5, 0.5), [(1.0, 1.0), (1.0, -0.06)] + arc(0.5, -0.06, 0.5, 0.36, 0, -150)[1:]])
G["n"] = (1.0, [[(0.0, 1.0), (0.0, 0.0)], [(0.0, 0.5)] + arc(0.5, 0.5, 0.5, 0.5, 180, 0)[1:] + [(1.0, 0.0)]])
G["h"] = (1.0, [[(0.0, ASC), (0.0, 0.0)], [(0.0, 0.5)] + arc(0.5, 0.5, 0.5, 0.5, 180, 0)[1:] + [(1.0, 0.0)]])
G["m"] = (1.56, [[(0.0, 1.0), (0.0, 0.0)],
                 [(0.0, 0.61)] + arc(0.39, 0.61, 0.39, 0.39, 180, 0)[1:] + [(0.78, 0.0)],
                 [(0.78, 0.61)] + arc(1.17, 0.61, 0.39, 0.39, 180, 0)[1:] + [(1.56, 0.0)]])
G["u"] = (1.0, [[(0.0, 1.0), (0.0, 0.5)] + arc(0.5, 0.5, 0.5, 0.5, 180, 360)[1:], [(1.0, 1.0), (1.0, 0.0)]])
G["r"] = (0.72, [[(0.0, 1.0), (0.0, 0.0)], [(0.0, 0.5)] + arc(0.5, 0.5, 0.5, 0.5, 180, 72)[1:]])
G["t"] = (0.72, [[(0.24, ASC - 0.1), (0.24, 0.3)] + arc(0.54, 0.3, 0.3, 0.3, 180, 270)[1:] + [(0.72, 0.0)],
                 [(0.0, 1.0), (0.66, 1.0)]])
G["f"] = (0.7, [[(0.26, 0.0), (0.26, 1.08)] + arc(0.6, 1.08, 0.34, 0.32, 180, 50)[1:], [(0.0, 1.0), (0.66, 1.0)]])
G["l"] = (0.3, [[(0.15, ASC), (0.15, 0.0)]])
G["i"] = (0.3, [[(0.15, 1.0), (0.15, 0.0)], dot(0.15, 1.34)])
G["j"] = (0.55, [[(0.4, 1.0), (0.4, -0.08)] + arc(0.12, -0.08, 0.28, 0.32, 0, -110)[1:], dot(0.4, 1.34)])
G["k"] = (0.86, [[(0.0, ASC), (0.0, 0.0)], [(0.82, 1.0), (0.0, 0.36)], [(0.3, 0.6), (0.86, 0.0)]])
G["s"] = (0.78, [arc(0.39, 0.745, 0.36, 0.255, 28, 270) + arc(0.39, 0.255, 0.39, 0.255, 90, -152)[1:]])
G["v"] = (0.92, [[(0.0, 1.0), (0.46, 0.0), (0.92, 1.0)]])
G["w"] = (1.44, [[(0.0, 1.0), (0.36, 0.0), (0.72, 1.0), (1.08, 0.0), (1.44, 1.0)]])
G["x"] = (0.86, [[(0.0, 1.0), (0.86, 0.0)], [(0.0, 0.0), (0.86, 1.0)]])
G["y"] = (0.92, [[(0.0, 1.0), (0.46, 0.0)], [(0.92, 1.0), (0.3, DESC)]])
G["z"] = (0.84, [[(0.02, 1.0), (0.84, 1.0), (0.0, 0.0), (0.84, 0.0)]])

# Lining figures, 1.4 tall
G["0"] = (0.9, [circle(0.45, 0.7, 0.45, 0.7)])
G["1"] = (0.62, [[(0.06, 1.12), (0.42, ASC), (0.42, 0.0)]])
G["2"] = (0.88, [arc(0.44, 1.0, 0.42, 0.4, 158, -28) + [(0.02, 0.0), (0.88, 0.0)]])
G["3"] = (0.88, [arc(0.42, 1.05, 0.38, 0.35, 150, -90) + arc(0.44, 0.37, 0.44, 0.37, 90, -150)[1:]])
G["4"] = (0.92, [[(0.68, 0.0), (0.68, ASC), (0.0, 0.42), (0.92, 0.42)]])
G["5"] = (0.88, [[(0.8, ASC), (0.1, ASC), (0.05, 0.78)] + arc(0.43, 0.45, 0.45, 0.45, 132, -148)[1:]])
G["6"] = (0.9, [[(0.64, ASC), (0.1, 0.66)], circle(0.45, 0.45, 0.45)])
G["7"] = (0.86, [[(0.0, ASC), (0.86, ASC), (0.26, 0.0)]])
G["8"] = (0.88, [circle(0.44, 1.06, 0.34), circle(0.44, 0.38, 0.4, 0.38)])
G["9"] = (0.9, [circle(0.45, 0.95, 0.45), [(0.8, 0.74), (0.26, 0.0)]])

# Punctuation and signs
G[" "] = (0.5, [])
G["."] = (0.22, [dot(0.11, 0.0)])
G[","] = (0.22, [[(0.13, 0.02), (0.02, -0.24)]])
G[":"] = (0.22, [dot(0.11, 0.0), dot(0.11, 0.86)])
G["-"] = (0.56, [[(0.04, 0.5), (0.52, 0.5)]])
G["/"] = (0.7, [[(0.0, -0.1), (0.7, ASC)]])
G["%"] = (1.12, [circle(0.24, 1.14, 0.24, 0.26), [(0.0, 0.0), (1.12, ASC)], circle(0.88, 0.26, 0.24, 0.26)])
G["'"] = (0.2, [[(0.1, ASC), (0.1, 1.06)]])
G["("] = (0.42, [arc(1.06, 0.49, 1.0, 1.385, 140, 220)])
G[")"] = (0.42, [arc(-0.64, 0.49, 1.0, 1.385, 40, -40)])
G[">"] = (0.8, [[(0.04, 1.0), (0.76, 0.5), (0.04, 0.0)]])
G["<"] = (0.8, [[(0.76, 1.0), (0.04, 0.5), (0.76, 0.0)]])
G["~"] = (0.9, [arc(0.225, 0.45, 0.225, 0.14, 180, 0) + arc(0.675, 0.45, 0.225, 0.14, 180, 360)[1:]])
G["→"] = (1.1, [[(0.0, 0.5), (1.06, 0.5)], [(0.74, 0.8), (1.06, 0.5), (0.74, 0.2)]])
G["×"] = (0.7, [[(0.05, 0.85), (0.65, 0.15)], [(0.05, 0.15), (0.65, 0.85)]])


# Every glyph is drawn on a round grid, then condensed: the circles become upright ellipses, which
# reads as technical lettering rather than a rounded display face
HSCALE = 0.86


def width(text, size, tracking=0.2):
    """Width in px of `text` with x-height `size`."""
    total = 0.0
    for i, ch in enumerate(text):
        total += G.get(ch, G[" "])[0] * HSCALE * size
        if i < len(text) - 1:
            total += tracking * size
    return total


def path(text, x, y, size, tracking=0.2, skew=0.0, anchor="start"):
    """SVG path data for `text`, baseline at y, x-height `size` px. skew in units of x per unit of height."""
    w = width(text, size, tracking)
    if anchor == "middle":
        x -= w / 2
    elif anchor == "end":
        x -= w
    out = []
    cursor = x
    for ch in text:
        adv, strokes = G.get(ch, G[" "])
        for stroke in strokes:
            pts = [(cursor + (px * HSCALE + skew * py) * size, y - py * size) for px, py in stroke]
            out.append("M" + " L".join(f"{px:.2f} {py:.2f}" for px, py in pts))
        cursor += (adv * HSCALE + tracking) * size
    return " ".join(out)


def text(s, x, y, size, color, weight=0.12, tracking=0.2, skew=0.0, anchor="start", extra=""):
    """A <path> element that writes `s`. weight = stroke width as a share of the x-height."""
    return (f'<path d="{path(s, x, y, size, tracking, skew, anchor)}" fill="none" stroke="{color}" '
            f'stroke-width="{weight * size:.2f}" stroke-linecap="round" stroke-linejoin="round"{extra}/>')
