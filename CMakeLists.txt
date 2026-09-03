# codecbench -- whole-buffer deflate benchmarks across implementations
#
# Builds one benchmark executable per codec backend from the same source so
# every binary registers identical benchmark names over the corpora files and
# synthetic data types, ready for comparison with scripts/compare_runs.py.
cmake_minimum_required(VERSION 3.28)

project(codecbench LANGUAGES C CXX)

if(NOT DEFINED CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

#============================================================================
# Google Benchmark
#============================================================================
find_package(benchmark 1.9.2 QUIET)
if(NOT benchmark_FOUND)
    if(NOT DEFINED GBENCHMARK_REPOSITORY)
        set(GBENCHMARK_REPOSITORY https://github.com/google/benchmark.git)
    endif()
    if(NOT DEFINED GBENCHMARK_TAG)
        set(GBENCHMARK_TAG v1.9.5)
    endif()

    set(BENCHMARK_ENABLE_TESTING OFF)
    set(BENCHMARK_ENABLE_INSTALL OFF)

    FetchContent_Declare(benchmark
        GIT_REPOSITORY ${GBENCHMARK_REPOSITORY}
        GIT_TAG ${GBENCHMARK_TAG}
        EXCLUDE_FROM_ALL)
    FetchContent_MakeAvailable(benchmark)
endif()

#============================================================================
# zlib-ng, the reference codec
#
# Always built with the native prefixed API (ZLIB_COMPAT=OFF) so the stock
# zlib backends, which export the standard unprefixed symbols, can coexist.
# Set ZLIBNG_SOURCE_DIR to a local checkout to benchmark work in progress.
#============================================================================
if(NOT DEFINED ZLIBNG_REPOSITORY)
    set(ZLIBNG_REPOSITORY https://github.com/zlib-ng/zlib-ng.git)
endif()
if(NOT DEFINED ZLIBNG_TAG)
    set(ZLIBNG_TAG 2.3.3)
endif()
set(ZLIBNG_SOURCE_DIR "" CACHE PATH "Local zlib-ng source directory overriding the fetched release")

set(BUILD_SHARED_LIBS OFF)
set(BUILD_TESTING OFF)
set(ZLIB_COMPAT OFF)
set(ZLIB_ALIASES OFF)

if(ZLIBNG_SOURCE_DIR)
    FetchContent_Declare(zlib_ng
        SOURCE_DIR ${ZLIBNG_SOURCE_DIR}
        EXCLUDE_FROM_ALL)
else()
    FetchContent_Declare(zlib_ng
        GIT_REPOSITORY ${ZLIBNG_REPOSITORY}
        GIT_TAG ${ZLIBNG_TAG}
        EXCLUDE_FROM_ALL)
endif()
FetchContent_MakeAvailable(zlib_ng)

#============================================================================
# libdeflate, always built alongside the zlib-ng reference
#============================================================================
if(NOT DEFINED LIBDEFLATE_REPOSITORY)
    set(LIBDEFLATE_REPOSITORY https://github.com/ebiggers/libdeflate.git)
endif()
if(NOT DEFINED LIBDEFLATE_TAG)
    set(LIBDEFLATE_TAG v1.26)
endif()

set(LIBDEFLATE_BUILD_SHARED_LIB OFF)
set(LIBDEFLATE_BUILD_GZIP OFF)
set(LIBDEFLATE_BUILD_TESTS OFF)

FetchContent_Declare(libdeflate
    GIT_REPOSITORY ${LIBDEFLATE_REPOSITORY}
    GIT_TAG ${LIBDEFLATE_TAG}
    EXCLUDE_FROM_ALL)
FetchContent_MakeAvailable(libdeflate)

# Third-party sources are not held to this project's warning set
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang|LCC")
    target_compile_options(libdeflate_static PRIVATE -w)
endif()

#============================================================================
# Codec benchmark executables, the same sources built once per backend
#============================================================================
set(BENCH_CODEC_SRCS
    benchmark_codec.cc
    benchmark_data_types.cc
    benchmark_main.cc
    )

add_executable(codecbench_zlibng ${BENCH_CODEC_SRCS})

add_executable(codecbench_libdeflate ${BENCH_CODEC_SRCS})
target_compile_definitions(codecbench_libdeflate PRIVATE BENCH_LIBDEFLATE=1)
target_link_libraries(codecbench_libdeflate libdeflate::libdeflate_static)

set(BENCH_CODEC_TARGETS codecbench_zlibng codecbench_libdeflate)

foreach(codec_target ${BENCH_CODEC_TARGETS})
    target_compile_definitions(${codec_target} PRIVATE
        -DTEST_DATA_DIR="${PROJECT_SOURCE_DIR}/test/data")
    if(MINGW)
        target_compile_definitions(${codec_target} PRIVATE -D_WIN32_WINNT=_WIN32_WINNT_WIN10)
    endif()
    target_include_directories(${codec_target} PRIVATE
        ${zlib_ng_SOURCE_DIR}
        ${zlib_ng_BINARY_DIR})
    target_link_libraries(${codec_target} zlib-ng benchmark::benchmark)
    if(WIN32)
        target_link_libraries(${codec_target} shlwapi)
    endif()
endforeach()
