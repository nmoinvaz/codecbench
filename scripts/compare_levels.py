#!/usr/bin/env python3
"""Compare the deflate level ladder of benchmark JSON outputs as an SVG.

Draws the levels of each run as a speed versus ratio chart and, below it, a
table of the compressed size and cpu time at every level, each later run
paired with its change against the first. Strategy variants found in the
runs (level:N/strategy:<name>) get their own lines and their own table.
Made for A/B runs of one codec, such as the base and head JSONs that
bench_pr.py leaves behind, whose commits head the chart as its subtitle.
Sizes and times are summed over the corpus files common to the runs, the
tar aggregates alone when any are present.

Usage:
    python3 scripts/compare_levels.py base.json head.json [more.json ...]
        [-o out.svg] [--filter regex] [--names a,b,...] [--title text]

Works with both single-iteration and aggregated (--benchmark_repetitions)
JSON outputs; for aggregated runs the median row is used for each benchmark.
The table is also printed to stdout.
"""
import argparse
import math
import os
import re
import sys

from compare_runs import to_seconds
from graph_runs import (GRID, INK, INK_SOFT, SERIES, STRATEGY_ORDER, STRATEGY_SHAPES, SURFACE, Svg,
                        better_arrow, collect, esc, fmt_speed, footnote, load, machine_line,
                        marker, nice_log_ticks, run_warnings)

# A time change is emphasized beyond this many repetition cvs, and never below the floor percent
NOISE_CVS = 3
NOISE_FLOOR = 1.0

LEVEL_W = 64
BLOCK_GAP = 36

# The zlib constant behind each strategy variant
STRATEGY_NAMES = {"": "default strategy", "filtered": "Z_FILTERED", "huffman": "Z_HUFFMAN_ONLY",
                  "rle": "Z_RLE", "fixed": "Z_FIXED"}


def strategy_name(strategy):
    return STRATEGY_NAMES.get(strategy, f"strategy {strategy}")


def commit(version):
    """Abbreviated commit of a git describe version, the version itself otherwise."""
    m = re.search(r"-g([0-9a-f]{7,40})$", version)
    return m.group(1) if m else version


def level_rows(runs, corpus_filter):
    """Per run: {strategy: {level: size, time, ratio, speed, cv}} summed over the common files."""
    ladders = [collect(b, corpus_filter)[0] for _, _, b, _ in runs]
    every = [set(files) for ladder in ladders for files in ladder.values()]
    labels = set.intersection(*every) if every else set()
    # A tar already holds its corpus files, summing both would count them twice
    tars = {l for l in labels if l.startswith("tars/")}
    labels = sorted(tars or labels)
    rows = []
    for ladder in ladders:
        row = {}
        for (level, strategy), files in ladder.items():
            picked = [files[l] for l in labels]
            size = sum(b.get("compressed", 0.0) for b in picked)
            raw = sum(b.get("compressed", 0.0) * b.get("ratio", 0.0) for b in picked)
            secs = sum(to_seconds(b, "cpu_time") for b in picked)
            if size <= 0 or raw <= 0 or secs <= 0:
                continue
            row.setdefault(strategy, {})[level] = {
                "size": size, "time": secs, "ratio": raw / size, "speed": raw / secs,
                "cv": max(b.get("_cv", 0.0) for b in picked)}
        rows.append(row)
    return rows, labels


def change(new, old):
    return (new - old) / old * 100.0


def table_blocks(levels, rows):
    """Size and time column blocks, a column per run plus a change column per later run.

    Takes the rows of one strategy, every column carries one (text, emphasized) cell per level.
    """
    measures = [("compressed size, bytes", "size", "{:,.0f}", 1.0, 124),
                ("cpu time, ms", "time", "{:,.1f}", 1e3, 104)]
    blocks = []
    for caption, key, fmt, scale, width in measures:
        cols = []
        for i, row in enumerate(rows):
            cols.append({"run": i, "width": width,
                         "cells": [(fmt.format(row[l][key] * scale) if l in row else "-", False)
                                   for l in levels]})
            if i == 0:
                continue
            cells = []
            for l in levels:
                ref, v = rows[0].get(l), row.get(l)
                if not ref or not v:
                    cells.append(("-", False))
                    continue
                d = change(v[key], ref[key])
                # Output bytes are deterministic, timings need to clear the noise
                if key == "size":
                    real = v[key] != ref[key]
                else:
                    real = abs(d) > max(NOISE_FLOOR, NOISE_CVS * 100.0 * max(ref["cv"], v["cv"]))
                # Only a size that really differs keeps the sign on a rounded zero
                signed = abs(d) >= 0.05 or (key == "size" and real)
                cells.append((f"{d:+.1f}%" if signed else "0.0%", real))
            cols.append({"run": None, "width": 84, "cells": cells})
        blocks.append((caption, cols))
    return blocks


