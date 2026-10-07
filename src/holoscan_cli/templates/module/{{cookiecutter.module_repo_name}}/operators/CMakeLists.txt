# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

# Each operator is gated on its own OP_<name> option, defaulting to ${BUILD_ALL}.
# Add one add_holohub_operator() call per operator.
add_holohub_operator({{ cookiecutter.operator_slug }})
