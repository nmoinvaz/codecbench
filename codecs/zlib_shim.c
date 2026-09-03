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

void *shim_zlib_deflate_new(int level) {
    z_stream *strm = (z_stream *)calloc(1, sizeof(z_stream));
    if (strm == NULL)
        return NULL;

    if (deflateInit2(strm, level, Z_DEFLATED, -MAX_WBITS, MAX_MEM_LEVEL,
                     Z_DEFAULT_STRATEGY) != Z_OK) {
        free(strm);
        return NULL;
    }
    return strm;
}

size_t shim_zlib_deflate_bound(void *comp, size_t in_size) {
    return (size_t)deflateBound((z_stream *)comp, (uLong)in_size);
}

size_t shim_zlib_compress(void *comp, const uint8_t *in, size_t in_size,
                          uint8_t *out, size_t out_size) {
    z_stream *strm = (z_stream *)comp;

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
    deflateEnd((z_stream *)comp);
    free(comp);
}

void *shim_zlib_inflate_new(void) {
    z_stream *strm = (z_stream *)calloc(1, sizeof(z_stream));
    if (strm == NULL)
        return NULL;

    if (inflateInit2(strm, -MAX_WBITS) != Z_OK) {
        free(strm);
        return NULL;
    }
    return strm;
}

size_t shim_zlib_decompress(void *decomp, const uint8_t *in, size_t in_size,
                            uint8_t *out, size_t out_size) {
    z_stream *strm = (z_stream *)decomp;

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
    inflateEnd((z_stream *)decomp);
    free(decomp);
}
