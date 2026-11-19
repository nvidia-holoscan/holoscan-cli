# SPDX-FileCopyrightText: Copyright (c) {{cookiecutter.year}} {{cookiecutter.copyright_holder}}.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 4.0)
project({{ cookiecutter.project_slug }} LANGUAGES CXX)

# The CLI passes the selected SDK through CMAKE_PREFIX_PATH. Also honor the
# standard SDK environment variable for direct CMake builds.
if(DEFINED ENV{HOLOSCAN_SDK_ROOT})
  list(PREPEND CMAKE_PREFIX_PATH "$ENV{HOLOSCAN_SDK_ROOT}")
endif()
find_package(holoscan {{ cookiecutter.holoscan_version }} REQUIRED CONFIG COMPONENTS core)

add_executable({{ cookiecutter.project_slug }} main.cpp)
target_compile_features({{ cookiecutter.project_slug }} PRIVATE cxx_std_20)
target_link_libraries({{ cookiecutter.project_slug }} PRIVATE holoscan::core)
# Place the executable in the application's build directory, where the CLI
# starts the run commands from metadata.json.
set_target_properties({{ cookiecutter.project_slug }} PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/.."
  CXX_EXTENSIONS OFF)
install(TARGETS {{ cookiecutter.project_slug }} RUNTIME DESTINATION bin)

if(BUILD_TESTING)
  # Keep tests in the C++ dependency scope and preserve their build directory.
  add_subdirectory(../tests "${CMAKE_CURRENT_BINARY_DIR}/../tests")
endif()
