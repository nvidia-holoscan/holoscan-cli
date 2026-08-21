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

| Command | What it does |
| --- | --- |
| `holoscan run-container` | Build and start the development container |
| `holoscan build {{ cookiecutter.module_slug }}_pipeline` | CMake configure + build inside the container |
| `holoscan run {{ cookiecutter.module_slug }}_pipeline` | Run the example pipeline |
| `holoscan test` | Run CTest (C++ unit tests) and pytest |
| `holoscan install --dev` | Install a `.pth` hook so `import holoscan.{{ cookiecutter.module_slug }}` works in any shell |

If you use [uv](https://docs.astral.sh/uv/), the project config selects NVIDIA's package index for
`holoscan-cli` while leaving other dependencies on PyPI. Run `uv sync --only-dev`, then
`source .venv/bin/activate` and use the same commands above. This installs the development tools
without trying to build the Module on the host.

To upgrade the tested development environment, update the CLI pin in both
`requirements-cli.txt` and `pyproject.toml`, reinstall the requirements (or rerun
`uv sync --only-dev`), and rebuild the image.

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
wheel packaging and records an optional PEP 735 development dependency group. Key fields to update
before publishing:

| Field | Purpose |
| --- | --- |
| `[project].name` | PyPI package name — should match `metadata.json:module.binary_packages.pypi` |
| `[project].version` | Sync with `metadata.json:module.version` |
| `[project].description` | Short description shown on PyPI |
| `[project].authors` | Your name / organisation |
| `[dependency-groups].dev` | Exact CLI convenience pin; keep synchronized with `requirements-cli.txt` |
| `[tool.uv]` | NVIDIA index selection for the pinned `holoscan-cli` development dependency |
| `[tool.scikit-build].cmake.args` | Extra CMake flags passed during `pip install` |

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
