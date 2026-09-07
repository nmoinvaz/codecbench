#!/usr/bin/env python3
"""Profile the statistical character of a corpus directory into an SVG.

Reads the data itself rather than codec output: byte-value distribution,
order-0 and order-1 entropy, a greedy LZ parse over sampled windows for
match coverage by distance and length, run structure, and deflate
reference points. One row per file, so the files' subtleties compare
directly.

Usage:
    scripts/profile_corpus.py test/data/corpora/silesia [-o silesia-profile.svg]
"""
import argparse
import math
import sys
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from graph_runs import (Svg, SURFACE, INK, INK_SOFT, GRID, SERIES, esc,
                        fmt_bytes, better_arrow)

WINDOW = 32768          # history a match may reach back over, deflate's window
SCAN = 65536            # bytes parsed per sampled block
BLOCKS = 8              # sampled blocks per file
MIN_MATCH = 4

DIST_BUCKETS = [(16, "dist 1-16"), (256, "17-256"), (4096, "257-4K"),
                (WINDOW, "4K-32K")]
LEN_BUCKETS = [(7, "len 4-7"), (15, "8-15"), (63, "16-63"), (257, "64-257"),
               (1 << 30, "258+")]


def entropy(counts, total):
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c:
            p = c / total
            h -= p * math.log2(p)
    return h


def sample_ranges(n):
    """Up to BLOCKS scan ranges with WINDOW bytes of preamble each."""
    if n <= (WINDOW + SCAN) * BLOCKS:
        return [(0, n)]
    step = n // BLOCKS
    return [(i * step, i * step + WINDOW + SCAN) for i in range(BLOCKS)]


def greedy_parse(data, start, end):
    """Greedy LZ parse of [start+WINDOW, end), matches reach into the preamble.

    Returns literal bytes, match byte counters by distance and length bucket,
    and the digram counter feeding order-1 entropy.
    """
    table = {}
    lit = 0
    dist_bytes = Counter()
    len_bytes = Counter()
    scan_from = start + min(WINDOW, end - start - 1) if end - start > SCAN else start
    pos = start
    n = end
    while pos < scan_from:
        table[bytes(data[pos:pos + MIN_MATCH])] = pos
        pos += 1
    while pos < n - MIN_MATCH:
        key = bytes(data[pos:pos + MIN_MATCH])
        cand = table.get(key)
        table[key] = pos
        # A greedy parse skips table inserts inside matches, so runs would
        # otherwise attribute to the last parse position instead of dist 1.
        if pos > start and key == bytes(data[pos - 1:pos - 1 + MIN_MATCH]):
            cand = pos - 1
        if cand is not None and pos - cand <= WINDOW:
            dist = pos - cand
            length = MIN_MATCH
            limit = min(n - pos, 16384)
            while length < limit and data[cand + length] == data[pos + length]:
                length += 1
            for cap, _ in DIST_BUCKETS:
                if dist <= cap:
                    dist_bytes[cap] += length
                    break
            for cap, _ in LEN_BUCKETS:
                if length <= cap:
                    len_bytes[cap] += length
                    break
            pos += length
        else:
            lit += 1
            pos += 1
    return lit, dist_bytes, len_bytes


def profile(path):
    data = path.read_bytes()
    n = len(data)
    st = {"name": path.name, "size": n}
    if n == 0:
        return None

    hist = Counter(data)
    counts = [hist.get(i, 0) for i in range(256)]
    st["hist"] = counts
    st["h0"] = entropy(counts, n)
    st["printable"] = sum(hist.get(i, 0) for i in
                          list(range(32, 127)) + [9, 10, 13]) / n
    st["top_byte"] = max(counts) / n

    digrams = Counter()
    lit = 0
    dist_bytes = Counter()
    len_bytes = Counter()
    for start, end in sample_ranges(n):
        block = data[start:end]
        digrams.update(zip(block, block[1:]))
        bl, bd, bn = greedy_parse(data, start, end)
        lit += bl
        dist_bytes += bd
        len_bytes += bn
    st["lit"] = lit
    st["dist_bytes"] = dist_bytes
    st["len_bytes"] = len_bytes

    # H(next | prev) from the sampled digrams
    total = sum(digrams.values())
    by_prev = Counter()
    for (a, _), c in digrams.items():
        by_prev[a] += c
    h1 = 0.0
    for (a, _), c in digrams.items():
        h1 -= c / total * math.log2(c / by_prev[a])
    st["h1"] = h1

    st["deflate1"] = len(zlib.compress(data, 1)) * 8 / n
    st["deflate6"] = len(zlib.compress(data, 6)) * 8 / n
    return st


