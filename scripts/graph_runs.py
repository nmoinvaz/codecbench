#!/usr/bin/env python3
"""Graph two benchmark JSON outputs as a codec comparison SVG.

Plots the codec_deflate benchmarks as a speed versus ratio chart, one point
per level and strategy aggregated across the corpus files common to both
runs, and the codec_inflate corpus benchmarks as a throughput panel. Levels
are connected in order, strategy variants get their own marker shapes.

Usage:
    python3 scripts/graph_runs.py a.json b.json [-o out.svg]
        [--filter regex] [--name-a name] [--name-b name] [--title text]

Works with both single-iteration and aggregated (--benchmark_repetitions)
JSON outputs; for aggregated runs the median row is used for each benchmark.
An aggregate table is also printed to stdout.
"""
import argparse
import json
import math
import os
import re
import sys

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"
GRID = "#e7e6e2"
SERIES = ["#2a78d6", "#eb6834"]

STRATEGY_ORDER = ["filtered", "huffman", "rle", "fixed"]

NAME_RE = re.compile(
    r"^codec_(?P<kind>deflate|inflate)/(?P<label>.+?)"
    r"(?:/level:(?P<level>\d+))?(?:/strategy:(?P<strategy>\w+))?$")


def load(path):
    """Load benchmarks keyed by run_name. Prefer median aggregates if present."""
    with open(path) as f:
        d = json.load(f)
    out = {}
    for b in d["benchmarks"]:
        if b.get("aggregate_name") == "median":
            out[b["run_name"]] = b
        elif b.get("run_type") == "iteration" and b["run_name"] not in out:
            out[b["run_name"]] = b
    executable = d.get("context", {}).get("executable", path)
    name = os.path.basename(executable)
    if name.startswith("codecbench_"):
        name = name[len("codecbench_"):]
    version = d.get("context", {}).get("codec_version", "")
    return name, version, out


def geomean(values):
    """Geometric mean of positive values; 0 if input empty or non-positive."""
    filtered = [v for v in values if v > 0]
    if not filtered:
        return 0.0
    log_sum = sum(math.log(v) for v in filtered)
    return math.exp(log_sum / len(filtered))


def collect(benchmarks, corpus_filter):
    """Split parsed benchmarks into deflate/inflate rows keyed by benchmark name."""
    deflate = {}
    inflate = {}
    for name, b in benchmarks.items():
        m = NAME_RE.match(name)
        if m is None or "bytes_per_second" not in b:
            continue
        label = m.group("label")
        if label.startswith("data/"):
            continue
        if corpus_filter and not corpus_filter.search(label):
            continue
        if m.group("kind") == "deflate":
            key = (int(m.group("level")), m.group("strategy") or "")
            deflate.setdefault(key, {})[label] = b
        else:
            inflate[label] = b
    return deflate, inflate


def aggregate(runs, corpus_filter):
    """Per codec: {(level, strategy): (speed, ratio, nfiles)} plus inflate speed.

    Aggregates with geometric means over the corpus files common to both runs
    for each benchmark group, so both codecs summarize identical inputs.
    """
    collected = [collect(b, corpus_filter) for _, _, b in runs]
    points = []
    for (deflate, inflate) in collected:
        points.append({"deflate": {}, "inflate": None})

    for key in sorted(set(collected[0][0]) | set(collected[1][0])):
        for i, (deflate, _) in enumerate(collected):
            if key not in deflate:
                continue
            other = collected[1 - i][0]
            labels = set(deflate[key])
            if key in other:
                labels &= set(other[key])
            rows = [deflate[key][l] for l in sorted(labels)]
            if not rows:
                continue
            speed = geomean([r["bytes_per_second"] for r in rows])
            ratio = geomean([r.get("ratio", 0.0) for r in rows])
            points[i]["deflate"][key] = (speed, ratio, len(rows))

    common_inflate = sorted(set(collected[0][1]) & set(collected[1][1]))
    for i, (_, inflate) in enumerate(collected):
        labels = common_inflate if common_inflate else sorted(inflate)
        rows = [inflate[l] for l in labels if l in inflate]
        if rows:
            speed = geomean([r["bytes_per_second"] for r in rows])
            points[i]["inflate"] = (speed, len(rows))
    return points


def fmt_speed(bps):
    if bps >= 1e9:
        return f"{bps / 1e9:.2f} GB/s"
    return f"{bps / 1e6:.0f} MB/s"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    def __init__(self, width, height):
        self.w = width
        self.h = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" '
            f'font-family="system-ui, sans-serif">',
            f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>']

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=12, fill=INK_SOFT, anchor="start", weight="normal"):
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
                 f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')

    def line(self, x1, y1, x2, y2, stroke, width=1):
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke="{stroke}" stroke-width="{width}"/>')

    def finish(self):
        self.parts.append("</svg>")
        return "\n".join(self.parts) + "\n"


