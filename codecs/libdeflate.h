/* codecs/libdeflate.h -- libdeflate whole-buffer codec backend
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * Reusable codec objects around libdeflate's one-shot raw deflate API. Only
 * compiled when BENCH_LIBDEFLATE selects this backend.
 */
#ifndef BENCHMARK_CODECS_LIBDEFLATE_H
#define BENCHMARK_CODECS_LIBDEFLATE_H

#include <stdint.h>
#include <libdeflate.h>

struct ld_codec_compressor {
    struct libdeflate_compressor *comp;

    bool init(int level) {
        comp = libdeflate_alloc_compressor(level);
        return comp != NULL;
    }

    size_t bound(size_t in_size) {
        return libdeflate_deflate_compress_bound(comp, in_size);
    }

    /* Returns compressed size, 0 on failure */
    size_t compress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        return libdeflate_deflate_compress(comp, in, in_size, out, out_size);
    }

    void end() {
        libdeflate_free_compressor(comp);
    }
};

struct ld_codec_decompressor {
    struct libdeflate_decompressor *decomp;

    bool init() {
        decomp = libdeflate_alloc_decompressor();
        return decomp != NULL;
    }

    /* Returns decompressed size, 0 on failure */
    size_t decompress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        size_t actual = 0;
        if (libdeflate_deflate_decompress(decomp, in, in_size, out, out_size, &actual) != LIBDEFLATE_SUCCESS)
            return 0;
        return actual;
    }

    void end() {
        libdeflate_free_decompressor(decomp);
    }
};

/* libdeflate spans levels 1 to 12. */
#define CODEC_LEVELS { 0, 1, 3, 6, 9, 12 }

typedef ld_codec_compressor   codec_compressor;
typedef ld_codec_decompressor codec_decompressor;

#endif
