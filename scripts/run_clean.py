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
import os
import re
import subprocess
import sys
import time


def busy_procs():
    if sys.platform == "win32":
        # ps under msys sees only msys processes, ask the perf counters
        query = ("Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | "
                 "Where-Object { $_.PercentProcessorTime -gt 50 -and "
                 "$_.Name -notin @('_Total', 'Idle', 'powershell') } | "
                 "ForEach-Object { $_.Name }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", query],
                             capture_output=True, text=True).stdout
        return [line.strip() for line in out.splitlines() if line.strip()]
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
    try:
        with open(out_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


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
    # CreateProcess rejects relative paths with forward slashes
    binary = os.path.abspath(args.binary)

    if not wait_idle():
        print("machine still busy, not running", file=sys.stderr)
        return 3
    doc = run(binary, args.filter, args.out, args)
    if doc is None:
        print(f"{args.out}: benchmark produced no output", file=sys.stderr)
        return 1
    for attempt in range(args.max_retries):
        bad = dirty_rows(doc, args.rc_limit, args.cv_limit)
        if not bad:
            break
        print(f"retry {attempt + 1}: {len(bad)} contaminated rows", file=sys.stderr)
        for name in bad:
            print(f"  {name}", file=sys.stderr)
        if not wait_idle():
            print("machine still busy, keeping the contaminated rows", file=sys.stderr)
            break
        flt = "^(" + "|".join(re.escape(n) for n in bad) + ")$"
        redo = run(binary, flt, args.out + ".retry", args)
        if redo is None:
            print("retry produced no output, keeping original rows", file=sys.stderr)
            break
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
