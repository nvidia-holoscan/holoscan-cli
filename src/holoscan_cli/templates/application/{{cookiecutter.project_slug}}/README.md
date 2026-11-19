{%- if cookiecutter.language == 'python' -%}
{%- set source = 'python/' ~ cookiecutter.project_slug ~ '.py' -%}
{%- else -%}
{%- set source = 'cpp/main.cpp' -%}
{%- endif -%}
# {{ cookiecutter.project_name }}

{{ cookiecutter.description }}

The application's graph emits a finite sequence of integers, doubles each value,
and verifies every result at the sink before printing a final verdict. Replace
the operators in `{{ source }}` with your pipeline and keep a finite mode that
checks its own result.

## Requirements

- Linux on x86_64 or aarch64 with an NVIDIA GPU and a compatible driver.
{%- if cookiecutter.language == 'python' %}
- Holoscan SDK {{ cookiecutter.holoscan_version }} or later with its Python package.
- Python 3.12 or later and CMake 3.24 or later.
{%- else %}
- Holoscan SDK {{ cookiecutter.holoscan_version }} or later (C++).
- CMake 4.0 or later and a C++20 compiler.
{%- endif %}
- The Holoscan CLI (`holoscan`).

Add your application's hardware, dependencies, and data preparation here, and
link the license terms of any separately downloaded models or datasets.

## Build and run

The CLI finds the project from the current directory. Run the commands below
from the project that contains this application, or from this directory when
the application is a project of its own.

### In a container

The CLI builds and runs in a container by default, using the `Dockerfile` at
the project root, such as the one a Module or a repository of applications
provides. Select the Holoscan SDK image, unless the project already configures
one:

```bash
export HOLOSCAN_CLI_BASE_IMAGE=nvcr.io/nvidia/clara-holoscan/holoscan:v{{ cookiecutter.holoscan_version }}-cuda13
holoscan run {{ cookiecutter.project_slug }}
holoscan run {{ cookiecutter.project_slug }} ci
```

Add `--dryrun --verbose` to preview the image and the build and run commands.
An application that is a project of its own has no `Dockerfile`; build and run
it [on the host](#on-the-host).

### On the host

Install the [requirements](#requirements) on the host and add `--local`:

```bash
holoscan run {{ cookiecutter.project_slug }} --local
```

The CLI finds an SDK installed under `/usr`, such as the Debian packages, by
default. For an SDK installed elsewhere or a source build, set
`HOLOSCAN_SDK_ROOT=/path/to/holoscan/install`.

### Modes and options

| Mode | Behavior |
| --- | --- |
| `default` | Processes 100 messages and verifies every result. |
| `ci` | Processes 10 messages without external data, a display, or devices. |

Each run prints `expected`, `received`, `mismatches`, and a `verdict`, and exits
nonzero on failure. `--run-args` appends options to the mode's command, for
example `--run-args='--period-ms 5'`; `--run-args='--help'` lists them all.

## Tests

`holoscan test` takes no mode. In a container, with the SDK image selected:

```bash
holoscan test {{ cookiecutter.project_slug }} --no-xvfb
```

For host tests, add `--local`.

`tests/CMakeLists.txt` registers tests that run the application, so they need
the SDK. Register tests that need no SDK, GPU, or external data in the
top-level `CMakeLists.txt`, outside the language switch, so they also run where
the SDK is not installed.
