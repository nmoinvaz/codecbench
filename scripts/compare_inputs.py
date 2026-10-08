#!/usr/bin/env python3
"""Compare two benchmark JSON outputs input by input as an SVG grid.

Lays the inputs the two runs share down the rows, corpus files and synthetic
data types alike, and the deflate levels across the columns, once for the
change in compressed size and once for the change in cpu time. Cells are
tinted by direction, smaller or faster in one hue and larger or slower in
the other, so the inputs a change helps or hurts stand out. Made to show
where an A/B result depends on the data, which compare_levels.py sums away.

Usage:
    python3 scripts/compare_inputs.py base.json head.json [-o out.svg]
        [--filter regex] [--names a,b] [--title text] [--levels 2-6]

Works with both single-iteration and aggregated (--benchmark_repetitions)
JSON outputs; for aggregated runs the median row is used for each benchmark.
The grids are also printed to stdout.
"""
import argparse
import os
import re
import statistics
import sys

from compare_levels import NOISE_CVS, NOISE_FLOOR, commit, judge, parse_levels, text_width
from compare_runs import to_seconds
from graph_runs import (DATA_TYPE_ORDER, GRID, INK, INK_SOFT, SERIES, Svg, collect, esc, footnote,
                        load, machine_line, run_warnings)

# Smaller or faster takes the first hue, larger or slower the second
BETTER, WORSE = SERIES[0], SERIES[1]
# The tint reaches full strength at these percent changes
CAPS = {"size": 5.0, "time": 25.0}
MEASURES = [("compressed size", "size"), ("cpu time", "time")]


def input_rows(benchmarks):
    """{input: {level: size, time, cv, raw}} over the plain levels of one run."""
    deflate, _, _, deflate_data, _, _, distp, _ = collect(benchmarks, None)
    found = {}
    for (level, strategy), files in deflate.items():
        if not strategy:
            for label, b in files.items():
                found.setdefault(label, {})[level] = b
    for (data_type, level), b in deflate_data.items():
        found.setdefault(f"data/{data_type}", {})[level] = b
    for (kind, dist, level), b in distp.items():
        if kind == "deflate":
            found.setdefault(f"data/dist:{dist}", {})[level] = b
    rows = {}
    for label, ladder in found.items():
        for level, b in ladder.items():
            size, secs = b.get("compressed", 0.0), to_seconds(b, "cpu_time")
            if size > 0 and secs > 0:
                rows.setdefault(label, {})[level] = {
                    "size": size, "time": secs, "cv": b.get("_cv", 0.0),
                    "raw": round(size * b.get("ratio", 0.0))}
    return rows


def order_inputs(labels):
    """Corpus files by name, the data types in registration order, then the periods."""
    def key(label):
        if not label.startswith("data/"):
            return (0, 0, label)
        name = label[len("data/"):]
        if name.startswith("dist:"):
            return (2, int(name[len("dist:"):]), name)
        return (1, DATA_TYPE_ORDER.index(name) if name in DATA_TYPE_ORDER else len(DATA_TYPE_ORDER),
                name)
    return sorted(labels, key=key)


def display(label):
    return label[len("data/"):] if label.startswith("data/") else label


def fmt_size(n):
    if n % 1048576 == 0:
        return f"{n // 1048576} MiB"
    if n % 1024 == 0:
        return f"{n // 1024} KiB"
    return f"{n:,} bytes"


def fmt_pct(d):
    """Signed percent, only an exact zero drops the sign."""
    return f"{d:+.1f}%" if d else "0.0%"


