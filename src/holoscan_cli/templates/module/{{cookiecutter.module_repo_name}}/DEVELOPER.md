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
├── pyproject.toml                  # Python packaging metadata (scikit-build-core)
├── metadata.json                   # Module-level metadata (schema: urn:holohub:module:v2)
├── operators/
│   └── {{ cookiecutter.operator_slug }}/
│       ├── {{ cookiecutter.operator_slug }}.{% if cookiecutter.language == 'cpp' %}cpp / .hpp{% else %}py{% endif %}  # Operator implementation
│       └── metadata.json           # Operator-level metadata
├── applications/
│   └── {{ cookiecutter.module_slug }}_pipeline/
│       ├── python/                 # Python pipeline + metadata.json (every module)
│       └── cpp/                    # C++ pipeline + metadata.json (cpp-language modules)
├── python/holoscan/{{ cookiecutter.module_slug }}/
│   └── __init__.py                 # Re-exports operators for `from holoscan.{{ cookiecutter.module_slug }} import ...`
└── tests/
    ├── cpp/                        # GTest suite (C++ modules only)
    └── python/                     # pytest suite
```

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
| `holoscan build {{ cookiecutter.module_slug }}_pipeline` | CMake configure + build inside the container |
| `holoscan run {{ cookiecutter.module_slug }}_pipeline` | Run the example pipeline |
| `holoscan test` | Run CTest (C++ unit tests) and pytest |
| `holoscan install --dev` | Install a `.pth` hook for live Module imports in the current Python environment |

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

To upgrade the tested development environment, update the CLI pin in both
`requirements-cli.txt` and `pyproject.toml`, reinstall the requirements (or rerun
`uv sync`), and rebuild the image.

---

## GitHub CI

The generated `.github/workflows/ci.yml` runs on pushes to `main`, pull requests
against `main`, and manual dispatch. Its required hosted jobs are:

- **Lint**: Python lint, metadata schema validation, and C++ formatting when applicable.
- **CPU build and package**: configure and compile with the CUDA 13 SDK Debian
  development package in an Ubuntu 24.04 amd64 container, then build a `.deb`.
- **Debian install**: verify the package name, version, architecture, and SDK
  dependency, then install it in a fresh Ubuntu container.

The build environment is described in `.github/workflows/Dockerfile.cpu`. It uses
Debian packages because the SDK Python wheel does not include C++ headers or its
CMake package. No GPU is requested by the hosted jobs, and they do not execute
GPU graphs. The dependency test expects the x86_64 CUDA 13 variant; additional
platforms and CUDA variants need their own build/install matrix.

**GPU build and test** is disabled by default. Configure a self-hosted runner with
`self-hosted`, `linux`, `x86_64`, and `gpu` labels, Docker GPU support, and access to
the selected SDK image. Enable `run_gpu` when manually dispatching the workflow,
or set repository variable `MODULE_CI_RUN_GPU=true` for push/PR events. Manual
runs use the input value rather than the repository default.

For local CPU build/package reproduction from this module's root:

```bash
docker build -f .github/workflows/Dockerfile.cpu -t module-ci-build .github/workflows
docker run --rm -v "$PWD:/work" module-ci-build \
  cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -D{{ cookiecutter.module_slug | upper }}_BUILD_TESTING=OFF -DBUILD_ALL=ON
docker run --rm -v "$PWD:/work" module-ci-build cmake --build build --parallel 2
docker run --rm -v "$PWD:/work" module-ci-build \
  cpack --config build/pkg/CPackConfig-{{ cookiecutter.module_repo_name }}.cmake \
  -B build/packages -G DEB
