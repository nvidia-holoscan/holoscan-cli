{% if cookiecutter.__pure_python == 'yes' -%}
# {{ cookiecutter.project_name }}

{{ cookiecutter.description }}

A **Holoscan Module** — a self-contained, redistributable package that extends
[Holoscan SDK](https://developer.nvidia.com/holoscan-sdk) 5 with reusable operators implemented
in Python, in the `holoscan_{{ cookiecutter.module_slug }}` package (also importable as `holoscan.{{ cookiecutter.module_slug }}`).
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

> This Module needs no C++ code or compiler. It ships as a pure-Python wheel; build it with
> `holoscan package {{ cookiecutter.module_repo_name }} --pkg-generator WHEEL`.

---

## Quick Start

Create and activate a standard Python virtual environment, then install the exact CLI version
pinned by this Module:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install \
  --extra-index-url https://pypi.nvidia.com \
  -r requirements-cli.txt

# Run the example application inside the development container
holoscan run {{ cookiecutter.module_slug }}_pipeline
```

If you use [uv](https://docs.astral.sh/uv/), no separate environment setup or activation is
needed. Prefix the same commands with `uv run --only-group dev`, for example:

```bash
uv run --only-group dev holoscan run {{ cookiecutter.module_slug }}_pipeline
```

`--only-group dev` installs only the development tools, not this Module or its `holoscan-cu13`
dependency.

---

## Operators

| Operator | Implementation | Ports | Parameters |
| --- | --- | --- | --- |
| `{{ op_class }}` | Python | `in` → `out` (TODO) | TODO |

### Namespace

- Python: `holoscan_{{ cookiecutter.module_slug }}`, also importable as `holoscan.{{ cookiecutter.module_slug }}`

---

## Usage

Holoscan SDK 5 applications follow three phases: **compose** a `holoscan.Graph`, **compile** it
into an execution plan, then **run** the plan. Structural mistakes (unknown ports, type
mismatches, missing clocks) are reported as diagnostics at compile time, before anything runs.

```python
import holoscan as hs
from holoscan_{{ cookiecutter.module_slug }}.operators import {{ op_class }}

graph = hs.Graph("my-pipeline", default_clock=hs.RealtimeClock)
op = graph.op({{ op_class }}, "{{ cookiecutter.operator_slug }}")
# TODO: add your source/sink operators and connect typed ports:
# graph.add_flow(source.output, op["in"])
# graph.add_flow(op.out, sink.input)

plan = hs.compile(graph)
plan.require_no_errors()
hs.run(plan)
```

See `applications/{{ cookiecutter.module_slug }}_pipeline/python/` for a complete example that owns
its own termination with `holoscan.run_async`.

---

## Installing without the Holoscan CLI

| Requirement | Version |
| --- | --- |
| Python | 3.12+ on Linux |
| Holoscan SDK | ≥ {{ cookiecutter.holoscan_version }} (the `holoscan-cu13` wheels, installed as a dependency) |
| CUDA | A driver that supports CUDA 13 |

The Holoscan SDK wheels need glibc 2.39 or newer, for example Ubuntu 24.04. Install the Module
with pip, then run its tests:

```bash
python -m pip install -e . pytest
python -m pytest tests/python
```

Building the wheel needs CMake 3.24 or newer, which pip downloads when it is missing, but no
compiler.

---

## Testing

```bash
holoscan test
```

`holoscan test` runs the pytest suite through CTest. The suite tests `{{ op_class }}` on finite
input with `holoscan.testing.OperatorTestHarness` and runs the example application. Extend the
inputs and assertions as your operator grows.

---

## License

{{ cookiecutter._license }} — see [LICENSE](LICENSE). Third-party software is listed in [NOTICE](NOTICE).
{%- else -%}
# {{ cookiecutter.project_name }}

{{ cookiecutter.description }}

A **Holoscan Module** — a self-contained, redistributable library that extends
[Holoscan SDK](https://developer.nvidia.com/holoscan-sdk) 5.0 with reusable operators under the
`holoscan::{{ cookiecutter.module_slug }}` namespace.
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}
{%- set mod_kebab = cookiecutter.module_slug.replace('_', '-') %}

{% if cookiecutter.__python_bindings == 'yes' -%}
> Holoscan SDK 5.0 is C++-first. This Module ships C++ operators plus Python bindings that expose
> them through the SDK operator registry (`import holoscan_{{ cookiecutter.module_slug }}`). Build the bindings into a wheel
> with `holoscan package {{ cookiecutter.module_repo_name }} --pkg-generator WHEEL`.
{%- else -%}
> Holoscan SDK 5.0 is C++-first. This Module ships C++ operators only; Python bindings and wheel
> packaging return in a later release.
{%- endif %}

---

## Quick Start

Create and activate a standard Python virtual environment, then install the exact CLI version
pinned by this Module:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install \
  --extra-index-url https://pypi.nvidia.com \
  -r requirements-cli.txt

# Build and run the C++ demo application inside the development container
holoscan run {{ cookiecutter.module_slug }}_pipeline{% if cookiecutter.__python_bindings == 'yes' %} --language cpp{% endif %}
{%- if cookiecutter.__python_bindings == 'yes' %}

# Or run the Python example, which calls the C++ operator through the bindings
holoscan run {{ cookiecutter.module_slug }}_pipeline --language python
{%- endif %}
```

If you use [uv](https://docs.astral.sh/uv/), no separate environment setup or activation is
needed. Prefix the same commands with `uv run{% if cookiecutter.__python_bindings == 'yes' %} --only-group dev{% endif %}`, for example:

```bash
uv run{% if cookiecutter.__python_bindings == 'yes' %} --only-group dev{% endif %} holoscan run {{ cookiecutter.module_slug }}_pipeline{% if cookiecutter.__python_bindings == 'yes' %} --language cpp{% endif %}
```

The project configuration installs the development tools without building the Module on the host.{% if cookiecutter.__python_bindings == 'yes' %}
`--only-group dev` also skips the wheel's `holoscan-core-cu13` runtime dependency.{% endif %}

---

## Operators

| Operator | Implementation | Ports | Parameters |
| --- | --- | --- | --- |
| `{{ op_class }}` | C++ | `in` → `out` (TODO) | TODO |

### Namespace

- C++: `holoscan::{{ cookiecutter.module_slug }}`

---

## Usage

Holoscan SDK 5.0 applications follow three phases: **compose** a `holoscan::Graph`, **compile**
it into an `ExecutionPlan`, then **run** the plan. Structural mistakes (unknown ports, type
mismatches, missing clocks) are reported as diagnostics at compile time, before anything runs.

```cpp
#include <iostream>

#include <holoscan/core/compile.hpp>
#include <holoscan/core/graph.hpp>
#include <holoscan/core/run.hpp>
#include <holoscan/time/realtime_clock.hpp>

#include <{{ cookiecutter.operator_slug }}/{{ cookiecutter.operator_slug }}.hpp>

int main() {
  holoscan::Graph graph{"my-pipeline"};
  const auto op = graph.op<holoscan::{{ cookiecutter.module_slug }}::{{ op_class }}>("{{ cookiecutter.operator_slug }}");
  // TODO: add your source/sink operators and connect typed ports:
  // graph.add_flow(source->out, op->in);
  // graph.add_flow(op->out, sink->in);
  graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));

  const holoscan::ExecutionPlan plan = holoscan::compile(graph);
  if (!plan.ok()) {
    std::cerr << plan.json() << '\n';
    return 1;
  }
  return holoscan::run(plan);
}
```

See `applications/{{ cookiecutter.module_slug }}_pipeline/cpp/` for a complete example that owns
its own termination with `holoscan::run_async`.

---

## Building from Source (without Holoscan CLI)

| Requirement | Version |
| --- | --- |
| Holoscan SDK | ≥ {{ cookiecutter.holoscan_version }} (`apt install holoscan`, the `holoscan-cuda-13` alias) |
| CUDA Toolkit | 13.x (matches the Holoscan SDK CUDA pin; the dev `Dockerfile` uses `cuda13`) |
| CMake | ≥ 4.0 |
| C++ compiler | C++20-capable |
| GoogleTest | any recent release (tests only) |
{%- if cookiecutter.__python_bindings == 'yes' %}
| Python | 3.12+ with development headers (Python bindings) |
| Holoscan SDK Python package | importable as `holoscan` (Python bindings and tests) |
| nanobind | 3.0.1 (CMake fetches it from GitHub when it is not installed) |
| pytest | any recent release (Python tests only) |
{%- endif %}

```bash
cmake -S . -B build -DBUILD_ALL=ON -D{{ cookiecutter.module_slug | upper }}_BUILD_TESTING=ON
cmake --build build -j$(nproc)
```

The module's `{{ cookiecutter.module_slug | upper }}_BUILD_TESTING` option defaults to `ON` in a
standalone build. For a build without tests, set `-D{{ cookiecutter.module_slug | upper }}_BUILD_TESTING:BOOL=OFF`
when configuring. The standard `-DBUILD_TESTING=OFF` does not control this module's tests.
Without an installed GoogleTest, CMake downloads it while configuring the tests.

---

## Testing

```bash
holoscan test
```

Or, without the Holoscan CLI:

```bash
ctest --test-dir build --output-on-failure -L unit
```

The generated GTest suite (`tests/cpp/test_operators.cpp`) covers two layers recommended by the
Holoscan SDK 5.0 testing guide: a compile-plan test that asserts the graph is accepted, and a
whole-graph test driven by a `holoscan::SyntheticClock` so it runs deterministically without
hardware. Extend the test doubles and assertions as your operator grows.

---

## License

{{ cookiecutter._license }} — see [LICENSE](LICENSE). Third-party software is listed in [NOTICE](NOTICE).
{%- endif %}
