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
Global controls must appear before the command: `--project-root PATH` selects a
source tree, `--log-level LEVEL` changes logging, and `--version` prints the CLI
version.

Per-repo wrappers install this package and delegate to `holoscan`, layering on their own configuration via `HOLOSCAN_CLI_*` environment variables:

| Repo | Wrapper | Adds |
| --- | --- | --- |
| [HoloHub](https://github.com/nvidia-holoscan/holohub) | `./holohub` | source-project metadata search paths, container/workspace names |
| [I4H Workflows](https://github.com/isaac-for-healthcare/i4h-workflows) | `./i4h` | RTI DDS license auto-download + mount, TTY serial device passthrough |

Common env vars: `HOLOSCAN_CLI_ROOT` (repo root), `HOLOSCAN_CLI_SEARCH_PATH`
(subdirs to scan for `metadata.json`), `HOLOSCAN_CLI_CREATE_TEMPLATE` (a
wrapper-selected default overridden by `create --template`),
`HOLOSCAN_CLI_PATH_PREFIX` (placeholder prefix in metadata templates), and
`HOLOSCAN_CLI_REPO_PREFIX` (source-tree identity; standalone image names use
`HOLOSCAN_CLI_CONTAINER_PREFIX`). The legacy
`HOLOHUB_*` spelling is no longer honored since holoscan v4.3.0 — set the
`HOLOSCAN_CLI_*` names directly. `holoscan env-info` reports a classified
diagnostic subset of the current shell and active project; it is not an
exhaustive inventory of every variable read by every subprocess.

## JSON output

`list`, `modes`, `status`, `env-info`, `env-check`, and `version` accept `--json`
and print a single machine-readable document instead of prose.

Every payload starts with a `schema_version` field, currently `1`. Within a
version the payloads change additively: new keys may appear, existing keys are
not removed or renamed. Consumers should ignore keys they do not recognize; a
removal or rename bumps `schema_version`.

`env-info --json` reports host state, so the values vary by machine — the
`docker`, `cuda_gpu`, and `git` sections are `null` when unavailable.

## Source layout

```text
src/holoscan_cli/
  __main__.py         native options, project discovery, and dispatch
  cli.py              source-project argparse and command selection
  configuration.py    safe effective-configuration reporting
  commands/           one file per subcommand + a central registry
  container/          HoloscanContainer + docker arg helpers + parser builders
  utils/              process, Docker, SDK, host setup, dependency, JSON,
                      manifest, and text helpers
  setup_scripts/      bundled bash scripts backing `setup --scripts` and
                      `build-container --extra-scripts`
  metadata/           project discovery, validation, utilities, and JSON schemas
  templates/module/   self-contained standalone Module cookiecutter
  testing/            CTest helpers shipped in the wheel
```

## Prerequisites

A platform supported by the [NVIDIA Holoscan SDK](https://docs.nvidia.com/holoscan/sdk-user-guide/sdk_installation.html#prerequisites): an x64 PC with Ubuntu and an NVIDIA GPU, or a supported NVIDIA ARM development kit.

## Installation

```bash
pip install holoscan-cli
holoscan --help
```

To scaffold a standalone Holoscan Module, install the optional creation
dependencies and run `create` from the directory that should contain the new
repository:

```bash
pip install 'holoscan-cli[create]'
holoscan create my-sensor
```

This creates `./holoscan-my-sensor` from the standard Module template bundled
with the package. Use `--directory <path>` to select another output parent or
`--template <path>` to use an explicit cookiecutter template. The generated
repository contains an exact `requirements-cli.txt` contract and uses the
environment's global `holoscan` command for build, run, test, install, and
package operations. It does not contain a local launcher or require a HoloHub
clone.

An existing empty destination, or a cloned repository containing only `.git`,
can also be populated without overwriting Git state. Because `--directory`
names the output parent, run this from inside a pre-cloned
`holoscan-my-sensor` repository:

```bash
holoscan create "My Sensor" --directory ..
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

`uvx` and `pipx run` are optional front ends, not project requirements. A
standard `python -m venv` plus `python -m pip install -r requirements-cli.txt`
remains the portable path. Both transient tools use their configured Python
package indexes; neither makes an offline or trusted installation automatic.

### Static project configuration

For a short task-oriented introduction, see the
[configuration guide](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/CONFIGURATION.md).

Standalone Modules may put static CLI policy in a versioned
`[tool.holoscan]` table in `pyproject.toml`. `metadata.json` remains the
Holoscan ecosystem descriptor; it should not accumulate installer policy,
machine-local paths, credentials, or generic executable hooks.

```toml
[tool.holoscan]
schema-version = 1
repo-prefix = "my_module"
container-prefix = "my-module"
search-path = ["."]
build-type = "Release"
ctest-script = "cmake/container.ctest"
cuda = 13
docker-build-args = ["--secret", "id=gitlab_token,env=GITLAB_ACCESS_TOKEN"]
docker-run-args = ["--pid=host", "--ulimit", "rtprio=10"]
forward-env = ["IS_CI_BUILD", "SCCACHE_MEMCACHED_ENDPOINT"]

[tool.holoscan.sdk]
version = "5.0.0"
search = ["../holoscan-sdk/install-{arch}"]
allow-parent-search = true
mount-read-only = true

[tool.holoscan.sdk.base-images]
x86_64 = "registry.example.com/holoscan/sdk-build-x86_64:reviewed-2026-08"
aarch64 = "registry.example.com/holoscan/sdk-build-aarch64:reviewed-2026-08"
```

The table is strict and schema-versioned: misspelled or unsupported fields
fail before lifecycle work. Metadata search paths and CTest scripts must stay
inside the project. SDK search paths must be relative; the only template token
is `{arch}`. `allow-parent-search` expands discovery only to the project's
direct sibling tree, and absolute machine-local SDK locations must be supplied
with `--local-sdk-root` or `HOLOSCAN_SDK_ROOT`. An invalid explicit SDK root is
an error rather than a signal to silently select another installation.
A successful `sdk.search` activates that installation for local builds and
container mounts, and places its Python package before the image copy.
`mount-read-only` controls the mount. The CLI validates the selected local SDK
layout, but does not infer SDK/CUDA compatibility from an arbitrary image name.

Resolution follows command option, typed environment override, selected
metadata mode, root `[tool.holoscan]` policy, then CLI default. Use a
wrapper or separate application only for a genuinely new dynamic workflow;
do not add a wrapper solely to bootstrap Python or export static defaults.

Scalar settings use strict precedence: command line, environment, project,
then CLI default. Repository mode values are project defaults and stay below
the real process environment. Layered Boolean controls provide both directions,
for example `--local` / `--container` and `--no-docker-build` /
`--docker-build`.

The Docker argument arrays are deliberately additive because `--build-args`
and `--docker-opts` are documented as extra options. They are composed from
project-wide defaults, the selected metadata mode, real environment additions,
and finally CLI additions. `--docker-opts` is repeatable. Use
`--replace-docker-opts='...'` to replace every inherited Docker-run fragment in
one operation, or bare `--replace-docker-opts` to clear them. An empty
`--docker-opts="$EXTRA_OPTS"` remains an additive no-op and never clears lower
layers. `--replace-build-args`, `--replace-configure-args`, and
`--replace-forward-env` provide the corresponding resets for the other
additive surfaces.

For a broader escape hatch, `--no-project-config`, `--no-mode-config`, and
`--no-inherited-config` suppress additive vectors from those layers. They do
not disable scalar project settings, mode commands/environments, SDK or image
selection, or CLI-generated invariants. Frequently overridden typed values
such as `--base-img` and `--cuda` are reserved and cannot be defeated by a raw
lower-precedence `--build-arg` with the same key. `--build-with` is a complete
operator selection rather than an addition: it replaces mode `build.depends`,
and `--build-with=` clears it.

`forward-env` contains names only. Docker inherits their host values without
putting secrets in its argv or dry-run output. Add names with repeated
`--forward-env NAME`, or combine it with `--replace-forward-env` to discard the
environment/project allowlist for one invocation. CLI-owned container invariants
such as `HOME` and `HOLOSCAN_CLI_BUILD_LOCAL` cannot be forwarded.
`hostname-prefix` is reserved for a future hostname policy and currently has
no runtime effect. Use `--verbose` on lifecycle commands to see effective
values and their sources without echoing opaque Docker/CMake option values or
mode-environment values.

## Versioning

`holoscan-cli` release versions are aligned with Holoscan SDK GA release
versions. For example, the CLI released with Holoscan SDK 4.4.0 is published as
`holoscan-cli==4.4.0`; the CLI released with Holoscan SDK 4.5.0 is published as
`holoscan-cli==4.5.0`.

CLI-only fixes between SDK releases use the patch component for the current SDK
release line, for example `holoscan-cli==4.4.1` before the next SDK-aligned
`4.5.0` release.

Version alignment does not imply that the CLI selects, installs, or requires a
matching Holoscan SDK runtime or container base image. For container builds, the
base image can be set with the CLI when your component's Dockerfile is configured
with `FROM ${BASE_IMAGE}`, using any of the methods below:

1. Pass the image to the `--base-img` flag:

   ```bash
   holoscan build-container my_app --base-img nvcr.io/nvidia/clara-holoscan/holoscan:v4.4.0-cuda13
   ```

2. Set `HOLOSCAN_CLI_BASE_IMAGE` to an exact tagged or digested image. It is
   used without adding another tag:

   ```bash
   export HOLOSCAN_CLI_BASE_IMAGE=nvcr.io/nvidia/clara-holoscan/holoscan:v4.4.0-cuda13
   holoscan build-container my_app
   ```

3. Set `HOLOSCAN_CLI_BASE_IMAGE` to an image repository (no tag) and
   `HOLOSCAN_CLI_BASE_SDK_VERSION` to a Holoscan semantic version. The base image
   then resolves to
   `$HOLOSCAN_CLI_BASE_IMAGE:v$HOLOSCAN_CLI_BASE_SDK_VERSION-$CUDA_TAG`, with the
   CUDA tag chosen dynamically from your host environment:

   ```bash
   export HOLOSCAN_CLI_BASE_IMAGE=nvcr.io/nvidia/clara-holoscan/holoscan
   export HOLOSCAN_CLI_BASE_SDK_VERSION=4.4.0
   # Resolves to nvcr.io/nvidia/clara-holoscan/holoscan:v4.4.0-cuda13 on hosts with NVIDIA drivers >= 580
   holoscan build-container my_app
   ```

If none of these is configured, the CLI asks for a base image instead of
inferring one from its own package version.

Advanced wrappers can set `HOLOSCAN_CLI_BASE_IMAGE_FORMAT` with
`{base_image}`, `{sdk_version}`, and `{cuda_tag}`, or
`HOLOSCAN_CLI_DEFAULT_IMAGE_FORMAT` with `{container_prefix}`,
`{sdk_version}`, and `{cuda_tag}`. An explicit base-image format controls
composition; without one, tagged images and digests are exact while an
untagged environment repository uses the SDK/CUDA-derived tag.

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

See
[CONTRIBUTING.md](https://github.com/nvidia-holoscan/holoscan-cli/blob/main/CONTRIBUTING.md)
for details.
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
now drives the HoloHub-style source-project runner, so it no longer launches
packaged images. Developers that still rely on HAP/MAP packaging should pin both
`holoscan-cli<=4.2.0`, the last CLI release that shipped that interface, and
`holoscan<=4.2.0`, because the legacy package command depends on the artifacts
JSON manifest and was only tested with those SDK versions. Otherwise, migrate to
the Holoscan SDK packaging workflows directly. See
[issue #164](https://github.com/nvidia-holoscan/holoscan-cli/issues/164) for the
deprecation timeline.
