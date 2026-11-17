// SPDX-FileCopyrightText: Copyright (c) {{cookiecutter.year}} {{cookiecutter.copyright_holder}}.
// SPDX-License-Identifier: Apache-2.0
//
// {{ cookiecutter.project_name }}: a minimal Holoscan SDK 5 application.
//
// The graph emits a finite sequence of integers, transforms each value, and
// verifies every result at the sink. Replace the operators with your pipeline
// and keep a finite, verifiable mode for CI.

#include <atomic>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <utility>

#include <holoscan/core/compile.hpp>
#include <holoscan/core/connection_options.hpp>
#include <holoscan/core/execution_context.hpp>
#include <holoscan/core/graph.hpp>
#include <holoscan/core/managed_shutdown_signals.hpp>
#include <holoscan/core/operator.hpp>
#include <holoscan/core/operator_spec.hpp>
#include <holoscan/core/run.hpp>
#include <holoscan/core/run_session.hpp>
#include <holoscan/core/temporal_contract.hpp>
#include <holoscan/time/realtime_clock.hpp>

namespace {

using std::chrono_literals::operator""ms;

constexpr std::string_view kAppName = "{{ cookiecutter.project_slug }}";

struct Options {
  std::uint32_t count{100U};
  std::uint32_t period_ms{10U};
  std::uint32_t timeout_seconds{30U};
  bool help{false};
};

// Written by the sink on a runtime thread and read by main() after the run.
struct Progress {
  std::uint32_t expected{};
  std::atomic<std::uint32_t> received{};
  std::atomic<std::uint32_t> mismatches{};
};

std::uint32_t parse_number(std::string_view value, std::string_view option) {
  std::uint32_t result{};
  const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), result);
  if (error != std::errc() || end != value.data() + value.size()) {
    throw std::invalid_argument(std::string(option) + " requires an unsigned 32-bit integer");
  }
  return result;
}

Options parse_args(int argc, char** argv) {
  Options opts;
  for (int i = 1; i < argc; ++i) {
    const std::string_view option{argv[i]};
    if (option == "--help" || option == "-h") {
      opts.help = true;
      return opts;
    }
    if (i + 1 >= argc) {
      throw std::invalid_argument("missing value for " + std::string(option));
    }
    const std::string_view value{argv[++i]};
    if (option == "--count") {
      opts.count = parse_number(value, option);
    } else if (option == "--period-ms") {
      opts.period_ms = parse_number(value, option);
    } else if (option == "--timeout-seconds") {
      opts.timeout_seconds = parse_number(value, option);
    } else {
      throw std::invalid_argument("unknown option: " + std::string(option));
    }
  }
  if (opts.count == 0U || opts.period_ms == 0U || opts.period_ms > 1000U ||
      opts.timeout_seconds == 0U) {
    throw std::invalid_argument(
        "--count and --timeout-seconds must be positive, and --period-ms must be 1..1000");
  }
  return opts;
}

void usage(const char* argv0) {
  std::cout << "Usage: " << argv0
            << " [options]\n"
               "  --count N            Messages to process (default: 100)\n"
               "  --period-ms N        Source period, 1..1000 ms (default: 10)\n"
               "  --timeout-seconds N  Allowance beyond the expected run time (default: 30)\n";
}

// A source has no inputs, so it opts into time: OnClock activates compute()
// once per period of the graph's default clock.
class CounterSourceOp final : public holoscan::Operator<> {
 public:
  CounterSourceOp(std::uint32_t count, std::chrono::nanoseconds period)
      : count_(count), period_(period) {}

  holoscan::Output<std::uint32_t> out;

  void setup(holoscan::OperatorSpec& spec) override { spec.output(out, "out"); }

  [[nodiscard]] holoscan::Contract contract() const override {
    holoscan::Contract result;
    result.trigger(holoscan::OnClock{.period = period_});
    return result;
  }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext&) override {
    if (next_ >= count_) {
      return {};  // Exhausted: stay idle until the sink requests completion.
    }
    return out.emit(++next_);
  }

 private:
  std::uint32_t count_;
  std::chrono::nanoseconds period_;
  std::uint32_t next_{};
};

