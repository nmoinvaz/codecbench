# codecbench

Whole-buffer deflate benchmarks across implementations.

The same benchmark source builds once per codec backend, so every executable
registers identical benchmark names over the corpora files and synthetic data
types. Their JSON outputs compare directly with `scripts/compare_runs.py`.
Decompression input is always produced by zlib-ng at level 9, so every backend
inflates identical streams, and all output is verified against the original
data through zlib-ng.

## Backends

| Executable                 | Backend                     | Option              | Requires        |
| -------------------------- | --------------------------- | ------------------- | --------------- |
| `codecbench_zlibng`        | [zlib-ng] (reference)       | always              |                 |
| `codecbench_libdeflate`    | [libdeflate]                | always              |                 |
| `codecbench_isal`          | [ISA-L] (igzip)             | `WITH_ISAL`         | nasm on x86     |

[zlib-ng]: https://github.com/zlib-ng/zlib-ng
[libdeflate]: https://github.com/ebiggers/libdeflate
[ISA-L]: https://github.com/intel/isa-l

All backends are on by default and fetched at pinned versions during the CMake
configure. Each `<NAME>_REPOSITORY` / `<NAME>_TAG` pair can be overridden.
Levels follow what each backend supports, libdeflate adds `level:12`, igzip
spans 0-3.

## Building

```sh
git clone https://github.com/zlib-ng/corpora test/data/corpora
cmake -B build
cmake --build build -j
```

## Running

```sh
build/codecbench_zlibng --benchmark_list_tests=true
build/codecbench_zlibng --benchmark_filter="silesia" --benchmark_data_types=all
```

`--benchmark_data_types=<type,...|all>` selects the synthetic inputs (text,
short_match, dna, random, literals, mixed, realistic_rgb, striped_rgb).
`--benchmark_cooldown=<seconds>` sleeps between benchmark families to mitigate
thermal throttling.

## Comparing

```sh
build/codecbench_zlibng --benchmark_out=zlibng.json --benchmark_out_format=json
build/codecbench_libdeflate --benchmark_out=libdeflate.json --benchmark_out_format=json
scripts/compare_runs.py zlibng.json libdeflate.json
```

## Benchmarking a local zlib-ng

Point the reference backend at a checkout instead of the pinned release to
measure work in progress:

```sh
cmake -B build -D ZLIBNG_SOURCE_DIR=~/Source/zlib-ng
cmake --build build -j
```
