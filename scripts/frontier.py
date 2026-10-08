#!/usr/bin/env python3
"""Chart two runs' level ladders per input as speed against size frontiers.

One small panel per input the runs share, cpu time across and compressed
size up, each run's levels joined into a ladder with the level numbers on
the points. A change is good where it moves a point down or to the left.
A point that the other run beats on both axes at any level is ringed,
since that run already offers a better trade through its level knob,
which the per-level grids cannot see. Time is compared beyond the noise
rule the grids use, sizes are exact.

Usage:
    python3 scripts/frontier.py base.json head.json [-o out.svg]
        [--filter regex] [--names a,b] [--title text] [--levels 2-6]
        [--columns 4]

Works with both single-iteration and aggregated (--benchmark_repetitions)
JSON outputs; for aggregated runs the median row is used for each benchmark.
The ringed points are also listed on stdout.
"""
import argparse
import os
import re
import sys

from compare_inputs import display, input_rows, order_inputs, run_warnings
from compare_levels import NOISE_CVS, NOISE_FLOOR, commit, parse_levels
from graph_runs import GRID, INK, INK_SOFT, SERIES, Svg, footnote, load, machine_line

PANEL_W, PANEL_H = 250, 170
PAD_L, PAD_R, PAD_T, PAD_B = 46, 14, 26, 42
GAP_X, GAP_Y = 26, 22


def noise(p, q):
    """Fraction of time two points must differ by to count as different."""
    return max(NOISE_FLOOR / 100, NOISE_CVS * max(p.get("cv", 0.0), q.get("cv", 0.0)))


def beaten(p, others):
    """The level of a point in others at least as small and clearly faster, or None."""
    for level, q in sorted(others.items()):
        if q["size"] <= p["size"] and q["time"] <= p["time"] * (1 - noise(p, q)):
            if q["size"] < p["size"] or q["time"] < p["time"]:
                return level
    return None


def fmt_time(secs):
    us = secs * 1e6
    if us >= 10000:
        return f"{us / 1000:.0f} ms"
    if us >= 1000:
        return f"{us / 1000:.1f} ms"
    return f"{us:.0f} µs"


def fmt_size(n):
    if n >= 1048576:
        return f"{n / 1048576:.2f} MB"
    if n >= 10240:
        return f"{n / 1024:.0f} KB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n:.0f} B"


def ticks(lo, hi, n=3):
    span = hi - lo
    if span <= 0:
        return [lo]
    step = span / (n - 1)
    return [lo + i * step for i in range(n)]


