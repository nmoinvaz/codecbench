## Project Basics

- Use CMake build system.
- Every backend is fetched at a pinned version during configure; override with
  the `<NAME>_REPOSITORY` / `<NAME>_TAG` variables.
- Binaries are named `codecbench_<backend>` and land in the build directory
  root. Backends: zlibng (reference), libdeflate, isal, slz, chromium_zlib,
  madler_zlib, zlib_rs.
- All binaries register identical benchmark names over the shared level set,
  so their JSON outputs compare directly. libdeflate adds `level:12`, igzip
  spans levels 0-3, libslz has a single level and registers no inflate
  benchmarks.
- Deflate strategy variants (`/strategy:<name>`) register only for zlib-ng.
- Decompression input is always produced by zlib-ng at level 9 and all output
  is verified against the original data, a failed roundtrip shows up as a
  benchmark error.

## Test Data

- Clone the corpora repo before running:
  `git clone https://github.com/zlib-ng/corpora test/data/corpora`.
- Synthetic inputs are selected with `--benchmark_data_types=<type,...|all>`
  (text, short_match, dna, random, literals, mixed, realistic_rgb,
  striped_rgb). The generators are vendored in `test_data.h` so input
  definitions stay pinned to this repository.

## Benchmarking

- To benchmark zlib-ng work in progress, configure with
  `-D ZLIBNG_SOURCE_DIR=<checkout>`. The default builds the pinned release,
  keep separate build directories for release and work-in-progress builds.
- When running with `--benchmark_repetitions`, also use
  `--benchmark_report_aggregates_only=true` and `--benchmark_cooldown=5`.
- Run benchmark processes sequentially, otherwise contention causes
  unreliable results.
- Don't run benchmarks in the background.
- Look for other benchmark processes running on the machine to avoid
  contamination and wait until they are done.

### Comparing Results

- Run with `--benchmark_out=<file>.json --benchmark_out_format=json` and
  compare with `scripts/compare_runs.py base.json contender.json`. It reports
  time, compression ratio, and byte deltas.

### Presenting Results

- Always show performance changes as percentage (e.g. -18.4%), not as
  speedup ratios (e.g. 1.23x).
- When publishing results as a GitHub gist, start the title and filename with
  the project name and include the machine specs.

### Thermal Throttling

Benchmark results are vulnerable to thermal throttling, sustained workloads
heat the CPU until it downclocks and later benchmarks run slower than earlier
ones.

Signs of thermal contamination:

- Later benchmarks in a run are slower than earlier ones.
- The same benchmark gives wildly different results across runs.
- CV exceeds 3% on benchmarks that normally have less than 1%.

Mitigation:

- Add `sleep 10` or longer between separate benchmark processes.
- Run benchmark groups separately rather than all in one long chain.
- Verify with a quick A/B sanity check before committing to a full run.

See https://gist.github.com/nmoinvaz/42d997329fc4878993ec0f4f8e600c91 for
platform-specific steps to stabilize benchmark environments.