def print_table(names, levels, blocks):
    cols = [c for _, block in blocks for c in block]
    heads = [names[c["run"]] if c["run"] is not None else "Δ" for c in cols]
    widths = [max(len(h), *(len(t) for t, _ in c["cells"])) + 2 for h, c in zip(heads, cols)]
    captions, k = " " * 5, 0
    for caption, block in blocks:
        captions += f"{caption:>{sum(widths[k:k + len(block)])}}"
        k += len(block)
    print(captions)
    print(f"{'level':<5}" + "".join(f"{h:>{w}}" for h, w in zip(heads, widths)))
    print("-" * (5 + sum(widths)))
    for r, level in enumerate(levels):
        print(f"{level:<5}" + "".join(f"{c['cells'][r][0]:>{w}}" for c, w in zip(cols, widths)))


def swatch(svg, i, x, y):
    """Legend mark matching the chart, the reference run is the open ring."""
    if i == 0:
        svg.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="none" '
                f'stroke="{SERIES[0]}" stroke-width="2"/>')
    else:
        svg.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{SERIES[i]}"/>')


def draw_chart(svg, names, strategies, rows, corpus_desc, px, py, pw, ph):
    """Speed versus ratio, one point per level, the levels of each ladder connected in order."""
    # Level 0 stays off the chart, its near-1.0 ratio would squeeze the axis
    ladders = {(i, s): sorted((l, v) for l, v in row.get(s, {}).items() if l != 0)
               for i, row in enumerate(rows) for s in strategies}
    speeds = [v["speed"] for ladder in ladders.values() for _, v in ladder]
    ratios = [v["ratio"] for ladder in ladders.values() for _, v in ladder]
    if not speeds:
        print("No levels above 0 to chart.", file=sys.stderr)
        sys.exit(1)
    smin, smax = min(speeds) / 1.4, max(speeds) * 1.25
    rmin, rmax = min(ratios) * 0.96, max(ratios) * 1.04

    def sx(ratio):
        return px + (ratio - rmin) / (rmax - rmin) * pw

    def sy(speed):
        return py + ph - (math.log10(speed) - math.log10(smin)) / \
            (math.log10(smax) - math.log10(smin)) * ph

    for v in nice_log_ticks(smin, smax):
        y = sy(v)
        svg.line(px, y, px + pw, y, GRID)
        svg.text(px + pw - 6, y - 4, fmt_speed(v), size=10, anchor="end")
    rstep = max(round((rmax - rmin) / 6, 1), 0.1)
    r = math.ceil(rmin / rstep) * rstep
    while r <= rmax:
        x = sx(r)
        svg.line(x, py, x, py + ph, GRID)
        svg.text(x, py + ph + 18, f"{r:g}", size=11, anchor="middle")
        r = round(r + rstep, 6)
    svg.line(px, py + ph, px + pw, py + ph, INK_SOFT)
    svg.text(px + pw / 2, py + ph + 40, "compression ratio", size=12, anchor="middle")
    svg.text(px, py - 22, f"deflate, {corpus_desc}", size=12, fill=INK)
    if any(0 in ladder for row in rows for ladder in row.values()):
        svg.text(px + pw, py - 22, "level 0 is in the table only", size=10, anchor="end")

    # Direction-of-better hint, up and right is faster and smaller output
    better_arrow(svg, px + pw - 128, py + 82, px + pw - 40, py + 24)

    # The reference is a wide soft band, a later run tracing it reads as a line inside.
    # Strategy variants dash that line.
    for (i, s), ladder in ladders.items():
        if len(ladder) < 2:
            continue
        path = " ".join(f"{'M' if j == 0 else 'L'}{sx(v['ratio']):.1f},{sy(v['speed']):.1f}"
                        for j, (_, v) in enumerate(ladder))
        if i == 0:
            stroke = 'stroke-width="7" stroke-opacity="0.28"'
        else:
            stroke = 'stroke-width="2" stroke-opacity="0.9"' + \
                (' stroke-dasharray="6 4"' if s else "")
        svg.add(f'<path d="{path}" fill="none" stroke="{SERIES[i]}" {stroke} '
                f'stroke-linejoin="round"/>')

    # A level that moved gets a dashed arrow from its reference point
    for (i, s), ladder in ladders.items():
        for level, v in ladder:
            ref = rows[0].get(s, {}).get(level)
            if i == 0 or not ref:
                continue
            x1, y1 = sx(ref["ratio"]), sy(ref["speed"])
            x2, y2 = sx(v["ratio"]), sy(v["speed"])
            ln = math.hypot(x2 - x1, y2 - y1)
            if ln < 30:
                continue
            ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
            ax, ay, bx, by = x1 + 13 * ux, y1 + 13 * uy, x2 - 10 * ux, y2 - 10 * uy
            head = (f"{bx:.1f},{by:.1f} "
                    f"{bx - 7 * ux - 3 * uy:.1f},{by - 7 * uy + 3 * ux:.1f} "
                    f"{bx - 7 * ux + 3 * uy:.1f},{by - 7 * uy - 3 * ux:.1f}")
            svg.add(f'<g opacity="0.75"><line x1="{ax:.1f}" y1="{ay:.1f}" '
                    f'x2="{bx - 5 * ux:.1f}" y2="{by - 5 * uy:.1f}" stroke="{INK_SOFT}" '
                    f'stroke-width="1.2" stroke-dasharray="3 3"/>'
                    f'<polygon points="{head}" fill="{INK_SOFT}"/></g>')

    # Rings first so a coincident later run sits inside its reference
    labeled = []
    for (i, s), ladder in ladders.items():
        for level, v in ladder:
            x, y = sx(v["ratio"]), sy(v["speed"])
            tip = (f"{names[i]} level:{level}" + (f" strategy:{s}" if s else "")
                   + f" - {fmt_speed(v['speed'])}, ratio {v['ratio']:.3f}, "
                   f"{v['size']:,.0f} bytes, {v['time'] * 1e3:,.1f} ms"
                   + (f", cv {v['cv'] * 100:.1f}%" if v["cv"] > 0 else ""))
            if i == 0:
                svg.add(f'<g><circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{SURFACE}" '
                        f'stroke="{SERIES[0]}" stroke-width="2"/><title>{esc(tip)}</title></g>')
            else:
                marker(svg, STRATEGY_SHAPES.get(s, "circle"), x, y, SERIES[i], tip)
            # Coincident points share one label
            if not any(abs(x - ox) < 24 and abs(y - oy) < 14 for ox, oy in labeled):
                labeled.append((x, y))
                svg.text(x + 11, y - 11, f"L{level}", size=10)

    # Each ladder is named under its last level once strategies share the chart
    for s in strategies if len(strategies) > 1 else []:
        ladder = next((ladders[(i, s)] for i in reversed(range(len(rows))) if ladders[(i, s)]),
                      None)
        if not ladder:
            continue
        name, v = strategy_name(s), ladder[-1][1]
        half = 3.0 * len(name)
        x = min(max(sx(v["ratio"]), px + half), px + pw - half)
        svg.text(x, sy(v["speed"]) + 26, name, size=10, anchor="middle")


