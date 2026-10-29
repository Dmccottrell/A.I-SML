# The Emvryx app for Windows (main.cc). Built on GitHub's Windows machine by .github/workflows/windows-app.yml:
#   cmake -S windows-app -B build -DEMVRYX_BUILT_FROM=<commit> && cmake --build build --config Release
cmake_minimum_required(VERSION 3.16)
project(emvryx_windows LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded")          # no separate Visual C++ download needed on the person's PC

foreach(off WEBVIEW_BUILD_TESTS WEBVIEW_BUILD_EXAMPLES WEBVIEW_BUILD_DOCS WEBVIEW_INSTALL_DOCS WEBVIEW_INSTALL_TARGETS WEBVIEW_ENABLE_CHECKS
            WEBVIEW_ENABLE_PACKAGING WEBVIEW_BUILD_SHARED_LIBRARY)
    set(${off} OFF CACHE BOOL "" FORCE)
endforeach()
set(WEBVIEW_USE_STATIC_MSVC_RUNTIME ON CACHE BOOL "" FORCE)

include(FetchContent)
# Pinned to webview 0.12.0, so every build gets the same library
FetchContent_Declare(webview GIT_REPOSITORY https://github.com/webview/webview.git GIT_TAG 0.12.0 GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(webview)

set(EMVRYX_BUILT_FROM "" CACHE STRING "The commit GitHub built this app from (app_updates)")
string(REGEX REPLACE "[^0-9a-f]" "" EMVRYX_BUILT_FROM_CLEAN "${EMVRYX_BUILT_FROM}")

add_executable(emvryx WIN32 main.cc emvryx.rc)
target_link_libraries(emvryx PRIVATE webview::core)
target_compile_definitions(emvryx PRIVATE "EMVRYX_BUILT_FROM=\"${EMVRYX_BUILT_FROM_CLEAN}\"")
set_target_properties(emvryx PROPERTIES OUTPUT_NAME "Emvryx")
