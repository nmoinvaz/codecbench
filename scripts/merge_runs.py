#!/usr/bin/env python3
"""Merge benchmark JSON files into one document.

Later files win on duplicate run_names, so a rerun of one segment can be
merged over an older result. Context comes from the first file.

Usage:
    scripts/merge_runs.py results/raw/*/zlibng-prs.json -o zlibng-prs.json
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsons", nargs="+")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    docs = []
    for p in args.jsons:
        with open(p) as f:
            docs.append(json.load(f))
    merged = dict(docs[0])
    rows = {}
    for d in docs:
        for b in d["benchmarks"]:
            rows[(b["run_name"], b.get("aggregate_name"))] = b
    merged["benchmarks"] = list(rows.values())
    with open(args.output, "w") as f:
        json.dump(merged, f)
    names = {rn for rn, _ in rows}
    print(f"{args.output}: {len(names)} benchmarks from {len(docs)} files")
    return 0


if __name__ == "__main__":
    main()
