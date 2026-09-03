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

include(FeatureSummary)
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
# libdeflate
#============================================================================
option(WITH_LIBDEFLATE "Add libdeflate codec benchmarks" ON)
if(WITH_LIBDEFLATE)
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
# Chromium zlib, the zlib shipped in Chrome. Built as an external project so
# its target names stay out of this build.
#============================================================================
option(WITH_CHROMIUM_ZLIB "Add Chromium zlib codec benchmarks" ON)
if(WITH_CHROMIUM_ZLIB)
    include(ExternalProject)

    if(NOT DEFINED CHROMIUM_ZLIB_REPOSITORY)
        set(CHROMIUM_ZLIB_REPOSITORY https://chromium.googlesource.com/chromium/src/third_party/zlib)
    endif()
    if(NOT DEFINED CHROMIUM_ZLIB_TAG)
        # Chromium zlib tracks the Chromium tree and tags no releases, so a
        # recent commit is pinned.
        set(CHROMIUM_ZLIB_TAG 285e94b8fa95ad3b7d16b80798ec8dce6febb8c8)
    endif()

    if(WIN32)
        set(CHROMIUM_ZLIB_NAME zs)
    else()
        set(CHROMIUM_ZLIB_NAME z)
    endif()
    set(CHROMIUM_ZLIB_LIB_NAME
        ${CMAKE_STATIC_LIBRARY_PREFIX}${CHROMIUM_ZLIB_NAME}${CMAKE_STATIC_LIBRARY_SUFFIX})

    # ENABLE_SIMD_OPTIMIZATIONS selects the configuration Chrome ships, not
    # the plain C fallback
    ExternalProject_Add(chromium_zlib
        GIT_REPOSITORY ${CHROMIUM_ZLIB_REPOSITORY}
        GIT_TAG ${CHROMIUM_ZLIB_TAG}
        CMAKE_ARGS
            -DCMAKE_C_COMPILER=${CMAKE_C_COMPILER}
            -DCMAKE_BUILD_TYPE=Release
            -DCMAKE_OSX_ARCHITECTURES=${CMAKE_OSX_ARCHITECTURES}
            -DZLIB_BUILD_TESTING=OFF
            -DZLIB_BUILD_SHARED=OFF
            -DZLIB_BUILD_STATIC=ON
            -DZLIB_INSTALL=OFF
            -DENABLE_SIMD_OPTIMIZATIONS=ON
        # Only the static library is wanted, the default build also makes
        # zlib_bench which needs the disabled shared target
        BUILD_COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> --target zlibstatic
        BUILD_BYPRODUCTS <BINARY_DIR>/${CHROMIUM_ZLIB_LIB_NAME}
        INSTALL_COMMAND ""
        )

    ExternalProject_Get_Property(chromium_zlib SOURCE_DIR BINARY_DIR)
    set(CHROMIUM_ZLIB_LIB ${BINARY_DIR}/${CHROMIUM_ZLIB_LIB_NAME})
    # zconf.h is generated into the external binary dir, zlib.h stays in source
    set(CHROMIUM_ZLIB_INCLUDE_DIRS ${BINARY_DIR} ${SOURCE_DIR})
endif()

#============================================================================
# madler zlib, stock upstream zlib as the baseline. Built as an external
# project so its target names stay out of this build.
#============================================================================
option(WITH_MADLER_ZLIB "Add madler zlib codec benchmarks" ON)
if(WITH_MADLER_ZLIB)
    include(ExternalProject)

    if(NOT DEFINED MADLER_ZLIB_REPOSITORY)
        set(MADLER_ZLIB_REPOSITORY https://github.com/madler/zlib.git)
    endif()
    if(NOT DEFINED MADLER_ZLIB_TAG)
        set(MADLER_ZLIB_TAG v1.3.1)
    endif()

    if(WIN32)
        set(MADLER_ZLIB_LIB_NAME zlibstatic${CMAKE_STATIC_LIBRARY_SUFFIX})
    else()
        set(MADLER_ZLIB_LIB_NAME ${CMAKE_STATIC_LIBRARY_PREFIX}z${CMAKE_STATIC_LIBRARY_SUFFIX})
    endif()

    ExternalProject_Add(madler_zlib
        GIT_REPOSITORY ${MADLER_ZLIB_REPOSITORY}
        GIT_TAG ${MADLER_ZLIB_TAG}
        CMAKE_ARGS
            -DCMAKE_C_COMPILER=${CMAKE_C_COMPILER}
            -DCMAKE_BUILD_TYPE=Release
            -DCMAKE_OSX_ARCHITECTURES=${CMAKE_OSX_ARCHITECTURES}
            -DZLIB_BUILD_EXAMPLES=OFF
        # Only the static library is wanted
        BUILD_COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> --target zlibstatic
        BUILD_BYPRODUCTS <BINARY_DIR>/${MADLER_ZLIB_LIB_NAME}
        INSTALL_COMMAND ""
        )

    ExternalProject_Get_Property(madler_zlib SOURCE_DIR BINARY_DIR)
    set(MADLER_ZLIB_LIB ${BINARY_DIR}/${MADLER_ZLIB_LIB_NAME})
    # zconf.h is generated into the external binary dir, zlib.h stays in source
    set(MADLER_ZLIB_INCLUDE_DIRS ${BINARY_DIR} ${SOURCE_DIR})
endif()

#============================================================================
# zlib-rs, trifectatech's memory-safe Rust implementation of the zlib API.
# Its libz-rs-sys-cdylib crate builds the C ABI static library with cargo.
#============================================================================
option(WITH_ZLIB_RS "Add zlib-rs codec benchmarks" ON)
if(WITH_ZLIB_RS)
    find_program(CARGO_EXECUTABLE cargo)
    if(NOT CARGO_EXECUTABLE)
        message(WARNING "Skipping zlib-rs codec benchmarks, cargo not found")
        set(WITH_ZLIB_RS OFF)
    endif()
endif()
if(WITH_ZLIB_RS)
    include(ExternalProject)

    if(NOT DEFINED ZLIB_RS_REPOSITORY)
        set(ZLIB_RS_REPOSITORY https://github.com/trifectatechfoundation/zlib-rs.git)
    endif()
    if(NOT DEFINED ZLIB_RS_TAG)
        set(ZLIB_RS_TAG v0.6.7)
    endif()

    set(ZLIB_RS_LIB_NAME ${CMAKE_STATIC_LIBRARY_PREFIX}z_rs${CMAKE_STATIC_LIBRARY_SUFFIX})

    # The default crate features select the C allocator and runtime SIMD
    # feature detection, the configuration of a drop-in libz replacement
    ExternalProject_Add(zlib_rs
        GIT_REPOSITORY ${ZLIB_RS_REPOSITORY}
        GIT_TAG ${ZLIB_RS_TAG}
        CONFIGURE_COMMAND ""
        BUILD_COMMAND ${CARGO_EXECUTABLE} build --release
            --manifest-path <SOURCE_DIR>/libz-rs-sys-cdylib/Cargo.toml
            --target-dir <BINARY_DIR>
        BUILD_BYPRODUCTS <BINARY_DIR>/release/${ZLIB_RS_LIB_NAME}
        INSTALL_COMMAND ""
        )

    ExternalProject_Get_Property(zlib_rs SOURCE_DIR BINARY_DIR)
    set(ZLIB_RS_LIB ${BINARY_DIR}/release/${ZLIB_RS_LIB_NAME})
    # The cdylib crate ships its own zlib.h and zconf.h
    set(ZLIB_RS_INCLUDE_DIRS ${SOURCE_DIR}/libz-rs-sys-cdylib/include)
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

set(BENCH_CODEC_TARGETS codecbench_zlibng)

if(WITH_LIBDEFLATE)
    add_executable(codecbench_libdeflate ${BENCH_CODEC_SRCS})
    target_compile_definitions(codecbench_libdeflate PRIVATE BENCH_LIBDEFLATE=1)
    target_link_libraries(codecbench_libdeflate libdeflate::libdeflate_static)
    list(APPEND BENCH_CODEC_TARGETS codecbench_libdeflate)
endif()

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

if(WITH_CHROMIUM_ZLIB)
    # The shim is the only TU compiled against Chromium's headers, they
    # cannot coexist with zlib-ng.h
    add_library(chromium_zlib_shim OBJECT codecs/zlib_shim.c)
    target_include_directories(chromium_zlib_shim PRIVATE ${CHROMIUM_ZLIB_INCLUDE_DIRS})
    add_dependencies(chromium_zlib_shim chromium_zlib)

    add_executable(codecbench_chromium_zlib ${BENCH_CODEC_SRCS})
    target_compile_definitions(codecbench_chromium_zlib PRIVATE BENCH_CHROMIUM_ZLIB=1)
    target_link_libraries(codecbench_chromium_zlib chromium_zlib_shim ${CHROMIUM_ZLIB_LIB})
    list(APPEND BENCH_CODEC_TARGETS codecbench_chromium_zlib)
endif()

if(WITH_MADLER_ZLIB)
    # The shim is the only TU compiled against madler zlib's headers, they
    # cannot coexist with zlib-ng.h
    add_library(madler_zlib_shim OBJECT codecs/zlib_shim.c)
    target_include_directories(madler_zlib_shim PRIVATE ${MADLER_ZLIB_INCLUDE_DIRS})
    add_dependencies(madler_zlib_shim madler_zlib)

    add_executable(codecbench_madler_zlib ${BENCH_CODEC_SRCS})
    target_compile_definitions(codecbench_madler_zlib PRIVATE BENCH_MADLER_ZLIB=1)
    target_link_libraries(codecbench_madler_zlib madler_zlib_shim ${MADLER_ZLIB_LIB})
    list(APPEND BENCH_CODEC_TARGETS codecbench_madler_zlib)
endif()

if(WITH_ZLIB_RS)
    # The shim is the only TU compiled against zlib-rs's headers, they
    # cannot coexist with zlib-ng.h
    add_library(zlib_rs_shim OBJECT codecs/zlib_shim.c)
    target_include_directories(zlib_rs_shim PRIVATE ${ZLIB_RS_INCLUDE_DIRS})
    add_dependencies(zlib_rs_shim zlib_rs)

    add_executable(codecbench_zlib_rs ${BENCH_CODEC_SRCS})
    target_compile_definitions(codecbench_zlib_rs PRIVATE BENCH_ZLIB_RS=1)
    target_link_libraries(codecbench_zlib_rs zlib_rs_shim ${ZLIB_RS_LIB})
    if(UNIX AND NOT APPLE)
        # The Rust standard library staticlib needs these on Linux
        target_link_libraries(codecbench_zlib_rs pthread dl m)
    endif()
    list(APPEND BENCH_CODEC_TARGETS codecbench_zlib_rs)
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

#============================================================================
# Config summary
#============================================================================
add_feature_info(WITH_LIBDEFLATE WITH_LIBDEFLATE "Add libdeflate codec benchmarks")
add_feature_info(WITH_ISAL WITH_ISAL "Add Intel ISA-L codec benchmarks")
add_feature_info(WITH_SLZ WITH_SLZ "Add libslz codec benchmarks")
add_feature_info(WITH_CHROMIUM_ZLIB WITH_CHROMIUM_ZLIB "Add Chromium zlib codec benchmarks")
add_feature_info(WITH_MADLER_ZLIB WITH_MADLER_ZLIB "Add madler zlib codec benchmarks")
add_feature_info(WITH_ZLIB_RS WITH_ZLIB_RS "Add zlib-rs codec benchmarks")
add_feature_info(ZLIBNG_SOURCE_DIR ZLIBNG_SOURCE_DIR "Benchmark a local zlib-ng checkout instead of the pinned release")

feature_summary(WHAT ALL INCLUDE_QUIET_PACKAGES)
