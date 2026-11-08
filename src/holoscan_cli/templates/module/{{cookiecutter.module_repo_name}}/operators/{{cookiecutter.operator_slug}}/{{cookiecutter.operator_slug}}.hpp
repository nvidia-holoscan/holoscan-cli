// SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
// SPDX-License-Identifier: {{ cookiecutter._license }}
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

#pragma once

#include <cstdint>

#include <holoscan/core/errors.hpp>
#include <holoscan/core/execution_context.hpp>
#include <holoscan/core/expected.hpp>
#include <holoscan/core/operator.hpp>
#include <holoscan/core/operator_spec.hpp>
#include <holoscan/core/port.hpp>

namespace holoscan::{{ cookiecutter.module_slug }} {

// TODO: rename {{ op_class }} and update the port declarations.
//
// Holoscan SDK 5.0 operators declare typed ports as members and bind them in
// setup(). With one connected input and no contract() override, compilation
// applies the OnAnyInput{} default: compute() runs once per accepted sample.
class {{ op_class }} final : public holoscan::Operator<> {
 public:
  // TODO: replace std::uint32_t with your payload type (e.g. holoscan::Tensor).
  holoscan::Input<std::uint32_t> in;
  holoscan::Output<std::uint32_t> out;

  void setup(holoscan::OperatorSpec& spec) override;

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext& context) override;
};

}  // namespace holoscan::{{ cookiecutter.module_slug }}
