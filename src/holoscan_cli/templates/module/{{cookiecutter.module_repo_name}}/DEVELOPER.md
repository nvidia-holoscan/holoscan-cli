# Developer Guide — {{ cookiecutter.project_name }}

{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

This guide covers the layout, build system, and day-to-day workflow for developing and
distributing this Holoscan Module.

---

## Module layout

```text
{{ cookiecutter.module_repo_name }}/
├── requirements-cli.txt            # Tested holoscan-cli development version
├── Dockerfile                      # Development container image
├── CMakeLists.txt                  # Root CMake — orchestrates operators/applications/tests
├── pyproject.toml                  # Development tooling (CLI pin, ruff); no wheel build
├── metadata.json                   # Module-level metadata (schema: urn:holoscan:module:v2)
├── AGENTS.md                       # Guidance for AI coding agents
├── cmake/                          # CMake helpers copied from the CLI at create time
├── operators/
│   └── {{ cookiecutter.operator_slug }}/
│       ├── {{ cookiecutter.operator_slug }}.cpp / .hpp  # Operator implementation (typed ports)
│       └── metadata.json           # Operator-level metadata
├── applications/
│   └── {{ cookiecutter.module_slug }}_pipeline/
│       {% if cookiecutter.__python_bindings == 'yes' %}├{% else %}└{% endif %}── cpp/                    # C++ pipeline (compose → compile → run) + metadata.json
{%- if cookiecutter.__python_bindings == 'yes' %}
│       └── python/                 # Python pipeline using the C++ operator + metadata.json
{%- endif %}
├── pkg/{{ cookiecutter.module_repo_name }}/  # Debian package (CPack) configuration
{%- if cookiecutter.__python_bindings == 'yes' %}
├── python/                         # nanobind extension + holoscan_{{ cookiecutter.module_slug }} package
{%- endif %}
└── tests/
    {% if cookiecutter.__python_bindings == 'yes' %}├{% else %}└{% endif %}── cpp/                        # GTest suite: compile-plan + SyntheticClock graph tests
{%- if cookiecutter.__python_bindings == 'yes' %}
    └── python/                     # pytest suite: registry, proxy ports, Python pipeline
{%- endif %}
```

{% if cookiecutter.__python_bindings == 'yes' -%}
Holoscan SDK 5.0 is C++-first. The C++ operators are the implementation; `python/` adds a
nanobind extension that registers them with the SDK operator registry when
`holoscan_{{ cookiecutter.module_slug }}` is imported. Python code then uses the typed registry proxies:

```python
import holoscan as hs
from holoscan_{{ cookiecutter.module_slug }}.operators import {{ cookiecutter.operator_slug.split('_')|map('capitalize')|join('') }}
```

- Register each new operator with `HOLOSCAN_REGISTER_OPERATOR` in
  `python/_{{ cookiecutter.module_slug }}.cpp` under a `holoscan.{{ cookiecutter.module_slug }}.` name, and link the operator's target to
  the extension in `python/CMakeLists.txt`.
- `HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_PYTHON` (default `ON` when this is the top-level project and `PKG_{{ cookiecutter.module_repo_name.replace('-', '_') }}` is off) builds the extension. It needs Python 3.12+, the SDK's
  Python package on `PYTHONPATH`, and nanobind 3.0.1, which CMake fetches when it is not
  installed.
- `tests/python` runs through CTest (label `python`).
- The example has a `metadata.json` in both `cpp/` and `python/`, so `holoscan run
  {{ cookiecutter.module_slug }}_pipeline` takes `--language cpp` or `--language python`. Without `--language`, the CLI picks
  Python. From a CMake build tree, run `PYTHONPATH=build/python/lib:$PYTHONPATH python3
  applications/{{ cookiecutter.module_slug }}_pipeline/python/{{ cookiecutter.module_slug }}_pipeline.py`.
- The package is installed only on request and is not part of the Debian package:
  `cmake --install build --component {{ cookiecutter.module_repo_name }}-python`.
- Native installs support `import holoscan_{{ cookiecutter.module_slug }}`. Wheel packaging and the `holoscan.{{ cookiecutter.module_slug }}`
  alias return in a later release; until then the `pyproject.toml` only provisions
  development tooling.
{%- else -%}
Holoscan SDK 5.0 is C++-first, so this scaffold contains no Python operator, pipeline, or
binding layer. Python support returns in a later release; until then the `pyproject.toml` only
provisions development tooling.
{%- endif %}

---

## Holoscan SDK 5.0 API cheat sheet

| 4.x | 5.0 |
| --- | --- |
| `class Op : public holoscan::Operator` | `class Op final : public holoscan::Operator<>` (or `Operator<ParamsStruct>`) |
| `spec.input<T>("in")` in `setup()` | `holoscan::Input<T> in;` member + `spec.input(in, "in")` |
| `compute(InputContext&, OutputContext&, ExecutionContext&)` | `expected<void, Error> compute(ExecutionContext&)` |
| `op_input.receive<T>("in").value()` | `HOLOSCAN_TRY(auto v, in.receive_data());` |
| `op_output.emit(v, "out")` | `return out.emit(v);` |
| `Application::compose()` + `make_operator` | `holoscan::Graph` + `graph.op<Op>("name")` |
| `add_flow(a, b, {{ '{{' }}"out", "in"{{ '}}' }})` | `graph.add_flow(a->out, b->in)` (typed) |
| `app->run()` | `compile(graph)` → check `plan.ok()` → `run(plan)` / `run_async(plan)` |
| Conditions (`PeriodicCondition`, ...) | `contract()` returning a `holoscan::Contract` (`OnClock`, `OnEach`, ...) |

Sources must opt into time: add a clock (`graph.add_clock<RealtimeClock>`) and make it the default
(`graph.set_default_clock`) before compiling a graph that uses `OnClock`.

---

## Holoscan CLI environment and commands

Create the development environment with the exact CLI version committed by this Module:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install \
  --extra-index-url https://pypi.nvidia.com \
  -r requirements-cli.txt
```

The exact pin makes fresh host environments and development images reproducible. Lifecycle
commands remain usable with another installed CLI version when its behavior is compatible.
The global `holoscan` command discovers this Module from its metadata. Target architecture and
CUDA default to host detection, and lifecycle commands use containers unless you pass `--local`.
Run a lifecycle command with `--verbose` to see what was selected.

| Command | What it does |
| --- | --- |
| `holoscan run-container` | Build and start the development container |
| `holoscan build {{ cookiecutter.module_slug }}_pipeline{% if cookiecutter.__python_bindings == 'yes' %} --language cpp{% endif %}` | CMake configure + build inside the container |
| `holoscan run {{ cookiecutter.module_slug }}_pipeline{% if cookiecutter.__python_bindings == 'yes' %} --language cpp{% endif %}` | Run the example pipeline |
{%- if cookiecutter.__python_bindings == 'yes' %}
| `holoscan run {{ cookiecutter.module_slug }}_pipeline --language python` | Run the Python example pipeline |
{%- endif %}
| `holoscan test` | Run CTest (C++ unit tests{% if cookiecutter.__python_bindings == 'yes' %} and the `tests/python` pytest suite{% endif %}) |
| `holoscan package {{ cookiecutter.module_repo_name }} --pkg-generator DEB` | Build the Debian package |

The scaffold intentionally ships no launcher wrapper. Projects that need custom environment or
bootstrap policy can add a thin wrapper as an advanced customization, keep it outside the Module's
build and package contract, and delegate to the installed `holoscan` command. HoloHub's
[`holohub` wrapper](https://github.com/nvidia-holoscan/holohub/blob/main/holohub) is one reference.

If you use [uv](https://docs.astral.sh/uv/), the project config selects NVIDIA's package index for
`holoscan-cli` while leaving other dependencies on PyPI. It also avoids installing the Module
during normal UV commands, so no separate setup or activation is needed:

```bash
uv run holoscan test
```

To upgrade the tested development environment, update the CLI pin in
`requirements-cli.txt`, `pyproject.toml`, and `.pre-commit-config.yaml`, reinstall the
requirements (or rerun `uv sync`), and rebuild the image. Upgrading the CLI does not update
the helpers in `cmake/`; they belong to this Module, so update them by hand if needed.

---

## Building without the Holoscan CLI

```bash
cmake -S . -B build -DBUILD_ALL=ON -D{{ cookiecutter.module_slug | upper }}_BUILD_TESTING=ON
cmake --build build -j"$(nproc)"
```

Requirements on the host: Holoscan SDK ≥ {{ cookiecutter.holoscan_version }} (`apt install holoscan`,
the `holoscan-cuda-13` alias), CMake ≥ 4.0, a C++20 compiler and GoogleTest. The development
container (`Dockerfile`) provides all of these.

`{{ cookiecutter.module_slug | upper }}_BUILD_TESTING` defaults to `ON` for a standalone build
and `OFF` when this module is included by a parent project. To build without
tests, configure with `-D{{ cookiecutter.module_slug | upper }}_BUILD_TESTING:BOOL=OFF`.
The standard `-DBUILD_TESTING=OFF` does not control this module's tests.
The C++ tests use an installed GoogleTest CMake package (1.14 or newer) when CMake
finds one; otherwise CMake downloads GoogleTest while configuring, which needs network access.

Run C++ tests:

```bash
ctest --test-dir build --output-on-failure -L unit
```

---

## `pyproject.toml`

`pyproject.toml` records a PEP 735 development dependency group and the ruff configuration for the
repository's helper scripts. It does not build a Python package (`[tool.uv].package = false`).

| Field | Purpose |
| --- | --- |
| `[project].version` | Sync with `metadata.json:module.version` |
| `[dependency-groups].dev` | Exact CLI convenience pin; keep synchronized with `requirements-cli.txt` |
| `[tool.uv]` | NVIDIA index selection for the pinned `holoscan-cli` development dependency |
| `[tool.holoscan]` | Optional Module-wide CUDA, CTest, Docker, environment, and base-image defaults consumed by the CLI |
| `[tool.ruff]` | Lint configuration used by `.pre-commit-config.yaml` and CI |

The supported `[tool.holoscan]` keys are `cuda`, `ctest-script`, `docker-build-args`,
`docker-run-args`, `forward-env`, `search-paths`, and `base-images.{x86_64,aarch64}`.
Docker argument arrays contain one command token per element. `search-paths` lists the folders
searched for projects, replacing the defaults (`applications`, `operators`, `pkg`, and other
conventional folders); for example, `search-paths = ["operators", "examples"]`.
Do not store credentials or machine paths here; use `HOLOSCAN_SDK_ROOT` or `--local-sdk-root`
for a machine-specific SDK.

---

## Module identity and support level

`metadata.json:module` records the Module's public identity:

| Field | Purpose |
| --- | --- |
| `name` | Repository name: `holoscan-` followed by the lowercase, hyphen-separated Module slug (`holoscan-{{ cookiecutter.module_slug.replace('_', '-') }}`) |
| `support_level` | Self-declared support level shown on the HoloHub ecosystem page: `community`, `supported_external`, or `supported_core` |
| `binary_packages.debian` | Debian package name that installs the Module |
| `binary_packages.wheel` | Normalized Python wheel distribution name, once the Module publishes a wheel |
| `binary_packages.install_commands` | Recommended shell commands to install the binary packages |

`binary_packages.pypi` is a deprecated alias for `binary_packages.wheel`: validation warns when it
is present and fails when it disagrees with `wheel`.

---

## Depending on operators from other Modules

`metadata.json:module.dependencies` declares other Holoscan Modules whose operators this Module
uses. Its `source` block is consumed by `holoscan build`, which emits a `FetchContent_Declare`
for each dependency and lets the consuming project's root `CMakeLists.txt` call
`FetchContent_MakeAvailable` only when one of the advertised operators is enabled. Example — an
imaginary `holoscan-example-utils` Module that supplies a `FrameCounterOp`:

```json
"dependencies": [
  {
    "name": "holoscan-example-utils",
    "version": "1.2.0",
    "source": {
      "git_url": "https://github.com/example/holoscan-example-utils.git",
      "ref": "0123456789abcdef0123456789abcdef01234567"
    },
    "provides_operators": ["FrameCounterOp"]
  }
]
```

| Field | Purpose |
| --- | --- |
| `name` | Module name as declared in the dependency's `metadata.json:module.name` |
| `source.git_url` / `source.ref` | Where to fetch the Module; `ref` must be an immutable full 40-character commit SHA (tags and branches are not accepted) |
| `provides_operators` | Operators the dependency supplies; the Module is fetched only when one of them is being built |

Then link the dependency's operator target (Modules alias each operator as
`holoscan::<operator_slug>`) from the consuming operator or application, e.g.
`target_link_libraries({{ cookiecutter.operator_slug }} PUBLIC holoscan::frame_counter)`.
While iterating on both Modules locally, set `HOLOSCAN_CLI_LOCAL_HOLOSCAN_EXAMPLE_UTILS=/path/to/checkout`
to use a working tree instead of fetching `source`. Binary, Python and system dependencies are not
declared here — install them from the `Dockerfile` or the Debian package's `DEPENDS` list.

---

## Naming conventions

| Context | Convention | Example |
| --- | --- | --- |
| C++ namespace | `snake_case` | `holoscan::{{ cookiecutter.module_slug }}` |
| Repository folder | `holoscan-<slug>` (kebab) | `{{ cookiecutter.module_repo_name }}` |
| Debian package | `holoscan-<slug>` (kebab) | `holoscan-{{ cookiecutter.module_slug.replace('_', '-') }}` |
| CMake option prefix | `UPPER_SNAKE` | `{{ cookiecutter.module_slug | upper }}_BUILD_TESTING` |
| CMake module target | `holoscan::<slug>` | `holoscan::{{ cookiecutter.module_slug }}` |

## Installed CMake package

Link the module aggregate to use all enabled operators:

```cmake
find_package({{ cookiecutter.module_repo_name }} CONFIG REQUIRED)
target_link_libraries(my_pipeline PRIVATE holoscan::{{ cookiecutter.module_slug }})
```

The individual `holoscan::{{ cookiecutter.operator_slug }}` target remains available.
When adding an operator, install it in `holoscan_{{ cookiecutter.module_slug }}_targets`
and register it with the aggregate inside its gated operator directory:

```cmake
target_link_libraries(holoscan_{{ cookiecutter.module_slug }} INTERFACE holoscan::my_new_op)
```

---

## Further reading

- [HoloHub documentation](https://github.com/nvidia-holoscan/holohub)
- [Holoscan SDK documentation](https://docs.nvidia.com/holoscan/sdk-user-guide/introduction/getting-started)
- [Holoscan Module ecosystem](https://nvidia-holoscan.github.io/)
