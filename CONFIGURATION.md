# Configuring Holoscan CLI

For installation and a standalone walkthrough, see [README.md](README.md).
For command behavior, previews, and diagnostics, see the
[CLI reference](CLI_REFERENCE.md).

Run `holoscan` inside a source project. To select another project, put the
global option before the command:

```bash
holoscan --project-root /path/to/module list
```

The root is selected from `--project-root`, `HOLOSCAN_CLI_ROOT`, then the current
directory and its ancestors.

## Metadata discovery

HoloHub-style roots search conventional component directories such as
`applications/` and `operators/`. Standalone Modules also include their root
`metadata.json`. The existing root-selection rules are unchanged: after checking
for a conventional source layout, discovery falls back to the nearest ancestor
with a `metadata.json`. An application descriptor at that selected root enables
standalone discovery. `--project-root` and `HOLOSCAN_CLI_ROOT` select a root
explicitly.

Application recognition requires a JSON object with `application` as its only
recognized project-type key, an object-valued `application`, and non-empty
strings for `application.name` and
`application.holoscan_sdk.minimum_required_version`. These are lightweight
recognition checks, not full JSON Schema validation; discovery needs no optional
creation dependencies. Unrelated or incomplete application descriptors are
ignored. Unreadable or malformed metadata produces a diagnostic.

Discovery and build-time Module dependency parsing read only regular,
non-symlink metadata files of at most 1 MiB, including `modules/module-sites.json`.
The read itself is bounded even if a file grows after its size check.
Special files such as FIFOs are rejected without waiting for a writer; oversized
files and JSON nesting that exceeds the parser's limit are also rejected.

Only the application's root `metadata.json` is added, so build directories,
dependency copies, and other descendants are not recursively discovered.
`HOLOSCAN_CLI_SEARCH_PATH` replaces the default search paths with comma-separated
directories or exact `metadata.json` files. Relative paths resolve from the
selected root. An explicitly empty value retains the conventional-directory
search. `HOLOSCAN_CLI_APP_NAME` overrides the standalone application's directory
name as its project selector; the CLI forwards this value automatically to
preserve the host selector across a renamed container mount.

## Module defaults

For standalone Modules, `metadata.json` supplies the identity, minimum SDK
version, Dockerfile, and modes. The CLI otherwise uses these defaults:

- Target architecture: `HOLOSCAN_CLI_TARGET_ARCH`, then the host architecture.
- CUDA: `--cuda`, `HOLOSCAN_CLI_DEFAULT_CUDA_VERSION`, `tool.holoscan.cuda`,
  then host detection.
- CTest script: `--ctest-script`, `HOLOSCAN_CLI_CTEST_SCRIPT`,
  `tool.holoscan.ctest-script`, then the bundled script.
- Execution: `--local`, `HOLOSCAN_CLI_BUILD_LOCAL`, the selected mode, then a container.
- Build type: `--build-type`, `CMAKE_BUILD_TYPE`, the selected mode, then release.
- Local SDK: `--local-sdk-root`, `HOLOSCAN_SDK_ROOT`, `/workspace/holoscan-sdk`
  for local container builds, a nearby `holoscan-sdk` install or configured source
  build supported by the SDK, then `/opt/nvidia/holoscan`. Both 4.x CUDA-qualified
  directories such as `install-cu13-x86_64` and 5.x architecture-only directories such as
  `install-x86_64` are supported; installs are preferred over builds. An invalid
  `HOLOSCAN_SDK_ROOT` warns and does not fall back.

`holoscan test` passes the selected SDK to CMake through `CMAKE_PREFIX_PATH`,
preserving existing environment prefixes; explicit CMake options can override it.

For a locally compiled HSDK 5, use its completed installation prefix. With a
compatible development image already built:

```bash
export HOLOSCAN_SDK_ROOT=/path/to/holoscan-sdk/install-x86_64
holoscan build my_app --img my-sdk-dev:local --no-docker-build
holoscan test my_app --img my-sdk-dev:local --no-docker-build
holoscan run my_app --img my-sdk-dev:local --no-docker-build
```

The CLI mounts the selected SDK at `/workspace/holoscan-sdk`; the image supplies
compatible build tools and runtime dependencies. Python applications also need
the SDK's Python bindings in that installation. Use `--local-sdk-root` to override
the selection for one command, or add `--local` to execute on the host.

## `pyproject.toml` settings

For a standalone Module, Holoscan CLI reads only the `[tool.holoscan]` table.
Other `pyproject.toml` tables belong to Python packaging and development tools.

