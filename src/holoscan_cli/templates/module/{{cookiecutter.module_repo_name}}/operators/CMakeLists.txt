# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}
{%- if cookiecutter.__pure_python == 'yes' %}

# Stage operators/__init__.py, which exports every operator staged next to it.
set(_python_build_var {{ cookiecutter.module_slug | upper }}_PYTHON_BUILD_DIR)
configure_file(__init__.py
    "${${_python_build_var}}/holoscan_{{ cookiecutter.module_slug }}/operators/__init__.py" COPYONLY)
{%- endif %}

# Each operator is gated on its own OP_<name> option, defaulting to ${BUILD_ALL}.
# Add one add_holohub_operator() call per operator.
add_holohub_operator({{ cookiecutter.operator_slug }})
