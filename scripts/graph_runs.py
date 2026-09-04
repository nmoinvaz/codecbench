#!/usr/bin/env python3
"""Graph two benchmark JSON outputs as a codec comparison SVG.

Plots the codec_deflate benchmarks as a speed versus ratio chart, one point
per level and strategy aggregated across the corpus files common to both
runs, and the codec_inflate corpus benchmarks as a throughput panel. Levels
are connected in order, strategy variants get their own marker shapes.
Synthetic data-type benchmarks (codec_inflate/data/<type>) common to both
runs get their own line panel, one line per codec across the types.

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
import platform
import re
import socket
import subprocess
import sys

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"
GRID = "#e7e6e2"
SERIES = ["#2a78d6", "#eb6834"]

STRATEGY_ORDER = ["filtered", "huffman", "rle", "fixed"]

# registration order in benchmark_codec.cc
DATA_TYPE_ORDER = ["text", "short_match", "dna", "random",
                   "literals", "mixed", "realistic_rgb", "striped_rgb"]

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
    context = d.get("context", {})
    executable = context.get("executable", path)
    name = os.path.basename(executable)
    if name.startswith("codecbench_"):
        name = name[len("codecbench_"):]
    version = context.get("codec_version", "")
    return name, version, out, context


def geomean(values):
    """Geometric mean of positive values; 0 if input empty or non-positive."""
    filtered = [v for v in values if v > 0]
    if not filtered:
        return 0.0
    log_sum = sum(math.log(v) for v in filtered)
    return math.exp(log_sum / len(filtered))


def collect(benchmarks, corpus_filter):
    """Split parsed benchmarks into deflate/inflate/data-type rows keyed by name."""
    deflate = {}
    inflate = {}
    inflate_data = {}
    for name, b in benchmarks.items():
        m = NAME_RE.match(name)
        if m is None or "bytes_per_second" not in b:
            continue
        label = m.group("label")
        if label.startswith("data/"):
            if m.group("kind") == "inflate":
                inflate_data[label[len("data/"):]] = b
            continue
        if corpus_filter and not corpus_filter.search(label):
            continue
        if m.group("kind") == "deflate":
            key = (int(m.group("level")), m.group("strategy") or "")
            deflate.setdefault(key, {})[label] = b
        else:
            inflate[label] = b
    return deflate, inflate, inflate_data


def aggregate(runs, corpus_filter):
    """Per codec: {(level, strategy): (speed, ratio, nfiles)} plus inflate speed.

    Aggregates with geometric means over the corpus files common to both runs
    for each benchmark group, so both codecs summarize identical inputs.
    """
    collected = [collect(b, corpus_filter) for _, _, b, _ in runs]
    points = []
    for _ in collected:
        points.append({"deflate": {}, "inflate": None, "inflate_data": {}})

    for key in sorted(set(collected[0][0]) | set(collected[1][0])):
        for i, (deflate, _, _) in enumerate(collected):
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
    for i, (_, inflate, _) in enumerate(collected):
        labels = common_inflate if common_inflate else sorted(inflate)
        rows = [inflate[l] for l in labels if l in inflate]
        if rows:
            speed = geomean([r["bytes_per_second"] for r in rows])
            points[i]["inflate"] = (speed, len(rows))

    common_types = set(collected[0][2]) & set(collected[1][2])
    for i, (_, _, inflate_data) in enumerate(collected):
        for t in common_types:
            points[i]["inflate_data"][t] = inflate_data[t]["bytes_per_second"]
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
    """11px marker with a 2px surface ring; shape encodes the strategy."""
    r = 5.5
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

# Point labels need unambiguous short tags, "filtered" and "fixed" share a first letter
STRATEGY_TAGS = {"filtered": "flt", "huffman": "huf", "rle": "rle", "fixed": "fix"}


def better_arrow(svg, x1, y1, x2, y2):
    """Semi-transparent direction-of-better hint with a label along the shaft."""
    ln = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
    head = (f"{x2:.1f},{y2:.1f} "
            f"{x2 - 9 * ux - 4 * uy:.1f},{y2 - 9 * uy + 4 * ux:.1f} "
            f"{x2 - 9 * ux + 4 * uy:.1f},{y2 - 9 * uy - 4 * ux:.1f}")
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
    svg.add(f'<g opacity="0.35"><line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2 - 6 * ux:.1f}" '
            f'y2="{y2 - 6 * uy:.1f}" stroke="{INK_SOFT}" stroke-width="2"/>'
            f'<polygon points="{head}" fill="{INK_SOFT}"/>'
            f'<text x="{mx:.1f}" y="{my - 7:.1f}" font-size="11" fill="{INK_SOFT}" '
            f'text-anchor="middle" transform="rotate({ang:.1f} {mx:.1f} {my:.1f})">'
            f'better</text></g>')


def machine_line(contexts):
    """Machine summary from the run context, CPU/RAM/OS added when run on this host."""
    host = contexts[0].get("host_name", "")
    parts = []
    if host and host == socket.gethostname():
        if sys.platform == "darwin":
            try:
                brand = subprocess.check_output(
                    ["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
                mem = int(subprocess.check_output(
                    ["sysctl", "-n", "hw.memsize"], text=True)) // (1024 ** 3)
                parts.append(f"{brand}, {mem} GB, macOS {platform.mac_ver()[0]}")
            except (subprocess.SubprocessError, OSError, ValueError):
                pass
        elif sys.platform.startswith("linux"):
            try:
                with open("/proc/cpuinfo") as f:
                    for line in f:
                        if line.startswith("model name"):
                            parts.append(line.split(":", 1)[1].strip())
                            break
            except OSError:
                pass
    ncpus = contexts[0].get("num_cpus")
    if ncpus:
        parts.append(f"{ncpus} cpus")
    if host:
        parts.append(host)
    date = contexts[0].get("date", "")
    if date:
        parts.append(date.split("T")[0])
    if any(c.get("host_name", host) != host for c in contexts[1:]):
        parts.append("hosts differ")
    return ", ".join(parts)


def ordered_types(points):
    """Data types common to both runs, in registration order, unknown ones last."""
    types = [t for t in DATA_TYPE_ORDER if t in points[0]["inflate_data"]]
    types += sorted(set(points[0]["inflate_data"]) - set(DATA_TYPE_ORDER))
    return types


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


def render(names, versions, machine, points, title, out_path):
    data_types = ordered_types(points)
    width = 1080
    height = 660 if data_types else 486
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

    # Direction-of-better hint, up and right is faster and smaller output
    better_arrow(svg, px + pw - 128, py + 82, px + pw - 40, py + 24)

    # Strategy shape key, only when strategy points exist
    strategies = sorted({k[1] for p in points for k in p["deflate"] if k[1]},
                        key=lambda s: STRATEGY_ORDER.index(s) if s in STRATEGY_ORDER else 9)
    kx = px + 240
    for s in strategies:
        marker(svg, STRATEGY_SHAPES[s], kx, py - 26, INK_SOFT, s)
        svg.text(kx + 9, py - 22, s, size=11)
        kx += 6.5 * len(s) + 44

    # Strategies whose points barely move across levels get one plain label
    level_free = {}
    for i, p in enumerate(points):
        by_strategy = {}
        for (level, strategy), (speed, ratio, n) in p["deflate"].items():
            if strategy and ratio > 0:
                by_strategy.setdefault(strategy, []).append((speed, ratio))
        for s, pts in by_strategy.items():
            hi_s = max(v for v, _ in pts)
            lo_s = min(v for v, _ in pts)
            hi_r = max(r for _, r in pts)
            lo_r = min(r for _, r in pts)
            level_free[(i, s)] = (len(pts) > 1 and hi_s / lo_s < 1.05
                                  and hi_r / lo_r < 1.005)

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
                if strategy:
                    stag = STRATEGY_TAGS.get(strategy, strategy[:3])
                    tag = stag if level_free.get((i, strategy)) else f"{stag}{level}"
                else:
                    tag = f"L{level}"
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
    better_arrow(svg, bx, by + 134, bx + 64, by + 134)

    # Data-type inflate panel, one line per codec across the synthetic types
    if data_types:
        dpx, dpy, dpw, dph = 78, 488, 942, 120
        svg.text(dpx, dpy - 18, "inflate, synthetic data types", size=12, fill=INK)
        vals = [p["inflate_data"][t] for p in points for t in data_types]
        dmin, dmax = min(vals) / 1.6, max(vals) * 1.6

        def dx(idx):
            return dpx + (idx + 0.5) / len(data_types) * dpw

        def dy(speed):
            return dpy + dph - (math.log10(speed) - math.log10(dmin)) / \
                (math.log10(dmax) - math.log10(dmin)) * dph

        for v in nice_log_ticks(dmin, dmax):
            y = dy(v)
            svg.line(dpx, y, dpx + dpw, y, GRID)
            svg.text(dpx - 8, y + 4, fmt_speed(v), size=11, anchor="end")
        svg.line(dpx, dpy + dph, dpx + dpw, dpy + dph, INK_SOFT)
        for j, t in enumerate(data_types):
            svg.text(dx(j), dpy + dph + 18, t, size=11, anchor="middle")
        for i, p in enumerate(points):
            path = " ".join(f"{'M' if j == 0 else 'L'}{dx(j):.1f},{dy(p['inflate_data'][t]):.1f}"
                            for j, t in enumerate(data_types))
            svg.add(f'<path d="{path}" fill="none" stroke="{SERIES[i]}" '
                    f'stroke-width="2" stroke-opacity="0.65"/>')
            for j, t in enumerate(data_types):
                speed = p["inflate_data"][t]
                tip = f"{names[i]} inflate {t} - {fmt_speed(speed)}"
                marker(svg, "circle", dx(j), dy(speed), SERIES[i], tip)
        better_arrow(svg, dpx + 26, dpy + 78, dpx + 26, dpy + 20)

    # Version and machine footnote
    note = "  \u00b7  ".join([f"{names[i]} {versions[i]}".strip() for i in range(2)]
                        + ([machine] if machine else []))
    svg.text(16, height - 12, note, size=10)

    with open(out_path, "w") as f:
        f.write(svg.finish())


def print_table(names, points):
    header = f"{'level/strategy':<22} {names[0]:>14} {names[1]:>14} {'Δ speed':>9}  {'ratio ' + names[0]:>14} {'ratio ' + names[1]:>14}"
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
        print(f"{tag:<22} {sa:>14} {sb:>14} {delta:>9}  {ra:>14} {rb:>14}")
    infl = []
    for i in range(2):
        infl.append(fmt_speed(points[i]["inflate"][0]) if points[i]["inflate"] else "-")
    if points[0]["inflate"] and points[1]["inflate"]:
        a, b = points[0]["inflate"][0], points[1]["inflate"][0]
        delta = f"{(b - a) / a * 100.0:+8.1f}%"
    else:
        delta = "-"
    print(f"{'inflate':<22} {infl[0]:>14} {infl[1]:>14} {delta:>9}")
    for t in ordered_types(points):
        a = points[0]["inflate_data"][t]
        b = points[1]["inflate_data"][t]
        delta = f"{(b - a) / a * 100.0:+8.1f}%"
        print(f"{'inflate/' + t:<22} {fmt_speed(a):>14} {fmt_speed(b):>14} {delta:>9}")


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
    machine = machine_line([runs[0][3], runs[1][3]])
    corpus_filter = re.compile(args.filter) if args.filter else None

    points = aggregate(runs, corpus_filter)
    title = args.title or f"{names[0]} vs {names[1]}"
    out = args.output or f"{names[0]}_vs_{names[1]}.svg".replace("/", "_")

    for i in range(2):
        if versions[i]:
            print(f"{names[i]} {versions[i]}")
    print_table(names, points)
    render(names, versions, machine, points, title, out)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