def build_grids(labels, levels, base, head):
    """Per measure: {input: {level: (percent change, real, tooltip)}} plus a median row."""
    grids = {}
    for _, key in MEASURES:
        grid, changes = {}, {level: [] for level in levels}
        for label in labels:
            cells = {}
            for level in levels:
                ref, v = base[label].get(level), head[label].get(level)
                if not ref or not v:
                    continue
                d, real = judge(key, ref, v)
                # A few bytes either way round to zero and are not worth the emphasis
                real = real and abs(d) >= 0.05
                if key == "size":
                    tip = f"{ref['size']:,.0f} to {v['size']:,.0f} bytes"
                else:
                    tip = (f"{ref['time'] * 1e3:,.3f} to {v['time'] * 1e3:,.3f} ms, "
                           f"cv {max(ref['cv'], v['cv']) * 100:.1f}%")
                cells[level] = (d, real, f"{display(label)} level:{level} - {tip}")
                changes[level].append(d)
            grid[label] = cells
        # The typical input per level. A median, one extreme input must not speak for the rest.
        floor = NOISE_FLOOR if key == "time" else 0.05
        typical = {}
        for level in levels:
            if len(changes[level]) > 1:
                d = statistics.median(changes[level])
                typical[level] = (d, abs(d) > floor,
                                  f"median of {len(changes[level])} inputs level:{level}")
        grids[key] = (grid, typical)
    return grids


def print_grids(labels, levels, grids):
    width = max([len(display(l)) for l in labels] + [len("median")]) + 2
    for caption, key in MEASURES:
        grid, typical = grids[key]
        print(f"\n{caption}")
        print(f"{'input':<{width}}" + "".join(f"{'L' + str(level):>9}" for level in levels))
        print("-" * (width + 9 * len(levels)))
        for name, cells in [(display(l), grid[l]) for l in labels] + [("median", typical)]:
            if cells:
                print(f"{name:<{width}}" + "".join(
                    f"{fmt_pct(cells[level][0]) if level in cells else '-':>9}"
                    for level in levels))


