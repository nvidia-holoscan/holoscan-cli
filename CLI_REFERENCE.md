# Holoscan CLI reference

Use `holoscan` directly in a standalone Holoscan Module repository. HoloHub
and other repositories may provide wrappers that add their own defaults;
follow that repository's guidance when using a wrapper.

This reference describes the CLI 5.x command surface. Check
`holoscan version --json` and `holoscan <command> --help` for the installed
version. CLI versions do not select or guarantee a matching SDK version.

## Select a project and environment

Follow the [installation and standalone quick start](README.md#installation).
Inside a generated module, `uv run holoscan` uses its committed development
dependencies. With an activated pip environment, use `holoscan` directly.

The CLI discovers the project root from the current directory and its
ancestors. To select a different root, place the global option before the
command:

```bash
holoscan --project-root /path/to/holoscan-my-sensor list --json
```

See [configuration](CONFIGURATION.md) for root selection, project settings,
SDK discovery, environment variables, and option precedence.

### Standalone applications

An application can keep its Holoscan `metadata.json` directly in its project
directory, without an `applications/` parent or a Module descriptor:

```text
my_app/
├── metadata.json
├── CMakeLists.txt
└── ...
```

From `my_app/` or one of its child directories:

```bash
holoscan list --json
holoscan build my_app --local --dryrun --verbose
holoscan run my_app --local --dryrun --verbose
```

The project selector is the directory name (`my_app`), while `application.name`
remains its display name. The CLI preserves the selector when entering a
container whose workspace directory has a different name. Builds and runs
still require the application's build files, run configuration, and SDK.

Standalone discovery includes only the root `metadata.json`. Nested applications
retain their enclosing Module's context; use `--project-root` to select the
application explicitly.
See [metadata discovery](CONFIGURATION.md#metadata-discovery) for recognition
rules, file-size limits, and search-path overrides.

## Commands

| Command | Purpose |
| --- | --- |
| `create <name>` | Scaffold an external Holoscan Module or a selected project template. |
| `list` | Discover projects and their types. |
| `modes <project>` | Inspect a project's supported modes. |
| `build [project] [mode]` | Configure and build a project. |
| `run <project> [mode]` | Build and run an application. |
| `build-container [project] [mode]` | Build its development image. |
| `run-container [project] [mode]` | Launch its development container. |
| `test [project]` | Run the selected CTest driver. |
| `install [project] [mode]` | Build and install through the project's install rules. |
| `package [project]` | Build Holoscan Module DEB and/or wheel artifacts. |
| `lint [path]` | Run the project's pre-commit hooks. |
| `setup` | Install development dependencies or selected setup scripts. |
| `clear-cache` | Remove selected build, data, or install caches. |
| `version`, `env-info`, `env-check`, `status` | Inspect CLI version, environment, capabilities, and project state. |
| `autocompletion_list` | Print targets for shell completion. |

Read command help for accepted options and required project inputs. Metadata
and the selected mode determine available applications and their behavior.

## Preview and execution

| Commands | Preview flags |
| --- | --- |
| `build`, `run`, `build-container`, `run-container`, `test`, `install`, `package` | `--dryrun --verbose` |
| `create`, `lint`, `setup`, `clear-cache` | `--dryrun` |
| `list`, `modes`, `version`, `env-info`, `env-check`, `status` | Read-only; no preview needed. |

Keep the same project, mode, language, image, and effect-bearing options
between preview and execution. A dry run is not a sandbox; see the
[project trust model](README.md#project-trust-model).

```bash
uv run holoscan build my_sensor_pipeline --dryrun --verbose
uv run holoscan build my_sensor_pipeline --verbose
```

Build and run use containers by default. `--local` selects native execution;
`--no-docker-build` reuses an existing image. `run --no-local-build` also skips
building the application, so use it only when the required artifacts exist.

For dash-leading values, use `=`, for example `--configure-args=-DFEATURE=ON`.
`--build-with` replaces the mode's operator selection; `--configure-args`
appends to its CMake options. Docker argument layers are described in
[configuration](CONFIGURATION.md).

`build --target <name>` configures the project normally, then builds only that
CMake target and its dependencies. Repeat `--target` to select multiple targets;
omit it to build the default target. For example:

```bash
holoscan build my_app --target my_target
```

`build` and `test` pass the selected language to CMake: `build` uses
`--language` or the project's metadata, and `test` uses `--language`. In a
Module, or for a Module selected in a HoloHub checkout, these options start
with `module.name` in upper case, with each character other than a letter or
digit replaced by `_`. For `holoscan-my-sensor`, `--language python` passes
`-DHOLOSCAN_MY_SENSOR_BUILD_PYTHON=ON -DHOLOSCAN_MY_SENSOR_BUILD_CPP=OFF`.
HoloHub projects read `HOLOHUB_BUILD_PYTHON` and `HOLOHUB_BUILD_CPP`. Modules
still receive these too, but should read their own names; a later release will
stop passing the HoloHub names to Modules. Other CMake variables keep their
HoloHub names: the bundled CMake helpers read `HOLOHUB_BUILD_OPERATORS` (from
`--build-with`), `HOLOHUB_PYTHON_MODULE_OUT_DIR`, and
`HOLOHUB_EXT_OP_<op>_PROVIDER`, and HoloHub applications read the data folder
from `HOLOHUB_DATA_DIR`.

Only `run-container` accepts a command after `--`. With its normal shell
entrypoint, quote a multi-argument or compound command as one argument:

```bash
uv run holoscan run-container -- "holoscan list --json"
```

## Profile an application

Add `--nsys-profile` to `run` to launch the application under Nsight Systems
after its build completes. This works in a container or with `--local`:

```bash
holoscan run my_app --nsys-profile --dryrun --verbose
holoscan run my_app --nsys-profile
```

By default, the CLI invokes `nsys profile --trace=cuda,vulkan,nvtx,osrt`.
Use `--nsys-args` to replace that option list. For NVTX-only tracing without
CPU sampling, backtraces, or context-switch collection:

```bash
holoscan run my_app \
  --nsys-args='--trace=nvtx --sample=none --backtrace=none --cpuctxsw=none -o profile' \
  --dryrun --verbose
```

Remove `--dryrun` to capture. `--nsys-args` implies `--nsys-profile`; its
value is split using shell-style quoting, without shell expansion. An empty
value (`--nsys-args=''`) supplies no profile options, using Nsight's defaults.
Use `--run-args` separately for application arguments.

The same options work with downstream wrappers such as `./holohub` and
`./isaac_os` once their host and container CLI versions include this feature.
The application's mode, environment, arguments, and working directory are
preserved. Relative output paths resolve from that working directory; for
container runs, use a writable mounted path to keep reports on the host.
Wait for Nsight to finish writing the `.nsys-rep` file after stopping the app.
Add `--force-overwrite=true` to `--nsys-args` only when replacing an existing
capture is intended.

Nsight Systems must be installed in the execution environment. Alternatively,
`--nsys-location /path/to/nsight-systems` mounts a host installation into the
container at `/opt/nvidia/nsys-host`; an `nsys` already on the container's
`PATH` takes precedence. Nsight reports permission limitations for the
requested collectors; the CLI does not change host perf settings.

`run-container --nsys-profile` only adds profiling permissions
(`--cap-add=SYS_ADMIN`). It does not start profiling or accept `--nsys-args`;
launch `nsys profile` yourself for commands run directly in that container.

## Create a module

`holoscan create my-sensor` uses the packaged module template and creates
`holoscan-my-sensor` under the current directory. `--directory` changes the
output parent. A selected application template can have different defaults.

Choose the SDK minimum explicitly with `--context holoscan_version=<version>`.
The packaged 5.0.0a1 template contains a `4.5.0` fallback; a configured base SDK
version overrides it, and explicit context values take precedence. See
[template defaults](src/holoscan_cli/templates/module/cookiecutter.json) and
[creation](src/holoscan_cli/commands/create.py). The generated module's
`README.md` and `DEVELOPER.md` document its implementation and consumer flow.

## Test, install, and package

`test` runs the selected CTest script. In a standalone module, use its documented
repository-wide tests and focused CTest/pytest targets. A module name in a
multi-project repository does not imply module-scoped test coverage. Inspect
the driver's build-directory cleanup before testing an existing workspace.

`install --dev` installs hooks from an already built module into the CLI's
Python environment. Inspect `env-info --json`, name the module, and select the
build directory explicitly when multiple builds exist. After consumer testing,
use `install <module> --dev --uninstall` in the same environment and verify the
hooks are removed. Omitting the module can affect multiple hooks.

`package <module> --pkg-generator DEB,WHEEL` builds distribution artifacts.
Inspect their metadata and payload, then test installation in a clean consumer.
A DEB needs its declared SDK dependency in the package database; a Python import
or unpacked archive does not prove that dependency is satisfied.

## Diagnostics and cleanup

`version`, `list`, `modes`, `env-info`, `env-check`, and `status` accept `--json`.
Parse stdout separately from stderr, tolerate additive JSON fields, and retain
`env-check` output even when it exits nonzero. Check whether the failed
capability is required for the intended operation.

`clear-cache` without a scope selects all supported caches. Preview a narrow
scope, such as `clear-cache --build --dryrun`, and inspect the resolved paths
before deleting data. Lint hooks can also modify source files; review their
changes before committing.
