/* codecs/libcompression.h -- Apple Compression framework codec backend
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * COMPRESSION_ZLIB encodes and decodes raw deflate (RFC 1951) at a single
 * fixed quality, roughly zlib level 5. Whole-buffer calls on a persistent
 * scratch buffer. Only compiled when BENCH_LIBCOMPRESSION selects this
 * backend, macOS only.
 */
#ifndef BENCHMARK_CODECS_LIBCOMPRESSION_H
#define BENCHMARK_CODECS_LIBCOMPRESSION_H

#include <stdint.h>
#include <stdlib.h>
#include <compression.h>

struct lc_codec_compressor {
    uint8_t *scratch;
    size_t scratch_size;

    bool init(int) {
        scratch_size = compression_encode_scratch_buffer_size(COMPRESSION_ZLIB);
        scratch = scratch_size ? (uint8_t *)malloc(scratch_size) : NULL;
        return scratch_size == 0 || scratch != NULL;
    }

    size_t bound(size_t in_size) {
        /* No bound API, leave room for incompressible input. */
        return in_size + (in_size >> 3) + 4096;
    }

    /* Bytes of encoder scratch the stream requires */
    size_t mem() {
        return scratch_size;
    }

    /* Returns compressed size, 0 on failure */
    size_t compress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        return compression_encode_buffer(out, out_size, in, in_size, scratch,
                                         COMPRESSION_ZLIB);
    }

    void end() {
        free(scratch);
        scratch = NULL;
    }
};

struct lc_codec_decompressor {
    uint8_t *scratch;
    size_t scratch_size;

    bool init() {
        scratch_size = compression_decode_scratch_buffer_size(COMPRESSION_ZLIB);
        scratch = scratch_size ? (uint8_t *)malloc(scratch_size) : NULL;
        return scratch_size == 0 || scratch != NULL;
    }

    /* Bytes of decoder scratch the stream requires */
    size_t mem() {
        return scratch_size;
    }

    /* Returns decompressed size, 0 on failure */
    size_t decompress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        return compression_decode_buffer(out, out_size, in, in_size, scratch,
                                         COMPRESSION_ZLIB);
    }

    void end() {
        free(scratch);
        scratch = NULL;
    }
};

/* The encoder has one fixed quality, roughly zlib level 5. */
#define CODEC_LEVELS { 5 }

#define CODEC_HAS_MEM 1

typedef lc_codec_compressor   codec_compressor;
typedef lc_codec_decompressor codec_decompressor;

#endif
