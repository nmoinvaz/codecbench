#!/usr/bin/env python3
"""Chart how the price of each symbol changed between two runs, per input.

One row per input the runs share at one level, four columns: bits per
literal, bits per match length code, bits per match distance code and
bits per byte a match produces. Each cell is a bar of the change from the
reference run, cheaper in one hue and dearer in the other, on one
symmetric scale per column, with the two absolute prices written beside
it. Paired bars of the prices themselves differ by a few percent at most
and show nothing, the change is what a matcher tuning moves. Needs the
bits_* counters codecbench emits from its stream walker.

Usage:
    python3 scripts/symbol_cost.py base.json head.json --level 2
        [-o out.svg] [--filter regex] [--names a,b] [--title text]

Sizes are deterministic, so single-iteration runs are enough. The prices
are also printed to stdout.
"""
import argparse
import math
import os
import re
import sys

from compare_inputs import BETTER, WORSE, display, order_inputs
from compare_levels import commit, text_width
from graph_runs import GRID, INK, INK_SOFT, Svg, footnote, load, machine_line
from stream_anatomy import stream_rows

COLUMNS = [("bits per literal", "literal"), ("bits per length code", "length"),
           ("bits per distance code", "distance"), ("bits per match byte", "match_byte")]
LABEL_W, CELL_W, GAP = 150, 196, 22
ROW_H, BAR_H = 34, 10


def costs(b):
    """Per-symbol prices of one benchmark row, None where the class is absent."""
    lit, matches, mbytes = b.get("lit_syms", 0.0), b.get("match_syms", 0.0), b.get("match_bytes", 0.0)
    return {
        "literal": b["bits_lit"] / lit if lit else None,
        "length": b["bits_len"] / matches if matches else None,
        "distance": b["bits_dist"] / matches if matches else None,
        "match_byte": (b["bits_len"] + b["bits_dist"]) / mbytes if mbytes else None,
        "match_len": mbytes / matches if matches else None,
    }


def nice(v):
    """A round number at or above v, for a symmetric scale."""
    if v <= 0:
        return 0.1
    step = 10 ** math.floor(math.log10(v))
    return next(m * step for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if m * step >= v)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jsons", nargs=2, help="two benchmark JSON outputs, the reference run first")
    ap.add_argument("--level", type=int, required=True, help="deflate level to chart")
    ap.add_argument("-o", "--output", default=None, help="output SVG path")
    ap.add_argument("--filter", default=None, help="regex applied to input names")
    ap.add_argument("--names", default=None, help="comma-separated run names")
    ap.add_argument("--title", default=None, help="chart title")
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

    rows = [stream_rows(r[2]) for r in runs]
    flt = re.compile(args.filter) if args.filter else None
    labels = [l for l in order_inputs(set(rows[0]) & set(rows[1]))
              if (not flt or flt.search(l)) and args.level in rows[0][l] and args.level in rows[1][l]
              and "bits_lit" in rows[0][l][args.level] and "bits_lit" in rows[1][l][args.level]]
    if not labels:
        print("No inputs with stream counters at that level in common.", file=sys.stderr)
        sys.exit(1)
    pairs = {l: [costs(rows[i][l][args.level]) for i in (0, 1)] for l in labels}

    def delta(label, key):
        c0, c1 = pairs[label]
        return None if c0[key] is None or c1[key] is None else c1[key] - c0[key]

    scales = {key: nice(max((abs(delta(l, key) or 0.0) for l in labels), default=0.0) * 1.05)
              for _, key in COLUMNS}

    width = 16 + LABEL_W + len(COLUMNS) * CELL_W + (len(COLUMNS) - 1) * GAP + 16
    top = 120
    svg = Svg(width)
    title = args.title or f"{names[1]} against {names[0]}, cost per symbol at level {args.level}"
    svg.text(16, 30, title, 20, INK, weight="bold")
    svg.text(16, 50, f"{names[0]} {commit(versions[0])} · {names[1]} {commit(versions[1])} · each bar "
             f"is the change in {names[1]} from {names[0]}, the figures beside it are the two prices",
             12, INK_SOFT)
    kx = 16 + LABEL_W
    for hue, meaning in ((BETTER, f"cheaper in {names[1]}"), (WORSE, f"dearer in {names[1]}")):
        svg.add(f'<rect x="{kx}" y="62" width="22" height="12" rx="3" fill="{hue}" fill-opacity="0.6"/>')
        svg.text(kx + 28, 72, meaning, 11, INK)
        kx += 28 + text_width(meaning, 11) + 22
    cx = [16 + LABEL_W + k * (CELL_W + GAP) for k in range(len(COLUMNS))]
    for x, (heading, key) in zip(cx, COLUMNS):
        svg.text(x + CELL_W / 2, top - 22, heading, 12, INK, anchor="middle", weight="bold")
        svg.text(x + CELL_W / 2, top - 8, f"±{scales[key]:g} b full scale", 9.5, INK_SOFT, anchor="middle")

    print(f"level {args.level}, cost per symbol, {names[0]} then {names[1]}")
    print(f"{'input':16s} {'bits/literal':>14s} {'bits/length':>14s} {'bits/distance':>14s} "
          f"{'bits/match byte':>16s} {'bytes/match':>14s}")
    for r, label in enumerate(labels):
        y = top + r * ROW_H
        c0, c1 = pairs[label]
        svg.text(cx[0] - 10, y + 12, display(label), 12, INK, anchor="end", weight="bold")
        if c0["match_len"] is not None and c1["match_len"] is not None:
            svg.text(cx[0] - 10, y + 26, f"{c0['match_len']:.1f} → {c1['match_len']:.1f} B per match",
                     10, INK_SOFT, anchor="end")
        for x, (_, key) in zip(cx, COLUMNS):
            mid = x + CELL_W / 2
            svg.line(mid, y + 2, mid, y + ROW_H - 6, GRID, 1)
            d = delta(label, key)
            if d is None:
                continue
            w = abs(d) / scales[key] * (CELL_W / 2 - 4)
            if w > 0.5:
                bx = mid - w if d < 0 else mid
                svg.add(f'<rect x="{bx:.1f}" y="{y + 4}" width="{w:.1f}" height="{BAR_H}" rx="2" '
                        f'fill="{BETTER if d < 0 else WORSE}" fill-opacity="0.75"/>')
            svg.text(mid, y + 26, f"{c0[key]:.2f} → {c1[key]:.2f}", 9.5, INK_SOFT, anchor="middle")

        def f(v, digits=2):
            return "-" if v is None else f"{v:.{digits}f}"
        print(f"{display(label):16s} {f(c0['literal']):>6s} {f(c1['literal']):>7s} "
              f"{f(c0['length']):>6s} {f(c1['length']):>7s} {f(c0['distance']):>6s} {f(c1['distance']):>7s} "
              f"{f(c0['match_byte']):>7s} {f(c1['match_byte']):>8s} "
              f"{f(c0['match_len'], 1):>6s} {f(c1['match_len'], 1):>7s}")

    body_bottom = top + len(labels) * ROW_H
    svg.text(16 + LABEL_W, body_bottom + 14, "a literal is one byte, so its bits per symbol are also its "
             "bits per byte, the last column is the match side of that comparison", 10.5, INK_SOFT)
    height = footnote(svg, names, versions, machine, [], body_bottom + 22)
    out = args.output or re.sub(r"[^\w.-]+", "_", "_vs_".join(names)) + f"_cost_l{args.level}.svg"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg.finish(height))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