def draw_table(svg, names, caption, levels, blocks, x, top, span):
    """Level table widened toward the chart, returns its bottom edge."""
    row_h = 22
    natural = sum(c["width"] for _, block in blocks for c in block)
    fixed = LEVEL_W + BLOCK_GAP * (len(blocks) - 1)
    k = min(max((span - fixed) / natural, 1.0), 1.35)

    svg.add('<g style="font-variant-numeric: tabular-nums">')
    if caption:
        svg.text(x, top + 12, caption, size=12, fill=INK, weight="bold")
    head_y = top + 34
    svg.text(x, head_y, "level", size=12)
    cx = x + LEVEL_W
    rights = []
    for measure, block in blocks:
        left = cx
        for c in block:
            cx += c["width"] * k
            rights.append(cx - 8)
            if c["run"] is None:
                svg.text(cx - 8, head_y, "Δ", size=12, anchor="end")
            else:
                name = names[c["run"]]
                svg.text(cx - 8, head_y, name, size=12, fill=INK, anchor="end")
                swatch(svg, c["run"], cx - 8 - 6.8 * len(name) - 10, head_y - 4)
        svg.text((left + cx) / 2, top + 12, measure, size=12, fill=INK, anchor="middle")
        svg.line(left + 12, top + 19, cx, top + 19, GRID)
        cx += BLOCK_GAP
    right = cx - BLOCK_GAP
    svg.line(x, top + 42, right, top + 42, INK_SOFT)

    cols = [c for _, block in blocks for c in block]
    for r, level in enumerate(levels):
        y = top + 42 + r * row_h + 16
        if r:
            svg.line(x, y - 16, right, y - 16, GRID)
        svg.text(x, y, str(level), size=12, fill=INK)
        for c, cell_x in zip(cols, rights):
            text, real = c["cells"][r]
            # Values in primary ink, changes recede unless they are real
            if c["run"] is not None or real:
                svg.text(cell_x, y, text, size=12, fill=INK, anchor="end",
                         weight="bold" if real else "normal")
            else:
                svg.text(cell_x, y, text, size=12, anchor="end")
    svg.add("</g>")
    return top + 42 + len(levels) * row_h