These are all currently supported Holoscan CLI settings:

| TOML path | Type and default | Behavior |
| --- | --- | --- |
| `tool.holoscan.cuda` | Integer; default detected from the host | Module-wide CUDA major version. |
| `tool.holoscan.ctest-script` | Relative path; default is the bundled script | Module-specific CTest driver. |
| `tool.holoscan.repo-prefix` | String; default derived from Module metadata | Override the repository naming prefix. |
| `tool.holoscan.container-prefix` | String; default derived from the repository prefix | Override the Docker image prefix. |
| `tool.holoscan.workspace-name` | String; default is the repository prefix | Directory name under `/workspace` in containers. |
| `tool.holoscan.forward-env` | Array of strings; default `[]` | Names of host environment variables allowed into project containers. |
| `tool.holoscan.docker-build-args` | Array of non-empty string tokens; default `[]` | Module-wide Docker build options. |
| `tool.holoscan.docker-run-args` | Array of non-empty string tokens; default `[]` | Module-wide Docker run options. |
| `tool.holoscan.base-images` | Table; default absent | Exact base images selected by target architecture. Only the two keys below are accepted. |
| `tool.holoscan.base-images.x86_64` | String; no default | Base image used when the normalized target architecture is `x86_64`. |
| `tool.holoscan.base-images.aarch64` | String; no default | Base image used when the normalized target architecture is `aarch64`. |

For example:

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

`cuda` selects the Module-wide CUDA major.
`ctest-script` must stay within the Module and is resolved from its root.
Environment variables and command options override both project defaults.

Naming settings accept lowercase letters, digits, `.`, `_`, and `-`, starting
with a letter or digit. Their corresponding `HOLOSCAN_CLI_REPO_PREFIX`,
`HOLOSCAN_CLI_CONTAINER_PREFIX`, and `HOLOSCAN_CLI_WORKSPACE_NAME` environment
variables take precedence. Use `docker-run-args = ["--hostname=my-module"]`
to set a container hostname.

`forward-env` entries must be valid environment variable names. Values are
never stored in the file or placed on the Docker command line; Docker inherits
the value only when that name exists on the host. Project entries are additive
with `HOLOSCAN_CLI_FORWARD_ENV` and repeated `--forward-env NAME` options.
`NVIDIA_DRIVER_CAPABILITIES`, `NVIDIA_VISIBLE_DEVICES`, `HOME`,
`CUPY_CACHE_DIR`, and `HOLOSCAN_CLI_BUILD_LOCAL` are CLI-owned and cannot be
listed.

Each Docker argument array element is one command token. Arguments are composed
in this order: project, selected `metadata.json` mode, environment
(`HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS` or
`HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS`), then command line. Later options can
therefore override earlier ones when Docker uses last-option-wins behavior.

Each `base-images` value must be a non-empty image reference without whitespace
and is used exactly as written. If the table exists, it must contain an entry
for the selected target architecture. Provide both entries when the Module
supports both architectures. `--base-img` and an explicit
`HOLOSCAN_CLI_BASE_IMAGE` override the project value.

Unknown keys in either `[tool.holoscan]` or `[tool.holoscan.base-images]` are
rejected. No other Holoscan CLI `pyproject.toml` settings are currently
supported.

Do not put credentials or machine-specific paths in project configuration.

## Command options

```bash
holoscan build my_app --local --build-type debug
holoscan build my_app --cuda 13 --base-img registry.example.com/sdk:reviewed
```

`--build-args` adds Docker build options. `--docker-opts`, `--configure-args`,
and `--forward-env NAME` are repeatable and additive.

`--build-with` replaces the selected mode's operator dependencies; use
`--build-with=` to select none.

Add `--dryrun` to a lifecycle command to see the resolved configuration and commands
without executing them. Scalar values include their source. Docker and CMake options show
which layers configured them without exposing their values; forwarded environment entries
show names but not values.

For example, a container build using the project settings above reports a summary like:

```text
Effective configuration (opaque option values hidden):
  project root: /workspace/my-module (directory discovery)
  mode: release (project default)
  execution: container (built-in default)
  build type: Release (built-in default)
  CUDA: 13 (project (tool.holoscan.cuda))
  local SDK: none (container image)
  base image: registry.example.com/holoscan/sdk-build-x86_64:5.0.0-cuda13 (project (tool.holoscan.base-images))
  Docker build options: configured by project (values hidden)
  run image: holoscan-my-module:review (derived default)
  Docker run options: configured by project (values hidden)
  forward-env: IS_CI_BUILD (project)
  CMake configure options: none
```
