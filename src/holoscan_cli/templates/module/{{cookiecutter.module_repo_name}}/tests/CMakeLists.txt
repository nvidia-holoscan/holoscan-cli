# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

add_subdirectory(cpp)
{%- if cookiecutter.__python_bindings == 'yes' %}
if(HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_PYTHON)
    add_subdirectory(python)
endif()
{%- endif %}
