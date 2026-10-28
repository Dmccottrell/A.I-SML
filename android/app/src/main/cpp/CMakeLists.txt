# android_offline_model: llama.cpp built into the app, so the phone runs your own model file itself when the PC is off.
# The same engine the PC runs (llama-server), at a fixed version. GGML_CPU_ALL_VARIANTS builds the CPU code for each family of phone chips and
# the right one is picked when the app starts (an older phone gets code it can run, a newer one the fast instructions).
cmake_minimum_required(VERSION 3.22.1)
project(emvryx_llama C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(BUILD_SHARED_LIBS ON CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_APP OFF CACHE BOOL "" FORCE)
set(LLAMA_OPENSSL OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_LLAMAFILE OFF CACHE BOOL "" FORCE)
# android_phone_vision: the picture reader (tools/mtmd) as a library on its own, without its command-line tools or video
set(LLAMA_BUILD_MTMD ON CACHE BOOL "" FORCE)
set(MTMD_VIDEO OFF CACHE BOOL "" FORCE)
if(ANDROID AND ANDROID_ABI STREQUAL "arm64-v8a")
    set(GGML_BACKEND_DL ON CACHE BOOL "" FORCE)
    set(GGML_CPU_ALL_VARIANTS ON CACHE BOOL "" FORCE)
endif()                                                  # x86_64 (the emulator): one plain CPU build, only for testing the app

include(FetchContent)
# A local copy can be used instead of the download: -DFETCHCONTENT_SOURCE_DIR_LLAMA=/path/to/llama.cpp
# Pinned to release b11940 (commit eb7818c0b85c), so the build always gets the same engine.
FetchContent_Declare(llama GIT_REPOSITORY https://github.com/ggml-org/llama.cpp.git GIT_TAG b11940 GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(llama)

add_library(emvryx_llama SHARED emvryx_llama.cpp)
target_link_libraries(emvryx_llama llama ggml mtmd)
if(ANDROID)
    target_link_libraries(emvryx_llama android log)
endif()
