#!/usr/bin/env python3
"""Compare two benchmark JSON outputs with time + compressed + ratio deltas.

Google Benchmark's stock compare.py only compares real_time and cpu_time. This
helper adds the user-defined counters (compressed, ratio) so that deflate and
corpora benchmarks can be A/B tested on compression quality as well as speed.

Usage:
    python3 .claude/scripts/compare_runs.py base.json contender.json

Works with both single-iteration and aggregated (--benchmark_repetitions) JSON
outputs; for aggregated runs the median row is used for each benchmark.

Borrowed semantics from Google Benchmark's compare.py:
- calculate_change handles old==0 edge case
- Overall summary uses geometric mean (not arithmetic)
- Time units harmonized via benchmark's time_unit field
- Color thresholds match compare.py (±5% warn, -7% win)
"""
import json
import math
import sys


_TIME_UNIT_TO_SECONDS = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}

BC_FAIL = "\033[91m"  # red
BC_CYAN = "\033[96m"  # cyan / win
BC_GREEN = "\033[92m"  # green / ratio win
BC_WHITE = "\033[0m"


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
    return out


def to_seconds(bench, field):
    """Convert a benchmark time field into seconds using its time_unit."""
    v = bench.get(field, 0.0)
    mult = _TIME_UNIT_TO_SECONDS.get(bench.get("time_unit", "s"), 1.0)
    return float(v) * mult


def calculate_change(old_val, new_val):
    """Percentage change from old to new, with edge case handling."""
    if old_val == 0 and new_val == 0:
        return 0.0
    if old_val == 0:
        return (new_val - old_val) / ((old_val + new_val) / 2.0) * 100.0
    return (new_val - old_val) / abs(old_val) * 100.0


def color_time(delta_pct):
    """compare.py thresholds: >5% regression red, -7% improvement cyan."""
    if delta_pct > 5.0:
        return BC_FAIL
    if delta_pct < -7.0:
        return BC_CYAN
    return BC_WHITE


def color_ratio(delta_pct):
    if delta_pct > 0.1:
        return BC_GREEN
    if delta_pct < -0.1:
        return BC_FAIL
    return BC_WHITE


def geomean(values):
    """Geometric mean of positive values; 0 if input empty or non-positive."""
    filtered = [v for v in values if v > 0]
    if not filtered:
        return 0.0
    log_sum = sum(math.log(v) for v in filtered)
    return math.exp(log_sum / len(filtered))


def format_row(short_name, width, delta_time, delta_cpu, delta_ratio, delta_bytes,
               base_time_s, new_time_s, base_ratio, new_ratio):
    has_ratio = base_ratio is not None and new_ratio is not None
    ct = color_time(delta_time)
    cc = color_time(delta_cpu)
    cr = color_ratio(delta_ratio) if has_ratio else BC_WHITE
    r = BC_WHITE
    # Display times in ms.
    b_t = base_time_s * 1e3
    n_t = new_time_s * 1e3
    b_rs = f"{base_ratio:>11.4f}" if has_ratio else f"{'-':>11}"
    n_rs = f"{new_ratio:>11.4f}" if has_ratio else f"{'-':>11}"
    return (f"{short_name:<{width}} {ct}{delta_time:>+8.2f}%{r} {cc}{delta_cpu:>+8.2f}%{r} "
            f"{cr}{delta_ratio:>+8.2f}%{r} {delta_bytes:>+10.0f}  "
            f"{b_t:>10.1f}ms {n_t:>10.1f}ms  {b_rs} {n_rs}")


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    base = load(sys.argv[1])
    cont = load(sys.argv[2])
    common = sorted(set(base) & set(cont))

    if not common:
        print("No benchmarks in common between the two inputs.", file=sys.stderr)
        sys.exit(1)

    short_names = [name.replace("deflate_corpora/", "").replace("silesia/", "") for name in common]
    width = max(20, max(len(s) for s in short_names))

    header = (f"{'Benchmark':<{width}} {'Δ time':>9} {'Δ cpu':>9} {'Δ ratio':>9} {'Δ bytes':>10}  "
              f"{'base time':>12} {'new time':>12}  {'base ratio':>11} {'new ratio':>11}")
    print(header)
    print("-" * len(header))

    base_times = []
    new_times = []
    time_deltas = []
    ratio_deltas = []

    for name, short in zip(common, short_names):
        b, c = base[name], cont[name]
        b_real = to_seconds(b, "real_time")
        c_real = to_seconds(c, "real_time")
        b_cpu = to_seconds(b, "cpu_time")
        c_cpu = to_seconds(c, "cpu_time")
        dtime = calculate_change(b_real, c_real)
        dcpu = calculate_change(b_cpu, c_cpu)
        base_ratio = b.get("ratio")
        new_ratio = c.get("ratio")
        dratio = calculate_change(base_ratio, new_ratio) if base_ratio is not None and new_ratio is not None else 0.0
        dbytes = (c.get("compressed", 0) - b.get("compressed", 0)) if "compressed" in b else 0

        base_times.append(b_real)
        new_times.append(c_real)
        time_deltas.append(dtime)
        if base_ratio is not None and new_ratio is not None:
            ratio_deltas.append(dratio)

        print(format_row(short, width, dtime, dcpu, dratio, dbytes,
                         b_real, c_real, base_ratio, new_ratio))

    print("-" * len(header))
    # Geometric mean of time ratios, like compare.py's OVERALL_GEOMEAN.
    if base_times and new_times:
        ratio_b = geomean(base_times)
        ratio_n = geomean(new_times)
        gm_delta = calculate_change(ratio_b, ratio_n)
    else:
        gm_delta = 0.0
    avg_r = sum(ratio_deltas) / len(ratio_deltas) if ratio_deltas else 0.0
    ct = color_time(gm_delta)
    cr = color_ratio(avg_r)
    r = BC_WHITE
    print(f"{'OVERALL_GEOMEAN':<{width}} {ct}{gm_delta:>+8.2f}%{r} {'':>10} "
          f"{cr}{avg_r:>+8.2f}%{r}  (ratio shown as arithmetic mean)")


if __name__ == "__main__":
    main()

