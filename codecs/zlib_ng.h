/* codecs/zlib_ng.h -- zlib-ng whole-buffer codec, the benchmark reference
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * One-shot raw deflate wrappers around a persistent zlib-ng stream. Always
 * compiled: it is the default codec backend, it produces the reference
 * streams every backend decompresses, and it verifies their output. Include
 * after the zlib-ng headers.
 */
#ifndef BENCHMARK_CODECS_ZLIB_NG_H
#define BENCHMARK_CODECS_ZLIB_NG_H

#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "mem_count.h"

/* zlib-ng codec, one-shot raw deflate calls on a persistent stream */
struct zng_codec_compressor {
    zng_stream strm;
    mem_counter mc;

    bool init(int level, int strategy = Z_DEFAULT_STRATEGY, int wbits = MAX_WBITS) {
        memset(&strm, 0, sizeof(strm));
        mc.live = mc.peak = 0;
        strm.zalloc = mem_count_alloc;
        strm.zfree = mem_count_free;
        strm.opaque = &mc;
        return zng_deflateInit2(&strm, level, Z_DEFLATED, -wbits, MAX_MEM_LEVEL,
                                strategy) == Z_OK;
    }

    /* Peak bytes the stream allocated */
    size_t mem() {
        return mc.peak;
    }

    size_t bound(size_t in_size) {
        return (size_t)zng_deflateBound(&strm, (unsigned long)in_size);
    }

    /* Returns compressed size, 0 on failure */
    size_t compress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        if (zng_deflateReset(&strm) != Z_OK)
            return 0;

        strm.next_in = (z_const uint8_t *)in;
        strm.avail_in = (uint32_t)in_size;
        strm.next_out = out;
        strm.avail_out = (uint32_t)out_size;

        if (zng_deflate(&strm, Z_FINISH) != Z_STREAM_END)
            return 0;
        return (size_t)strm.total_out;
    }

    void end() {
        zng_deflateEnd(&strm);
    }
};

struct zng_codec_decompressor {
    zng_stream strm;
    mem_counter mc;

    bool init() {
        memset(&strm, 0, sizeof(strm));
        mc.live = mc.peak = 0;
        strm.zalloc = mem_count_alloc;
        strm.zfree = mem_count_free;
        strm.opaque = &mc;
        return zng_inflateInit2(&strm, -MAX_WBITS) == Z_OK;
    }

    /* Peak bytes the stream allocated */
    size_t mem() {
        return mc.peak;
    }

    /* Returns decompressed size, 0 on failure */
    size_t decompress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        if (zng_inflateReset(&strm) != Z_OK)
            return 0;

        strm.next_in = (z_const uint8_t *)in;
        strm.avail_in = (uint32_t)in_size;
        strm.next_out = out;
        strm.avail_out = (uint32_t)out_size;

        if (zng_inflate(&strm, Z_FINISH) != Z_STREAM_END)
            return 0;
        return (size_t)strm.total_out;
    }

    void end() {
        zng_inflateEnd(&strm);
    }
};

/* Compress a buffer with zlib-ng raw deflate at level 9, so every codec
   backend decompresses an identical input stream. Returns a malloc'd buffer. */
static inline uint8_t *reference_compress(const uint8_t *data, size_t size, size_t *comp_size) {
    zng_codec_compressor comp;
    if (!comp.init(Z_BEST_COMPRESSION))
        return NULL;

    size_t bound = comp.bound(size);
    uint8_t *buf = (uint8_t *)malloc(bound);
    if (buf != NULL) {
        *comp_size = comp.compress(data, size, buf, bound);
        if (*comp_size == 0) {
            free(buf);
            buf = NULL;
        }
    }

    comp.end();
    return buf;
}

/* Decompress with zlib-ng raw inflate and compare against the original data.
   Verifying through zlib-ng also proves cross-library interoperability. */
static inline bool verify_compressed(const uint8_t *comp, size_t comp_size,
                                     const uint8_t *data, size_t size) {
    uint8_t *out = (uint8_t *)malloc(size);
    if (out == NULL)
        return false;

    zng_codec_decompressor decomp;
    bool ok = decomp.init();
    if (ok) {
        ok = decomp.decompress(comp, comp_size, out, size) == size &&
             memcmp(out, data, size) == 0;
        decomp.end();
    }

    free(out);
    return ok;
}

#endif
