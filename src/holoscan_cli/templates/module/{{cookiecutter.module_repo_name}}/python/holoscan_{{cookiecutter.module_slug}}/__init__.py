# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

"""{{ cookiecutter.project_name }} Python bindings."""

from . import _{{ cookiecutter.module_slug }} as _{{ cookiecutter.module_slug }}
from . import operators as operators

__all__ = ["operators"]
