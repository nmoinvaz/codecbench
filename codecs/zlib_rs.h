/* codecs/zlib_rs.h -- zlib-rs whole-buffer codec backend
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * zlib-rs is trifectatech's memory-safe Rust implementation of the zlib API,
 * consumed through the libz-rs-sys-cdylib C ABI crate. It exports the
 * standard unprefixed zlib symbols, so this backend builds only against a
 * native-API zlib-ng (ZLIB_COMPAT=OFF), calling through the stock zlib shim.
 * Only compiled when BENCH_ZLIB_RS selects this backend.
 */
#ifndef BENCHMARK_CODECS_ZLIB_RS_H
#define BENCHMARK_CODECS_ZLIB_RS_H

#include "zlib_shim.h"

/* zlib-rs spans the standard levels 0 to 9. */
#define CODEC_LEVELS { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 }

/* Standard zlib API deflate strategies, values match zlib-ng's. */
#define CODEC_STRATEGIES { {"filtered", Z_FILTERED}, {"huffman", Z_HUFFMAN_ONLY}, \
                           {"rle", Z_RLE}, {"fixed", Z_FIXED} }

typedef shim_codec_compressor   codec_compressor;
typedef shim_codec_decompressor codec_decompressor;

#endif