def marker(svg, shape, x, y, color, title):
    """8px marker with a 2px surface ring; shape encodes the strategy."""
    r = 4.5
    ring = f'stroke="{SURFACE}" stroke-width="2"'
    if shape == "circle":
        body = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}" {ring}/>'
    elif shape == "square":
        body = (f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.1f}" '
                f'height="{2 * r:.1f}" fill="{color}" {ring}/>')
    elif shape == "diamond":
        pts = f"{x:.1f},{y - r - 1:.1f} {x + r + 1:.1f},{y:.1f} {x:.1f},{y + r + 1:.1f} {x - r - 1:.1f},{y:.1f}"
        body = f'<polygon points="{pts}" fill="{color}" {ring}/>'
    elif shape == "triangle":
        pts = f"{x:.1f},{y - r - 1:.1f} {x + r + 1:.1f},{y + r:.1f} {x - r - 1:.1f},{y + r:.1f}"
        body = f'<polygon points="{pts}" fill="{color}" {ring}/>'
    else:  # triangle-down
        pts = f"{x:.1f},{y + r + 1:.1f} {x + r + 1:.1f},{y - r:.1f} {x - r - 1:.1f},{y - r:.1f}"
        body = f'<polygon points="{pts}" fill="{color}" {ring}/>'
    svg.add(f"<g>{body}<title>{esc(title)}</title></g>")


STRATEGY_SHAPES = {"": "circle", "filtered": "square", "huffman": "diamond",
                   "rle": "triangle", "fixed": "triangle-down"}


def nice_log_ticks(lo, hi):
    ticks = []
    e = math.floor(math.log10(lo))
    while 10 ** e <= hi * 1.001:
        for mult in (1, 2, 5):
            v = mult * 10 ** e
            if lo * 0.999 <= v <= hi * 1.001:
                ticks.append(v)
        e += 1
    return ticks


def render(names, versions, points, title, out_path):
    width, height = 1080, 486
    svg = Svg(width, height)

    svg.text(16, 28, title, size=15, fill=INK, weight="bold")

    # Legend, color carries the codec identity
    lx = width - 16
    for i in reversed(range(2)):
        label = names[i]
        svg.text(lx, 28, label, size=12, fill=INK, anchor="end")
        lx -= 7.2 * len(label) + 12
        svg.add(f'<circle cx="{lx:.1f}" cy="24" r="5" fill="{SERIES[i]}"/>')
        lx -= 20

    # Deflate panel, speed versus ratio
    px, py, pw, ph = 60, 76, 620, 320
    all_pts = [v for p in points for v in p["deflate"].values()]
    if not all_pts:
        print("No codec_deflate benchmarks in common.", file=sys.stderr)
        sys.exit(1)
    speeds = [s for s, _, _ in all_pts]
    ratios = [r for _, r, _ in all_pts if r > 0]
    smin, smax = min(speeds) / 1.6, max(speeds) * 1.6
    rmin, rmax = min(ratios) * 0.96, max(ratios) * 1.04

    def sx(ratio):
        return px + (ratio - rmin) / (rmax - rmin) * pw

    def sy(speed):
        return py + ph - (math.log10(speed) - math.log10(smin)) / \
            (math.log10(smax) - math.log10(smin)) * ph

    for v in nice_log_ticks(smin, smax):
        y = sy(v)
        svg.line(px, y, px + pw, y, GRID)
        svg.text(px - 8, y + 4, fmt_speed(v), size=11, anchor="end")
    rstep = max(round((rmax - rmin) / 6, 1), 0.1)
    r = math.ceil(rmin / rstep) * rstep
    while r <= rmax:
        x = sx(r)
        svg.line(x, py, x, py + ph, GRID)
        svg.text(x, py + ph + 18, f"{r:g}", size=11, anchor="middle")
        r = round(r + rstep, 6)
    svg.line(px, py + ph, px + pw, py + ph, INK_SOFT)
    svg.text(px + pw / 2, py + ph + 40, "compression ratio", size=12, anchor="middle")
    svg.text(px, py - 22, "deflate, corpus geomean", size=12, fill=INK)

    # Strategy shape key, only when strategy points exist
    strategies = sorted({k[1] for p in points for k in p["deflate"] if k[1]},
                        key=lambda s: STRATEGY_ORDER.index(s) if s in STRATEGY_ORDER else 9)
    kx = px + 240
    for s in strategies:
        marker(svg, STRATEGY_SHAPES[s], kx, py - 26, INK_SOFT, s)
        svg.text(kx + 9, py - 22, s, size=11)
        kx += 6.5 * len(s) + 44

    labeled = []

    def label_point(x, y, tag):
        """Skip labels crowding an already labeled point, tooltips still work."""
        for ox, oy, _ in labeled:
            if abs(x - ox) < 24 and abs(y - oy) < 14:
                return
        labeled.append((x, y, tag))

    # Default-strategy levels first so their labels win over strategy points
    for i, p in enumerate(points):
        level_pts = sorted((k, v) for k, v in p["deflate"].items() if k[1] == "")
        path = " ".join(f"{'M' if j == 0 else 'L'}{sx(v[1]):.1f},{sy(v[0]):.1f}"
                        for j, (_, v) in enumerate(level_pts))
        if len(level_pts) > 1:
            svg.add(f'<path d="{path}" fill="none" stroke="{SERIES[i]}" '
                    f'stroke-width="2" stroke-opacity="0.65"/>')
    for pass_strategies in (False, True):
        for i, p in enumerate(points):
            for (level, strategy), (speed, ratio, n) in sorted(p["deflate"].items()):
                if ratio <= 0 or bool(strategy) != pass_strategies:
                    continue
                shape = STRATEGY_SHAPES.get(strategy, "circle")
                tip = (f"{names[i]} level:{level}"
                       + (f" strategy:{strategy}" if strategy else "")
                       + f" - {fmt_speed(speed)}, ratio {ratio:.3f}, {n} files")
                marker(svg, shape, sx(ratio), sy(speed), SERIES[i], tip)
                tag = f"{strategy[0]}{level}" if strategy else str(level)
                label_point(sx(ratio), sy(speed), tag)
    # Labels last so markers never cover them
    for x, y, tag in labeled:
        svg.text(x + 7, y - 7, tag, size=10)

    # Inflate panel, throughput bars
    bx, by, bw = 800, 76, 240
    svg.text(bx, by - 22, "inflate, corpus geomean", size=12, fill=INK)
    bar_max = max((p["inflate"][0] for p in points if p["inflate"]), default=0)
    for i, p in enumerate(points):
        y = by + 20 + i * 66
        svg.text(bx, y, names[i], size=11)
        if p["inflate"] is None:
            svg.text(bx, y + 22, "no inflate benchmarks", size=11)
            continue
        speed, n = p["inflate"]
        w = max(bw * speed / bar_max, 8)
        svg.add(f'<path d="M{bx} {y + 8} h{w - 4:.1f} a4 4 0 0 1 4 4 v12 '
                f'a4 4 0 0 1 -4 4 h{-(w - 4):.1f} z" fill="{SERIES[i]}">'
                f'<title>{esc(f"{names[i]} inflate - {fmt_speed(speed)}, {n} files")}</title></path>')
        svg.text(bx + bw, y, fmt_speed(speed), size=11, fill=INK, anchor="end")

    # Version footnote
    note = "  \u00b7  ".join(f"{names[i]} {versions[i]}".strip() for i in range(2))
    svg.text(16, height - 12, note, size=10)

    with open(out_path, "w") as f:
        f.write(svg.finish())


