/* codecs/miniz_codec.h -- miniz whole-buffer codec backend
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * miniz is the single-file DEFLATE implementation embedded across many
 * projects. Built with MINIZ_NO_ZLIB_COMPATIBLE_NAMES its mz_-prefixed
 * symbols coexist with zlib-ng.h, so no shim is needed. Only compiled when
 * BENCH_MINIZ selects this backend.
 */
#ifndef BENCHMARK_CODECS_MINIZ_CODEC_H
#define BENCHMARK_CODECS_MINIZ_CODEC_H

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <miniz.h>

#include "mem_count.h"

/* miniz alloc callbacks take size_t, adapt them to the counting allocators */
static void *miniz_count_alloc(void *opaque, size_t items, size_t size) {
    return mem_count_alloc(opaque, (unsigned int)items, (unsigned int)size);
}

static void miniz_count_free(void *opaque, void *address) {
    mem_count_free(opaque, address);
}

struct miniz_codec_compressor {
    mz_stream strm;
    mem_counter mc;

    bool init(int level, int strategy = MZ_DEFAULT_STRATEGY) {
        memset(&strm, 0, sizeof(strm));
        mc.live = mc.peak = 0;
        strm.zalloc = miniz_count_alloc;
        strm.zfree = miniz_count_free;
        strm.opaque = &mc;
        return mz_deflateInit2(&strm, level, MZ_DEFLATED, -MZ_DEFAULT_WINDOW_BITS,
                               9, strategy) == MZ_OK;
    }

    size_t bound(size_t in_size) {
        return (size_t)mz_deflateBound(&strm, (mz_ulong)in_size);
    }

    /* Peak bytes the stream allocated */
    size_t mem() {
        return mc.peak;
    }

    /* Returns compressed size, 0 on failure */
    size_t compress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        if (mz_deflateReset(&strm) != MZ_OK)
            return 0;

        strm.next_in = in;
        strm.avail_in = (unsigned int)in_size;
        strm.next_out = out;
        strm.avail_out = (unsigned int)out_size;

        if (mz_deflate(&strm, MZ_FINISH) != MZ_STREAM_END)
            return 0;
        return (size_t)strm.total_out;
    }

    void end() {
        mz_deflateEnd(&strm);
    }
};

struct miniz_codec_decompressor {
    mz_stream strm;
    mem_counter mc;

    bool init() {
        memset(&strm, 0, sizeof(strm));
        mc.live = mc.peak = 0;
        strm.zalloc = miniz_count_alloc;
        strm.zfree = miniz_count_free;
        strm.opaque = &mc;
        return mz_inflateInit2(&strm, -MZ_DEFAULT_WINDOW_BITS) == MZ_OK;
    }

    /* Peak bytes the stream allocated */
    size_t mem() {
        return mc.peak;
    }

    /* Returns decompressed size, 0 on failure */
    size_t decompress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        if (mz_inflateReset(&strm) != MZ_OK)
            return 0;

        strm.next_in = in;
        strm.avail_in = (unsigned int)in_size;
        strm.next_out = out;
        strm.avail_out = (unsigned int)out_size;

        if (mz_inflate(&strm, MZ_FINISH) != MZ_STREAM_END)
            return 0;
        return (size_t)strm.total_out;
    }

    void end() {
        mz_inflateEnd(&strm);
    }
};

/* miniz spans levels 0 to 10, 10 is MZ_UBER_COMPRESSION */
#define CODEC_LEVELS { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 }

/* Standard zlib API deflate strategies, values match zlib-ng's. */
#define CODEC_STRATEGIES { {"filtered", MZ_FILTERED}, {"huffman", MZ_HUFFMAN_ONLY}, \
                           {"rle", MZ_RLE}, {"fixed", MZ_FIXED} }

#define CODEC_HAS_MEM 1

typedef miniz_codec_compressor   codec_compressor;
typedef miniz_codec_decompressor codec_decompressor;

#endif
