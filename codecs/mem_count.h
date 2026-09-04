/* codecs/mem_count.h -- counting stream allocators for peak memory
 * Copyright (C) 2026 Nathan Moinvaziri
 * For conditions of distribution and use, see copyright notice in zlib.h
 *
 * Drop-in zalloc/zfree callbacks that track live and peak bytes per
 * counter. Each block is over-allocated by 16 bytes to remember its size
 * on free, keeping malloc's 16-byte alignment.
 */
#ifndef BENCHMARK_CODECS_MEM_COUNT_H
#define BENCHMARK_CODECS_MEM_COUNT_H

#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef struct {
    size_t live;
    size_t peak;
} mem_counter;

static void *mem_count_alloc(void *opaque, unsigned int items, unsigned int size) {
    mem_counter *mc = (mem_counter *)opaque;
    size_t bytes = (size_t)items * size;

    uint8_t *block = (uint8_t *)malloc(bytes + 16);
    if (block == NULL)
        return NULL;
    memcpy(block, &bytes, sizeof(bytes));

    mc->live += bytes;
    if (mc->live > mc->peak)
        mc->peak = mc->live;
    return block + 16;
}

static void mem_count_free(void *opaque, void *address) {
    mem_counter *mc = (mem_counter *)opaque;
    uint8_t *block = (uint8_t *)address - 16;
    size_t bytes;

    memcpy(&bytes, block, sizeof(bytes));
    mc->live -= bytes;
    free(block);
}

#endif
