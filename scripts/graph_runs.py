#!/usr/bin/env python3
"""Graph benchmark JSON outputs as a codec comparison SVG.

Plots the codec_deflate benchmarks as a speed versus ratio chart, one point
per level and strategy aggregated across the corpus files common to the
runs, and the codec_inflate corpus benchmarks as a throughput panel. Levels
are connected in order, strategy variants get their own marker shapes.
Synthetic data-type benchmarks (codec_inflate/data/<type>) common to the
runs get their own line panel, one line per codec across the types.
windowBits variants (level:N/wbits:M) get a speed line panel at the bottom,
one line per codec across the window sizes.

Usage:
    python3 scripts/graph_runs.py a.json b.json [c.json ...] [-o out.svg]
        [--filter regex] [--names a,b,...] [--title text]

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
# Categorical slots in fixed order, assigned by run position, never cycled.
# The neutral ninth slot is for a run of least interest, order inputs so.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#4a3aa7", "#e34948", "#7a7668"]

STRATEGY_ORDER = ["filtered", "huffman", "rle", "fixed"]

# registration order in benchmark_codec.cc
DATA_TYPE_ORDER = ["text", "short_match", "dna", "random",
                   "literals", "mixed", "realistic_rgb", "striped_rgb"]

REPO_URL = "https://github.com/nmoinvaz/codecbench"

NAME_RE = re.compile(
    r"^codec_(?P<kind>deflate|inflate)/(?P<label>.+?)"
    r"(?:/level:(?P<level>\d+))?(?:/strategy:(?P<strategy>\w+))?"
    r"(?:/wbits:(?P<wbits>\d+))?$")


def load(path):
    """Load benchmarks keyed by run_name. Prefer median aggregates if present."""
    with open(path) as f:
        d = json.load(f)
    out = {}
    for b in d["benchmarks"]:
        rn = b["run_name"]
        agg = b.get("aggregate_name")
        if agg == "median":
            out[rn] = {**out.get(rn, {}), **b}
        elif agg == "cv":
            out[rn] = {**out.get(rn, {}), "_cv": b.get("bytes_per_second", 0.0)}
        elif agg is None and b.get("run_type") == "iteration" and rn not in out:
            out[rn] = b
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
    """Split parsed benchmarks into deflate/inflate/data-type/wbits rows keyed by name."""
    deflate = {}
    inflate = {}
    inflate_data = {}
    deflate_data = {}
    wbits = {}
    for name, b in benchmarks.items():
        m = NAME_RE.match(name)
        if m is None or "bytes_per_second" not in b:
            continue
        label = m.group("label")
        if label.startswith("data/"):
            if m.group("kind") == "inflate":
                inflate_data[label[len("data/"):]] = b
            elif m.group("level"):
                deflate_data[(label[len("data/"):], int(m.group("level")))] = b
            continue
        if corpus_filter and not corpus_filter.search(label):
            continue
        if m.group("kind") == "deflate":
            if m.group("wbits"):
                wbits.setdefault((int(m.group("level")), int(m.group("wbits"))), {})[label] = b
                continue
            key = (int(m.group("level")), m.group("strategy") or "")
            deflate.setdefault(key, {})[label] = b
        else:
            inflate[label] = b
    return deflate, inflate, inflate_data, deflate_data, wbits


def aggregate(runs, corpus_filter):
    """Per codec: deflate/inflate summaries with spread and worst repetition cv.

    Aggregates with geometric means over the corpus files common to the runs
    that share each benchmark group, so codecs summarize identical inputs.
    """
    collected = [collect(b, corpus_filter) for _, _, b, _ in runs]
    points = [{"deflate": {}, "inflate": None, "inflate_data": {}, "deflate_data": {},
               "wbits": {}} for _ in collected]

    for key in sorted(set().union(*(set(c[0]) for c in collected))):
        have = [i for i, c in enumerate(collected) if key in c[0]]
        labels = set.intersection(*(set(collected[i][0][key]) for i in have))
        for i in have:
            rows = [collected[i][0][key][l] for l in sorted(labels)]
            if not rows:
                continue
            speeds = [r["bytes_per_second"] for r in rows]
            points[i]["deflate"][key] = {
                "speed": geomean(speeds),
                "ratio": geomean([r.get("ratio", 0.0) for r in rows]),
                "n": len(rows),
                "smin": min(speeds), "smax": max(speeds),
                "cv": max(r.get("_cv", 0.0) for r in rows),
                "mem": max(r.get("mem", 0.0) for r in rows),
            }

    for key in sorted(set().union(*(set(c[4]) for c in collected))):
        have = [i for i, c in enumerate(collected) if key in c[4]]
        labels = set.intersection(*(set(collected[i][4][key]) for i in have))
        for i in have:
            rows = [collected[i][4][key][l] for l in sorted(labels)]
            if not rows:
                continue
            speeds = [r["bytes_per_second"] for r in rows]
            points[i]["wbits"][key] = {
                "speed": geomean(speeds),
                "ratio": geomean([r.get("ratio", 0.0) for r in rows]),
                "n": len(rows),
                "smin": min(speeds), "smax": max(speeds),
                "cv": max(r.get("_cv", 0.0) for r in rows),
            }

    with_inflate = [set(c[1]) for c in collected if c[1]]
    common_inflate = sorted(set.intersection(*with_inflate)) if with_inflate else []
    for i, (_, inflate, _, _, _) in enumerate(collected):
        labels = common_inflate if common_inflate else sorted(inflate)
        rows = [inflate[l] for l in labels if l in inflate]
        if rows:
            speeds = [r["bytes_per_second"] for r in rows]
            points[i]["inflate"] = {
                "speed": geomean(speeds), "n": len(rows),
                "smin": min(speeds), "smax": max(speeds),
                "cv": max(r.get("_cv", 0.0) for r in rows),
                "mem": max(r.get("mem", 0.0) for r in rows),
            }

    with_types = [set(c[2]) for c in collected if c[2]]
    common_types = set.intersection(*with_types) if with_types else set()
    for i, (_, _, inflate_data, _, _) in enumerate(collected):
        for t in common_types & set(inflate_data):
            points[i]["inflate_data"][t] = {
                "speed": inflate_data[t]["bytes_per_second"],
                "cv": inflate_data[t].get("_cv", 0.0),
                "mem": inflate_data[t].get("mem", 0.0),
            }

    # Synthetic inputs are pinned generators, identical across runs, so every
    # run keeps its own level set here
    for i, (_, _, _, deflate_data, _) in enumerate(collected):
        for k in deflate_data:
            points[i]["deflate_data"][k] = {
                "speed": deflate_data[k]["bytes_per_second"],
                "ratio": deflate_data[k].get("ratio", 0.0),
                "cv": deflate_data[k].get("_cv", 0.0),
                "mem": deflate_data[k].get("mem", 0.0),
            }

    label_sets = [set().union(*(set(v) for v in c[0].values())) for c in collected if c[0]]
    corpus = sorted(set.intersection(*label_sets)) if label_sets else []
    return points, corpus


def fmt_speed(bps):
    if bps >= 1e9:
        return f"{bps / 1e9:.2f} GB/s"
    return f"{bps / 1e6:.0f} MB/s"


def fmt_mem(b):
    if b >= 1048576:
        return f"{b / 1048576:.2f} MiB"
    return f"{b / 1024:.1f} KiB"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    """Collects body elements; the height is decided at finish time."""

    def __init__(self, width):
        self.w = width
        self.parts = []

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=12, fill=INK_SOFT, anchor="start", weight="normal"):
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
                 f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')

    def line(self, x1, y1, x2, y2, stroke, width=1):
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke="{stroke}" stroke-width="{width}"/>')

    def finish(self, height):
        header = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
            f'height="{height}" viewBox="0 0 {self.w} {height}" '
            f'font-family="system-ui, sans-serif">',
            f'<rect width="{self.w}" height="{height}" fill="{SURFACE}"/>']
        return "\n".join(header + self.parts + ["</svg>"]) + "\n"


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
    elif shape == "cross":
        a, c = 2.2, r + 1
        pts = " ".join(f"{x + dx:.1f},{y + dy:.1f}" for dx, dy in (
            (-a, -c), (a, -c), (a, -a), (c, -a), (c, a), (a, a),
            (a, c), (-a, c), (-a, a), (-c, a), (-c, -a), (-a, -a)))
        body = f'<polygon points="{pts}" fill="{color}" {ring}/>'
    else:  # triangle-down
        pts = f"{x:.1f},{y + r + 1:.1f} {x + r + 1:.1f},{y - r:.1f} {x - r - 1:.1f},{y - r:.1f}"
        body = f'<polygon points="{pts}" fill="{color}" {ring}/>'
    svg.add(f"<g>{body}<title>{esc(title)}</title></g>")


STRATEGY_SHAPES = {"": "circle", "filtered": "square", "huffman": "diamond",
                   "rle": "triangle", "fixed": "cross"}

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
    if ang > 90 or ang < -90:
        ang += 180  # keep the label reading left to right
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


def run_warnings(names, runs):
    """Conditions recorded with a run that make its numbers suspect."""
    warns = []
    noisy = []
    for i, (_, _, benchmarks, ctx) in enumerate(runs):
        if ctx.get("cpu_scaling_enabled"):
            warns.append(f"{names[i]}: cpu scaling enabled")
        load1 = (ctx.get("load_avg") or [0])[0]
        ncpus = ctx.get("num_cpus") or 1
        if load1 > ncpus / 2:
            warns.append(f"{names[i]}: load {load1:.1f} during run")
        if "debug" in str(ctx.get("library_build_type", "")).lower():
            warns.append(f"{names[i]}: debug build")
        n = sum(1 for b in benchmarks.values() if b.get("_cv", 0.0) > 0.03)
        if n:
            noisy.append(f"{names[i]} {n}")
    if noisy:
        warns.append("benchmarks with cv above 3%: " + ", ".join(noisy))
    return warns


def peak_mem(entries):
    """Largest per-stream peak across benchmark entries, None when unreported."""
    return max((e.get("mem", 0.0) for e in entries), default=0.0) or None


def run_mems(points):
    """Per run: (deflate peak, inflate peak) stream memory."""
    mems = []
    for p in points:
        d = peak_mem(list(p["deflate"].values()) + list(p["deflate_data"].values()))
        f = peak_mem(list(p["inflate_data"].values())
                     + ([p["inflate"]] if p["inflate"] else []))
        mems.append((d, f))
    return mems


def order_types(seen):
    """Data types in registration order, unknown ones last."""
    types = [t for t in DATA_TYPE_ORDER if t in seen]
    return types + sorted(set(seen) - set(DATA_TYPE_ORDER))


def ordered_types(points):
    """Inflate data types on the graph, in registration order."""
    return order_types(set().union(*(set(p["inflate_data"]) for p in points)))


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


def render(names, versions, machine, corpus_desc, warnings, points, title, out_path):
    data_types = ordered_types(points)
    dd_types = order_types({k[0] for p in points for k in p["deflate_data"]})

    width = 1080
    svg = Svg(width)

    svg.text(16, 28, title, size=15, fill=INK, weight="bold")

    # Legend, color carries the codec identity
    lx = width - 16
    for i in reversed(range(len(names))):
        label = names[i]
        svg.text(lx, 28, label, size=12, fill=INK, anchor="end")
        lx -= 7.2 * len(label) + 12
        svg.add(f'<circle cx="{lx:.1f}" cy="24" r="5" fill="{SERIES[i]}"/>')
        lx -= 20

    # Inflate panel, throughput bars
    bx, by, bw = 800, 76, 240
    svg.text(bx, by - 22, f"inflate, {corpus_desc}", size=12, fill=INK)
    bar_max = max((p["inflate"]["speed"] for p in points if p["inflate"]), default=0)
    row_h = 66 if len(points) <= 2 else 48
    for i, p in enumerate(points):
        y = by + 20 + i * row_h
        svg.text(bx, y, names[i], size=11)
        if p["inflate"] is None:
            svg.text(bx, y + 22, "no inflate benchmarks", size=11)
            continue
        v = p["inflate"]
        speed = v["speed"]
        w = max(bw * speed / bar_max, 8)
        tip = (f"{names[i]} inflate - {fmt_speed(speed)}, {v['n']} files"
               + (f", cv {v['cv'] * 100:.1f}%" if v["cv"] > 0 else "")
               + (f", mem {fmt_mem(v['mem'])}" if v["mem"] > 0 else ""))
        svg.add(f'<path d="M{bx} {y + 8} h{w - 4:.1f} a4 4 0 0 1 4 4 v8 '
                f'a4 4 0 0 1 -4 4 h{-(w - 4):.1f} z" fill="{SERIES[i]}">'
                f'<title>{esc(tip)}</title></path>')
        if v["n"] > 1 and v["smax"] > v["smin"]:
            svg.add(f'<line x1="{bx + bw * v["smin"] / bar_max:.1f}" y1="{y + 16}" '
                    f'x2="{bx + min(bw * v["smax"] / bar_max, bw):.1f}" y2="{y + 16}" '
                    f'stroke="{INK_SOFT}" stroke-width="1.5" stroke-opacity="0.4"/>')
        value = fmt_speed(speed)
        if i > 0 and points[0]["inflate"]:
            base = points[0]["inflate"]["speed"]
            value += f" ({(speed - base) / base * 100.0:+.1f}%)"
        svg.text(bx + bw, y, value, size=11, fill=INK, anchor="end")
    arrow_y = by + 20 + len(points) * row_h + 2
    better_arrow(svg, bx, arrow_y, bx + 64, arrow_y)
    right_bottom = arrow_y + 8

    # Peak stream memory bars, lower is better
    mems = run_mems(points)
    if any(dm or im for dm, im in mems):
        mem_max = max(v for dm, im in mems for v in (dm or 0, im or 0))
        yrow = arrow_y + 44
        svg.text(bx, yrow, "peak stream memory", size=12, fill=INK)
        yrow += 12
        for di, dirname in enumerate(("deflate", "inflate")):
            if not any(m[di] for m in mems):
                continue
            svg.text(bx, yrow + 9, dirname, size=11)
            yrow += 14
            for i, m in enumerate(mems):
                v = m[di]
                if not v:
                    continue
                w = max((bw - 110) * v / mem_max, 4)
                svg.add(f'<rect x="{bx}" y="{yrow}" width="{w:.1f}" height="8" rx="3" '
                        f'fill="{SERIES[i]}"><title>'
                        f'{esc(f"{names[i]} {dirname} - {fmt_mem(v)} peak per stream")}'
                        f'</title></rect>')
                value = fmt_mem(v)
                if i > 0 and mems[0][di]:
                    value += f" ({(v - mems[0][di]) / mems[0][di] * 100.0:+.0f}%)"
                svg.text(bx + bw, yrow + 8, value, size=10, fill=INK, anchor="end")
                yrow += 14
            yrow += 8
        better_arrow(svg, bx + 64, yrow + 2, bx, yrow + 2)
        right_bottom = yrow + 12

    # Level 0 throughput, stored-block framing for most codecs, kept off the
    # scatter so its near-1.0 ratios cannot squeeze the axis
    l0 = [p["deflate"].get((0, "")) for p in points]
    if any(l0):
        l0_max = max(v["speed"] for v in l0 if v)
        yrow = right_bottom + 30
        svg.text(bx, yrow, "deflate level:0", size=12, fill=INK)
        yrow += 8
        for i, v in enumerate(l0):
            if not v:
                continue
            w = max((bw - 110) * v["speed"] / l0_max, 4)
            tip = (f"{names[i]} level:0 - {fmt_speed(v['speed'])}, ratio {v['ratio']:.3f}"
                   + (f", cv {v['cv'] * 100:.1f}%" if v["cv"] > 0 else ""))
            svg.add(f'<rect x="{bx}" y="{yrow}" width="{w:.1f}" height="8" rx="3" '
                    f'fill="{SERIES[i]}"><title>{esc(tip)}</title></rect>')
            value = fmt_speed(v["speed"])
            if v["ratio"] > 1.05:
                value += f", ratio {v['ratio']:.2f}"
            if i > 0 and l0[0]:
                value += f" ({(v['speed'] - l0[0]['speed']) / l0[0]['speed'] * 100.0:+.0f}%)"
            svg.text(bx + bw, yrow + 8, value, size=10, fill=INK, anchor="end")
            yrow += 14
        arrow_y = yrow + 8
        better_arrow(svg, bx, arrow_y, bx + 64, arrow_y)
        right_bottom = arrow_y + 10

    # Deflate panel, speed versus ratio, stretched to the right column's height
    px, py, pw = 78, 76, 682
    ph = max(320, right_bottom - py - 40)
    all_pts = [v for p in points for k, v in p["deflate"].items() if k != (0, "")]
    if not all_pts:
        print("No codec_deflate benchmarks in common.", file=sys.stderr)
        sys.exit(1)
    speeds = [v["speed"] for v in all_pts]
    ratios = [v["ratio"] for v in all_pts if v["ratio"] > 0]
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
    svg.text(px, py - 22, f"deflate, {corpus_desc}", size=12, fill=INK)

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
        for (level, strategy), v in p["deflate"].items():
            if strategy and v["ratio"] > 0:
                by_strategy.setdefault(strategy, []).append((v["speed"], v["ratio"]))
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
        level_pts = sorted((k, v) for k, v in p["deflate"].items()
                           if k[1] == "" and k[0] != 0)
        path = " ".join(f"{'M' if j == 0 else 'L'}{sx(v['ratio']):.1f},{sy(v['speed']):.1f}"
                        for j, (_, v) in enumerate(level_pts))
        if len(level_pts) > 1:
            svg.add(f'<path d="{path}" fill="none" stroke="{SERIES[i]}" '
                    f'stroke-width="2" stroke-opacity="0.65"/>')
    for pass_strategies in (False, True):
        for i, p in enumerate(points):
            for (level, strategy), v in sorted(p["deflate"].items()):
                speed, ratio = v["speed"], v["ratio"]
                if ratio <= 0 or bool(strategy) != pass_strategies:
                    continue
                if level == 0 and not strategy:
                    continue
                x = sx(ratio)
                if v["n"] > 1 and v["smax"] > v["smin"]:
                    svg.add(f'<line x1="{x:.1f}" y1="{sy(v["smin"]):.1f}" x2="{x:.1f}" '
                            f'y2="{sy(v["smax"]):.1f}" stroke="{SERIES[i]}" '
                            f'stroke-width="3" stroke-opacity="0.18"/>')
                if v["cv"] > 0:
                    y1, y2 = sy(speed * (1 - v["cv"])), sy(speed * (1 + v["cv"]))
                    svg.add(f'<g stroke="{SERIES[i]}" stroke-opacity="0.7" stroke-width="1.5">'
                            f'<line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}"/>'
                            f'<line x1="{x - 3:.1f}" y1="{y1:.1f}" x2="{x + 3:.1f}" y2="{y1:.1f}"/>'
                            f'<line x1="{x - 3:.1f}" y1="{y2:.1f}" x2="{x + 3:.1f}" y2="{y2:.1f}"/></g>')
                shape = STRATEGY_SHAPES.get(strategy, "circle")
                tip = (f"{names[i]} level:{level}"
                       + (f" strategy:{strategy}" if strategy else "")
                       + f" - {fmt_speed(speed)}, ratio {ratio:.3f}, {v['n']} files"
                       + (f", cv {v['cv'] * 100:.1f}%" if v["cv"] > 0 else "")
                       + (f", mem {fmt_mem(v['mem'])}" if v["mem"] > 0 else ""))
                marker(svg, shape, x, sy(speed), SERIES[i], tip)
                if strategy:
                    stag = STRATEGY_TAGS.get(strategy, strategy[:3])
                    tag = stag if level_free.get((i, strategy)) else f"{stag}{level}"
                else:
                    tag = f"L{level}"
                base = points[0]["deflate"].get((level, strategy))
                if i > 0 and len(points) == 2 and base:
                    tag += f" {(speed - base['speed']) / base['speed'] * 100.0:+.0f}%"
                label_point(x, sy(speed), tag)
    # Labels last so markers never cover them
    for x, y, tag in labeled:
        svg.text(x + 7, y - 7, tag, size=10)

    # Synthetic data-type line panels, inflate plus deflate at one level
    panels = []
    if data_types:
        panels.append(("inflate, synthetic data types", "inflate",
                       [p["inflate_data"] for p in points], None))

    data_top = max(488, py + ph + 76, right_bottom + 36)
    for pi, (caption, tipword, series, note) in enumerate(panels):
        types = order_types(set().union(*(set(s) for s in series)))
        dpx, dpy, dpw, dph = 78, data_top + pi * 234, 942, 180
        svg.text(dpx, dpy - 18, f"{caption}, each group scaled to its fastest",
                 size=12, fill=INK)
        if note:
            svg.text(dpx + dpw, dpy - 18, note, size=10, anchor="end")
        svg.line(dpx, dpy + dph, dpx + dpw, dpy + dph, INK_SOFT)

        group = dpw / len(types)
        active = [i for i, s in enumerate(series) if s]
        nbars = len(active)
        bar_w = min(14.0, (group - 24) / nbars)
        for j, t in enumerate(types):
            gx = dpx + j * group
            if j:
                svg.line(gx, dpy + 8, gx, dpy + dph, GRID)
            svg.text(gx + group / 2, dpy + dph + 18, t, size=11, anchor="middle")
            gvals = [(s[t]["speed"], i) for i, s in enumerate(series) if t in s]
            if not gvals:
                continue
            gmax, gmax_i = max(gvals)
            scale = (dph - 30) / gmax
            x0 = gx + (group - nbars * bar_w - (nbars - 1) * 2) / 2
            for i, s in enumerate(series):
                if t not in s:
                    continue
                v = s[t]
                h = max(v["speed"] * scale, 2)
                x = x0 + active.index(i) * (bar_w + 2)
                ytop = dpy + dph - h
                tip = (f"{names[i]} {tipword} {t} - {fmt_speed(v['speed'])}"
                       + (f", {(v['speed'] / series[0][t]['speed'] - 1) * 100.0:+.1f}% "
                          f"vs {names[0]}" if i > 0 and t in series[0] else "")
                       + (f", cv {v['cv'] * 100:.1f}%" if v["cv"] > 0 else ""))
                svg.add(f'<rect x="{x:.1f}" y="{ytop:.1f}" width="{bar_w:.1f}" '
                        f'height="{h:.1f}" rx="1.5" fill="{SERIES[i]}">'
                        f'<title>{esc(tip)}</title></rect>')
                if i == gmax_i:
                    lx = min(max(x + bar_w / 2, gx + 26), gx + group - 26)
                    svg.text(lx, ytop - 6, fmt_speed(v["speed"]), size=9, anchor="middle")
                if v["cv"] > 0:
                    xc = x + bar_w / 2
                    y1 = dpy + dph - h * (1 + v["cv"])
                    y2 = dpy + dph - h * (1 - v["cv"])
                    svg.add(f'<line x1="{xc:.1f}" y1="{y1:.1f}" x2="{xc:.1f}" y2="{y2:.1f}" '
                            f'stroke="{INK_SOFT}" stroke-opacity="0.7" stroke-width="1"/>')
        better_arrow(svg, dpx + dpw + 18, dpy + 92, dpx + dpw + 18, dpy + 30)

    if panels:
        body_bottom = data_top + (len(panels) - 1) * 234 + 198
    else:
        body_bottom = max(456, right_bottom)

    # Deflate data types faceted per type, the level ladder on the x axis and
    # one line per codec, so every level reads as one set of curves
    if dd_types and any(k[1] > 0 for p in points for k in p["deflate_data"]):
        gtop = data_top + len(panels) * 234
        svg.text(78, gtop - 18, "deflate, synthetic data types by level",
                 size=12, fill=INK)
        svg.text(1020, gtop - 18, "level:0 in the panel above", size=10, anchor="end")
        gtop += 18
        lvs_all = sorted({k[1] for p in points for k in p["deflate_data"] if k[1] > 0})
        lvmin, lvmax = lvs_all[0], lvs_all[-1]

        def lxp(lv):
            return (lv - lvmin) / (lvmax - lvmin) if lvmax > lvmin else 0.5
        cols, fw, fh, gapx, gapy = 2, 459, 170, 24, 48
        for j, t in enumerate(dd_types):
            fx = 78 + (j % cols) * (fw + gapx)
            fy = gtop + (j // cols) * (fh + gapy)
            svg.text(fx, fy - 5, t, size=11, fill=INK)

            # Each facet spans its own range, labeled inside, so within-type
            # differences use the full height
            fspeeds = [v["speed"] for p in points
                       for k, v in p["deflate_data"].items()
                       if k[0] == t and k[1] > 0]
            if not fspeeds:
                continue
            lo, hi = min(fspeeds) / 1.3, max(fspeeds) * 1.3

            def fyv(s, top=fy, l=lo, h=hi):
                return top + fh - (math.log10(s) - math.log10(l)) / \
                    (math.log10(h) - math.log10(l)) * fh

            for e in range(6, 12):
                for mult in (1, 2, 5):
                    v = mult * 10.0 ** e
                    if lo <= v <= hi:
                        yy = fyv(v)
                        svg.line(fx, yy, fx + fw, yy, GRID)
                        svg.text(fx + fw - 4, yy - 3, fmt_speed(v), size=8, anchor="end")
            svg.line(fx, fy + fh, fx + fw, fy + fh, INK_SOFT)
            for lv in (1, 3, 6, 9, 12):
                if lvmin <= lv <= lvmax:
                    svg.text(fx + lxp(lv) * fw, fy + fh + 12, str(lv),
                             size=9, anchor="middle")
            for i, p in enumerate(points):
                pts = sorted((k[1], v) for k, v in p["deflate_data"].items()
                             if k[0] == t and k[1] > 0)
                if not pts:
                    continue
                coords = [(fx + lxp(lv) * fw, fyv(v["speed"])) for lv, v in pts]
                if len(coords) > 1:
                    path = " ".join(f"{'M' if q == 0 else 'L'}{x:.1f},{y:.1f}"
                                    for q, (x, y) in enumerate(coords))
                    svg.add(f'<path d="{path}" fill="none" stroke="{SERIES[i]}" '
                            f'stroke-width="2" stroke-opacity="0.7"/>')
                for (lv, v), (x, y) in zip(pts, coords):
                    tip = (f"{names[i]} deflate level:{lv} {t} - "
                           f"{fmt_speed(v['speed'])}, ratio {v['ratio']:.3f}"
                           + (f", cv {v['cv'] * 100:.1f}%" if v["cv"] > 0 else ""))
                    svg.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" '
                            f'fill="{SERIES[i]}" stroke="{SURFACE}" stroke-width="1.5">'
                            f'<title>{esc(tip)}</title></circle>')
        rows = (len(dd_types) + cols - 1) // cols
        better_arrow(svg, 1038, gtop + 92, 1038, gtop + 30)
        body_bottom = gtop + rows * (fh + gapy) - gapy + 20

    # windowBits line panel, deflate speed across the lookback window sizes
    wb_keys = sorted(set().union(*(set(p["wbits"]) for p in points)))
    if wb_keys:
        wtop = body_bottom + 66
        wpx, wpw, wph = 78, 942, 170
        levels = sorted({k[0] for k in wb_keys})
        caption = "deflate speed by windowBits"
        if len(levels) == 1:
            caption += f", level:{levels[0]}"
        svg.text(wpx, wtop - 18, caption, size=12, fill=INK)
        wvals = sorted({k[1] for k in wb_keys})
        wmin, wmax = wvals[0], wvals[-1]

        def wx(w):
            return wpx + (w - wmin) / (wmax - wmin) * wpw if wmax > wmin else wpx + wpw / 2

        wspeeds = [v["speed"] for p in points for v in p["wbits"].values()]
        wlo, whi = min(wspeeds) / 1.3, max(wspeeds) * 1.3

        def wy(s):
            return wtop + wph - (math.log10(s) - math.log10(wlo)) / \
                (math.log10(whi) - math.log10(wlo)) * wph

        for v in nice_log_ticks(wlo, whi):
            yy = wy(v)
            svg.line(wpx, yy, wpx + wpw, yy, GRID)
            svg.text(wpx - 8, yy + 4, fmt_speed(v), size=11, anchor="end")
        svg.line(wpx, wtop + wph, wpx + wpw, wtop + wph, INK_SOFT)
        for w in wvals:
            svg.text(wx(w), wtop + wph + 16, str(w), size=11, anchor="middle")
        svg.text(wpx + wpw / 2, wtop + wph + 34, "windowBits", size=12, anchor="middle")

        for lv in levels:
            for i, p in enumerate(points):
                pts = sorted((k[1], v) for k, v in p["wbits"].items() if k[0] == lv)
                if not pts:
                    continue
                coords = [(wx(w), wy(v["speed"])) for w, v in pts]
                if len(coords) > 1:
                    path = " ".join(f"{'M' if q == 0 else 'L'}{x:.1f},{y:.1f}"
                                    for q, (x, y) in enumerate(coords))
                    svg.add(f'<path d="{path}" fill="none" stroke="{SERIES[i]}" '
                            f'stroke-width="2" stroke-opacity="0.7"/>')
                for (w, v), (x, y) in zip(pts, coords):
                    if v["cv"] > 0:
                        y1, y2 = wy(v["speed"] * (1 - v["cv"])), wy(v["speed"] * (1 + v["cv"]))
                        svg.add(f'<line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" '
                                f'stroke="{SERIES[i]}" stroke-opacity="0.7" stroke-width="1.5"/>')
                    tip = (f"{names[i]} level:{lv} wbits:{w} - {fmt_speed(v['speed'])}"
                           + (f", ratio {v['ratio']:.3f}" if v["ratio"] > 0 else "")
                           + f", {v['n']} files"
                           + (f", cv {v['cv'] * 100:.1f}%" if v["cv"] > 0 else ""))
                    svg.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
                            f'fill="{SERIES[i]}" stroke="{SURFACE}" stroke-width="1.5">'
                            f'<title>{esc(tip)}</title></circle>')
                lw, lval = pts[-1]
                svg.text(wx(lw) - 8, wy(lval["speed"]) - 8, fmt_speed(lval["speed"]),
                         size=9, anchor="end")
        better_arrow(svg, wpx + wpw + 18, wtop + 92, wpx + wpw + 18, wtop + 30)
        body_bottom = wtop + wph + 44

    # Version and machine footnote, wrapped when the runs make it long
    note_parts = [f"{names[i]} {versions[i]}".strip() for i in range(len(names))]
    note = "  \u00b7  ".join(note_parts + ([machine] if machine else []))
    two_lines = machine and len(note) > 155
    height = body_bottom + 28 + (14 if two_lines else 0) + (16 if warnings else 0)
    y = height - 12
    if two_lines:
        svg.text(16, y, machine, size=10)
        y -= 14
        svg.text(16, y, "  \u00b7  ".join(note_parts), size=10)
    else:
        svg.text(16, y, note, size=10)

    # Warning badge above the footnote, never color alone
    if warnings:
        svg.text(16, y - 16, "\u26a0", size=10, fill="#c98500")
        svg.text(30, y - 16, " \u00b7 ".join(warnings), size=10)

    # Repository link on the bottom line
    svg.add(f'<a href="{REPO_URL}"><text x="{width - 16}" y="{height - 12}" '
            f'font-size="10" fill="{INK_SOFT}" text-anchor="end" '
            f'text-decoration="underline">{esc(REPO_URL.removeprefix("https://"))}'
            f'</text></a>')

    with open(out_path, "w") as f:
        f.write(svg.finish(height))


def print_table(names, points):
    n = len(names)

    def speed_cells(values, fmt=fmt_speed):
        """First run plain, later runs paired with their delta against it."""
        cells = [f"{fmt(values[0]) if values[0] else '-':>14}"]
        for i in range(1, n):
            s = fmt(values[i]) if values[i] else "-"
            if values[i] and values[0]:
                d = f"{(values[i] - values[0]) / values[0] * 100.0:+7.1f}%"
            else:
                d = "-"
            cells.append(f"{s:>14} {d:>8}")
        return " ".join(cells)

    cols = [f"{names[0]:>14}"] + [f"{names[i]:>14} {'Δ':>8}" for i in range(1, n)]
    ratio_cols = [f"{'ratio ' + names[i]:>14}" for i in range(n)]
    header = f"{'level/strategy':<22} " + " ".join(cols) + "  " + " ".join(ratio_cols)
    print(header)
    print("-" * len(header))

    for key in sorted(set().union(*(set(p["deflate"]) for p in points))):
        level, strategy = key
        tag = f"level:{level}" + (f"/{strategy}" if strategy else "")
        vals = [p["deflate"].get(key) for p in points]
        ratios = "  " + " ".join(
            f"{(format(v['ratio'], '.4f') if v else '-'):>14}" for v in vals)
        print(f"{tag:<22} " + speed_cells([v["speed"] if v else None for v in vals]) + ratios)

    for lv, w in sorted(set().union(*(set(p["wbits"]) for p in points))):
        print(f"{f'level:{lv}/wbits:{w}':<22} " + speed_cells(
            [p["wbits"][(lv, w)]["speed"] if (lv, w) in p["wbits"] else None
             for p in points]))

    dd_keys = sorted(
        set().union(*(set(p["deflate_data"]) for p in points)),
        key=lambda k: (DATA_TYPE_ORDER.index(k[0]) if k[0] in DATA_TYPE_ORDER else 9, k[1]))
    for t, l in dd_keys:
        print(f"{f'deflate/{t}:{l}':<22} " + speed_cells(
            [p["deflate_data"][(t, l)]["speed"] if (t, l) in p["deflate_data"] else None
             for p in points]))

    print(f"{'inflate':<22} "
          + speed_cells([p["inflate"]["speed"] if p["inflate"] else None for p in points]))
    for t in ordered_types(points):
        print(f"{'inflate/' + t:<22} " + speed_cells(
            [p["inflate_data"][t]["speed"] if t in p["inflate_data"] else None for p in points]))

    mems = run_mems(points)
    for di, dirname in enumerate(("deflate", "inflate")):
        if any(m[di] for m in mems):
            print(f"{dirname + ' memory':<22} "
                  + speed_cells([m[di] for m in mems], fmt_mem))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jsons", nargs="+", help="two or more benchmark JSON outputs")
    ap.add_argument("-o", "--output", default=None, help="output SVG path")
    ap.add_argument("--filter", default=None, help="regex applied to corpus labels")
    ap.add_argument("--names", default=None, help="comma-separated legend names")
    ap.add_argument("--title", default=None, help="chart title")
    args = ap.parse_args()

    if len(args.jsons) < 2:
        ap.error("need at least two runs to compare")
    runs = [load(p) for p in args.jsons]
    names = [r[0] for r in runs]
    if args.names:
        for i, given in enumerate(args.names.split(",")[:len(names)]):
            if given:
                names[i] = given
    versions = [r[1] for r in runs]
    machine = machine_line([r[3] for r in runs])
    corpus_filter = re.compile(args.filter) if args.filter else None

    points, corpus = aggregate(runs, corpus_filter)
    if len(corpus) == 1:
        corpus_desc = corpus[0]
    elif corpus:
        corpus_desc = f"geomean of {len(corpus)} corpus files"
    else:
        corpus_desc = "corpus geomean"
    warnings = run_warnings(names, runs)
    title = args.title or " vs ".join(names)
    out = args.output or "_vs_".join(names).replace("/", "_") + ".svg"

    for i in range(len(runs)):
        if versions[i]:
            print(f"{names[i]} {versions[i]}")
    for w in warnings:
        print(f"warning: {w}")
    print_table(names, points)
    render(names, versions, machine, corpus_desc, warnings, points, title, out)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
