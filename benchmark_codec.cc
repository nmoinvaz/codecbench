/* benchmark_codec.cc -- whole-buffer deflate benchmarks across implementations
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * Compresses and decompresses corpus files through a minimal whole-buffer
 * codec interface so identical benchmark names can be produced for different
 * deflate implementations and compared with compare_runs.py.
 *
 * The backend is selected at compile time by benchmark_codec.h, zlib-ng by
 * default or another backend when its BENCH_* macro is defined.
 * Decompression input is always produced by zlib-ng at level 9, so every
 * backend inflates identical streams. All output is verified against the
 * original file contents. Deflate strategy variants are registered only by
 * backends that declare CODEC_STRATEGIES, windowBits variants only by
 * backends that declare CODEC_WBITS. Backends that declare CODEC_HAS_CRC32
 * or CODEC_HAS_ADLER32 register checksum benchmarks over a size ladder,
 * their results verified against zlib-ng.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vector>
#include <string>
#include <algorithm>
#include <benchmark/benchmark.h>

#include "zlib-ng.h"

extern "C" {
#  include "test_data.h"
}

#include "benchmark_corpora.h"
#include "codecs/benchmark_codec.h"
#include "benchmark_data_types.h"

static std::vector<corpus_file> corpora_files;

/* Synthetic data-type input sizes, in-cache and DRAM-resident */
#define CODEC_DATA_SIZE (128 * 1024)
#define CODEC_DATA_LARGE_SIZE (8 * 1024 * 1024)

class codec_deflate : public benchmark::Fixture {
private:
    int level;
    int strategy;
    int wbits;
    uint8_t *outbuff;
    size_t outbuff_size;
    size_t compressed_size;
    codec_compressor comp;
    bool comp_init;

protected:
    corpus_file *cf;

    /* Make cf->data available, or leave it NULL on failure */
    virtual void acquire_data() {
        load_corpus_file(cf);
    }
    virtual void release_data() {}

public:
    codec_deflate(const std::string &name, corpus_file *cf, int level,
                  int strategy = Z_DEFAULT_STRATEGY, int wbits = MAX_WBITS)
        : level(level), strategy(strategy), wbits(wbits), outbuff(NULL), outbuff_size(0),
          compressed_size(0), comp(), comp_init(false), cf(cf) {
        this->SetName(name);
    }

    void SetUp(const benchmark::State &) override {
        acquire_data();
        if (cf->data == NULL)
            return;

#if defined(CODEC_WBITS)
        comp_init = comp.init(level, strategy, wbits);
#elif defined(CODEC_STRATEGIES)
        (void)wbits;
        comp_init = comp.init(level, strategy);
#else
        (void)strategy;
        (void)wbits;
        comp_init = comp.init(level);
#endif
        if (!comp_init)
            return;

        outbuff_size = comp.bound(cf->size);
        outbuff = (uint8_t *)malloc(outbuff_size);
    }

    void BenchmarkCase(benchmark::State &state) override {
        if (cf->data == NULL || !comp_init || outbuff == NULL) {
            state.SkipWithError("setup failed");
            return;
        }

        for (auto _ : state) {
            compressed_size = comp.compress(cf->data, cf->size, outbuff, outbuff_size);
            if (compressed_size == 0) {
                state.SkipWithError("compress failed");
                break;
            }
        }

        if (state.skipped())
            return;

        if (!verify_compressed(outbuff, compressed_size, cf->data, cf->size)) {
            state.SkipWithError("roundtrip verification failed");
            return;
        }

        state.SetBytesProcessed((int64_t)state.iterations() * (int64_t)cf->size);
        state.counters["compressed"] = benchmark::Counter(double(compressed_size));
        state.counters["ratio"] = benchmark::Counter(double(cf->size) / double(compressed_size));
#ifdef CODEC_HAS_MEM
        state.counters["mem"] = benchmark::Counter(double(comp.mem()));
#endif
    }

    void TearDown(const benchmark::State &) override {
        if (comp_init) {
            comp.end();
            comp_init = false;
        }
        free(outbuff);
        outbuff = NULL;
        release_data();
    }
};

