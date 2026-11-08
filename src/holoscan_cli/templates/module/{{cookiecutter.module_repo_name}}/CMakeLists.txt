# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}
{%- if cookiecutter.__pure_python == 'yes' %}

cmake_minimum_required(VERSION 3.24)

# This Module is implemented in Python. CMake only stages the package for
# `holoscan build|run|test` and runs the pytest suite through CTest, so it
# enables no compiled languages.
project(holoscan_{{ cookiecutter.module_slug }}
    VERSION {{ cookiecutter.version }}
    DESCRIPTION "{{ cookiecutter.description }}"
    LANGUAGES NONE
)

# Wheel builds (scikit-build-core) take the package and its metadata from pyproject.toml.
if(SKBUILD)
    return()
endif()

# ---------------------------------------------------------------------------
# Build options
# ---------------------------------------------------------------------------
# BUILD_ALL toggles every application on by default. Each application is a
# CMake option (APP_<name>) defined by add_holohub_application, defaulting to
# ${BUILD_ALL}. It is ON when this is the top-level project and OFF when the
# Module is nested in another project.
if(NOT DEFINED BUILD_ALL)
    if(PROJECT_IS_TOP_LEVEL)
        set(BUILD_ALL ON CACHE BOOL "Build all applications by default")
    else()
        set(BUILD_ALL OFF)
    endif()
endif()

# Module tests live behind a module-namespaced flag rather than the standard
# CMake BUILD_TESTING variable, so a parent project keeps its own setting.
# Defaults ON when standalone, OFF when nested.
if(NOT DEFINED {{ cookiecutter.module_slug | upper }}_BUILD_TESTING)
    if(PROJECT_IS_TOP_LEVEL)
        set({{ cookiecutter.module_slug | upper }}_BUILD_TESTING ON
            CACHE BOOL "Build the {{ cookiecutter.module_slug }} module's CTest suite")
    else()
        set({{ cookiecutter.module_slug | upper }}_BUILD_TESTING OFF
            CACHE BOOL "Build the {{ cookiecutter.module_slug }} module's CTest suite")
    endif()
endif()

# Found at the root so python/ and tests/python/ see the same interpreter.
if(Python3_EXECUTABLE AND NOT Python_EXECUTABLE)
    set(Python_EXECUTABLE "${Python3_EXECUTABLE}")
endif()
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter)

# ---------------------------------------------------------------------------
# CMake helpers
# ---------------------------------------------------------------------------
# HoloHubConfigHelpers.cmake provides add_holohub_application, which gates each
# application on its own APP_<name> option. The helpers are bundled in this
# generated repository so it builds without a HoloHub clone.
list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(HoloHubConfigHelpers)

# Every install carries the license and third-party notices.
install(FILES LICENSE NOTICE
    DESTINATION "share/doc/{{ cookiecutter.module_repo_name }}")

# ---------------------------------------------------------------------------
# Subprojects
# ---------------------------------------------------------------------------
add_subdirectory(python)
add_subdirectory(applications)

if({{ cookiecutter.module_slug | upper }}_BUILD_TESTING)
    enable_testing()
    add_subdirectory(tests)
endif()
{%- else %}

cmake_minimum_required(VERSION 4.0)

project(holoscan_{{ cookiecutter.module_slug }}
    VERSION {{ cookiecutter.version }}
    DESCRIPTION "{{ cookiecutter.description }}"
    LANGUAGES CXX
)

# Holoscan SDK 5.0 headers require C++20.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
find_package(holoscan 5.0 REQUIRED CONFIG COMPONENTS core)

# ---------------------------------------------------------------------------
# Build options
# ---------------------------------------------------------------------------
# BUILD_ALL toggles every operator/application/package on by default. It
# matches the HoloHub-monorepo convention: each subproject is a CMake option
# (e.g. APP_<name>, OP_<name>, PKG_<name>) defined via add_holohub_application
# / add_holohub_operator / add_holohub_package, defaulting to ${BUILD_ALL}.
# To build a single subproject, configure with -DBUILD_ALL=OFF -DAPP_<name>=ON.
#
# Default to ON only when this is the top-level CMake project (standalone
# build). When nested under another project (e.g. consumed as a HoloHub
# external dependency via add_subdirectory), defer to whatever the parent
# build has decided — otherwise this module's BUILD_ALL=ON would leak into
# the parent's variable scope and force-enable unrelated subprojects there.

if(NOT DEFINED BUILD_ALL)
    if(PROJECT_IS_TOP_LEVEL)
        set(BUILD_ALL ON CACHE BOOL "Build all operators, applications, and packages by default")
    else()
        set(BUILD_ALL OFF)
    endif()
endif()