// Replace this transform with your processing. With one connected input and no
// contract() override, compute() runs once per received message.
class ScaleOp final : public holoscan::Operator<> {
 public:
  holoscan::Input<std::uint32_t> in;
  holoscan::Output<std::uint32_t> out;

  void setup(holoscan::OperatorSpec& spec) override {
    spec.input(in, "in");
    spec.output(out, "out");
  }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext&) override {
    auto value = in.receive_data();
    if (!value) {
      return holoscan::make_unexpected(std::move(value).error());
    }
    return out.emit(*value * 2U);
  }
};

// Checks each result and requests completion after the last expected message.
class VerifySinkOp final : public holoscan::Operator<> {
 public:
  explicit VerifySinkOp(std::shared_ptr<Progress> progress) : progress_(std::move(progress)) {}

  holoscan::Input<std::uint32_t> in;

  void setup(holoscan::OperatorSpec& spec) override { spec.input(in, "in"); }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext& context) override {
    auto value = in.receive_data();
    if (!value) {
      return holoscan::make_unexpected(std::move(value).error());
    }
    const std::uint32_t index = progress_->received.fetch_add(1U) + 1U;
    if (*value != index * 2U) {
      progress_->mismatches.fetch_add(1U);
    }
    if (index == progress_->expected) {
      context.request_completion();
    }
    return {};
  }

 private:
  std::shared_ptr<Progress> progress_;
};

int execute(const Options& opts) {
  // Take ownership of SIGINT/SIGTERM so Ctrl+C stops the run cooperatively.
  auto signals = holoscan::ManagedShutdownSignals::create();
  if (!signals) {
    throw std::runtime_error(signals.error().message);
  }
  auto progress = std::make_shared<Progress>();
  progress->expected = opts.count;

  holoscan::Graph graph{std::string(kAppName)};
  auto source =
      graph.op<CounterSourceOp>("source", opts.count, std::chrono::milliseconds(opts.period_ms));
  auto scale = graph.op<ScaleOp>("scale");
  auto sink = graph.op<VerifySinkOp>("sink", progress);
  // Blocking queues keep every message and apply backpressure to the source.
  const holoscan::ConnectionOptions lossless{.queue_policy = holoscan::QueuePolicy::kBlocking,
                                             .queue_depth = 2U};
  graph.add_flow(source->out, scale->in, lossless);
  graph.add_flow(scale->out, sink->in, lossless);
  graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));

  const auto plan = holoscan::compile(graph);
  if (!plan.ok()) {
    for (const auto& diagnostic : plan.diagnostics()) {
      std::cerr << "compile: " << diagnostic.token << " required=" << diagnostic.required
                << " provided=" << diagnostic.provided << '\n';
    }
    return 1;
  }

  auto session = holoscan::run_async(plan, *signals);
  const auto deadline = std::chrono::steady_clock::now() +
                        std::chrono::seconds(opts.timeout_seconds) +
                        std::chrono::milliseconds(std::uint64_t{opts.count} * opts.period_ms);
  while (session.is_running() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  const bool finished = !session.is_running();
  if (!finished) {
    std::cerr << kAppName << ": timed out\n";
    session.request_stop();
  }
  session.wait();
  for (const auto& diagnostic : session.diagnostics()) {
    std::cerr << "diagnostic: " << diagnostic.token << " required=" << diagnostic.required
              << " provided=" << diagnostic.provided << '\n';
  }

  const std::uint32_t received = progress->received.load();
  const std::uint32_t mismatches = progress->mismatches.load();
  const bool passed = finished && session.diagnostics().empty() &&
                      session.termination() == holoscan::RunTermination::kRequestedCompleted &&
                      received == opts.count && mismatches == 0U;
  std::cout << kAppName << ": expected=" << opts.count << " received=" << received
            << " mismatches=" << mismatches << " verdict=" << (passed ? "PASS" : "FAIL") << '\n';
  return passed ? 0 : 1;
}

}  // namespace

int main(int argc, char** argv) try {
  const auto opts = parse_args(argc, argv);
  if (opts.help) {
    usage(argv[0]);
    return 0;
  }
  return execute(opts);
} catch (const std::invalid_argument& error) {
  std::cerr << "error: " << error.what() << '\n';
  return 2;
} catch (const std::exception& error) {
  std::cerr << "error: " << error.what() << '\n';
  return 1;
}