/* Synthetic data-type compression, isolates encoder paths by input composition */
class codec_deflate_type : public codec_deflate {
private:
    enum test_data_type type;
    corpus_file synth;

public:
    codec_deflate_type(const std::string &name, enum test_data_type type, int level)
        : codec_deflate(name, NULL, level), type(type), synth{"", NULL, CODEC_DATA_SIZE} {
        cf = &synth;
    }

protected:
    void acquire_data() override {
        synth.data = gen_test_data(type, synth.size);
    }

    void release_data() override {
        free(synth.data);
        synth.data = NULL;
    }
};

#ifndef CODEC_NO_INFLATE
/* Shared decompression benchmark, subclasses point cf at the original data */
class codec_inflate_base : public benchmark::Fixture {
private:
    uint8_t *compressed;
    size_t compressed_size;
    uint8_t *outbuff;
    codec_decompressor decomp;
    bool decomp_init;

protected:
    corpus_file *cf;

    /* Make cf->data available, or leave it NULL on failure */
    virtual void acquire_data() = 0;
    virtual void release_data() {}

public:
    codec_inflate_base(const std::string &name)
        : compressed(NULL), compressed_size(0), outbuff(NULL), decomp(), decomp_init(false),
          cf(NULL) {
        this->SetName(name);
    }

    void SetUp(const benchmark::State &) override {
        acquire_data();
        if (cf->data == NULL)
            return;

        compressed = reference_compress(cf->data, cf->size, &compressed_size);
        outbuff = (uint8_t *)malloc(cf->size);
        decomp_init = decomp.init();
    }

    void BenchmarkCase(benchmark::State &state) override {
        if (compressed == NULL || outbuff == NULL || !decomp_init) {
            state.SkipWithError("setup failed");
            return;
        }

        for (auto _ : state) {
            size_t out_size = decomp.decompress(compressed, compressed_size, outbuff, cf->size);
            if (out_size != cf->size) {
                state.SkipWithError("decompress failed");
                break;
            }
        }

        if (state.skipped())
            return;

        if (memcmp(outbuff, cf->data, cf->size) != 0) {
            state.SkipWithError("output does not match original");
            return;
        }

        state.SetBytesProcessed((int64_t)state.iterations() * (int64_t)cf->size);
        state.counters["compressed"] = benchmark::Counter(double(compressed_size));
        state.counters["ratio"] = benchmark::Counter(double(cf->size) / double(compressed_size));
#ifdef CODEC_HAS_MEM
        state.counters["mem"] = benchmark::Counter(double(decomp.mem()));
#endif
    }

    void TearDown(const benchmark::State &) override {
        if (decomp_init) {
            decomp.end();
            decomp_init = false;
        }
        free(compressed);
        compressed = NULL;
        free(outbuff);
        outbuff = NULL;
        release_data();
    }
};

/* Corpus file decompression */
class codec_inflate : public codec_inflate_base {
public:
    codec_inflate(const std::string &name, corpus_file *file)
        : codec_inflate_base(name) {
        cf = file;
    }

protected:
    void acquire_data() override {
        load_corpus_file(cf);
    }
};

/* Synthetic data-type decompression, isolates decoder paths by stream composition */
class codec_inflate_type : public codec_inflate_base {
private:
    enum test_data_type type;
    corpus_file synth;

public:
    codec_inflate_type(const std::string &name, enum test_data_type type, size_t size)
        : codec_inflate_base(name), type(type), synth{"", NULL, size} {
        cf = &synth;
    }

protected:
    void acquire_data() override {
        synth.data = gen_test_data(type, synth.size);
    }

    void release_data() override {
        free(synth.data);
        synth.data = NULL;
    }
};

#endif /* CODEC_NO_INFLATE */

#if defined(CODEC_HAS_CRC32) || defined(CODEC_HAS_ADLER32)
/* Whole-buffer checksum over random data, one benchmark per input size.
   The result is checked against zlib-ng once per run, so an incompatible
   or wrong checksum shows up as a benchmark error. */
