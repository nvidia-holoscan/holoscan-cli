// SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
// SPDX-License-Identifier: {{ cookiecutter._license }}
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

// Python extension that registers this Module's C++ operators with the Holoscan SDK operator
// registry. Importing holoscan_{{ cookiecutter.module_slug }} loads it; Python then reaches each
// operator through a typed registry proxy, so no per-operator bindings are needed.

#include <nanobind/nanobind.h>

#include <holoscan/authoring/register_operator.hpp>
#include <holoscan/core/errors.hpp>

#include <{{ cookiecutter.operator_slug }}/{{ cookiecutter.operator_slug }}.hpp>

// Register each operator once under a stable "holoscan.{{ cookiecutter.module_slug }}." name.
HOLOSCAN_REGISTER_OPERATOR(holoscan::{{ cookiecutter.module_slug }}::{{ op_class }},
                           "holoscan.{{ cookiecutter.module_slug }}.{{ op_class }}");

NB_MODULE(_{{ cookiecutter.module_slug }}, module) {
  auto registered = holoscan::authoring::authoring_registry().registration_status();
  if (!registered) {
    throw holoscan::RuntimeError{registered.error()};
  }
  module.doc() = "{{ cookiecutter.project_name }} operator-registry initializer.";
}
