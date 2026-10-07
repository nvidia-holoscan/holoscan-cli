# {{ cookiecutter.project_name }}

{{ cookiecutter.description }}

A **Holoscan Module** — a self-contained, redistributable library that extends
[Holoscan SDK](https://developer.nvidia.com/holoscan-sdk) 5.0 with reusable operators under the
`holoscan::{{ cookiecutter.module_slug }}` namespace.
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}
{%- set mod_kebab = cookiecutter.module_slug.replace('_', '-') %}

> Holoscan SDK 5.0 is C++-first. This Module ships C++ operators only; Python bindings and wheel
> packaging return in a later release.

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
holoscan run {{ cookiecutter.module_slug }}_pipeline
```

If you use [uv](https://docs.astral.sh/uv/), no separate environment setup or activation is
needed. Prefix the same commands with `uv run`, for example:

```bash
uv run holoscan run {{ cookiecutter.module_slug }}_pipeline
```

The project configuration installs the development tools without building the Module on the host.

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

{{ cookiecutter._license }} — see [LICENSE](LICENSE).