class codec_checksum : public benchmark::Fixture {
private:
    uint32_t (*fn)(uint32_t, const uint8_t *, size_t);
    uint32_t (*ref)(uint32_t, const uint8_t *, size_t);
    uint32_t seed;
    size_t size;
    uint8_t *data;

public:
    codec_checksum(const std::string &name, uint32_t (*fn)(uint32_t, const uint8_t *, size_t),
                   uint32_t (*ref)(uint32_t, const uint8_t *, size_t), uint32_t seed, size_t size)
        : fn(fn), ref(ref), seed(seed), size(size), data(NULL) {
        this->SetName(name);
    }

    void SetUp(const benchmark::State &) override {
        data = gen_test_data(TEST_DATA_RANDOM, size);
    }

    void BenchmarkCase(benchmark::State &state) override {
        if (data == NULL) {
            state.SkipWithError("setup failed");
            return;
        }
        if (fn(seed, data, size) != ref(seed, data, size)) {
            state.SkipWithError("checksum does not match zlib-ng");
            return;
        }

        for (auto _ : state) {
            uint32_t sum = fn(seed, data, size);
            benchmark::DoNotOptimize(sum);
        }

        state.SetBytesProcessed((int64_t)state.iterations() * (int64_t)size);
    }

    void TearDown(const benchmark::State &) override {
        free(data);
        data = NULL;
    }
};

static uint32_t ref_crc32(uint32_t crc, const uint8_t *buf, size_t len) {
    return zng_crc32_z(crc, buf, len);
}

static uint32_t ref_adler32(uint32_t adler, const uint8_t *buf, size_t len) {
    return zng_adler32_z(adler, buf, len);
}

/* Small-buffer call overhead through streaming throughput, a factor 8 apart */
static const size_t codec_checksum_sizes[] = {64, 512, 4096, 32768, 262144, 2097152};

static int register_checksum_benchmarks(void) {
    for (size_t i = 0; i < sizeof(codec_checksum_sizes) / sizeof(codec_checksum_sizes[0]); i++) {
        size_t size = codec_checksum_sizes[i];
#ifdef CODEC_HAS_CRC32
        benchmark::internal::RegisterBenchmarkInternal(
            ::benchmark::internal::make_unique<codec_checksum>(
                "codec_crc32/size:" + std::to_string(size), codec_crc32, ref_crc32, 0, size));
#endif
#ifdef CODEC_HAS_ADLER32
        benchmark::internal::RegisterBenchmarkInternal(
            ::benchmark::internal::make_unique<codec_checksum>(
                "codec_adler32/size:" + std::to_string(size), codec_adler32, ref_adler32, 1, size));
#endif
    }
    return 0;
}

static int checksum_init = register_checksum_benchmarks();
#endif /* CODEC_HAS_CRC32 || CODEC_HAS_ADLER32 */

/* Registered at runtime for the data types selected by --benchmark_data_types */
static void codec_register_data_types(uint32_t mask) {
    static const struct {
        const char *name;
        enum test_data_type type;
    } types[] = {
        {"text",          TEST_DATA_TEXT},
        {"short_match",   TEST_DATA_SHORT_MATCH},
        {"dna",           TEST_DATA_DNA},
        {"random",        TEST_DATA_RANDOM},
        {"literals",      TEST_DATA_LITERALS},
        {"mixed",         TEST_DATA_MIXED},
        {"realistic_rgb", TEST_DATA_REALISTIC_RGB},
        {"phased",        TEST_DATA_PHASED},
        {"runs",          TEST_DATA_RUNS},
        {"striped_rgb",   TEST_DATA_STRIPED_RGB},
        {"far_match",     TEST_DATA_FAR_MATCH},
        {"records",       TEST_DATA_RECORDS},
    };

    for (size_t i = 0; i < sizeof(types) / sizeof(types[0]); i++) {
        if (!(mask & (1u << types[i].type)))
            continue;

        for (size_t l = 0; l < sizeof(codec_levels) / sizeof(codec_levels[0]); l++) {
            int level = codec_levels[l];
            std::string name = std::string("codec_deflate/data/") + types[i].name +
                               "/level:" + std::to_string(level);
            benchmark::internal::RegisterBenchmarkInternal(
                ::benchmark::internal::make_unique<codec_deflate_type>(name, types[i].type, level));
        }

#ifndef CODEC_NO_INFLATE
        std::string name = std::string("codec_inflate/data/") + types[i].name;
        benchmark::internal::RegisterBenchmarkInternal(
            ::benchmark::internal::make_unique<codec_inflate_type>(name, types[i].type,
                                                                   CODEC_DATA_SIZE));
        /* DRAM-resident variant, in-cache inflate ranks the backends differently */
        benchmark::internal::RegisterBenchmarkInternal(
            ::benchmark::internal::make_unique<codec_inflate_type>(
                name + "/size:" + std::to_string(CODEC_DATA_LARGE_SIZE), types[i].type,
                CODEC_DATA_LARGE_SIZE));
#endif
    }
}

