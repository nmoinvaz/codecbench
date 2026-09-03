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
# ISA-L (Intel igzip), needs nasm on x86
#============================================================================
option(WITH_ISAL "Add Intel ISA-L codec benchmarks" ON)
if(WITH_ISAL AND CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64|i.86")
    find_program(NASM_EXECUTABLE nasm)
    if(NOT NASM_EXECUTABLE)
        message(WARNING "Skipping ISA-L codec benchmarks, nasm not found")
        set(WITH_ISAL OFF)
    endif()
endif()
if(WITH_ISAL)
    find_package(isal QUIET)
    if(NOT isal_FOUND)
        if(NOT DEFINED ISAL_REPOSITORY)
            set(ISAL_REPOSITORY https://github.com/intel/isa-l.git)
        endif()
        if(NOT DEFINED ISAL_TAG)
            # ISA-L's CMake support postdates its v2.31.1 release, so a
            # post-release commit is pinned until a CMake-capable tag ships.
            set(ISAL_TAG ebcec1aea3239108a67cc6309aaaeed6211fed89)
        endif()

        FetchContent_Declare(isal
            GIT_REPOSITORY ${ISAL_REPOSITORY}
            GIT_TAG ${ISAL_TAG}
            EXCLUDE_FROM_ALL)
        FetchContent_MakeAvailable(isal)

        if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang|LCC")
            target_compile_options(isal PRIVATE -w)
        endif()
    endif()
endif()

#============================================================================
# libslz (Willy Tarreau), compress-only. Ships no CMake, so its sources are
# compiled into the codec executable directly.
#============================================================================
option(WITH_SLZ "Add libslz codec benchmarks" ON)
if(WITH_SLZ)
    if(NOT DEFINED SLZ_REPOSITORY)
        set(SLZ_REPOSITORY https://github.com/wtarreau/libslz.git)
    endif()
    if(NOT DEFINED SLZ_TAG)
        set(SLZ_TAG master)
    endif()
    FetchContent_Declare(slz
        GIT_REPOSITORY ${SLZ_REPOSITORY}
        GIT_TAG ${SLZ_TAG}
        EXCLUDE_FROM_ALL)
    FetchContent_MakeAvailable(slz)
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

if(WITH_ISAL)
    add_executable(codecbench_isal ${BENCH_CODEC_SRCS})
    target_compile_definitions(codecbench_isal PRIVATE BENCH_ISAL=1)
    target_link_libraries(codecbench_isal isal)
    list(APPEND BENCH_CODEC_TARGETS codecbench_isal)
endif()

if(WITH_SLZ)
    add_executable(codecbench_slz ${BENCH_CODEC_SRCS} ${slz_SOURCE_DIR}/src/slz.c ${slz_SOURCE_DIR}/src/slz_common.c)
    target_compile_definitions(codecbench_slz PRIVATE BENCH_SLZ=1)
    target_include_directories(codecbench_slz PRIVATE ${slz_SOURCE_DIR}/src)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang|LCC")
        set_source_files_properties(${slz_SOURCE_DIR}/src/slz.c ${slz_SOURCE_DIR}/src/slz_common.c PROPERTIES COMPILE_OPTIONS "-w;-std=gnu11")
    endif()
    list(APPEND BENCH_CODEC_TARGETS codecbench_slz)
endif()

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
