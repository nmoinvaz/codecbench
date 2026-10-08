#!/usr/bin/env python3
"""Break two runs' deflate streams down by what the bits were spent on.

For every input the runs share, at one level, a pair of stacked bars of
the bits spent on literals, match lengths, match distances, stored bytes
and block overhead, the head bar drawn under the base bar at the same
scale so the class that moved stands out. Beside them the match mix by
distance and by length, so a hashing change shows whether it found
longer matches, nearer matches or fewer literals. Needs the bits_* and
dist_*, len_* counters codecbench emits from its stream walker.

Usage:
    python3 scripts/stream_anatomy.py base.json head.json --level 2
        [-o out.svg] [--filter regex] [--names a,b] [--title text]

Sizes are deterministic, so single-iteration runs are enough. The per
class bits and the mixes are also printed to stdout.
"""
import argparse
import os
import re
import sys

from compare_inputs import display, order_inputs
from compare_levels import commit
from graph_runs import GRID, INK, INK_SOFT, SERIES, Svg, collect, esc, footnote, load, machine_line

CLASSES = [("literals", "bits_lit", SERIES[0]), ("lengths", "bits_len", SERIES[2]),
           ("distances", "bits_dist", SERIES[1]), ("stored", "bits_stored", SERIES[3]),
           ("overhead", "bits_hdr", SERIES[9])]
DIST_BUCKETS = [("≤4", "dist_le4"), ("≤32", "dist_le32"), ("≤256", "dist_le256"),
                ("≤4K", "dist_le4k"), (">4K", "dist_gt4k")]
LEN_BUCKETS = [("≤4", "len_le4"), ("≤8", "len_le8"), ("≤16", "len_le16"),
               ("≤64", "len_le64"), (">64", "len_gt64")]
# One hue light to dark per mix, far distances and long matches darkest
DIST_RAMP = ["#d6e4f7", "#a9c6ee", "#73a4e3", "#3f7fd3", "#1f5aa8"]
LEN_RAMP = ["#cdeedd", "#9cdcbc", "#62c497", "#2aa872", "#157a50"]

LABEL_W, BAR_W, MIX_W, GAP = 170, 380, 200, 112
ROW_H, BAR_H = 50, 13


def stream_rows(benchmarks):
    """{input: {level: benchmark dict}} over the plain deflate levels of one run."""
    deflate, _, _, deflate_data, _, _, _, _ = collect(benchmarks, None)
    rows = {}
    for (level, strategy), files in deflate.items():
        if not strategy:
            for label, b in files.items():
                rows.setdefault(label, {})[level] = b
    for (data_type, level), b in deflate_data.items():
        rows.setdefault(f"data/{data_type}", {})[level] = b
    return rows


def bits(b):
    return {key: b.get(key, 0.0) for _, key, _ in CLASSES}


