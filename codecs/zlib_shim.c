/* codecs/zlib_shim.c -- stock zlib calls behind an opaque API
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * Compiled once per stock-zlib backend against that backend's headers, the
 * only translation unit that sees them, they cannot coexist with zlib-ng.h.
 * One-shot raw deflate calls on persistent heap-allocated streams, reset
 * per call.
 */
#include <stdlib.h>
#include <string.h>

#include <zlib.h>

#include "zlib_shim.h"
#include "mem_count.h"

/* Stream plus its allocation counter, the opaque handle type */
typedef struct {
    z_stream strm;
    mem_counter mc;
} shim_stream;

static shim_stream *shim_stream_new(void) {
    shim_stream *ss = (shim_stream *)calloc(1, sizeof(shim_stream));
    if (ss == NULL)
        return NULL;
    ss->strm.zalloc = mem_count_alloc;
    ss->strm.zfree = mem_count_free;
    ss->strm.opaque = &ss->mc;
    return ss;
}

void *shim_zlib_deflate_new(int level, int strategy, int window_bits) {
    shim_stream *ss = shim_stream_new();
    if (ss == NULL)
        return NULL;

    if (deflateInit2(&ss->strm, level, Z_DEFLATED, -window_bits, MAX_MEM_LEVEL,
                     strategy) != Z_OK) {
        free(ss);
        return NULL;
    }
    return ss;
}

size_t shim_zlib_deflate_bound(void *comp, size_t in_size) {
    return (size_t)deflateBound(&((shim_stream *)comp)->strm, (uLong)in_size);
}

size_t shim_zlib_deflate_mem(void *comp) {
    return ((shim_stream *)comp)->mc.peak;
}

size_t shim_zlib_compress(void *comp, const uint8_t *in, size_t in_size,
                          uint8_t *out, size_t out_size) {
    z_stream *strm = &((shim_stream *)comp)->strm;

    if (deflateReset(strm) != Z_OK)
        return 0;

    strm->next_in = (Bytef *)in;
    strm->avail_in = (uInt)in_size;
    strm->next_out = out;
    strm->avail_out = (uInt)out_size;

    if (deflate(strm, Z_FINISH) != Z_STREAM_END)
        return 0;
    return (size_t)strm->total_out;
}

void shim_zlib_deflate_free(void *comp) {
    deflateEnd(&((shim_stream *)comp)->strm);
    free(comp);
}

void *shim_zlib_inflate_new(void) {
    shim_stream *ss = shim_stream_new();
    if (ss == NULL)
        return NULL;

    if (inflateInit2(&ss->strm, -MAX_WBITS) != Z_OK) {
        free(ss);
        return NULL;
    }
    return ss;
}

size_t shim_zlib_inflate_mem(void *decomp) {
    return ((shim_stream *)decomp)->mc.peak;
}

size_t shim_zlib_decompress(void *decomp, const uint8_t *in, size_t in_size,
                            uint8_t *out, size_t out_size) {
    z_stream *strm = &((shim_stream *)decomp)->strm;

    if (inflateReset(strm) != Z_OK)
        return 0;

    strm->next_in = (Bytef *)in;
    strm->avail_in = (uInt)in_size;
    strm->next_out = out;
    strm->avail_out = (uInt)out_size;

    if (inflate(strm, Z_FINISH) != Z_STREAM_END)
        return 0;
    return (size_t)strm->total_out;
}

void shim_zlib_inflate_free(void *decomp) {
    inflateEnd(&((shim_stream *)decomp)->strm);
    free(decomp);
}
