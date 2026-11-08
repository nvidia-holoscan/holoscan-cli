// SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
// SPDX-License-Identifier: {{ cookiecutter._license }}
//
// GTest coverage for {{ cookiecutter.operator_slug.split('_')|map('capitalize')|join('') }}.
//
// Two layers, following the Holoscan SDK 5.0 testing guide:
//   1. compile-plan tests: compose a graph, compile it, assert the plan is
//      accepted (or rejected with the diagnostics you expect). No runtime.
//   2. whole-graph tests under a SyntheticClock: bind → default → compile →
//      run_async → advance → stop → assert. Deterministic, no hardware.
// TODO: extend the test doubles and assertions for your operator's behaviour.
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

#include <gtest/gtest.h>

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <utility>
#include <vector>

#include <holoscan/core/compile.hpp>
#include <holoscan/core/connection_options.hpp>
#include <holoscan/core/execution_context.hpp>
#include <holoscan/core/execution_plan.hpp>
#include <holoscan/core/graph.hpp>
#include <holoscan/core/operator.hpp>
#include <holoscan/core/operator_spec.hpp>
#include <holoscan/core/run.hpp>
#include <holoscan/core/run_session.hpp>
#include <holoscan/core/temporal_contract.hpp>
#include <holoscan/time/synthetic_clock.hpp>

#include <{{ cookiecutter.operator_slug }}/{{ cookiecutter.operator_slug }}.hpp>

namespace mm = holoscan::{{ cookiecutter.module_slug }};

namespace {

constexpr std::chrono::nanoseconds kTickPeriod = std::chrono::milliseconds{10};

// Test double for an upstream sensor: emits 1, 2, 3, ... once per clock period.
class CounterSourceTestOp final : public holoscan::Operator<> {
 public:
  holoscan::Output<std::uint32_t> out;

  void setup(holoscan::OperatorSpec& spec) override { spec.output(out, "out"); }

  [[nodiscard]] holoscan::Contract contract() const override {
    holoscan::Contract result;
    result.trigger(holoscan::OnClock{.period = kTickPeriod});
    return result;
  }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext&) override {
    return out.emit(++next_);
  }

 private:
  std::uint32_t next_{};
};

// Test double for a downstream consumer: records everything it receives.
// Operators run on runtime threads, so the recording is guarded and the test
// waits on a condition variable after each clock advance.
class RecordingSinkTestOp final : public holoscan::Operator<> {
 public:
  holoscan::Input<std::uint32_t> in;

  void setup(holoscan::OperatorSpec& spec) override { spec.input(in, "in"); }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext&) override {
    auto value = in.receive_data();
    if (!value) {
      return holoscan::make_unexpected(std::move(value).error());
    }
    {
      const std::lock_guard lock(mutex);
      received.push_back(*value);
    }
    ready.notify_all();
    return {};
  }

  [[nodiscard]] static bool wait_for(std::size_t expected) {
    std::unique_lock lock(mutex);
    return ready.wait_for(lock, std::chrono::seconds{10},
                          [expected] { return received.size() >= expected; });
  }

  static std::vector<std::uint32_t> snapshot() {
    const std::lock_guard lock(mutex);
    return received;
  }

  static void reset() {
    const std::lock_guard lock(mutex);
    received.clear();
  }

 private:
  static inline std::mutex mutex;
  static inline std::condition_variable ready;
  static inline std::vector<std::uint32_t> received;
};

}  // namespace

TEST({{ op_class }}Test, GraphCompiles) {
  holoscan::Graph graph{"{{ cookiecutter.operator_slug }}-compiles"};
  const auto source = graph.op<CounterSourceTestOp>("source");
  const auto op = graph.op<mm::{{ op_class }}>("{{ cookiecutter.operator_slug }}");
  const auto sink = graph.op<RecordingSinkTestOp>("sink");
  graph.add_flow(source->out, op->in);
  graph.add_flow(op->out, sink->in);
  graph.set_default_clock(
      graph.bind_shared_clock("clock", std::make_shared<holoscan::SyntheticClock>(0)));

  const holoscan::ExecutionPlan plan = holoscan::compile(graph);
  EXPECT_TRUE(plan.ok()) << plan.json();
}

TEST({{ op_class }}Test, ForwardsSamplesUnderSyntheticClock) {
  RecordingSinkTestOp::reset();
  // Keep the shared_ptr: it is the handle the test uses to drive time.
  auto test_clock = std::make_shared<holoscan::SyntheticClock>(0);

  holoscan::Graph graph{"{{ cookiecutter.operator_slug }}-under-test"};
  const auto source = graph.op<CounterSourceTestOp>("source");
  const auto op = graph.op<mm::{{ op_class }}>("{{ cookiecutter.operator_slug }}");
  const auto sink = graph.op<RecordingSinkTestOp>("sink");
  graph.add_flow(source->out, op->in, holoscan::ConnectionOptions{.queue_depth = 8U});
  graph.add_flow(op->out, sink->in, holoscan::ConnectionOptions{.queue_depth = 8U});
  graph.set_default_clock(graph.bind_shared_clock("test", test_clock));

  const holoscan::ExecutionPlan plan = holoscan::compile(graph);
  ASSERT_TRUE(plan.ok()) << plan.json();

  constexpr std::size_t kTicks = 5U;
  holoscan::RunSession session = holoscan::run_async(plan);
  // Advancing time releases work but is not a barrier: step one period at a
  // time and wait for the sink to observe each sample before the next step.
  bool complete = true;
  for (std::size_t tick = 1; tick <= kTicks && complete; ++tick) {
    test_clock->advance_by(kTickPeriod);
    complete = RecordingSinkTestOp::wait_for(tick);
  }
  session.request_stop();
  session.wait();

  EXPECT_TRUE(complete);
  EXPECT_EQ(session.termination(), holoscan::RunTermination::kStopped);
  EXPECT_TRUE(session.diagnostics().empty());

  // TODO: assert on your operator's transformation instead of pass-through.
  const auto received = RecordingSinkTestOp::snapshot();
  ASSERT_GE(received.size(), kTicks);
  for (std::size_t i = 0; i < kTicks; ++i) {
    EXPECT_EQ(received[i], static_cast<std::uint32_t>(i + 1U));
  }
}
