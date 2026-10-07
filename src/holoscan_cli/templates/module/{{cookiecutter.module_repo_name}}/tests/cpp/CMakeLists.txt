# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

find_package(GTest 1.14 CONFIG QUIET)
if(NOT GTest_FOUND)
    include(FetchContent)
    FetchContent_Declare(googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG v1.17.0
        GIT_SHALLOW TRUE)
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
endif()

add_executable(test_operators test_operators.cpp)

target_link_libraries(test_operators PRIVATE
    holoscan::{{ cookiecutter.operator_slug }}
    holoscan::core
    GTest::gtest_main)

target_include_directories(test_operators PRIVATE
    ${PROJECT_SOURCE_DIR}/operators)

include(GoogleTest)
gtest_discover_tests(test_operators PROPERTIES LABELS "unit")
