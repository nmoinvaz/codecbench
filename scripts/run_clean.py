#!/usr/bin/env python3
"""Run a codecbench binary and retry contaminated rows until clean.

Waits for the machine to go idle, runs the benchmark, then reruns any
benchmark whose worst repetition diverged (real/cpu above the threshold)
or whose cv exceeds the limit, splicing the clean rerun into the output.

Usage:
    scripts/run_clean.py <binary> --filter <regex> --out <file.json>
        [--reps 3] [--cooldown 5] [--data-types all]
        [--max-retries 2] [--rc-limit 1.03] [--cv-limit 0.06]
"""
import argparse
import json
import re
import subprocess
import sys
import time


def busy_procs():
    out = subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout
    procs = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 10)
        if len(parts) > 10 and float(parts[2]) > 50.0:
            procs.append(parts[10])
    return procs


def wait_idle(timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        procs = busy_procs()
        if not procs:
            return True
        print(f"waiting for idle: {procs[0]}", file=sys.stderr)
        time.sleep(15)
    return False


def run(binary, flt, out_path, args):
    cmd = [binary, f"--benchmark_filter={flt}",
           f"--benchmark_repetitions={args.reps}",
           "--benchmark_report_aggregates_only=true",
           f"--benchmark_cooldown={args.cooldown}",
           f"--benchmark_out={out_path}", "--benchmark_out_format=json"]
    if args.data_types:
        cmd.append(f"--benchmark_data_types={args.data_types}")
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    with open(out_path) as f:
        return json.load(f)


def dirty_rows(doc, rc_limit, cv_limit):
    rows = {}
    for b in doc["benchmarks"]:
        rows.setdefault(b["run_name"], {})[b.get("aggregate_name")] = b
    bad = []
    for name, aggs in rows.items():
        mean = aggs.get("mean")
        cv = aggs.get("cv")
        if mean and mean.get("error_occurred"):
            bad.append(name)
        elif mean and mean["real_time"] / mean["cpu_time"] > rc_limit:
            bad.append(name)
        elif cv and cv["real_time"] > cv_limit:
            bad.append(name)
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("binary")
    ap.add_argument("--filter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--cooldown", type=int, default=5)
    ap.add_argument("--data-types", default=None)
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument("--rc-limit", type=float, default=1.03)
    ap.add_argument("--cv-limit", type=float, default=0.06)
    args = ap.parse_args()

    wait_idle()
    doc = run(args.binary, args.filter, args.out, args)
    for attempt in range(args.max_retries):
        bad = dirty_rows(doc, args.rc_limit, args.cv_limit)
        if not bad:
            break
        print(f"retry {attempt + 1}: {len(bad)} contaminated rows", file=sys.stderr)
        for name in bad:
            print(f"  {name}", file=sys.stderr)
        wait_idle()
        flt = "^(" + "|".join(re.escape(n) for n in bad) + ")$"
        redo = run(args.binary, flt, args.out + ".retry", args)
        redone = {b["run_name"] for b in redo["benchmarks"]}
        doc["benchmarks"] = [b for b in doc["benchmarks"]
                             if b["run_name"] not in redone] + redo["benchmarks"]
    with open(args.out, "w") as f:
        json.dump(doc, f)
    remaining = dirty_rows(doc, args.rc_limit, args.cv_limit)
    n = len({b["run_name"] for b in doc["benchmarks"]})
    print(f"{args.out}: {n} benchmarks, {len(remaining)} still dirty"
          + (f" ({', '.join(remaining[:3])})" if remaining else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