def render(corpus, stats, out_path):
    width = 1080
    svg = Svg(width)
    left = 150
    pw = width - left - 40
    row_h = 22

    svg.text(16, 28, f"{corpus} corpus profile", size=15, fill=INK, weight="bold")
    svg.text(16, 46, f"{len(stats)} files, {fmt_bytes(sum(s['size'] for s in stats))} total"
             ", greedy 4-byte parse over sampled 32K-history windows", size=11)

    def row_labels(top):
        for i, s in enumerate(stats):
            y = top + i * row_h
            svg.text(left - 8, y + row_h / 2 + 4, s["name"], size=10, anchor="end")

    # Byte-value heatmap, log-scaled intensity
    top = 92
    svg.text(left, top - 10, "byte value distribution, log intensity", size=12, fill=INK)
    svg.text(left + pw, top - 10, "0 .. 255", size=10, anchor="end")
    row_labels(top)
    cell = pw / 256
    for i, s in enumerate(stats):
        y = top + i * row_h
        peak = math.log1p(max(s["hist"]))
        cells = []
        for v, c in enumerate(s["hist"]):
            if c == 0:
                continue
            o = 0.08 + 0.92 * math.log1p(c) / peak
            cells.append(f'<rect x="{left + v * cell:.2f}" y="{y + 2:.1f}" '
                         f'width="{cell + 0.05:.2f}" height="{row_h - 4}" '
                         f'opacity="{o:.2f}"/>')
        svg.add(f'<g fill="{SERIES[0]}">{"".join(cells)}</g>')
    for x, lbl in ((0, "0"), (32, "32"), (127, "127"), (255, "255")):
        svg.text(left + x * cell, top + len(stats) * row_h + 14, lbl, size=9,
                 anchor="middle")
    top += len(stats) * row_h + 52

    # Bits per byte: order-0, order-1, deflate references
    svg.text(left, top - 10, "bits per byte", size=12, fill=INK)
    series = [("h0", "order-0 entropy", SERIES[0]), ("h1", "order-1 entropy", SERIES[1]),
              ("deflate1", "deflate level 1", SERIES[3]), ("deflate6", "deflate level 6", SERIES[2])]
    lx = left + pw
    for key, lbl, color in reversed(series):
        svg.text(lx, top - 10, lbl, size=9, anchor="end")
        lx -= 5.2 * len(lbl) + 8
        svg.add(f'<circle cx="{lx:.1f}" cy="{top - 14}" r="4" fill="{color}"/>')
        lx -= 14
    row_labels(top)
    for b in range(0, 9, 2):
        x = left + b / 8 * pw
        svg.line(x, top, x, top + len(stats) * row_h, GRID)
        svg.text(x, top + len(stats) * row_h + 14, str(b), size=9, anchor="middle")
    for i, s in enumerate(stats):
        y = top + i * row_h + row_h / 2
        svg.line(left, y, left + pw, y, GRID)
        for key, lbl, color in series:
            x = left + min(s[key], 8.0) / 8 * pw
            svg.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{color}" '
                    f'stroke="{SURFACE}" stroke-width="1.5">'
                    f'<title>{esc(f"{s['name']} {lbl} - {s[key]:.2f} bits/byte")}</title>'
                    f'</circle>')
    better_arrow(svg, left + 120, top + len(stats) * row_h + 26,
                 left + 20, top + len(stats) * row_h + 26)
    top += len(stats) * row_h + 64

    # Stacked coverage by nearest-match distance
    svg.text(left, top - 10, "greedy parse bytes by match distance", size=12, fill=INK)
    dist_series = [(None, "literals", "#7a7668")] + \
        [(cap, lbl, SERIES[j]) for j, (cap, lbl) in enumerate(DIST_BUCKETS)]
    lx = left + pw
    for cap, lbl, color in reversed(dist_series):
        svg.text(lx, top - 10, lbl, size=9, anchor="end")
        lx -= 5.2 * len(lbl) + 8
        svg.add(f'<circle cx="{lx:.1f}" cy="{top - 14}" r="4" fill="{color}"/>')
        lx -= 14
    row_labels(top)
    for i, s in enumerate(stats):
        y = top + i * row_h
        total = s["lit"] + sum(s["dist_bytes"].values())
        x = left
        for cap, lbl, color in dist_series:
            v = s["lit"] if cap is None else s["dist_bytes"].get(cap, 0)
            if v == 0:
                continue
            w = v / total * pw
            share = v / total * 100
            svg.add(f'<rect x="{x:.1f}" y="{y + 3}" width="{max(w, 0.8):.1f}" '
                    f'height="{row_h - 6}" fill="{color}">'
                    f'<title>{esc(f"{s['name']} {lbl} - {share:.1f}%")}</title></rect>')
            if w > 34:
                svg.text(x + w / 2, y + row_h / 2 + 4, f"{share:.0f}%", size=9,
                         fill=SURFACE, anchor="middle")
            x += w
    top += len(stats) * row_h + 30

    # Stacked matched bytes by match length
    svg.text(left, top - 10, "matched bytes by match length", size=12, fill=INK)
    len_series = [(cap, lbl, SERIES[j]) for j, (cap, lbl) in enumerate(LEN_BUCKETS)]
    lx = left + pw
    for cap, lbl, color in reversed(len_series):
        svg.text(lx, top - 10, lbl, size=9, anchor="end")
        lx -= 5.2 * len(lbl) + 8
        svg.add(f'<circle cx="{lx:.1f}" cy="{top - 14}" r="4" fill="{color}"/>')
        lx -= 14
    row_labels(top)
    for i, s in enumerate(stats):
        y = top + i * row_h
        total = sum(s["len_bytes"].values())
        if total == 0:
            svg.text(left, y + row_h / 2 + 4, "no matches", size=10)
            continue
        x = left
        for cap, lbl, color in len_series:
            v = s["len_bytes"].get(cap, 0)
            if v == 0:
                continue
            w = v / total * pw
            share = v / total * 100
            svg.add(f'<rect x="{x:.1f}" y="{y + 3}" width="{max(w, 0.8):.1f}" '
                    f'height="{row_h - 6}" fill="{color}">'
                    f'<title>{esc(f"{s['name']} {lbl} - {share:.1f}% of matched bytes")}'
                    f'</title></rect>')
            if w > 34:
                svg.text(x + w / 2, y + row_h / 2 + 4, f"{share:.0f}%", size=9,
                         fill=SURFACE, anchor="middle")
            x += w
    top += len(stats) * row_h + 30

    # Size, printable share, top byte share
    svg.text(left, top - 10, "file size, printable share, most common byte", size=12, fill=INK)
    row_labels(top + 14)
    size_max = max(s["size"] for s in stats)
    col_w = (pw - 80) / 3
    for j, hdr in enumerate(("size", "printable", "top byte")):
        svg.text(left + j * (col_w + 40) + col_w, top + 8, hdr, size=9, anchor="end")
    top += 14
    for i, s in enumerate(stats):
        y = top + i * row_h
        vals = [(s["size"] / size_max, fmt_bytes(s["size"])),
                (s["printable"], f"{s['printable'] * 100:.0f}%"),
                (s["top_byte"], f"{s['top_byte'] * 100:.1f}%")]
        for j, (frac, lbl) in enumerate(vals):
            x = left + j * (col_w + 40)
            svg.add(f'<rect x="{x:.1f}" y="{y + 5}" width="{max(frac * (col_w - 52), 1):.1f}" '
                    f'height="{row_h - 10}" rx="3" fill="{SERIES[j]}"/>')
            svg.text(x + col_w, y + row_h / 2 + 4, lbl, size=9, anchor="end")
    top += len(stats) * row_h + 20

    svg.text(16, top, "profile_corpus.py, entropy and deflate rates on whole files, "
             "parse statistics on sampled windows", size=9)
    Path(out_path).write_text(svg.finish(top + 16))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus", help="corpus directory")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    d = Path(args.corpus)
    files = sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        sys.exit(f"no files in {d}")
    stats = []
    for p in files:
        s = profile(p)
        if s:
            stats.append(s)
            print(f"{s['name']}: h0 {s['h0']:.2f} h1 {s['h1']:.2f} "
                  f"deflate6 {s['deflate6']:.2f} bits/byte, "
                  f"literals {s['lit'] / (s['lit'] + sum(s['dist_bytes'].values()) or 1) * 100:.0f}%")
    out = args.output or f"{d.name}-profile.svg"
    render(d.name, stats, out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
