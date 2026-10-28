# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}
{%- if cookiecutter.__pure_python == 'yes' %}

{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

"""{{ cookiecutter.project_name }} operators."""

from .{{ cookiecutter.operator_slug }} import {{ op_class }}

__all__ = ["{{ op_class }}"]
{%- else %}

"""Registered {{ cookiecutter.project_name }} operator proxies."""

from holoscan.registry import operators as _operators

from .. import _{{ cookiecutter.module_slug }} as _{{ cookiecutter.module_slug }}

_registry_prefix = "holoscan.{{ cookiecutter.module_slug }}."
_operator_types = {
    operator.name.removeprefix(_registry_prefix): operator
    for operator in _operators()
    if operator.name.startswith(_registry_prefix)
}
globals().update(_operator_types)
__all__: list[str] = sorted(_operator_types)
{%- endif %}
