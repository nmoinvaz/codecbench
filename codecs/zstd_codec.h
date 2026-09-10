/* codecs/zstd_codec.h -- zstd whole-buffer codec backend (compress only)
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * zstd is not a deflate implementation, it is benchmarked as context for
 * what a modern format reaches on the same inputs. Compression only, the
 * inflate benchmarks decode shared zlib-ng streams a zstd decoder cannot
 * read. Streams verify through zstd's own decompressor.
 */
#ifndef BENCHMARK_CODECS_ZSTD_H
#define BENCHMARK_CODECS_ZSTD_H

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <zstd.h>

struct zstd_codec_compressor {
    ZSTD_CCtx *cctx = NULL;
    int level = 0;

    bool init(int level_) {
        cctx = ZSTD_createCCtx();
        level = level_;
        return cctx != NULL;
    }

    size_t bound(size_t in_size) {
        return ZSTD_compressBound(in_size);
    }

    /* Returns compressed size, 0 on failure */
    size_t compress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        size_t r = ZSTD_compressCCtx(cctx, out, out_size, in, in_size, level);
        return ZSTD_isError(r) ? 0 : r;
    }

    void end() {
        ZSTD_freeCCtx(cctx);
        cctx = NULL;
    }
};

/* zstd streams verify through zstd, not the zlib-ng reference inflater. */
static inline bool zstd_verify_compressed(const uint8_t *comp, size_t comp_size,
                                          const uint8_t *data, size_t size) {
    uint8_t *out = (uint8_t *)malloc(size ? size : 1);
    if (out == NULL)
        return false;
    size_t r = ZSTD_decompress(out, size, comp, comp_size);
    bool ok = !ZSTD_isError(r) && r == size && memcmp(out, data, size) == 0;
    free(out);
    return ok;
}
#define verify_compressed zstd_verify_compressed

/* A thinned ladder over zstd's 1..19 range keeps the high levels affordable
   while tracing the whole speed-ratio curve. */
#define CODEC_LEVELS { 1, 2, 3, 4, 5, 6, 7, 9, 12, 15, 17, 19 }
#define CODEC_NO_INFLATE 1

typedef zstd_codec_compressor codec_compressor;

#endif
