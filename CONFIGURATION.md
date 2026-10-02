# Configuring Holoscan CLI

Run `holoscan` inside your project, or select one explicitly:

```bash
holoscan --project-root /path/to/project list
```

Root selection uses `--project-root`, then `HOLOSCAN_CLI_ROOT`, then discovery
from the current directory and its ancestors. The root option goes before the command.

See [README.md](README.md) for installation and the
[CLI reference](CLI_REFERENCE.md) for commands and diagnostics.

## Metadata discovery

- HoloHub-style projects search component directories such as `applications/` and `operators/`.
- Standalone Modules also include their root `metadata.json`.
- Standalone applications use only their root `metadata.json`, not descendant copies.

Moving into an application's language or component folders keeps the owning
project context, even with app-local `operators/` or `modules/`. A nested Module
can establish its own context. Use `--project-root` to select just an application
inside a Module.

Standalone recognition requires an `application` object as the only recognized
project type, a non-empty `name`, and either `holoscan_sdk.minimum_required_version`
or `holoscan_sdk.required_versions` (a non-empty string or list of non-empty
strings). Incomplete or unrelated descriptors are ignored; this is not full
schema validation and needs no optional dependencies.

Use `HOLOSCAN_CLI_SEARCH_PATH` for custom directories such as `examples/`.
It replaces defaults with comma-separated directories or exact `metadata.json`
paths, relative to the root; an empty value uses conventional directories.
`HOLOSCAN_CLI_APP_NAME` overrides the application's directory-based selector and
is forwarded automatically to preserve it across renamed container mounts.

Discovery and dependency parsing (including `modules/module-sites.json`) accept
only regular, non-symlink files up to 1 MiB. Reads stay bounded if a file grows;
FIFOs are rejected without waiting for a writer. Read and JSON decoding errors,
including excessive nesting, are reported.

## Module defaults

Module `metadata.json` supplies the identity, SDK requirements, Dockerfile,
and modes. Other settings resolve in this order, highest priority first:

| Setting | Precedence |
| --- | --- |
| Architecture | `HOLOSCAN_CLI_TARGET_ARCH` → host |
| CUDA | `--cuda` → `HOLOSCAN_CLI_DEFAULT_CUDA_VERSION` → `tool.holoscan.cuda` → host detection |
| CTest script | `--ctest-script` → `HOLOSCAN_CLI_CTEST_SCRIPT` → `tool.holoscan.ctest-script` → bundled script |
| Execution | `--local` → `HOLOSCAN_CLI_BUILD_LOCAL` → selected mode → container |
| Build type | `--build-type` → `CMAKE_BUILD_TYPE` → selected mode → release |

SDK selection uses `--local-sdk-root`, `HOLOSCAN_SDK_ROOT`, the mounted
`/workspace/holoscan-sdk` for local container builds, a nearby `holoscan-sdk`,
then `/opt/nvidia/holoscan`. Nearby installs take priority over configured source
builds; both `install-cu13-x86_64` and `install-x86_64` layouts are supported.
An invalid `HOLOSCAN_SDK_ROOT` warns without falling back.

To use a local SDK installation with an existing compatible development image:

```bash
export HOLOSCAN_SDK_ROOT=/path/to/holoscan-sdk/install-x86_64
holoscan build my_app --img my-sdk-dev:local --no-docker-build
```

The SDK mounts at `/workspace/holoscan-sdk`; the image provides tools and runtime
dependencies. Python apps also need the SDK's Python bindings. Add `--local` to
run on the host. `holoscan test` adds the SDK to `CMAKE_PREFIX_PATH`, preserving
existing prefixes unless explicit CMake options override them.

### Automatic SDK base images

Set `holoscan_sdk.required_versions` in `metadata.json` to select the newest
published stable SDK image matching your requirements and CUDA/GPU variant:

```json
{
  "holoscan_sdk": {
    "required_versions": ">=4.1,<5",
    "tested_versions": ["4.6.0"]
  }
}
```