# Module tests live behind a module-namespaced flag rather than the standard
# CMake BUILD_TESTING variable. This lets a parent project (HoloHub, another
# module) keep its own BUILD_TESTING setting independent of whether *this*
# module's tests are built. Defaults ON when standalone, OFF when nested.
if(NOT DEFINED {{ cookiecutter.module_slug | upper }}_BUILD_TESTING)
    if(PROJECT_IS_TOP_LEVEL)
        set({{ cookiecutter.module_slug | upper }}_BUILD_TESTING ON
            CACHE BOOL "Build the {{ cookiecutter.module_slug }} module's CTest suite")
    else()
        set({{ cookiecutter.module_slug | upper }}_BUILD_TESTING OFF
            CACHE BOOL "Build the {{ cookiecutter.module_slug }} module's CTest suite")
    endif()
endif()
{%- if cookiecutter.__python_bindings == 'yes' %}

# The Python bindings follow the same rule: ON when standalone, OFF when nested.
# They are also OFF when packaging, because the Debian package ships no Python files.
if(NOT DEFINED HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_PYTHON)
    if(PROJECT_IS_TOP_LEVEL AND NOT PKG_{{ cookiecutter.module_repo_name.replace('-', '_') }})
        set(HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_PYTHON ON
            CACHE BOOL "Build the holoscan_{{ cookiecutter.module_slug }} Python bindings")
    else()
        set(HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_PYTHON OFF
            CACHE BOOL "Build the holoscan_{{ cookiecutter.module_slug }} Python bindings")
    endif()
endif()
if(HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_PYTHON)
    # The operator libraries are linked into the Python extension module.
    set(CMAKE_POSITION_INDEPENDENT_CODE ON)
    # Found at the root so python/ and tests/python/ see the same interpreter.
    if(Python3_EXECUTABLE AND NOT Python_EXECUTABLE)
        set(Python_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    find_package(Python 3.12 REQUIRED
        COMPONENTS Interpreter Development.Module Development.SABIModule)
endif()
{%- endif %}

# Application languages. The Holoscan CLI sets these from --language or the
# application's metadata.json; a plain CMake build includes every language.
option(HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_CPP "Build C++ applications" ON)

# ---------------------------------------------------------------------------
# CMake helpers
# ---------------------------------------------------------------------------
# HoloHubConfigHelpers.cmake provides add_holohub_application/operator/package
# which gate each subproject on its own option (APP_/OP_/PKG_<name>). The
# helpers are bundled directly in this generated repository so it builds
# without a HoloHub clone.
list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(HoloHubConfigHelpers)

add_library(holoscan_{{ cookiecutter.module_slug }} INTERFACE)
add_library(holoscan::{{ cookiecutter.module_slug }} ALIAS holoscan_{{ cookiecutter.module_slug }})
set_target_properties(holoscan_{{ cookiecutter.module_slug }} PROPERTIES
    EXPORT_NAME {{ cookiecutter.module_slug }})
install(TARGETS holoscan_{{ cookiecutter.module_slug }}
    EXPORT holoscan_{{ cookiecutter.module_slug }}_targets)

# Every install and package carries the license and third-party notices.
include(GNUInstallDirs)
install(FILES LICENSE NOTICE
    DESTINATION "${CMAKE_INSTALL_DATAROOTDIR}/doc/{{ cookiecutter.module_repo_name }}")

# ---------------------------------------------------------------------------
# Subprojects
# ---------------------------------------------------------------------------
# pkg/ must come *before* operators/ and applications/: add_holohub_package()
# inside pkg/ uses set(... CACHE BOOL "" FORCE) to flip OP_<x>=ON / APP_<x>=ON
# when its PKG_<name> option is ON, and the operator/application macros that
# read those values run their `option(OP_<x> ... ${BUILD_ALL})` calls when
# their subdirectories are processed — those bind the cache value the FIRST
# time option() is encountered, so the FORCE has to happen before then.

add_subdirectory(pkg)
add_subdirectory(operators)
add_subdirectory(applications)
{%- if cookiecutter.__python_bindings == 'yes' %}

if(HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_PYTHON)
    add_subdirectory(python)
endif()
{%- endif %}

if({{ cookiecutter.module_slug | upper }}_BUILD_TESTING)
    enable_testing()
    add_subdirectory(tests)
endif()

# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------
# Debian packaging lives under pkg/. pkg/CMakeLists.txt calls
# add_holohub_package({{ cookiecutter.module_repo_name }} OPERATORS {{ cookiecutter.operator_slug }}
# APPLICATIONS {{ cookiecutter.module_slug }}_pipeline), which defines the
# PKG_{{ cookiecutter.module_repo_name.replace('-', '_') }} option, FORCEs the OP_/APP_ deps to ON when the
# package is enabled, and enters pkg/{{ cookiecutter.module_repo_name }}/CMakeLists.txt
# for the holohub_configure_deb() call.
{%- endif %}
