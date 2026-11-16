// SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
// SPDX-License-Identifier: {{ cookiecutter._license }}
//
// C++ pipeline example for {{ cookiecutter.project_name }}.
// TODO: replace the source/sink stubs with your actual pipeline topology.
//
// Holoscan SDK 5.0 applications follow three phases:
//   1. compose a holoscan::Graph,
//   2. compile it into a holoscan::ExecutionPlan (structural errors surface here),
//   3. run the plan.
//
// Build: cmake -S . -B build -DBUILD_ALL=ON && cmake --build build
// Run:   ./build/applications/{{ cookiecutter.module_slug }}_pipeline/cpp/{{ cookiecutter.module_slug }}_pipeline
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <utility>

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
#include <holoscan/time/realtime_clock.hpp>

#include <{{ cookiecutter.operator_slug }}/{{ cookiecutter.operator_slug }}.hpp>

namespace mm = holoscan::{{ cookiecutter.module_slug }};

namespace {

constexpr std::chrono::nanoseconds kTickPeriod = std::chrono::milliseconds{10};
constexpr std::uint32_t kTickLimit = 10U;

// Operators run on runtime threads; main() waits on this instead of polling.
struct PipelineObservation {
  static void record() {
    {
      const std::lock_guard lock(mutex);
      count.fetch_add(1U, std::memory_order_release);
    }
    ready.notify_all();
  }

  [[nodiscard]] static bool wait_for(std::uint32_t expected) {
    std::unique_lock lock(mutex);
    return ready.wait_for(
        lock, std::chrono::seconds{10},
        [expected] { return count.load(std::memory_order_acquire) >= expected; });
  }

  static inline std::mutex mutex;
  static inline std::condition_variable ready;
  static inline std::atomic<std::uint32_t> count{};
};

// A source has no inputs, so it opts into time: OnClock activates compute()
// on every period of the graph's default clock.
class CounterSourceOp final : public holoscan::Operator<> {
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
    if (next_ >= kTickLimit) {
      return {};  // exhausted: keep ticking idly until main() stops the run
    }
    return out.emit(++next_);
  }

 private:
  std::uint32_t next_{};
};

class PrintSinkOp final : public holoscan::Operator<> {
 public:
  holoscan::Input<std::uint32_t> in;

  void setup(holoscan::OperatorSpec& spec) override { spec.input(in, "in"); }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext&) override {
    auto value = in.receive_data();
    if (!value) {
      return holoscan::make_unexpected(std::move(value).error());
    }
    std::cout << "{{ cookiecutter.operator_slug }} -> " << *value << '\n';
    PipelineObservation::record();
    return {};
  }
};

}  // namespace

int main(int, char**) {
  // Phase 1: compose.
  holoscan::Graph graph{"{{ cookiecutter.module_slug }}_pipeline"};
  const auto source = graph.op<CounterSourceOp>("source");
  const auto op = graph.op<mm::{{ op_class }}>("{{ cookiecutter.operator_slug }}");
  const auto sink = graph.op<PrintSinkOp>("sink");
  graph.add_flow(source->out, op->in, holoscan::ConnectionOptions{.queue_depth = 4U});
  graph.add_flow(op->out, sink->in, holoscan::ConnectionOptions{.queue_depth = 4U});
  graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));

  // Phase 2: compile. The plan is either accepted or rejected with diagnostics.
  const holoscan::ExecutionPlan plan = holoscan::compile(graph);
  if (!plan.ok()) {
    std::cerr << plan.json() << '\n';
    return 1;
  }

  // Phase 3: run. main() owns termination: observe, then cooperatively stop.
  holoscan::RunSession session = holoscan::run_async(plan);
  const bool complete = PipelineObservation::wait_for(kTickLimit);
  session.request_stop();
  session.wait();

  if (!complete) {
    std::cerr << "{{ cookiecutter.module_slug }}_pipeline: timed out waiting for " << kTickLimit
              << " samples\n";
    return 2;
  }
  if (session.termination() != holoscan::RunTermination::kStopped ||
      !session.diagnostics().empty()) {
    std::cerr << "{{ cookiecutter.module_slug }}_pipeline: unexpected termination state\n";
    return 2;
  }
  return 0;
}
