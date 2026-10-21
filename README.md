[![Code Check](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yaml/badge.svg)](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yaml)
[![Coverage Status](https://coveralls.io/repos/github/nvidia-holoscan/holoscan-cli/badge.svg)](https://coveralls.io/github/nvidia-holoscan/holoscan-cli)

# Holoscan CLI

Command-line tool for creating, discovering, building, running, testing, and packaging Holoscan Modules and applications. Published as the [`holoscan-cli`](https://pypi.org/project/holoscan-cli/) PyPI package and installs the `holoscan` console script.

## Overview

The CLI presents a single command surface for the source-project development lifecycle:

- **Project lifecycle:** `build`, `run`, `test`, `install`, `package`
- **Container:** `build-container`, `run-container`
- **Discovery / diagnostics:** `list`, `modes`, `status`, `env-info`, `env-check`, `autocompletion_list`, `version`
- **Workspace:** `lint`, `setup`, `clear-cache`, `create`

Run `holoscan <command> --help` for per-command flags, and `holoscan env-info`
for the values of the main environment variables the CLI reads. The
[CLI reference](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/CLI_REFERENCE.md)
describes command behavior, including JSON output and CPU limits.
[Configuring Holoscan CLI](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/CONFIGURATION.md)
covers settings, base images, and their precedence.

## Prerequisites

A platform supported by the [NVIDIA Holoscan SDK](https://docs.nvidia.com/holoscan/sdk-user-guide/sdk_installation.html#prerequisites): an x64 PC with Ubuntu and an NVIDIA GPU, or a supported NVIDIA ARM development kit.

## Installation

Python 3.12 or 3.13 is recommended for this walkthrough. Check the selected
release's Python requirement before using another interpreter.

With [uv](https://docs.astral.sh/uv/), try the CLI without a persistent install:

```bash
uvx holoscan-cli --help
```

The package also provides the canonical `holoscan` command. For a persistent
pip environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install holoscan-cli
holoscan --help
```

### Create and work on a standalone module

Creating a module requires the `create` extra:

```bash
uvx --from 'holoscan-cli[create]>=5.0.0' holoscan create my-sensor --interactive false --context holoscan_version=5.0.0 --dryrun
uvx --from 'holoscan-cli[create]>=5.0.0' holoscan create my-sensor --interactive false --context holoscan_version=5.0.0
cd holoscan-my-sensor
uv run holoscan list --json
uv run holoscan build my_sensor_pipeline --dryrun --verbose
```

The packaged template creates C++ modules for Holoscan SDK 5.0.0 or later.
Replace `5.0.0` with the module's intended minimum SDK version. CLI and SDK
versions are independent. Review the preview before running the build without
`--dryrun`; builds require the module's documented SDK/container prerequisites.
The generated project records the creating CLI version, and `uv run` prepares
its development environment without installing the module itself.

For the pip alternative, install the same creation extra in the activated
`.venv`, then run `holoscan create` with the same arguments:

```bash
python -m pip install 'holoscan-cli[create]>=5.0.0'
```

In an existing generated module, use its `requirements-cli.txt` to provision
a pip environment. Follow its `README.md` and `DEVELOPER.md` for implementation,
tests, packaging, and consumer verification.

See the [CLI reference](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/CLI_REFERENCE.md) for project selection, command
semantics, previews, diagnostics, and cleanup.

### Project configuration

Standalone Modules can persist a small set of settings that cannot be inferred
from `metadata.json` or the host:

```toml
[tool.holoscan]
cuda = 13
ctest-script = "ci/container.ctest"
forward-env = ["IS_CI_BUILD"]
docker-build-args = ["--build-arg", "PROJECT_FEATURE=ON"]
docker-run-args = ["--network=host"]

[tool.holoscan.base-images]
x86_64 = "registry.example.com/holoscan/sdk-build-x86_64:5.0.0-cuda13"
aarch64 = "registry.example.com/holoscan/sdk-build-aarch64:5.0.0-cuda13"
```

`cuda` and `ctest-script` provide Module-wide toolchain defaults,
`forward-env` contains names only, the Docker argument arrays provide static
defaults, and `base-images` contains exact images for the supported target
architectures. Use command options for one-off choices. See
[Configuring Holoscan CLI](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/CONFIGURATION.md)
for the complete user-facing behavior.

## Project trust model

Holoscan source projects are executable code, not passive data. In particular,
`metadata.json` can define a `run.command` (directly or through a mode), and
`holoscan run` executes that project-defined command. Build files, Dockerfiles,
setup scripts, and test configuration can execute project code as well. Review
the source and metadata before building or running a repository you do not
trust.

For a plain `run.command` string, the CLI expands Holoscan placeholders, parses
the result into an argument vector, and launches it without an implicit shell.
A project can still request a shell explicitly (for example, `bash -c ...`) or
name any other executable. Local execution runs with the invoking user's
permissions; elevation happens only when the user explicitly passes
`--as-root`.

Use `holoscan run <project> --dryrun --local --verbose` to inspect the resolved
local build and run commands without executing them. A dry run helps with
review, but it is not a sandbox and does not make untrusted project code safe.

## Versioning

`holoscan-cli` release versions are aligned with Holoscan SDK GA release
versions. For example, the CLI released with Holoscan SDK 4.4.0 is published as
`holoscan-cli==4.4.0`; the CLI released with Holoscan SDK 4.5.0 is published as
`holoscan-cli==4.5.0`.

CLI-only fixes between SDK releases use the patch component for the current SDK
release line, for example `holoscan-cli==4.4.1` before the next SDK-aligned
`4.5.0` release.

Version alignment does not imply that the CLI selects, installs, or requires a
matching Holoscan SDK runtime or container base image. Choose the base image for
container builds with `--base-img`, `HOLOSCAN_CLI_BASE_IMAGE`, or a Module's
`[tool.holoscan.base-images]`; see
[base images](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/CONFIGURATION.md#base-images).

## Contributing

See
[CONTRIBUTING.md](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/CONTRIBUTING.md)
for development setup, tests, and builds.
[`.github/CI.md`](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/.github/CI.md)
covers the CI/release pipelines that back the workflow badges at the top of
this page.

## Deprecations

### HAP/MAP application packaging

Application packaging (HAP/MAP) is no longer part of this CLI: `holoscan nics`
and the `monai-deploy` console script are intentionally not provided. The current
`holoscan package` command is for building Holoscan Module distribution artifacts;
it is not the legacy HAP/MAP application packager. Before holoscan v4.3.0,
`holoscan run` was the HAP/MAP packaged-image runner; since v4.3.0 the same name
now drives the source-project runner, so it no longer launches packaged images.
Developers that still rely on HAP/MAP packaging should pin both
`holoscan-cli<=4.2.0`, the last CLI release that shipped that interface, and
`holoscan<=4.2.0`, because the legacy package command depends on the artifacts
JSON manifest and was only tested with those SDK versions. Otherwise, migrate to
the Holoscan SDK packaging workflows directly. See
[issue #164](https://github.com/nvidia-holoscan/holoscan-cli/issues/164) for the
deprecation timeline.

### `pybind11_add_holohub_module()` CMake helper

`holoscan create` no longer copies the pybind11 helper
`pybind11_add_holohub_module.cmake` into new Modules; Modules created earlier
keep their copy. Holoscan SDK 5 builds Python bindings with nanobind: see
`python/CMakeLists.txt` in a Module created with
`holoscan create --language cpp python`. Holoscan SDK 4 templates that call the
helper need their own copy of it or holoscan-cli 4.6.
