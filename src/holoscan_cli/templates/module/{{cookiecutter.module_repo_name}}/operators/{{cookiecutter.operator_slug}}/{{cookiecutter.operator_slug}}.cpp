// SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
// SPDX-License-Identifier: {{ cookiecutter._license }}
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

#include "{{ cookiecutter.operator_slug }}/{{ cookiecutter.operator_slug }}.hpp"

#include <holoscan/core/expected_macros.hpp>

namespace holoscan::{{ cookiecutter.module_slug }} {

void {{ op_class }}::setup(holoscan::OperatorSpec& spec) {
  // TODO: bind your ports. Port names are the strings used by
  // holoscan::Graph::add_flow diagnostics and by tooling.
  spec.input(in, "in");
  spec.output(out, "out");
}

holoscan::expected<void, holoscan::Error> {{ op_class }}::compute(
    holoscan::ExecutionContext& /*context*/) {
  // TODO: implement your compute logic. HOLOSCAN_TRY propagates receive errors;
  // emit() returns an expected so failures reach the runtime instead of throwing.
  HOLOSCAN_TRY(auto value, in.receive_data());
  return out.emit(value);
}

}  // namespace holoscan::{{ cookiecutter.module_slug }}
