/* benchmark_codec.h -- codec backend selection for the codec benchmarks
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * Selects one whole-buffer codec backend at compile time and exposes it as
 * codec_compressor / codec_decompressor with the level set it supports. The
 * zlib-ng reference codec is always available for producing and verifying the
 * streams every backend shares. Include after the zlib-ng headers.
 */
#ifndef BENCHMARK_CODEC_H
#define BENCHMARK_CODEC_H

/* Reference codec plus reference_compress() / verify_compressed(), always
   compiled regardless of which backend is benchmarked. */
#include "zlib_ng.h"

#if defined(BENCH_LIBDEFLATE)
#  include "libdeflate.h"
#elif defined(BENCH_ISAL)
#  include "isal.h"
#elif defined(BENCH_SLZ)
#  include "slz.h"
#elif defined(BENCH_CHROMIUM_ZLIB)
#  include "chromium_zlib.h"
#elif defined(BENCH_MADLER_ZLIB)
#  include "madler_zlib.h"
#elif defined(BENCH_ZLIB_RS)
#  include "zlib_rs.h"
#else
/* zlib-ng is both the reference and the default backend. */
typedef zng_codec_compressor   codec_compressor;
typedef zng_codec_decompressor codec_decompressor;
#  define CODEC_LEVELS { 1, 3, 6, 9 }
/* Deflate strategies from the zlib API, also declared by the stock zlib
   backends. libdeflate, isal, and slz have no equivalent. */
#  define CODEC_STRATEGIES { {"filtered", Z_FILTERED}, {"huffman", Z_HUFFMAN_ONLY}, \
                             {"rle", Z_RLE}, {"fixed", Z_FIXED} }
#  define CODEC_HAS_MEM 1
#endif

static const int codec_levels[] = CODEC_LEVELS;

#endif
