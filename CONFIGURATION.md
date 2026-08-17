# Configuring Holoscan CLI

Most standalone Module projects need only a small `pyproject.toml` section.
Put shared defaults there, use environment variables for machine-specific
values, and use command options for one-off choices. HoloHub-style source trees
continue to use their component metadata and environment settings.

When the same setting appears in several places, the order is:

```text
command line > environment > selected mode > pyproject.toml > CLI default
```

## A good starting point

```toml
[tool.holoscan]
schema-version = 1
build-type = "Release"
cuda = 13
forward-env = ["IS_CI_BUILD"]

[tool.holoscan.sdk]
version = "5.0.0"
search = ["../holoscan-sdk/install-{arch}"]
allow-parent-search = true
mount-read-only = true

[tool.holoscan.sdk.base-images]
x86_64 = "registry.example.com/holoscan/sdk-build-x86_64:5.0.0-cuda13"
aarch64 = "registry.example.com/holoscan/sdk-build-aarch64:5.0.0-cuda13"
```

Keep absolute SDK paths and credentials out of this file. On each development
machine, select an SDK installation or its parent directory with:

```bash
export HOLOSCAN_SDK_ROOT=/opt/nvidia/holoscan
# or for one command
holoscan build my_app --local-sdk-root /opt/nvidia/holoscan
```

If `sdk.search` finds an installation, the CLI uses it for local builds and
mounts it into containers. Its Python package takes priority over the SDK copy
inside the image. SDK-root selection does not change the base image; configure
the local SDK and container image independently.

## One-command choices

Use command options when experimenting or overriding a project default:

```bash
holoscan build my_app --build-type debug --cuda 13
holoscan build my_app --base-img registry.example.com/sdk:reviewed
holoscan run my_app --container --no-docker-build
holoscan run my_app dev  # select a metadata mode named "dev"
```

`--base-img` is used exactly as written. A tagged or digested
`HOLOSCAN_CLI_BASE_IMAGE` is also exact. An untagged environment image repository
is combined with the selected SDK version and CUDA tag when an SDK version is
configured; otherwise it is used as written. Images pinned under
`tool.holoscan.sdk.base-images` are exact architecture-specific choices.

## Adding Docker, CMake, and environment options

These settings add to lower project defaults:

- `--build-args` for Docker build options;
- repeatable `--docker-opts` for Docker run options;
- `--configure-args` for CMake options;
- repeated `--forward-env NAME` for host environment names.

For example, repeated Docker-run fragments keep their token boundaries and are
appended in the order written:

```bash
holoscan run my_app \
  --docker-opts='--network=host' \
  --docker-opts='--read-only'
```

Replace inherited Docker-run options in one operation, or omit the value to
clear them:

```bash
holoscan run my_app --replace-docker-opts='--network=none'
holoscan run my_app --replace-docker-opts
```

`--docker-opts="$EXTRA_OPTS"` always means append. If `EXTRA_OPTS` is empty,
it is a harmless no-op; it never clears project, mode, or wrapper options.
The older two-flag spelling, `--replace-docker-opts --docker-opts='...'`, is
also accepted.

The other additive surfaces use a reset plus their normal addition option:

```bash
holoscan build my_app \
  --replace-build-args \
  --build-args='--network=none'

holoscan build my_app \
  --replace-configure-args \
  --configure-args=-DFEATURE=ON
```

`--replace-forward-env` similarly clears the lower allowlist before repeated
`--forward-env NAME` additions. These resets affect configurable raw options,
not the CLI's generated safety and identity arguments.

To ignore a whole inherited additive layer for one command, use:

- `--no-project-config` for `[tool.holoscan]` Docker and forwarded-name vectors;
- `--no-mode-config` for the selected mode's Docker and CMake vectors;
- `--no-inherited-config` for project, mode, and environment vectors, including
  wrapper-provided Docker defaults.

Despite their short names, these switches affect only additive option vectors.
They do not disable project discovery, scalar settings such as `build-type`, the
mode command or environment, SDK/image selection, or CLI-generated invariants.

`--build-with` is intentionally different: it is a complete operator selection,
not an additive option. It replaces a mode's `build.depends`; use
`--build-with=` to select no optional operators.

Forward environment variables by name instead of putting secret values in raw
Docker arguments:

```bash
export API_TOKEN=...
holoscan run my_app --forward-env API_TOKEN
```

## See what was selected

Add `--verbose` to a lifecycle command. The report shows the project, mode,
build type, CUDA choice, SDK, images, and the contributing option layers.
Opaque Docker/CMake values and mode-environment values are hidden; only safe
source and contribution details are shown.

```bash
holoscan run my_app --verbose
```

The CLI validates paths and settings it can inspect. It cannot prove that an
arbitrary prebuilt image contains a compatible SDK/CUDA combination, so keep
fixed images aligned with the profile tested by your project.
