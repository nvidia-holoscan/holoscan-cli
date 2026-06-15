[![Code Check](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yaml/badge.svg)](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yaml)
[![Coverage Status](https://coveralls.io/repos/github/nvidia-holoscan/holoscan-cli/badge.svg)](https://coveralls.io/github/nvidia-holoscan/holoscan-cli)

# Holoscan CLI

Command-line tool for discovering, building, running, testing, and linting HoloHub-style Holoscan source projects. Published as the [`holoscan-cli`](https://pypi.org/project/holoscan-cli/) PyPI package and installs the `holoscan` console script.

## Overview

The CLI presents a single command surface for the source-project development lifecycle:

- **Project lifecycle:** `build`, `run`, `test`, `install`, `package`
- **Container:** `build-container`, `run-container`
- **Discovery / diagnostics:** `list`, `modes`, `status`, `env-info`, `env-check`, `autocompletion_list`, `version`
- **Workspace:** `lint`, `setup`, `clear-cache`, `create`

Run `holoscan <command> --help` for per-command flags.

Per-repo wrappers install this package and delegate to `holoscan`, layering on their own configuration via `HOLOSCAN_CLI_*` environment variables:

| Repo | Wrapper | Adds |
| --- | --- | --- |
| [HoloHub](https://github.com/nvidia-holoscan/holohub) | `./holohub` | source-project metadata search paths, container/workspace names |
| [I4H Workflows](https://github.com/isaac-for-healthcare/i4h-workflows) | `./i4h` | RTI DDS license auto-download + mount, TTY serial device passthrough |

Common env vars: `HOLOSCAN_CLI_ROOT` (repo root), `HOLOSCAN_CLI_SEARCH_PATH` (subdirs to scan for `metadata.json`), `HOLOSCAN_CLI_PATH_PREFIX` (placeholder prefix in metadata templates), `HOLOSCAN_CLI_REPO_PREFIX` (container image name prefix). The legacy `HOLOHUB_*` spelling is no longer honored in v1 — set the `HOLOSCAN_CLI_*` names directly. `holoscan env-info` lists every env var the CLI reads in the current shell.

## Source layout

```text
src/holoscan_cli/
  cli.py              top-level argparse + dispatch (HoloscanCLI)
  commands/           one file per subcommand + a central registry
  container/          HoloscanContainer + docker arg helpers + parser builders
  utils/              io.py, text.py, sdk.py, docker.py, host_setup.py,
                      env_info.py, holohub.py
  setup_scripts/      bundled bash scripts backing `setup --scripts` and
                      `build-container --extra-scripts`
  metadata/           project metadata JSON schemas
  testing/            CTest helpers shipped in the wheel
```

## Prerequisites

A platform supported by the [NVIDIA Holoscan SDK](https://docs.nvidia.com/holoscan/sdk-user-guide/sdk_installation.html#prerequisites): an x64 PC with Ubuntu and an NVIDIA GPU, or a supported NVIDIA ARM development kit.

## Installation

```bash
pip install holoscan-cli
holoscan --help
```

For transient use without keeping an installed environment, package-name based
tool runners can use the compatibility alias:

```bash
uvx holoscan-cli --help
pipx run holoscan-cli --help
```

The primary CLI command remains `holoscan`. Explicit package/command forms also
work when you want the canonical command name from a transient runner:

```bash
uvx --from holoscan-cli holoscan --help
pipx run --spec holoscan-cli holoscan --help
```

## Versioning

`holoscan-cli` release versions are aligned with Holoscan SDK GA release
versions. For example, the CLI released with Holoscan SDK 4.4.0 is published as
`holoscan-cli==4.4.0`; the CLI released with Holoscan SDK 4.5.0 is published as
`holoscan-cli==4.5.0`.

CLI-only fixes between SDK releases use the patch component for the current SDK
release line, for example `holoscan-cli==4.4.1` before the next SDK-aligned
`4.5.0` release.

Version alignment does not imply that the CLI selects, installs, or requires a
matching Holoscan SDK runtime or container base image. For container builds,
choose the base image explicitly with `--base-img` or configure one in the
environment:

```bash
export HOLOSCAN_CLI_BASE_IMAGE=nvcr.io/nvidia/clara-holoscan/holoscan:v4.4.0-cuda13
holoscan build-container my_app
```

Wrapper repos can also configure the Holoscan SDK container repository and SDK
version separately:

```bash
export HOLOSCAN_CLI_BASE_IMAGE=nvcr.io/nvidia/clara-holoscan/holoscan
export HOLOSCAN_CLI_BASE_SDK_VERSION=4.4.0
holoscan build-container my_app
```

With the default CUDA selection, that derives the full base image string
`nvcr.io/nvidia/clara-holoscan/holoscan:v4.4.0-cuda13`. If neither an explicit
base image tag nor a base SDK version is configured, the CLI asks for a base
image instead of inferring one from its own package version.

## Build from source

Python 3.10+ and [Poetry 2.0+](https://python-poetry.org/docs/#installation) required.

```bash
# Create + activate a virtual environment
poetry env use python3.12
eval $(poetry env activate)

# Install dependencies + dev tooling
poetry install --with test
pre-commit install

# Run the test suite
poetry run pytest

# Build sdist + wheel
poetry build
```

### Testing against an in-tree source-project fixture

The repo ships a minimal HoloHub-style fixture at
`tests/fixtures/holohub_smoke/` (one application with a `metadata.json` that
validates against the application schema). Point the CLI at it without
needing a HoloHub / I4H checkout:

```bash
HOLOSCAN_CLI_ROOT=tests/fixtures/holohub_smoke holoscan list
HOLOSCAN_CLI_ROOT=tests/fixtures/holohub_smoke holoscan modes smoke_app
```

The same fixture is what `.github/scripts/smoke_test.sh` exercises against
the installed wheel on every CI run, so a passing fixture run locally is a
strong proxy for the `smoke-test` job passing on push.

### Testing against the downstream wrappers

Each consuming repo (HoloHub / I4H Workflows) carries a
`test_holoscan_cli_consolidation.py` that exercises the unified `holoscan`
CLI against its project tree. Point the wrapper at a local checkout via
`HOLOSCAN_CLI_SOURCE`:

```bash
cd /path/to/holohub
HOLOSCAN_CLI_SOURCE=/path/to/holoscan-cli \
  python -m pytest -q -o addopts='' utilities/cli/tests/test_holoscan_cli_consolidation.py
```

The wrapper prepends `<HOLOSCAN_CLI_SOURCE>/src` to `PYTHONPATH`, so an
in-progress branch can be exercised end-to-end without publishing a wheel
first.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.
[`.github/CI.md`](./.github/CI.md) covers the CI/release pipelines that back
the workflow badges at the top of this page.

## Deprecations

### HAP/MAP application packaging

Application packaging (HAP/MAP) is no longer part of this CLI: `holoscan nics` and the `monai-deploy` console script are intentionally not provided. The current `holoscan package` command is for building Holoscan Module distribution artifacts; it is not the legacy HAP/MAP application packager. The pre-v1 `holoscan run` was the HAP/MAP packaged-image runner; in v1 the same name now drives the HoloHub-style source-project runner, so it no longer launches packaged images. Developers that still rely on HAP/MAP packaging should pin `holoscan-cli<=4.2.0`, the last release that shipped that interface, or migrate to the Holoscan SDK packaging workflows directly. See [issue #164](https://github.com/nvidia-holoscan/holoscan-cli/issues/164) for the deprecation timeline.
