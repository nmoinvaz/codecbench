/* codecs/isal.h -- Intel ISA-L (igzip) whole-buffer codec backend
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * Reusable codec objects around igzip's one-shot raw deflate API. Only
 * compiled when BENCH_ISAL selects this backend. igzip encodes and decodes
 * raw deflate via IGZIP_DEFLATE / ISAL_DEFLATE, matching the reference stream.
 */
#ifndef BENCHMARK_CODECS_ISAL_H
#define BENCHMARK_CODECS_ISAL_H

#include <stdint.h>
#include <stdlib.h>
#include <isa-l/igzip_lib.h>

struct isal_codec_compressor {
    struct isal_zstream strm;
    uint8_t *level_buf;
    int level;

    bool init(int lvl) {
        level = lvl;
        /* Largest per-level working buffer, reused across resets. */
        uint32_t sizes[] = {ISAL_DEF_LVL0_DEFAULT, ISAL_DEF_LVL1_DEFAULT,
                            ISAL_DEF_LVL2_DEFAULT, ISAL_DEF_LVL3_DEFAULT};
        uint32_t buf_size = sizes[lvl < 0 ? 0 : (lvl > ISAL_DEF_MAX_LEVEL ? ISAL_DEF_MAX_LEVEL : lvl)];
        level_buf = buf_size ? (uint8_t *)malloc(buf_size) : NULL;
        if (buf_size && level_buf == NULL)
            return false;
        isal_deflate_init(&strm);
        strm.level = (uint32_t)lvl;
        strm.level_buf = level_buf;
        strm.level_buf_size = buf_size;
        return true;
    }

    size_t bound(size_t in_size) {
        /* igzip level 0 huffman-codes with its default tables and never emits
           stored blocks, incompressible input can expand well past the
           deflate stored-block worst case. */
        return in_size + (in_size >> 1) + 4096;
    }

    /* Returns compressed size, 0 on failure */
    size_t compress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        isal_deflate_reset(&strm);
        strm.level = (uint32_t)level;
        strm.level_buf = level_buf;
        strm.gzip_flag = IGZIP_DEFLATE;
        strm.next_in = (uint8_t *)in;
        strm.avail_in = (uint32_t)in_size;
        strm.next_out = out;
        strm.avail_out = (uint32_t)out_size;
        strm.end_of_stream = 1;
        strm.flush = NO_FLUSH;
        if (isal_deflate(&strm) != ISAL_DECOMP_OK || strm.internal_state.state != ZSTATE_END)
            return 0;
        return (size_t)strm.total_out;
    }

    void end() {
        free(level_buf);
        level_buf = NULL;
    }
};

struct isal_codec_decompressor {
    struct inflate_state state;

    bool init() {
        return true;
    }

    /* Returns decompressed size, 0 on failure */
    size_t decompress(const uint8_t *in, size_t in_size, uint8_t *out, size_t out_size) {
        isal_inflate_init(&state);
        state.crc_flag = ISAL_DEFLATE;
        state.next_in = (uint8_t *)in;
        state.avail_in = (uint32_t)in_size;
        state.next_out = out;
        state.avail_out = (uint32_t)out_size;
        if (isal_inflate(&state) != ISAL_DECOMP_OK)
            return 0;
        return (size_t)state.total_out;
    }

    void end() {}
};

/* igzip spans levels 0 to 3. */
#define CODEC_LEVELS { 0, 1, 2, 3 }

typedef isal_codec_compressor   codec_compressor;
typedef isal_codec_decompressor codec_decompressor;

#endif
