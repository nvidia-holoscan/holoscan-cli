# SPDX-FileCopyrightText: Copyright (c) {{cookiecutter.year}} {{cookiecutter.copyright_holder}}.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.24)
project({{ cookiecutter.project_slug }}_apps LANGUAGES NONE)
include(CTest)

# Register SDK-free tests here, under BUILD_TESTING and outside the language
# scope below, so they run without the SDK, a GPU, or external data.
# Tests that need the SDK belong in tests/CMakeLists.txt.

# The CLI's --language option sets this switch. It defaults to ON so that plain
# CMake builds include the application.
{%- if cookiecutter.language == 'python' %}
option(HOLOHUB_BUILD_PYTHON "Build the Python application" ON)

if(HOLOHUB_BUILD_PYTHON)
  add_subdirectory(python)
endif()
{%- else %}
option(HOLOHUB_BUILD_CPP "Build the C++ application" ON)

if(HOLOHUB_BUILD_CPP)
  add_subdirectory(cpp)
endif()
{%- endif %}
