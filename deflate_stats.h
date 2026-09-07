/* deflate_stats.h -- count literal and match symbols in a raw deflate stream
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * A minimal count-only raw-deflate walker in the spirit of puff and infgen.
 * It decodes block headers and Huffman symbols without producing output, so
 * every backend's stream can be characterized the same way. Stored bytes
 * count as literals. Returns 0 on success, nonzero on a malformed stream.
 */
#ifndef DEFLATE_STATS_H
#define DEFLATE_STATS_H

#include <stdint.h>
#include <string.h>

struct deflate_stats {
    uint64_t lit_syms;    /* literal symbols plus stored bytes */
    uint64_t match_syms;  /* length/distance pairs */
    uint64_t match_bytes; /* output bytes produced by matches */
    uint64_t blocks;
};

struct dstats_state {
    const uint8_t *in;
    size_t in_len, in_pos;
    uint32_t bitbuf;
    int bitcnt;
};

static int dstats_bits(struct dstats_state *st, int need) {
    while (st->bitcnt < need) {
        if (st->in_pos >= st->in_len)
            return -1;
        st->bitbuf |= (uint32_t)st->in[st->in_pos++] << st->bitcnt;
        st->bitcnt += 8;
    }
    int val = st->bitbuf & ((1u << need) - 1);
    st->bitbuf >>= need;
    st->bitcnt -= need;
    return val;
}

struct dstats_huff {
    uint16_t count[16];  /* number of codes per bit length */
    uint16_t symbol[288];
};

static int dstats_build(struct dstats_huff *h, const uint8_t *lengths, int n) {
    int len, left;
    uint16_t offs[16];

    memset(h->count, 0, sizeof(h->count));
    for (int i = 0; i < n; i++)
        h->count[lengths[i]]++;
    if (h->count[0] == n)
        return 0;
    left = 1;
    for (len = 1; len < 16; len++) {
        left <<= 1;
        left -= h->count[len];
        if (left < 0)
            return -1;
    }
    offs[1] = 0;
    for (len = 1; len < 15; len++)
        offs[len + 1] = (uint16_t)(offs[len] + h->count[len]);
    for (int i = 0; i < n; i++)
        if (lengths[i])
            h->symbol[offs[lengths[i]]++] = (uint16_t)i;
    return 0;
}

static int dstats_decode(struct dstats_state *st, const struct dstats_huff *h) {
    int code = 0, first = 0, index = 0;

    for (int len = 1; len < 16; len++) {
        int b = dstats_bits(st, 1);
        if (b < 0)
            return -1;
        code |= b;
        int cnt = h->count[len];
        if (code - first < cnt)
            return h->symbol[index + (code - first)];
        index += cnt;
        first = (first + cnt) << 1;
        code <<= 1;
    }
    return -1;
}

static const uint16_t dstats_len_base[29] = {
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
    35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
static const uint8_t dstats_len_extra[29] = {
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
    3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
static const uint8_t dstats_dist_extra[30] = {
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
    7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

static int dstats_block(struct dstats_state *st, const struct dstats_huff *lit,
                        const struct dstats_huff *dist, struct deflate_stats *out) {
    for (;;) {
        int sym = dstats_decode(st, lit);
        if (sym < 0)
            return -1;
        if (sym < 256) {
            out->lit_syms++;
        } else if (sym == 256) {
            return 0;
        } else {
            sym -= 257;
            if (sym >= 29)
                return -1;
            int extra = dstats_bits(st, dstats_len_extra[sym]);
            if (extra < 0)
                return -1;
            out->match_syms++;
            out->match_bytes += (uint64_t)dstats_len_base[sym] + (uint64_t)extra;
            int dsym = dstats_decode(st, dist);
            if (dsym < 0 || dsym >= 30)
                return -1;
            if (dstats_bits(st, dstats_dist_extra[dsym]) < 0)
                return -1;
        }
    }
}

static int deflate_stream_stats(const uint8_t *in, size_t in_len, struct deflate_stats *out) {
    struct dstats_state st = {in, in_len, 0, 0, 0};
    static const uint8_t clen_order[19] = {
        16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
    int last;

    memset(out, 0, sizeof(*out));
    do {
        last = dstats_bits(&st, 1);
        int type = dstats_bits(&st, 2);
        if (last < 0 || type < 0 || type == 3)
            return -1;
        out->blocks++;
        if (type == 0) {
            /* Stored block, byte aligned length header */
            st.bitbuf = 0;
            st.bitcnt = 0;
            if (st.in_pos + 4 > st.in_len)
                return -1;
            unsigned len = st.in[st.in_pos] | (st.in[st.in_pos + 1] << 8);
            st.in_pos += 4;
            if (st.in_pos + len > st.in_len)
                return -1;
            st.in_pos += len;
            out->lit_syms += len;
            continue;
        }
        struct dstats_huff lit, dist;
        uint8_t lengths[320];
        if (type == 1) {
            for (int i = 0; i < 144; i++) lengths[i] = 8;
            for (int i = 144; i < 256; i++) lengths[i] = 9;
            for (int i = 256; i < 280; i++) lengths[i] = 7;
            for (int i = 280; i < 288; i++) lengths[i] = 8;
            if (dstats_build(&lit, lengths, 288) < 0)
                return -1;
            for (int i = 0; i < 30; i++) lengths[i] = 5;
            if (dstats_build(&dist, lengths, 30) < 0)
                return -1;
        } else {
            int hlit = dstats_bits(&st, 5);
            int hdist = dstats_bits(&st, 5);
            int hclen = dstats_bits(&st, 4);
            if (hlit < 0 || hdist < 0 || hclen < 0)
                return -1;
            int nlit = hlit + 257, ndist = hdist + 1, nclen = hclen + 4;
            uint8_t clens[19];
            memset(clens, 0, sizeof(clens));
            for (int i = 0; i < nclen; i++) {
                int b = dstats_bits(&st, 3);
                if (b < 0)
                    return -1;
                clens[clen_order[i]] = (uint8_t)b;
            }
            struct dstats_huff clh;
            if (dstats_build(&clh, clens, 19) < 0)
                return -1;
            int n = 0;
            while (n < nlit + ndist) {
                int sym = dstats_decode(&st, &clh);
                if (sym < 0)
                    return -1;
                if (sym < 16) {
                    lengths[n++] = (uint8_t)sym;
                } else {
                    int rep, val = 0;
                    if (sym == 16) {
                        if (n == 0)
                            return -1;
                        val = lengths[n - 1];
                        rep = dstats_bits(&st, 2);
                        if (rep < 0)
                            return -1;
                        rep += 3;
                    } else if (sym == 17) {
                        rep = dstats_bits(&st, 3);
                        if (rep < 0)
                            return -1;
                        rep += 3;
                    } else {
                        rep = dstats_bits(&st, 7);
                        if (rep < 0)
                            return -1;
                        rep += 11;
                    }
                    if (n + rep > nlit + ndist)
                        return -1;
                    while (rep--)
                        lengths[n++] = (uint8_t)val;
                }
            }
            if (dstats_build(&lit, lengths, nlit) < 0)
                return -1;
            if (dstats_build(&dist, lengths + nlit, ndist) < 0)
                return -1;
        }
        if (dstats_block(&st, &lit, &dist, out) < 0)
            return -1;
    } while (!last);
    return 0;
}

#endif
