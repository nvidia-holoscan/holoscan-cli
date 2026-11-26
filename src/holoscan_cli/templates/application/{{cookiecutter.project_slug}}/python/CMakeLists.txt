# SPDX-FileCopyrightText: Copyright (c) {{cookiecutter.year}} {{cookiecutter.copyright_holder}}.
# SPDX-License-Identifier: Apache-2.0

# The application runs from source, so there is nothing to build.
if(BUILD_TESTING)
  # Keep tests in the Python scope and preserve their build directory.
  add_subdirectory(../tests "${CMAKE_CURRENT_BINARY_DIR}/../tests")
endif()
