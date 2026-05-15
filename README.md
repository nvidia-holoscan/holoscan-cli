[![Code Check](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yaml/badge.svg)](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yaml)
[![Coverage Status](https://coveralls.io/repos/github/nvidia-holoscan/holoscan-cli/badge.svg)](https://coveralls.io/github/nvidia-holoscan/holoscan-cli)

# Holoscan CLI

Command-line tool for discovering, building, running, testing, and linting HoloHub-style Holoscan source projects. Published as the [`holoscan-cli`](https://pypi.org/project/holoscan-cli/) PyPI package and installs the `holoscan` console script.

## Overview

The CLI presents a single command surface for the source-project development lifecycle:

- **Project lifecycle:** `build`, `run`, `test`, `install`
- **Container:** `build-container`, `run-container`
- **Discovery / diagnostics:** `list`, `modes`, `status`, `env-info`, `env-check`, `autocompletion_list`, `version`
- **Workspace:** `lint`, `setup`, `clear-cache`, `vscode`, `create`

Run `holoscan <command> --help` for per-command flags.

Per-repo wrappers install this package and delegate to `holoscan`, layering on their own configuration via `HOLOSCAN_CLI_*` environment variables:

| Repo | Wrapper | Adds |
| --- | --- | --- |
| [HoloHub](https://github.com/nvidia-holoscan/holohub) | `./holohub` | source-project metadata search paths, container/workspace names |
| Isaac OS | `./isaac_os` | HSB hardware auto-detection, `--privileged` docker run args, sccache memcached endpoint |
| [I4H Workflows](https://github.com/isaac-for-healthcare/i4h-workflows) | `./i4h` | RTI DDS license auto-download + mount, TTY serial device passthrough |

Common env vars: `HOLOSCAN_CLI_ROOT` (repo root), `HOLOSCAN_CLI_SEARCH_PATH` (subdirs to scan for `metadata.json`), `HOLOSCAN_CLI_PATH_PREFIX` (placeholder prefix in metadata templates), `HOLOSCAN_CLI_REPO_PREFIX` (container image name prefix). The legacy `HOLOHUB_*` spelling is still honored with a one-line deprecation warning and will be removed in the next minor release. `holoscan env-info` lists every env var the CLI reads in the current shell.

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

## Build from source

Python 3.10+ and [Poetry 2.0+](https://python-poetry.org/docs/#installation) required.

```bash
# Create + activate a virtual environment
poetry env use python3.12
eval $(poetry env activate)

# Install dependencies + dev tooling
poetry install
pre-commit install

# Run the test suite
poetry run pytest

# Build sdist + wheel
poetry build
```

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.

## Deprecations

### HAP/MAP application packaging

Application packaging (HAP/MAP) is no longer part of this CLI: `holoscan package`, `holoscan nics`, and the `monai-deploy` console script are intentionally not provided. The pre-v1 `holoscan run` was the HAP/MAP packaged-image runner; in v1 the same name now drives the HoloHub-style source-project runner, so it no longer launches packaged images. Developers that still rely on HAP/MAP packaging should pin `holoscan-cli<=4.2.0`, the last release that shipped that interface, or migrate to the Holoscan SDK packaging workflows directly. See [issue #164](https://github.com/nvidia-holoscan/holoscan-cli/issues/164) for the deprecation timeline.
