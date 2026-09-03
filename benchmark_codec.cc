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
 * original file contents.
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

class codec_deflate : public benchmark::Fixture {
private:
    corpus_file *cf;
    int level;
    uint8_t *outbuff;
    size_t outbuff_size;
    size_t compressed_size;
    codec_compressor comp;
    bool comp_init;

public:
    codec_deflate(const std::string &name, corpus_file *cf, int level)
        : cf(cf), level(level), outbuff(NULL), outbuff_size(0), compressed_size(0),
          comp(), comp_init(false) {
        this->SetName(name);
    }

    void SetUp(const benchmark::State &) override {
        if (!load_corpus_file(cf))
            return;

        comp_init = comp.init(level);
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
    }

    void TearDown(const benchmark::State &) override {
        if (comp_init) {
            comp.end();
            comp_init = false;
        }
        free(outbuff);
        outbuff = NULL;
    }
};

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
    codec_inflate_type(const std::string &name, enum test_data_type type)
        : codec_inflate_base(name), type(type), synth{"", NULL, 1024 * 1024} {
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
        {"striped_rgb",   TEST_DATA_STRIPED_RGB},
    };

    for (size_t i = 0; i < sizeof(types) / sizeof(types[0]); i++) {
        if (!(mask & (1u << types[i].type)))
            continue;
        std::string name = std::string("codec_inflate/data/") + types[i].name;
        benchmark::internal::RegisterBenchmarkInternal(
            ::benchmark::internal::make_unique<codec_inflate_type>(name, types[i].type));
    }
}

static int codec_data_types = benchmark_data_types_hook(codec_register_data_types);

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

        std::string name = "codec_inflate/" + label;
        benchmark::internal::RegisterBenchmarkInternal(
            ::benchmark::internal::make_unique<codec_inflate>(name, cf));
    }

    return 0;
}

static int codec_init = register_codec_benchmarks();
