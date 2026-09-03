/* codecs/slz.h -- libslz whole-buffer codec backend (compress only)
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * libslz is a stateless, single-pass raw deflate encoder aimed at maximum
 * speed and minimal memory, with no decoder. Only compiled when BENCH_SLZ
 * selects this backend; CODEC_NO_INFLATE suppresses the inflate benchmarks.
 */
#ifndef BENCHMARK_CODECS_SLZ_H
#define BENCHMARK_CODECS_SLZ_H

#include <stdint.h>
extern "C" {
#include <slz.h>
}

struct slz_codec_compressor {
    bool init(int) { return true; }

    size_t bound(size_t in_size) {
        /* Stored-block fallback plus envelope, generous for any input. */
        return in_size + (in_size >> 3) + 512;
    }

    /* Returns compressed size, 0 on failure */
    size_t compress(const uint8_t *in, size_t in_size, uint8_t *out, size_t) {
        struct slz_stream strm;
        slz_init(&strm, 1, SLZ_FMT_DEFLATE);
        long n = slz_encode(&strm, out, in, (long)in_size, 0);
        n += slz_finish(&strm, out + n);
        return (size_t)n;
    }

    void end() {}
};

/* libslz has a single compression level (0 = store, 1 = compress). */
#define CODEC_LEVELS { 1 }
#define CODEC_NO_INFLATE 1

typedef slz_codec_compressor codec_compressor;

#endif
