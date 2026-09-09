# Configuring Holoscan CLI

Run `holoscan` inside a source project. To select another project, put the
global option before the command:

```bash
holoscan --project-root /path/to/module list
```

The root is selected from `--project-root`, `HOLOSCAN_CLI_ROOT`, then the current
directory and its ancestors.

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
  build, then `/opt/nvidia/holoscan`. Both 4.x CUDA-qualified directories such as
  `install-cu13-x86_64` and 5.x architecture-only directories such as
  `install-x86_64` are supported; installs are preferred over builds. An invalid
  `HOLOSCAN_SDK_ROOT` warns and does not fall back.

## `pyproject.toml` settings

For a standalone Module, Holoscan CLI reads only the `[tool.holoscan]` table.
Other `pyproject.toml` tables belong to Python packaging and development tools.

These are all currently supported Holoscan CLI settings:

| TOML path | Type and default | Behavior |
| --- | --- | --- |
| `tool.holoscan.cuda` | Integer; default detected from the host | Module-wide CUDA major version. |
| `tool.holoscan.ctest-script` | Relative path; default is the bundled script | Module-specific CTest driver. |
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