Use [Python version specifiers](https://packaging.python.org/en/latest/specifications/version-specifiers/).
A bare version or wildcard is shorthand for `==`. Commas combine conditions
with **AND**; list entries are alternatives (**OR**).

| `required_versions` | Matching versions |
| --- | --- |
| `">=4.1,<5"` | At least 4.1, below 5. |
| `">4.1,<=4.6"` | Above 4.1, through 4.6 inclusive. |
| `"4.1.*"` | Any 4.1 patch release. |
| `["4.1.0", "4.3.*"]` | Exactly 4.1.0 or any 4.3 patch release. |
| `"~=4.1.0,!=4.1.2"` | Compatible 4.1 releases, excluding 4.1.2. |

`required_versions` replaces `minimum_required_version` in the same SDK object
when both are present. The owning Module's requirements also apply; a legacy
minimum in another object becomes an inclusive lower bound during selection.
`tested_versions` records testing history and does not restrict selection.

Selection queries NGC and caches its tags for the current CLI process. Invalid
specifiers, unavailable registry access, or no matching image produce an error.
`holoscan lint` validates specifier syntax. Install the CLI normally to include
its `packaging` dependency, which interprets the version expressions.

Existing metadata without `required_versions` keeps its original defaults and
does not query the registry. `--base-img`, `HOLOSCAN_CLI_BASE_SDK_VERSION`,
configured base images, and base image format overrides retain their precedence
and skip automatic selection. These remain available for pinned or offline use.

## `pyproject.toml` settings

Standalone Modules can set defaults in `[tool.holoscan]`. Other TOML tables are
unrelated to CLI configuration. Supported keys:

| Key | Type / default | Purpose |
| --- | --- | --- |
| `cuda` | Integer / host detection | CUDA major version. |
| `ctest-script` | Relative path / bundled script | CTest driver; must stay within the Module root. |
| `repo-prefix` | String / Module metadata | Repository naming prefix. |
| `container-prefix` | String / repository prefix | Docker image prefix. |
| `workspace-name` | String / repository prefix | Directory under `/workspace`. |
| `forward-env` | String array / `[]` | Host variable names to forward into containers. |
| `docker-build-args` | Token array / `[]` | Extra Docker build options. |
| `docker-run-args` | Token array / `[]` | Extra Docker run options. |
| `base-images` | Table / absent | Exact image references keyed by `x86_64` or `aarch64`. |

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

- Naming values use lowercase letters, digits, `.`, `_`, or `-`, starting with
  a letter or digit. `HOLOSCAN_CLI_REPO_PREFIX`, `HOLOSCAN_CLI_CONTAINER_PREFIX`,
  and `HOLOSCAN_CLI_WORKSPACE_NAME` override their project settings.
- Docker arrays contain one non-empty token per element. Layers are appended:
  project → mode → `HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS` or
  `HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS` → command line. Later options win only
  where Docker supports that behavior.
- `base-images`, when present, must include the selected architecture. References
  are used unchanged and cannot be empty or contain whitespace. `--base-img`, then
  `HOLOSCAN_CLI_BASE_IMAGE`, take precedence.
- `forward-env` accepts valid host variable names, never values. Existing host
  values are inherited without appearing on the Docker command line. Names combine
  with `HOLOSCAN_CLI_FORWARD_ENV` and repeated `--forward-env NAME` options.
  CLI-owned names are forbidden: `NVIDIA_DRIVER_CAPABILITIES`,
  `NVIDIA_VISIBLE_DEVICES`, `HOME`, `CUPY_CACHE_DIR`, `HOLOSCAN_CLI_BUILD_LOCAL`.

Unknown Holoscan keys are rejected. Keep credentials and machine-specific paths
out of project configuration.

## Command options

```bash
holoscan build my_app --local --build-type debug
holoscan build my_app --cuda 13 --base-img registry.example.com/sdk:reviewed
```

- `--build-args` adds Docker build options.
- `--docker-opts`, `--configure-args`, and `--forward-env NAME` are repeatable and additive.
- `--build-with` replaces mode operator dependencies; `--build-with=` selects none.

Add `--dryrun` to preview lifecycle commands and resolved settings with their
sources. Docker/CMake option values and forwarded environment values stay hidden.
See [preview and execution](CLI_REFERENCE.md#preview-and-execution) for precautions.