def print_table(names, points):
    header = f"{'level/strategy':<18} {names[0]:>14} {names[1]:>14} {'Δ speed':>9}  {'ratio ' + names[0]:>14} {'ratio ' + names[1]:>14}"
    print(header)
    print("-" * len(header))
    keys = sorted(set(points[0]["deflate"]) | set(points[1]["deflate"]))
    for key in keys:
        level, strategy = key
        tag = f"level:{level}" + (f"/{strategy}" if strategy else "")
        a = points[0]["deflate"].get(key)
        b = points[1]["deflate"].get(key)
        sa = fmt_speed(a[0]) if a else "-"
        sb = fmt_speed(b[0]) if b else "-"
        if a and b:
            delta = f"{(b[0] - a[0]) / a[0] * 100.0:+8.1f}%"
        else:
            delta = "-"
        ra = f"{a[1]:.4f}" if a else "-"
        rb = f"{b[1]:.4f}" if b else "-"
        print(f"{tag:<18} {sa:>14} {sb:>14} {delta:>9}  {ra:>14} {rb:>14}")
    infl = []
    for i in range(2):
        infl.append(fmt_speed(points[i]["inflate"][0]) if points[i]["inflate"] else "-")
    if points[0]["inflate"] and points[1]["inflate"]:
        a, b = points[0]["inflate"][0], points[1]["inflate"][0]
        delta = f"{(b - a) / a * 100.0:+8.1f}%"
    else:
        delta = "-"
    print(f"{'inflate':<18} {infl[0]:>14} {infl[1]:>14} {delta:>9}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_a")
    ap.add_argument("json_b")
    ap.add_argument("-o", "--output", default=None, help="output SVG path")
    ap.add_argument("--filter", default=None, help="regex applied to corpus labels")
    ap.add_argument("--name-a", default=None, help="legend name for the first run")
    ap.add_argument("--name-b", default=None, help="legend name for the second run")
    ap.add_argument("--title", default=None, help="chart title")
    args = ap.parse_args()

    runs = [load(args.json_a), load(args.json_b)]
    names = [args.name_a or runs[0][0], args.name_b or runs[1][0]]
    versions = [runs[0][1], runs[1][1]]
    corpus_filter = re.compile(args.filter) if args.filter else None

    points = aggregate(runs, corpus_filter)
    title = args.title or f"{names[0]} vs {names[1]}"
    out = args.output or f"{names[0]}_vs_{names[1]}.svg".replace("/", "_")

    for i in range(2):
        if versions[i]:
            print(f"{names[i]} {versions[i]}")
    print_table(names, points)
    render(names, versions, points, title, out)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