def panel(svg, x0, y0, label, levels, ladders, names, rings):
    """One frontier panel, ladders maps a run index to {level: point}."""
    pts = [p for ladder in ladders.values() for p in ladder.values()]
    tmin, tmax = min(p["time"] for p in pts), max(p["time"] for p in pts)
    smin, smax = min(p["size"] for p in pts), max(p["size"] for p in pts)
    tpad = (tmax - tmin) * 0.12 or tmax * 0.05
    spad = (smax - smin) * 0.12 or smax * 0.05
    tlo, thi = max(0.0, tmin - tpad), tmax + tpad
    slo, shi = max(0.0, smin - spad), smax + spad
    px, py = x0 + PAD_L, y0 + PAD_T
    pw, ph = PANEL_W - PAD_L - PAD_R, PANEL_H - PAD_T - PAD_B

    def sx(t):
        return px + (t - tlo) / (thi - tlo) * pw

    def sy(s):
        return py + ph - (s - slo) / (shi - slo) * ph

    svg.text(x0 + PAD_L, y0 + 14, display(label), 12, INK, weight="bold")
    # which way is better, on every panel so none is read without it
    svg.text(x0 + PANEL_W - PAD_R, y0 + 14, "\u2193 smaller", 9, INK_SOFT, anchor="end")
    svg.text(px, py + ph + 28, "\u2190 faster", 9, INK_SOFT)
    svg.add(f'<rect x="{px:.1f}" y="{py:.1f}" width="{pw:.1f}" height="{ph:.1f}" fill="none" '
            f'stroke="{GRID}" stroke-width="1"/>')
    for t in ticks(tlo, thi):
        svg.line(sx(t), py, sx(t), py + ph, GRID, 0.5)
        svg.text(sx(t), py + ph + 14, fmt_time(t), 9, INK_SOFT, anchor="middle")
    for s in ticks(slo, shi):
        svg.line(px, sy(s), px + pw, sy(s), GRID, 0.5)
        svg.text(px - 4, sy(s) + 3, fmt_size(s), 9, INK_SOFT, anchor="end")
    for i, ladder in ladders.items():
        color = SERIES[i]
        seq = [ladder[l] for l in levels if l in ladder]
        path = " ".join(f"{'M' if k == 0 else 'L'}{sx(p['time']):.1f},{sy(p['size']):.1f}"
                        for k, p in enumerate(seq))
        if len(seq) > 1:
            svg.add(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
                    f'stroke-linejoin="round" stroke-opacity="0.85"/>')
        for level in levels:
            if level not in ladder:
                continue
            p = ladder[level]
            cx, cy = sx(p["time"]), sy(p["size"])
            svg.add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{color}" '
                    f'stroke="{GRID}" stroke-width="1"/>')
            by = rings.get((i, level))
            if by is not None:
                svg.add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="none" '
                        f'stroke="{SERIES[1 - i]}" stroke-width="1.5"/>')
            # base labels sit above right, head labels below left, so coincident
            # points of the two runs keep both numbers legible
            if i == 0:
                svg.text(cx + 7, cy - 5, str(level), 9, INK_SOFT)
            else:
                svg.text(cx - 7, cy + 12, str(level), 9, INK_SOFT, anchor="end")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jsons", nargs=2, help="two benchmark JSON outputs, the reference run first")
    ap.add_argument("-o", "--output", default=None, help="output SVG path")
    ap.add_argument("--filter", default=None, help="regex applied to input names")
    ap.add_argument("--names", default=None, help="comma-separated run names")
    ap.add_argument("--title", default=None, help="chart title")
    ap.add_argument("--levels", default=None, help="levels to keep, such as 2-6 or 1,6,9")
    ap.add_argument("--columns", type=int, default=4, help="panels per row")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    runs = [load(p) for p in args.jsons]
    names = [r[0] for r in runs]
    if len(set(names)) < len(names):
        names = [os.path.splitext(os.path.basename(p))[0] for p in args.jsons]
    if args.names:
        for i, given in enumerate(args.names.split(",")[:len(names)]):
            if given:
                names[i] = given
    versions = [r[1] for r in runs]
    machine = machine_line([r[3] for r in runs])

    rows = [input_rows(r[2]) for r in runs]
    flt = re.compile(args.filter) if args.filter else None
    labels = [l for l in order_inputs(set(rows[0]) & set(rows[1])) if not flt or flt.search(l)]
    levels = sorted({level for l in labels for level in set(rows[0][l]) & set(rows[1][l])})
    if args.levels is not None:
        try:
            keep = parse_levels(args.levels)
        except ValueError:
            ap.error(f"cannot read levels from {args.levels!r}, expected a form like 2-6 or 1,6,9")
        levels = [level for level in levels if level in keep]
    labels = [l for l in labels if any(level in rows[0][l] and level in rows[1][l] for level in levels)]
    if not labels:
        print("No codec_deflate inputs and levels in common.", file=sys.stderr)
        sys.exit(1)

    cols = max(1, args.columns)
    nrows = (len(labels) + cols - 1) // cols
    width = 16 + cols * PANEL_W + (cols - 1) * GAP_X + 16
    top = 100
    svg = Svg(width)
    title = args.title or f"{names[1]} against {names[0]}, speed against size by input"
    svg.text(16, 30, title, 20, INK, weight="bold")
    sub = f"{names[0]} {commit(versions[0])} · {names[1]} {commit(versions[1])} · levels " \
          f"{', '.join(str(l) for l in levels)}, cpu time across, compressed size up, lower left " \
          f"is better, a ring marks a point the other run beats on both axes"
    svg.text(16, 50, sub, 12, INK_SOFT)
    ly = 72
    for i in (0, 1):
        x = 16 + i * 150
        svg.add(f'<rect x="{x}" y="{ly - 9}" width="14" height="10" rx="2" fill="{SERIES[i]}"/>')
        svg.text(x + 20, ly, names[i], 11, INK)
    svg.text(16 + 300, ly, "ring: beaten by the other run on both axes, time beyond "
             f"{NOISE_FLOOR:.0f}% and {NOISE_CVS} times the repetition cv", 10.5, INK_SOFT)

    beaten_list = []
    for k, label in enumerate(labels):
        ladders = {i: {l: rows[i][label][l] for l in levels if l in rows[i][label]} for i in (0, 1)}
        rings = {}
        for i in (0, 1):
            for level, p in ladders[i].items():
                by = beaten(p, ladders[1 - i])
                if by is not None:
                    rings[(i, level)] = by
                    beaten_list.append((display(label), names[i], level, names[1 - i], by))
        x0 = 16 + (k % cols) * (PANEL_W + GAP_X)
        y0 = top + (k // cols) * (PANEL_H + GAP_Y)
        panel(svg, x0, y0, label, levels, ladders, names, rings)

    body_bottom = top + nrows * (PANEL_H + GAP_Y) - GAP_Y + 8
    warnings = run_warnings(names, runs)
    height = footnote(svg, names, versions, machine, warnings, body_bottom)
    out = args.output or re.sub(r"[^\w.-]+", "_", "_vs_".join(names)) + "_frontier.svg"
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg.finish(height))

    if beaten_list:
        print("points beaten on both axes:")
        for label, run, level, other, by in beaten_list:
            print(f"  {label:16s} {run} level {level} by {other} level {by}")
    else:
        print("no point is beaten on both axes")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
