/* codecs/zlib_shim.h -- stock zlib API behind an opaque shim
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * Shared by backends that implement the standard unprefixed zlib API, such
 * as Chromium zlib and madler zlib. Their headers cannot coexist with
 * zlib-ng.h in one translation unit, both define struct gzFile_s, so all
 * calls go through zlib_shim.c, compiled once per backend against that
 * backend's headers.
 */
#ifndef BENCHMARK_CODECS_ZLIB_SHIM_H
#define BENCHMARK_CODECS_ZLIB_SHIM_H

#include <stdint.h>
#include <stddef.h>

/* All shim backends report per-stream peak memory */
#define CODEC_HAS_MEM 1

#ifdef __cplusplus
extern "C" {
#endif

/* Implemented in zlib_shim.c. Handles are heap-allocated raw
   deflate/inflate streams, NULL on allocation or init failure. */
void *shim_zlib_deflate_new(int level, int strategy);
size_t shim_zlib_deflate_bound(void *comp, size_t in_size);
size_t shim_zlib_deflate_mem(void *comp);
size_t shim_zlib_compress(void *comp, const uint8_t *in, size_t in_size,
                          uint8_t *out, size_t out_size);
void shim_zlib_deflate_free(void *comp);

void *shim_zlib_inflate_new(void);
size_t shim_zlib_inflate_mem(void *decomp);
size_t shim_zlib_decompress(void *decomp, const uint8_t *in, size_t in_size,
                            uint8_t *out, size_t out_size);
void shim_zlib_inflate_free(void *decomp);

#ifdef __cplusplus
}

struct shim_codec_compressor {
    void *handle;

    /* strategy 0 is Z_DEFAULT_STRATEGY */
    bool init(int level, int strategy = 0) {
        handle = shim_zlib_deflate_new(level, strategy);
        return handle != NULL;
    }

    size_t bound(size_t in_size) {
        return shim_zlib_deflate_bound(handle, in_size);
    }

    /* Peak bytes the stream allocated */
    size_t mem() {
        return shim_zlib_deflate_mem(handle);
    }

    /* Returns compressed size, 0 on failure */
    size_t compress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        return shim_zlib_compress(handle, in, in_size, out, out_size);
    }

    void end() {
        shim_zlib_deflate_free(handle);
    }
};

struct shim_codec_decompressor {
    void *handle;

    bool init() {
        handle = shim_zlib_inflate_new();
        return handle != NULL;
    }

    /* Peak bytes the stream allocated */
    size_t mem() {
        return shim_zlib_inflate_mem(handle);
    }

    /* Returns decompressed size, 0 on failure */
    size_t decompress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        return shim_zlib_decompress(handle, in, in_size, out, out_size);
    }

    void end() {
        shim_zlib_inflate_free(handle);
    }
};
#endif

#endif
