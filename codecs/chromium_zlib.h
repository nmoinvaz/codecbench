/* codecs/chromium_zlib.h -- Chromium zlib whole-buffer codec backend
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * Chromium's zlib fork is the zlib shipped in Chrome, a streaming API
 * identical to upstream zlib with SIMD adler32/crc32 and chunked inflate
 * copies. It exports the standard unprefixed zlib symbols, so this backend
 * builds only against a native-API zlib-ng (ZLIB_COMPAT=OFF), calling
 * through the stock zlib shim. Only compiled when BENCH_CHROMIUM_ZLIB
 * selects this backend.
 */
#ifndef BENCHMARK_CODECS_CHROMIUM_ZLIB_H
#define BENCHMARK_CODECS_CHROMIUM_ZLIB_H

#include "zlib_shim.h"

/* Chromium zlib spans the standard levels 0 to 9. */
#define CODEC_LEVELS { 0, 1, 3, 6, 9 }

/* Standard zlib API deflate strategies, values match zlib-ng's. */
#define CODEC_STRATEGIES { {"filtered", Z_FILTERED}, {"huffman", Z_HUFFMAN_ONLY}, \
                           {"rle", Z_RLE}, {"fixed", Z_FIXED} }

typedef shim_codec_compressor   codec_compressor;
typedef shim_codec_decompressor codec_decompressor;

#endif