def render(names, versions, machine, corpus_desc, warnings, rows, tables, title, out_path):
    px, py, ph = 78, 100, 340
    strategies = list(tables)
    blocks = tables[strategies[0]][1]
    natural = sum(c["width"] for _, block in blocks for c in block)
    # A third run and beyond widen the chart to fit their table columns
    width = max(1080, px + LEVEL_W + BLOCK_GAP * (len(blocks) - 1) + natural + 40)
    pw = width - px - 40
    svg = Svg(width)

    svg.text(16, 28, title, size=15, fill=INK, weight="bold")
    # Subtitle, the commit each run was built from
    built = [f"{names[i]} {commit(v)}" for i, v in enumerate(versions) if v]
    svg.text(16, 48, "  ·  ".join(built), size=12)

    # Legend on its own line, a long title never collides with it
    lx = width - 16
    for i in reversed(range(len(names))):
        svg.text(lx, 52, names[i], size=12, fill=INK, anchor="end")
        lx -= 7.2 * len(names[i]) + 12
        swatch(svg, i, lx, 48)
        lx -= 20

    draw_chart(svg, names, strategies, rows, corpus_desc, px, py, pw, ph)
    top = py + ph + 72
    for s in strategies:
        levels, blocks = tables[s]
        caption = strategy_name(s) if len(strategies) > 1 else ""
        bottom = draw_table(svg, names, caption, levels, blocks, px, top, pw)
        top = bottom + 34
    svg.text(px, bottom + 22, f"Δ is the change against {names[0]}, bold where the size "
             f"differs or the time moves by more than {NOISE_FLOOR:g}% and {NOISE_CVS} "
             f"times the repetition cv.", size=10)

    height = footnote(svg, names, versions, machine, warnings, bottom + 32)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg.finish(height))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jsons", nargs="+", help="benchmark JSON outputs, the reference run first")
    ap.add_argument("-o", "--output", default=None, help="output SVG path")
    ap.add_argument("--filter", default=None, help="regex applied to corpus labels")
    ap.add_argument("--names", default=None, help="comma-separated legend names")
    ap.add_argument("--title", default=None, help="chart title")
    args = ap.parse_args()
    # The table uses deltas, Windows consoles default to cp1252
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not 2 <= len(args.jsons) <= len(SERIES):
        ap.error(f"need between two and {len(SERIES)} runs to compare")
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
    corpus_filter = re.compile(args.filter) if args.filter else None

    rows, labels = level_rows(runs, corpus_filter)
    # The default ladder first, then the strategy variants in their usual order
    strategies = sorted(set().union(*(set(row) for row in rows)),
                        key=lambda s: (s != "", STRATEGY_ORDER.index(s)
                                       if s in STRATEGY_ORDER else len(STRATEGY_ORDER), s))
    if not strategies:
        print("No codec_deflate level benchmarks in common.", file=sys.stderr)
        sys.exit(1)
    tables = {}
    for s in strategies:
        ladder = [row.get(s, {}) for row in rows]
        levels = sorted(set().union(*(set(r) for r in ladder)))
        tables[s] = (levels, table_blocks(levels, ladder))
    corpus_desc = labels[0] if len(labels) == 1 else f"{len(labels)} corpus files"
    warnings = run_warnings(names, runs)
    title = args.title or " vs ".join(names) + ", deflate levels"
    out = args.output or re.sub(r"[^\w.-]+", "_", "_vs_".join(names)) + "_levels.svg"

    for i in range(len(runs)):
        if versions[i]:
            print(f"{names[i]} {versions[i]}")
    for w in warnings:
        print(f"warning: {w}")
    print(f"deflate, {corpus_desc}")
    for s in strategies:
        if len(strategies) > 1:
            print(f"\n{strategy_name(s)}")
        print_table(names, *tables[s])
    render(names, versions, machine, corpus_desc, warnings, rows, tables, title, out)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