```

The workflow supports optional candidate CLI artifact inputs for CLI development:
`cli_run_id`, `cli_artifact_id`, `cli_wheel_sha256`, and `cli_version`. Supply all
four together, using an artifact in the same repository; the wheel must match
`requirements-cli.txt`. Leave them empty for normal published-CLI installation.
`e2e_id` only identifies the upstream validation run. Neither path changes the
module's generated version pin. Build logs and Debian packages are available in
the workflow's artifacts.

---

## Building without the Holoscan CLI

```bash
cmake -S . -B build -DBUILD_ALL=ON -D{{ cookiecutter.module_slug | upper }}_BUILD_TESTING=ON
cmake --build build -j"$(nproc)"
```

{% if cookiecutter.language == 'cpp' -%}
Run C++ tests:

```bash
ctest --test-dir build --output-on-failure -L unit
```

{% endif -%}
Run Python tests:

```bash
{{ cookiecutter.module_slug | upper }}_BUILD_DIR=build \
PYTHONPATH=build/python/lib${PYTHONPATH:+:$PYTHONPATH} \
pytest tests/python/ -v
```

`PYTHONPATH` is **prepended via `${PYTHONPATH:+:$PYTHONPATH}`** so that an existing entry on the variable is kept while an unset/empty variable doesn't yield a trailing colon. Two failure modes the shorter forms invite:

- **`PYTHONPATH=build/python/lib`** (replace): drops any ambient holoscan SDK install on `PYTHONPATH`. The module-level `importorskip("holoscan")` then fires, pytest exits with code 5, and CTest marks the run as Skipped.
- **`PYTHONPATH=build/python/lib:$PYTHONPATH`** (naive prepend): on a fresh shell or CI runner where `$PYTHONPATH` is unset, this expands to `PYTHONPATH=build/python/lib:` — Python treats the trailing empty entry as the current directory, silently shadowing installed packages with whatever happens to live in the test CWD.

---

## `pyproject.toml`

`pyproject.toml` configures [scikit-build-core](https://scikit-build-core.readthedocs.io/) for
wheel packaging and records an optional PEP 735 development dependency group. Key fields to
update before publishing:

| Field | Purpose |
| --- | --- |
| `[project].name` | PyPI package name — should match `metadata.json:module.binary_packages.pypi` |
| `[project].version` | Sync with `metadata.json:module.version` |
| `[project].description` | Short description shown on PyPI |
| `[project].authors` | Your name / organisation |
| `[dependency-groups].dev` | Exact CLI convenience pin; keep synchronized with `requirements-cli.txt` |
| `[tool.uv]` | UV development environment and NVIDIA index selection for `holoscan-cli` |
| `[tool.holoscan]` | Optional Module-wide CUDA, CTest, Docker, environment, and base-image defaults |
| `[tool.scikit-build].cmake.args` | Extra CMake flags passed during `pip install` |

The supported keys are `tool.holoscan.cuda`, `tool.holoscan.ctest-script`,
`tool.holoscan.docker-build-args`, `tool.holoscan.docker-run-args`,
`tool.holoscan.forward-env`, and `tool.holoscan.base-images.{x86_64,aarch64}`. Docker argument
arrays contain one command token per element. Do not store credentials or machine paths here;
use `HOLOSCAN_SDK_ROOT` or `--local-sdk-root` for a machine-specific SDK.

Build a wheel:

```bash
pip install build
python -m build --wheel
```

---

## Naming conventions

| Context | Convention | Example |
| --- | --- | --- |
| Python import / C++ namespace | `snake_case` | `holoscan.{{ cookiecutter.module_slug }}` |
| Repository folder | `holoscan-<slug>` (kebab) | `{{ cookiecutter.module_repo_name }}` |
| Debian package | `holoscan-<slug>` (kebab) | `holoscan-{{ cookiecutter.module_slug.replace('_', '-') }}` |
| PyPI package | `holoscan-<slug>` (kebab) | `holoscan-{{ cookiecutter.module_slug.replace('_', '-') }}` |
| CMake option prefix | `UPPER_SNAKE` | `{{ cookiecutter.module_slug | upper }}_BUILD_TESTING` |

---

## Further reading

- [HoloHub documentation](https://github.com/nvidia-holoscan/holohub)
- [Holoscan SDK documentation](https://docs.nvidia.com/holoscan/sdk-user-guide/introduction/getting-started)
- [Holoscan Module ecosystem](https://nvidia-holoscan.github.io/)
