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

Only `run-container` accepts a command after `--`. With its normal shell
entrypoint, quote a multi-argument or compound command as one argument:

```bash
uv run holoscan run-container -- "holoscan list --json"
```

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
