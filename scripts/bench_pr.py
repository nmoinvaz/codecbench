#!/usr/bin/env python3
"""Benchmark a zlib-ng pull request against upstream develop.

Fetches the PR from zlib-ng/zlib-ng, builds codecbench_zlibng once
against the PR head and once against its merge-base with develop (so a
stale PR is not credited with unrelated develop movement), runs both
sequentially through run_clean.py, and prints the compare_runs.py
report. Checkouts, builds, and result JSONs live under --workdir and
are reused across invocations.

Usage:
    scripts/bench_pr.py <pr-number> [--filter <re>] [--data-types <t,..>]
        [--reps 3] [--base <ref>] [--graph out.svg] [--workdir .pr-bench]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

UPSTREAM = "https://github.com/zlib-ng/zlib-ng.git"
SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
BACKEND_OFF = ["WITH_LIBDEFLATE", "WITH_ISAL", "WITH_SLZ", "WITH_MINIZ",
               "WITH_CHROMIUM_ZLIB", "WITH_MADLER_ZLIB", "WITH_ZLIB_RS",
               "WITH_LIBCOMPRESSION"]


def sh(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    subprocess.run(cmd, check=True, **kw)


def out(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True,
                          **kw).stdout.strip()


def checkout(workdir, pr, base_ref):
    """Fetch develop and the PR head, park each in its own worktree."""
    repo = workdir / "zlib-ng"
    if not repo.exists():
        sh(["git", "clone", UPSTREAM, str(repo)])
    sh(["git", "-C", str(repo), "fetch", "origin", "develop",
        f"+pull/{pr}/head:refs/pr/{pr}"])
    head = out(["git", "-C", str(repo), "rev-parse", f"refs/pr/{pr}"])
    if base_ref:
        base = out(["git", "-C", str(repo), "rev-parse", base_ref])
    else:
        base = out(["git", "-C", str(repo), "merge-base",
                    "origin/develop", head])
    trees = {}
    for name, rev in (("base", base), (f"pr-{pr}", head)):
        tree = workdir / name
        if not tree.exists():
            sh(["git", "-C", str(repo), "worktree", "add", "--detach",
                str(tree), rev])
        else:
            sh(["git", "-C", str(tree), "checkout", "--detach", rev])
        trees[name] = tree
    for name, rev in (("base", base), (f"pr-{pr}", head)):
        line = out(["git", "-C", str(repo), "log", "-1",
                    "--format=%h %s", rev])
        print(f"{name}: {line}")
    return trees


def build(workdir, name, source_dir):
    build_dir = workdir / f"build-{name}"
    flags = [f"-D{opt}=OFF" for opt in BACKEND_OFF]
    sh(["cmake", "-B", str(build_dir), "-S", str(ROOT),
        f"-DZLIBNG_SOURCE_DIR={source_dir}"] + flags,
       stdout=subprocess.DEVNULL)
    sh(["cmake", "--build", str(build_dir), "-j", "--target",
        "codecbench_zlibng"], stdout=subprocess.DEVNULL)
    return build_dir / "codecbench_zlibng"


def bench(binary, out_json, args):
    cmd = [sys.executable, str(SCRIPTS / "run_clean.py"), str(binary),
           "--filter", args.filter, "--out", str(out_json),
           "--reps", str(args.reps)]
    if args.data_types:
        cmd += ["--data-types", args.data_types]
    sh(cmd)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pr", type=int, help="zlib-ng/zlib-ng pull request number")
    ap.add_argument("--filter", default=None,
                    help="benchmark filter regex (default: tar levels plus "
                         "inflate, widened to the synthetic rows when "
                         "--data-types is given)")
    ap.add_argument("--data-types", default=None,
                    help="synthetic data types to include (type,..|all)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--base", default=None,
                    help="base ref (default: merge-base of develop and the PR)")
    ap.add_argument("--graph", default=None, metavar="SVG",
                    help="also render a comparison chart")
    ap.add_argument("--workdir", default=str(ROOT / ".pr-bench"))
    args = ap.parse_args()

    if args.filter is None:
        args.filter = r"tars/[^/]+/level:[0-9]$|^codec_inflate/tars/[^/]+$"
        if args.data_types:
            args.filter += r"|/data/"

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    trees = checkout(workdir, args.pr, args.base)

    binaries = {name: build(workdir, name, tree)
                for name, tree in trees.items()}

    jsons = {}
    for name, binary in binaries.items():
        jsons[name] = workdir / (f"pr{args.pr}-base.json" if name == "base"
                                 else f"pr{args.pr}-head.json")
        bench(binary, jsons[name], args)

    sh([sys.executable, str(SCRIPTS / "compare_runs.py"),
        str(jsons["base"]), str(jsons[f"pr-{args.pr}"])])
    if args.graph:
        sh([sys.executable, str(SCRIPTS / "graph_runs.py"),
            str(jsons["base"]), str(jsons[f"pr-{args.pr}"]),
            "--names", f"develop,pr-{args.pr}",
            "--title", f"zlib-ng develop vs PR #{args.pr}",
            "-o", args.graph])
    return 0


if __name__ == "__main__":
    sys.exit(main())
