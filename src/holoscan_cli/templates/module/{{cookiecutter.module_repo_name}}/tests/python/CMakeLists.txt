# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

set(_python_build_var {{ cookiecutter.module_slug | upper }}_PYTHON_BUILD_DIR)

add_test(NAME python.{{ cookiecutter.module_slug }}
    COMMAND "${Python_EXECUTABLE}" -m pytest -q "${CMAKE_CURRENT_SOURCE_DIR}")
set_tests_properties(python.{{ cookiecutter.module_slug }} PROPERTIES
    ENVIRONMENT_MODIFICATION
        "PYTHONPATH=path_list_prepend:${${_python_build_var}}"
    LABELS "python;unit")
