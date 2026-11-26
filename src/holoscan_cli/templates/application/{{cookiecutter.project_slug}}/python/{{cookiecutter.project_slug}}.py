# SPDX-FileCopyrightText: Copyright (c) {{cookiecutter.year}} {{cookiecutter.copyright_holder}}.
# SPDX-License-Identifier: Apache-2.0
#
# {{ cookiecutter.project_name }}: a minimal Holoscan SDK 5 application.
#
# The graph emits a finite sequence of integers, transforms each value, and
# verifies every result at the sink. Replace the operators with your pipeline
# and keep a finite, verifiable mode for CI.

"""Run a finite pipeline and verify every result."""

import argparse
import signal
import sys
import threading
import time

import holoscan as hs

APP_NAME = "{{ cookiecutter.project_slug }}"


class Results:
    """Counts written by the sink on a runtime thread and read by main() after the run."""

    received = 0
    mismatches = 0


class CounterSource(hs.Operator):
    """Emit 1..count, one value per clock period."""

    out = hs.Output("out", hs.payload.uint32)
    count = hs.Param(100, description="Values to emit")
    period_ms = hs.Param(10, description="Clock period in milliseconds")

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.output(self.out)

    def contract(self) -> hs.Contract:
        # A source has no inputs, so it opts into time: OnClock activates
        # compute() once per period of the graph's default clock.
        return hs.Contract().trigger(hs.OnClock(period=hs.time.ms(self.period_ms)))

    def start(self) -> None:
        self.next_value = 1

    def compute(self, context: hs.ExecutionContext) -> None:
        if self.next_value > self.count:
            return  # Exhausted: stay idle until the sink requests completion.
        self.out.emit(self.next_value)
        self.next_value += 1


class ScaleOp(hs.Operator):
    """Double each value. Replace this transform with your processing."""

    inp = hs.Input("in", hs.payload.uint32)
    out = hs.Output("out", hs.payload.uint32)

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.input(self.inp)
        spec.output(self.out)

    def compute(self, context: hs.ExecutionContext) -> None:
        # With one connected input and no contract() override, compute() runs
        # once per received message.
        self.out.emit(self.inp.receive_data() * 2)


class VerifySink(hs.Operator):
    """Check each result and request completion after the last expected message."""

    inp = hs.Input("in", hs.payload.uint32)
    expected = hs.Param(100, description="Values to receive before completing")

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.input(self.inp)

    def compute(self, context: hs.ExecutionContext) -> None:
        value = self.inp.receive_data()
        Results.received += 1
        if value != Results.received * 2:
            Results.mismatches += 1
        if Results.received == self.expected:
            context.request_completion()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{APP_NAME}: a minimal Holoscan application")
    parser.add_argument("--count", type=int, default=100, help="messages to process (default: 100)")
    parser.add_argument(
        "--period-ms", type=int, default=10, help="source period, 1..1000 ms (default: 10)"
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="allowance beyond the expected run time (default: 30)",
    )
    args = parser.parse_args()
    if args.count < 1 or args.timeout_seconds < 1 or not 1 <= args.period_ms <= 1000:
        parser.error(
            "--count and --timeout-seconds must be positive, and --period-ms must be 1..1000"
        )
    return args


def build_graph(args: argparse.Namespace) -> hs.Graph:
    graph = hs.Graph(APP_NAME, default_clock=hs.RealtimeClock)
    source = graph.op(CounterSource, "source", count=args.count, period_ms=args.period_ms)
    scale = graph.op(ScaleOp, "scale")
    sink = graph.op(VerifySink, "sink", expected=args.count)
    # Blocking queues keep every message and apply backpressure to the source.
    lossless = {"queue_policy": hs.QueuePolicy.BLOCKING, "queue_depth": 2}
    graph.add_flow(source.out, scale["in"], **lossless)
    graph.add_flow(scale.out, sink["in"], **lossless)
    return graph


def execute(args: argparse.Namespace) -> int:
    plan = hs.compile(build_graph(args))
    if not plan.ok:
        print(plan.summary(), file=sys.stderr)
        return 1

    # Python runs leave process signals to the application: stop the run
    # cooperatively on Ctrl+C or SIGTERM.
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())

    deadline = time.monotonic() + args.timeout_seconds + args.count * args.period_ms / 1000
    with hs.run_async(plan) as session:
        finished = session.wait(timeout=0.01)
        while not finished and not stop.is_set() and time.monotonic() < deadline:
            finished = session.wait(timeout=0.01)
        if not finished:
            if not stop.is_set():
                print(f"{APP_NAME}: timed out", file=sys.stderr)
            session.request_stop()
            session.wait()
    if session.diagnostics:
        print(session.summary(), file=sys.stderr)

    passed = (
        finished
        and not session.diagnostics
        and session.termination is hs.RunTermination.REQUESTED_COMPLETED
        and Results.received == args.count
        and Results.mismatches == 0
    )
    print(
        f"{APP_NAME}: expected={args.count} received={Results.received} "
        f"mismatches={Results.mismatches} verdict={'PASS' if passed else 'FAIL'}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(execute(parse_args()))