def stacked(svg, x, y, width, parts, colors, scale):
    """Horizontal stacked bar, parts in bits scaled to pixels, 2px gaps between fills."""
    cx = x
    for value, color in zip(parts, colors):
        w = value * scale
        if w <= 0:
            continue
        svg.add(f'<rect x="{cx:.1f}" y="{y:.1f}" width="{max(0.0, w - 2):.1f}" height="{BAR_H}" '
                f'rx="1.5" fill="{color}"/>')
        cx += w


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

    width = 16 + LABEL_W + BAR_W + GAP + MIX_W + GAP + MIX_W + 16
    top = 124
    svg = Svg(width)
    title = args.title or f"{names[1]} against {names[0]}, stream anatomy at level {args.level}"
    svg.text(16, 30, title, 20, INK, weight="bold")
    svg.text(16, 50, f"{names[0]} {commit(versions[0])} · {names[1]} {commit(versions[1])} · per input the "
             f"{names[0]} bar above the {names[1]} bar at one scale, the {names[0]} bar filling the width",
             12, INK_SOFT)
    bx = 16 + LABEL_W
    dx = bx + BAR_W + GAP
    lx = dx + MIX_W + GAP
    ly = 74
    x = bx
    for name, _, color in CLASSES:
        svg.add(f'<rect x="{x}" y="{ly - 9}" width="12" height="10" rx="2" fill="{color}"/>')
        svg.text(x + 16, ly, name, 10.5, INK)
        x += 16 + 7 * len(name) + 14
    x = dx
    for (name, _), color in zip(DIST_BUCKETS, DIST_RAMP):
        svg.add(f'<rect x="{x}" y="{ly - 9}" width="12" height="10" rx="2" fill="{color}"/>')
        svg.text(x + 15, ly, name, 10.5, INK)
        x += 15 + 7 * len(name) + 10
    x = lx
    for (name, _), color in zip(LEN_BUCKETS, LEN_RAMP):
        svg.add(f'<rect x="{x}" y="{ly - 9}" width="12" height="10" rx="2" fill="{color}"/>')
        svg.text(x + 15, ly, name, 10.5, INK)
        x += 15 + 7 * len(name) + 10
    svg.text(bx, top - 14, "bits by symbol class", 12, INK, weight="bold")
    svg.text(dx, top - 14, "matches by distance", 12, INK, weight="bold")
    svg.text(lx, top - 14, "matches by length", 12, INK, weight="bold")

    print(f"level {args.level}, bits per class, {names[1]} against {names[0]}")
    print(f"{'input':16s} {'bytes':>9s} {'change':>7s}  " + "  ".join(f"{c:>10s}" for c, _, _ in CLASSES)
          + "   distance mix ≤4/≤32/≤256/≤4K/>4K   length mix ≤4/≤8/≤16/≤64/>64")
    for k, label in enumerate(labels):
        y = top + k * ROW_H
        pair = [rows[i][label][args.level] for i in (0, 1)]
        totals = [sum(bits(b).values()) for b in pair]
        scale = BAR_W / max(totals[0], 1)
        sizes = [b.get("compressed", 0.0) for b in pair]
        change = (sizes[1] - sizes[0]) * 100 / sizes[0] if sizes[0] else 0.0
        svg.text(bx - 10, y + 10, display(label), 12, INK, anchor="end", weight="bold")
        svg.text(bx - 10, y + 25, f"{sizes[0]:,.0f} → {sizes[1]:,.0f} B", 10.5, INK_SOFT, anchor="end")
        svg.text(bx - 10, y + 39, f"{change:+.2f}%", 10.5, INK_SOFT, anchor="end")
        colors = [c for _, _, c in CLASSES]
        for i, b in enumerate(pair):
            parts = [bits(b)[key] for _, key, _ in CLASSES]
            stacked(svg, bx, y + i * (BAR_H + 4), BAR_W, parts, colors, scale)
            matches = max(1.0, sum(b.get(key, 0.0) for _, key in DIST_BUCKETS))
            mscale = MIX_W / max(1.0, sum(pair[0].get(key, 0.0) for _, key in DIST_BUCKETS))
            stacked(svg, dx, y + i * (BAR_H + 4), MIX_W,
                    [b.get(key, 0.0) for _, key in DIST_BUCKETS], DIST_RAMP, mscale)
            stacked(svg, lx, y + i * (BAR_H + 4), MIX_W,
                    [b.get(key, 0.0) for _, key in LEN_BUCKETS], LEN_RAMP, mscale)
        # the class that moved most, in bits of the base total
        deltas = [(bits(pair[1])[key] - bits(pair[0])[key], name) for name, key, _ in CLASSES]
        d, name = max(deltas, key=lambda t: abs(t[0]))
        if totals[0] and abs(d) / totals[0] >= 0.002:
            svg.text(bx + BAR_W + 8, y + BAR_H + 6, f"{name} {d * 100 / totals[0]:+.1f}", 10, INK_SOFT)
        line = f"{display(label):16s} {sizes[1]:9,.0f} {change:+6.2f}%  "
        line += "  ".join(f"{(bits(pair[1])[key] - bits(pair[0])[key]) * 100 / max(totals[0], 1):+9.2f}%"
                          for _, key, _ in CLASSES)
        mix = [[b.get(key, 0.0) for _, key in DIST_BUCKETS] for b in pair]
        lmix = [[b.get(key, 0.0) for _, key in LEN_BUCKETS] for b in pair]
        def pct(v, tot):
            return "/".join(f"{100 * x / max(tot, 1):.0f}" for x in v)
        line += f"   {pct(mix[0], sum(mix[0]))} → {pct(mix[1], sum(mix[1]))}"
        line += f"   {pct(lmix[0], sum(lmix[0]))} → {pct(lmix[1], sum(lmix[1]))}"
        print(line)

    body_bottom = top + len(labels) * ROW_H + 6
    ly = body_bottom
    svg.text(bx, ly, "the annotation after a bar pair is the class that moved most, in percent of "
             f"the {names[0]} stream · the mixes count matches, scaled to the {names[0]} match count",
             10.5, INK_SOFT)
    height = footnote(svg, names, versions, machine, [], ly + 8)
    out = args.output or re.sub(r"[^\w.-]+", "_", "_vs_".join(names)) + f"_anatomy_l{args.level}.svg"
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg.finish(height))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