static int codec_data_types = benchmark_data_types_hook(codec_register_data_types);

#ifdef CODEC_STRATEGIES
static const struct {
    const char *name;
    int strategy;
} codec_strategies[] = CODEC_STRATEGIES;

/* Strategy variants use the reduced level ladder of the deflate_bench strategy benchmarks */
static const int codec_strategy_levels[] = {1, 6, 9};
#endif

#ifdef CODEC_WBITS
/* windowBits variants sweep the lookback window at the default level. wbits 15
   duplicates the plain level run so the series is self-contained. */
static const int codec_wbits[] = CODEC_WBITS;
static const int codec_wbits_level = 6;
#endif

/* Dynamic benchmark registration at static init time */
static int register_codec_benchmarks(void) {
    corpora_files = discover_corpora();
    if (corpora_files.empty())
        return 0;

    size_t prefix_len = strlen(CORPORA_DIR) + 1;

    for (size_t i = 0; i < corpora_files.size(); i++) {
        corpus_file *cf = &corpora_files[i];
        std::string label = cf->path.substr(prefix_len);
        std::replace(label.begin(), label.end(), '\\', '/');

        for (size_t l = 0; l < sizeof(codec_levels) / sizeof(codec_levels[0]); l++) {
            int level = codec_levels[l];
            std::string name = "codec_deflate/" + label + "/level:" + std::to_string(level);
            benchmark::internal::RegisterBenchmarkInternal(
                ::benchmark::internal::make_unique<codec_deflate>(name, cf, level));
        }

#ifdef CODEC_STRATEGIES
        for (size_t s = 0; s < sizeof(codec_strategies) / sizeof(codec_strategies[0]); s++) {
            for (size_t l = 0; l < sizeof(codec_strategy_levels) / sizeof(codec_strategy_levels[0]); l++) {
                int level = codec_strategy_levels[l];
                /* Filtered only changes match selection in the deflate_slow
                   levels, so it skips level 1 and swaps level 6 for the first
                   slow level. zlib-ng runs deflate_medium through level 6 and
                   ignores the strategy there entirely. */
                if (codec_strategies[s].strategy == Z_FILTERED) {
                    if (level == 1)
                        continue;
                    if (level == 6)
                        level = 7;
                }
                std::string name = "codec_deflate/" + label + "/level:" + std::to_string(level) +
                                   "/strategy:" + codec_strategies[s].name;
                benchmark::internal::RegisterBenchmarkInternal(
                    ::benchmark::internal::make_unique<codec_deflate>(name, cf, level,
                                                                      codec_strategies[s].strategy));
            }
        }
#endif

#ifdef CODEC_WBITS
        for (size_t w = 0; w < sizeof(codec_wbits) / sizeof(codec_wbits[0]); w++) {
            std::string name = "codec_deflate/" + label +
                               "/level:" + std::to_string(codec_wbits_level) +
                               "/wbits:" + std::to_string(codec_wbits[w]);
            benchmark::internal::RegisterBenchmarkInternal(
                ::benchmark::internal::make_unique<codec_deflate>(name, cf, codec_wbits_level,
                                                                  Z_DEFAULT_STRATEGY,
                                                                  codec_wbits[w]));
        }
#endif

#ifndef CODEC_NO_INFLATE
        std::string name = "codec_inflate/" + label;
        benchmark::internal::RegisterBenchmarkInternal(
            ::benchmark::internal::make_unique<codec_inflate>(name, cf));
#endif
    }

    return 0;
}

static int codec_init = register_codec_benchmarks();
