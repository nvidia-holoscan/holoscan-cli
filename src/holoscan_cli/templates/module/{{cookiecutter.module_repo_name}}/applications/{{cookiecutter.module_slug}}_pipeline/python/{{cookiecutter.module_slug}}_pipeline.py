# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}
{%- if cookiecutter.__pure_python == 'yes' %}

{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

"""Run the {{ op_class }} operator: source -> {{ op_class }} -> sink."""

import threading
import time

from holoscan_{{ cookiecutter.module_slug }}.operators import {{ op_class }}

import holoscan as hs

TICK_LIMIT = 10


class PipelineObservation:
    """Record sink progress so the application thread can wait for it."""

    condition = threading.Condition()
    count = 0

    @classmethod
    def record(cls) -> None:
        with cls.condition:
            cls.count += 1
            cls.condition.notify_all()

    @classmethod
    def wait_for(cls, expected: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with cls.condition:
            while cls.count < expected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                cls.condition.wait(remaining)
        return True


class CounterSource(hs.Operator):
    """Emit 1..TICK_LIMIT on a 10 ms clock."""

    output = hs.Output("output", hs.payload.uint32)

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.output(self.output)

    def contract(self) -> hs.Contract:
        return hs.Contract().trigger(hs.OnClock(period=hs.time.ms(10)))

    def compute(self, context: hs.ExecutionContext) -> None:
        value = getattr(self, "next_value", 1)
        if value <= TICK_LIMIT:
            self.output.emit(value)
            self.next_value = value + 1


class CountingSink(hs.Operator):
    """Count each received sample."""

    input = hs.Input("input", hs.payload.uint32)

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.input(self.input, queue_depth=8)

    def contract(self) -> hs.Contract:
        return hs.Contract().trigger(hs.OnEach(self.input))

    def compute(self, context: hs.ExecutionContext) -> None:
        self.input.receive_data()
        PipelineObservation.record()


def build_graph() -> hs.Graph:
    graph = hs.Graph("{{ cookiecutter.module_slug }}_pipeline", default_clock=hs.RealtimeClock)
    source = graph.op(CounterSource, "source")
    forward = graph.op({{ op_class }}, "{{ cookiecutter.operator_slug }}")
    sink = graph.op(CountingSink, "sink")
    graph.add_flow(source.output, forward["in"])
    graph.add_flow(forward.out, sink.input)
    return graph


def main() -> None:
    plan = hs.compile(build_graph())
    plan.require_no_errors()
    with hs.run_async(plan) as session:
        observed = PipelineObservation.wait_for(TICK_LIMIT, 10.0)
        session.request_stop()
        stopped = session.wait(timeout=5.0)
    if not observed:
        raise TimeoutError(f"sink did not receive {TICK_LIMIT} samples: {session.diagnostics!r}")
    if not stopped:
        raise TimeoutError("pipeline did not stop within five seconds")
    print(f"{{ cookiecutter.module_slug }}_pipeline received {TICK_LIMIT} samples")


if __name__ == "__main__":
    main()
{%- else %}
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

"""Run the {{ op_class }} C++ operator from Python: source -> {{ op_class }} -> sink."""

import threading
import time

from holoscan_{{ cookiecutter.module_slug }}.operators import {{ op_class }}

import holoscan as hs

TICK_LIMIT = 10


class PipelineObservation:
    """Record sink progress so the application thread can wait for it."""

    condition = threading.Condition()
    count = 0

    @classmethod
    def record(cls) -> None:
        with cls.condition:
            cls.count += 1
            cls.condition.notify_all()

    @classmethod
    def wait_for(cls, expected: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with cls.condition:
            while cls.count < expected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                cls.condition.wait(remaining)
        return True


class CounterSource(hs.Operator):
    """Emit 1..TICK_LIMIT on a 10 ms clock."""

    output = hs.Output("output", hs.payload.uint32)

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.output(self.output)

    def contract(self) -> hs.Contract:
        return hs.Contract().trigger(hs.OnClock(period=hs.time.ms(10)))

    def compute(self, context: hs.ExecutionContext) -> None:
        value = getattr(self, "next_value", 1)
        if value <= TICK_LIMIT:
            self.output.emit(value)
            self.next_value = value + 1


class CountingSink(hs.Operator):
    """Count each received sample."""

    input = hs.Input("input", hs.payload.uint32)

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.input(self.input, queue_depth=8)

    def contract(self) -> hs.Contract:
        return hs.Contract().trigger(hs.OnEach(self.input))

    def compute(self, context: hs.ExecutionContext) -> None:
        self.input.receive_data()
        PipelineObservation.record()


def build_graph() -> hs.Graph:
    graph = hs.Graph("{{ cookiecutter.module_slug }}_pipeline", default_clock=hs.RealtimeClock)
    source = graph.op(CounterSource, "source")
    forward = {{ op_class }}(graph, "{{ cookiecutter.operator_slug }}")
    sink = graph.op(CountingSink, "sink")
    graph.add_flow(source.output, forward["in"])
    graph.add_flow(forward.out, sink.input)
    return graph


def main() -> None:
    plan = hs.compile(build_graph())
    plan.require_no_errors()
    with hs.run_async(plan) as session:
        observed = PipelineObservation.wait_for(TICK_LIMIT, 10.0)
        session.request_stop()
        stopped = session.wait(timeout=5.0)
    if not observed:
        raise TimeoutError(f"sink did not receive {TICK_LIMIT} samples: {session.diagnostics!r}")
    if not stopped:
        raise TimeoutError("pipeline did not stop within five seconds")
    print(f"{{ cookiecutter.module_slug }}_pipeline received {TICK_LIMIT} samples")


if __name__ == "__main__":
    main()
{%- endif %}
