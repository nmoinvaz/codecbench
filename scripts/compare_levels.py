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
        [--strategies name,...] [--levels 2-9]

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


def parse_levels(spec):
    """Levels named by a spec of numbers and ranges, such as 2-9 or 1,6,9."""
    levels = set()
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        levels.update(range(int(lo), int(hi or lo) + 1))
    return levels


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


def table_blocks(names, levels, rows):
    """Size and time column blocks, a column per run plus a change column per later run.

    Takes the rows of one strategy and leaves out the runs that have none. Every column carries
    one (text, emphasized) cell per level.
    """
    measures = [("compressed size, bytes", "size", "{:,.0f}", 1.0, 124),
                ("cpu time, ms", "time", "{:,.1f}", 1e3, 104)]
    blocks = []
    for caption, key, fmt, scale, width in measures:
        cols = []
        for i, row in enumerate(rows):
            if not row:
                continue
            # The header needs room for the run's name and swatch
            cols.append({"run": i, "width": max(width, text_width(names[i]) + 36),
                         "cells": [(fmt.format(row[l][key] * scale) if l in row else "-", False)
                                   for l in levels]})
            if i == 0 or not rows[0]:
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


def text_width(s, size=12):
    """Rough rendered width of a system-ui string, enough to seat a swatch or dodge a label."""
    return sum(3.6 if c in "iljtfrI .,:;'!|" else 9.6 if c in "mwMW" else 6.9
               for c in s) * size / 12


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

    # A strategy that ignores the level lands all of its levels on one point, drawn once
    flat = {}
    for key, ladder in ladders.items():
        xs = [sx(v["ratio"]) for _, v in ladder]
        ys = [sy(v["speed"]) for _, v in ladder]
        if len(ladder) > 1 and max(xs) - min(xs) < 6 and max(ys) - min(ys) < 6:
            flat[key] = ", ".join(str(level) for level, _ in ladder)
            ladders[key] = [ladder[len(ladder) // 2]]

    # The reference is a wide soft band, a later run tracing it reads as a line inside.
    # Strategy variants dash that line. Later runs stack with the first of them on top.
    for i, s in [(i, s) for i in [0, *range(len(rows) - 1, 0, -1)] for s in strategies]:
        ladder = ladders[(i, s)]
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

    # A level that moved gets a dashed arrow from its reference point. A run with most of
    # its levels elsewhere is a different curve, arrows would only clutter it.
    for (i, s), ladder in ladders.items():
        moves = []
        for level, v in ladder:
            ref = rows[0].get(s, {}).get(level)
            if i and ref:
                moves.append((sx(ref["ratio"]), sy(ref["speed"]),
                              sx(v["ratio"]), sy(v["speed"])))
        apart = [m for m in moves if math.hypot(m[2] - m[0], m[3] - m[1]) > 12]
        if len(moves) > 1 and len(apart) * 2 >= len(moves):
            continue
        for x1, y1, x2, y2 in apart:
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

    # Rings first so a coincident later run sits inside its reference. A later run landing
    # on another later run shrinks to a core, so every run at a shared point stays visible.
    points, marks, dots = [], [], []
    for (i, s), ladder in ladders.items():
        for level, v in ladder:
            x, y = sx(v["ratio"]), sy(v["speed"])
            levels = flat.get((i, s))
            tip = (f"{names[i]} " + (f"levels {levels}" if levels else f"level:{level}")
                   + (f" strategy:{s}" if s else "")
                   + f" - {fmt_speed(v['speed'])}, ratio {v['ratio']:.3f}, "
                   f"{v['size']:,.0f} bytes, {v['time'] * 1e3:,.1f} ms"
                   + (f", cv {v['cv'] * 100:.1f}%" if v["cv"] > 0 else ""))
            # A collapsed ladder carries no level label, its strategy name is enough
            if not levels:
                points.append((i, level, x, y))
            if i == 0:
                svg.add(f'<g><circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{SURFACE}" '
                        f'stroke="{SERIES[0]}" stroke-width="2"/><title>{esc(tip)}</title></g>')
                marks.append((x, y, 10))
                continue
            stacked = sum(1 for ox, oy in dots if math.hypot(x - ox, y - oy) < 4)
            dots.append((x, y))
            marks.append((x, y, 7))
            if stacked:
                svg.add(f'<g transform="translate({x:.1f} {y:.1f}) '
                        f'scale({max(0.58 - 0.14 * stacked, 0.25):.2f}) '
                        f'translate({-x:.1f} {-y:.1f})">')
            marker(svg, STRATEGY_SHAPES.get(s, "circle"), x, y, SERIES[i], tip)
            if stacked:
                svg.add("</g>")

    boxes = []

    def free(box):
        """True when a label box sits inside the plot, clear of placed labels and markers."""
        x0, y0, x1, y1 = box
        if y0 < py - 6 or y1 > py + ph - 2:
            return False
        if any(x0 < bx1 and bx0 < x1 and y0 < by1 and by0 < y1 for bx0, by0, bx1, by1 in boxes):
            return False
        return all(math.hypot(mx - min(max(mx, x0), x1), my - min(max(my, y0), y1)) > mr
                   for mx, my, mr in marks)

    def place(x, y, label, slots):
        """Draw a label in the first slot around its point that is free, the first otherwise."""
        w = text_width(label, 10)

        def box_at(dx, dy, anchor):
            # Slide a label that would leave the plot sideways back inside it
            x0 = x + dx - {"start": 0, "middle": w / 2, "end": w}[anchor]
            x0 = min(max(x0, px + 2), px + pw - w - 2)
            return (x0 - 2, y + dy - 9, x0 + w + 2, y + dy + 2)

        box = next((b for b in (box_at(*slot) for slot in slots) if free(b)), box_at(*slots[0]))
        boxes.append(box)
        svg.text(box[0] + 2, box[3] - 2, label, size=10)

    # Each ladder is named beside its last level once strategies share the chart
    for s in strategies if len(strategies) > 1 else []:
        ladder = next((ladders[(i, s)] for i in reversed(range(len(rows))) if ladders[(i, s)]),
                      None)
        if ladder:
            v = ladder[-1][1]
            place(sx(v["ratio"]), sy(v["speed"]), strategy_name(s),
                  [(0, 26, "middle"), (14, 4, "start"), (-14, 4, "end"), (0, -17, "middle")])

    # Level labels step around the markers and each other. Coincident points share a label,
    # unless their levels differ, then the later run's label carries its name.
    spots = []
    for i, level, x, y in points:
        text = f"L{level}"
        if any(t == text and abs(x - ox) < 24 and abs(y - oy) < 14 for ox, oy, t in spots):
            continue
        shared = any(math.hypot(x - ox, y - oy) < 4 for ox, oy, _ in spots)
        spots.append((x, y, text))
        place(x, y, f"{text} {names[i]}" if shared else text,
              [(11, -11, "start"), (11, 19, "start"), (-11, 19, "end"), (-11, -11, "end")])


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
                swatch(svg, c["run"], cx - 8 - text_width(name) - 10, head_y - 4)
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
            # Values in primary ink, gaps and changes recede unless a change is real
            if (c["run"] is not None or real) and text != "-":
                svg.text(cell_x, y, text, size=12, fill=INK, anchor="end",
                         weight="bold" if real else "normal")
            else:
                svg.text(cell_x, y, text, size=12, anchor="end")
    svg.add("</g>")
    return top + 42 + len(levels) * row_h


def render(names, versions, machine, corpus_desc, warnings, rows, tables, title, out_path):
    px, py, ph = 78, 100, 340
    strategies = list(tables)
    needed = max(LEVEL_W + BLOCK_GAP * (len(blocks) - 1)
                 + sum(c["width"] for _, block in blocks for c in block)
                 for _, blocks in tables.values())
    # A third run and beyond widen the chart to fit their table columns
    width = max(1080, math.ceil(px + needed + 40))
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
        lx -= text_width(names[i]) + 12
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
    ap.add_argument("--strategies", default=None,
                    help="comma-separated strategy variants to keep, all found by default, "
                         "the plain ladder alone with just \"default\"")
    ap.add_argument("--levels", default=None,
                    help="levels to keep, such as 2-9 or 1,6,9, all found by default")
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
    if args.strategies is not None:
        keep = set(filter(None, args.strategies.split(","))) - {"default"}
        found = set().union(*(set(row) for row in rows)) - {""}
        if keep - found:
            ap.error(f"no {', '.join(sorted(keep - found))} strategy rows, "
                     f"found {', '.join(sorted(found)) or 'none'}")
        rows = [{s: ladder for s, ladder in row.items() if not s or s in keep} for row in rows]
    if args.levels is not None:
        try:
            keep = parse_levels(args.levels)
        except ValueError:
            ap.error(f"cannot read levels from {args.levels!r}, expected a form like 2-9 or 1,6,9")
        rows = [{s: {l: v for l, v in ladder.items() if l in keep} for s, ladder in row.items()}
                for row in rows]
        rows = [{s: ladder for s, ladder in row.items() if ladder} for row in rows]
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
        tables[s] = (levels, table_blocks(names, levels, ladder))
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