def render(names, versions, machine, warnings, labels, levels, grids, caption, title,
           out_path):
    width, x0, gap, row_h = 1080, 40, 40, 28
    label_w = max(110.0, max(text_width(display(l)) for l in labels) + 18)
    block_w = (width - x0 - 40 - label_w - gap) / 2
    cell_w = block_w / len(levels)
    size = 11 if cell_w >= 56 else 9
    svg = Svg(width)

    svg.text(16, 28, title, size=15, fill=INK, weight="bold")
    # Subtitle, the commit each run was built from
    built = [f"{names[i]} {commit(v)}" for i, v in enumerate(versions) if v]
    svg.text(16, 48, "  ·  ".join(built), size=12)
    svg.text(x0, 84, caption, size=12, fill=INK)
    # Key, the direction each hue stands for, beside the caption
    kx = x0 + text_width(caption, 12) + 36
    for hue, meaning in ((BETTER, "smaller or faster"), (WORSE, "larger or slower")):
        svg.add(f'<rect x="{kx}" y="74" width="22" height="12" rx="3" fill="{hue}" '
                f'fill-opacity="0.6"/>')
        svg.text(kx + 28, 84, meaning, size=11, fill=INK)
        kx += 28 + text_width(meaning, 11) + 22

    top = 132
    svg.add('<g style="font-variant-numeric: tabular-nums">')
    for r, label in enumerate(labels):
        svg.text(x0, top + r * row_h + 18, display(label), size=12, fill=INK)
    typical_y = top + len(labels) * row_h + 10
    has_typical = any(grids[key][1] for _, key in MEASURES)
    if has_typical:
        svg.text(x0, typical_y + 18, "median", size=12)

    for m, (measure, key) in enumerate(MEASURES):
        grid, typical = grids[key]
        bx = x0 + label_w + m * (block_w + gap)
        svg.text(bx + block_w / 2, top - 30, f"{measure}, {names[1]} against {names[0]}",
                 size=12, fill=INK, anchor="middle")
        for c, level in enumerate(levels):
            svg.text(bx + (c + 0.5) * cell_w, top - 8, f"L{level}", size=11, anchor="middle")
        if has_typical:
            svg.line(bx, typical_y - 4, bx + block_w, typical_y - 4, INK_SOFT)
        rows = [(top + r * row_h, grid[label]) for r, label in enumerate(labels)]
        for y, cells in rows + ([(typical_y, typical)] if has_typical else []):
            for c, level in enumerate(levels):
                if level not in cells:
                    continue
                d, real, tip = cells[level]
                x = bx + c * cell_w
                # A neutral cell keeps the grid legible, the tint marks a real change
                body = (f'<rect x="{x + 1:.1f}" y="{y + 1}" width="{cell_w - 2:.1f}" '
                        f'height="{row_h - 2}" rx="3" fill="{GRID}" fill-opacity="0.45"/>')
                if real:
                    strength = max(0.08, 0.6 * min(1.0, abs(d) / CAPS[key]))
                    body += (f'<rect x="{x + 1:.1f}" y="{y + 1}" width="{cell_w - 2:.1f}" '
                             f'height="{row_h - 2}" rx="3" fill="{BETTER if d < 0 else WORSE}" '
                             f'fill-opacity="{strength:.2f}"/>')
                svg.add(f"<g>{body}<title>{esc(tip)}</title></g>")
                svg.text(x + cell_w / 2, y + 18, fmt_pct(d), size=size,
                         fill=INK if real else INK_SOFT, anchor="middle",
                         weight="bold" if real else "normal")
    svg.add("</g>")

    ky = typical_y + (row_h if has_typical else 0) + 22
    svg.text(x0, ky, f"The tint is full at {CAPS['size']:g}% for size and "
             f"{CAPS['time']:g}% for time. A time change stays plain unless it moves by more "
             f"than {NOISE_FLOOR:g}% and {NOISE_CVS} times the repetition cv.", size=10)

    height = footnote(svg, names, versions, machine, warnings, ky + 10)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg.finish(height))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jsons", nargs=2, help="two benchmark JSON outputs, the reference run first")
    ap.add_argument("-o", "--output", default=None, help="output SVG path")
    ap.add_argument("--filter", default=None, help="regex applied to input names")
    ap.add_argument("--names", default=None, help="comma-separated run names")
    ap.add_argument("--title", default=None, help="chart title")
    ap.add_argument("--levels", default=None,
                    help="levels to keep, such as 2-6 or 1,6,9, all found by default")
    args = ap.parse_args()
    # The grids use deltas, Windows consoles default to cp1252
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    runs = [load(p) for p in args.jsons]
    names = [r[0] for r in runs]
    # A/B runs of one codec share a binary name, their files tell them apart
    if len(set(names)) < len(names):
        names = [os.path.splitext(os.path.basename(p))[0] for p in args.jsons]
    if args.names:
        for i, given in enumerate(args.names.split(",")[:len(names)]):
            if given:
                names[i] = given
    versions = [r[1] for r in runs]
    machine = machine_line([r[3] for r in runs])

    base, head = (input_rows(r[2]) for r in runs)
    flt = re.compile(args.filter) if args.filter else None
    labels = [l for l in order_inputs(set(base) & set(head)) if not flt or flt.search(l)]
    levels = sorted({level for l in labels for level in set(base[l]) & set(head[l])})
    if args.levels is not None:
        try:
            keep = parse_levels(args.levels)
        except ValueError:
            ap.error(f"cannot read levels from {args.levels!r}, expected a form like 2-6 or 1,6,9")
        levels = [level for level in levels if level in keep]
    labels = [l for l in labels if any(level in base[l] and level in head[l] for level in levels)]
    if not labels:
        print("No codec_deflate inputs and levels in common.", file=sys.stderr)
        sys.exit(1)

    grids = build_grids(labels, levels, base, head)
    sizes = {v["raw"] for l in labels for v in base[l].values()}
    caption = f"deflate, {len(labels)} input" + ("s" if len(labels) > 1 else "")
    if len(sizes) == 1:
        caption += f" of {fmt_size(sizes.pop())}" + (" each" if len(labels) > 1 else "")
    warnings = run_warnings(names, runs)
    title = args.title or f"{names[1]} against {names[0]}, by input"
    out = args.output or re.sub(r"[^\w.-]+", "_", "_vs_".join(names)) + "_inputs.svg"

    for i in range(len(runs)):
        if versions[i]:
            print(f"{names[i]} {versions[i]}")
    for w in warnings:
        print(f"warning: {w}")
    print(caption)
    print_grids(labels, levels, grids)
    render(names, versions, machine, warnings, labels, levels, grids, caption, title, out)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
