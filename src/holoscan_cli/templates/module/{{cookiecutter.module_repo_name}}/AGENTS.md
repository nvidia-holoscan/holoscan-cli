# AGENTS.md

Guidance for AI agents working on {{ cookiecutter.project_name }}, a Holoscan Module for Holoscan
SDK {{ cookiecutter.holoscan_version }} or later. [README.md](README.md) covers setup and usage, and
[DEVELOPER.md](DEVELOPER.md) covers the layout, build options, and metadata.

## Holoscan SDK 5

{% if cookiecutter.__python_bindings == 'yes' -%}
- This Module's operators are C++ and ship as a Debian package. `python/` exposes them to
  Python through the SDK operator registry; there are no operators implemented in Python and no wheel.
{%- else -%}
- This Module is C++ only and ships as a Debian package. It has no Python operators, bindings,
  pytest suite, or wheel.
{%- endif %}
- Holoscan SDK 5 changed the operator and application APIs, and most published Holoscan examples still use
  the 4.x API. Follow the code in this repository and the API cheat sheet in DEVELOPER.md:
  - Operators derive from `holoscan::Operator<>` (or `holoscan::Operator<ParamsStruct>`), declare
    `holoscan::Input<T>` and `holoscan::Output<T>` members, and bind them in `setup()`.
  - `compute(holoscan::ExecutionContext&)` returns `holoscan::expected<void, holoscan::Error>`.
  - Applications build a `holoscan::Graph` with `graph.op<Op>(...)` and
    `graph.add_flow(a->out, b->in)`, call `holoscan::compile()`, check `plan.ok()`, and then call
    `holoscan::run()` or `holoscan::run_async()`. Print `plan.json()` to see why a graph failed to
    compile.
  - An operator with no inputs needs a contract such as `OnClock`, and the graph needs a default
    clock.
- The example application stops after a fixed number of results. Keep it finite.
- The tests run the graph on a `SyntheticClock`. Advancing the clock does not wait for the work to
  finish, so wait for each expected result and stop the run on every exit path.

## Commands

Install the CLI version pinned in `requirements-cli.txt` (see README.md), or prefix commands with
`uv run`. Build, run, test, and package commands run in the development container unless you pass
`--local`.

| Task | Command |
| --- | --- |
| Build the example | `holoscan build {{ cookiecutter.module_slug }}_pipeline{% if cookiecutter.__python_bindings == 'yes' %} --language cpp{% endif %}` |
| Run the example | `holoscan run {{ cookiecutter.module_slug }}_pipeline{% if cookiecutter.__python_bindings == 'yes' %} --language cpp{% endif %}` |
{%- if cookiecutter.__python_bindings == 'yes' %}
| Run the Python example | `holoscan run {{ cookiecutter.module_slug }}_pipeline --language python` |
{%- endif %}
| Run the tests | `holoscan test` |
| Lint | `holoscan lint` |
| Build the Debian package | `holoscan package {{ cookiecutter.module_repo_name }} --pkg-generator DEB` |
| List projects and check the host | `holoscan list --json`, `holoscan env-check --json` |

- `holoscan lint` runs the hooks in `.pre-commit-config.yaml` and fixes some files in place; review
  those changes. If pre-commit is missing, `holoscan lint --install-dependencies` installs it into
  the active environment.
- Without a GPU, add `--docker-opts="--runtime=runc"` to container commands so Docker does not use
  the NVIDIA runtime. `holoscan env-check` reports the missing GPU as a failed check.
- With a compatible SDK on the host, add `--local` and set
  `HOLOSCAN_CLI_BUILD_PARENT_DIR="$PWD/build-native"` so native output stays apart from container
  output. Select the SDK with `--local-sdk-root` or `HOLOSCAN_SDK_ROOT`.
- To build without the CLI, use the CMake commands in DEVELOPER.md.

A change is done when `holoscan lint`, the build, and `holoscan test` pass.

## Files that change together

- CLI version: `requirements-cli.txt`, `pyproject.toml`, and `.pre-commit-config.yaml`.
- Module version: `CMakeLists.txt`, `pyproject.toml`, and the Module, operator, and application
  `metadata.json` files.
- SDK version and image: `Dockerfile`, `pyproject.toml`, `.github/workflows/ci.yml`, the Module,
  operator, and application `metadata.json` files, and
  `pkg/{{ cookiecutter.module_repo_name }}/CMakeLists.txt`.
- Operator ports or parameters: the operator's `metadata.json`, the tests, and the operator table in
  README.md.
- Third-party dependencies: `NOTICE`, which lists each one with its version and license.

`cmake/` holds CMake helpers that `holoscan create` copied from the CLI. They belong to this Module,
and you can edit them. Upgrading the CLI does not update them; update them by hand if needed.

## Boundaries

- **Always** preview commands that build, run, test, or package with `--dryrun --verbose`, using the
  options you intend to run. Read-only commands (`version`, `list`, `modes`, `env-info`,
  `env-check`, `status`) need no preview.
- **Always** run `holoscan lint` and `holoscan test` before committing.
- **Ask first** before changing the SDK version, base images, or CLI pin, and before renaming the
  Module, its namespace, package, or operators.
- **Ask first** before running anything that needs `sudo` or changes the host, such as `apt` or
  installing the Debian package.
{% if cookiecutter.__python_bindings == 'yes' -%}
- Register every new operator in `python/_{{ cookiecutter.module_slug }}.cpp` and cover it in `tests/python`.
- **Never** add Python-implemented operators or wheel packaging.
{%- else -%}
- **Never** add Python operators, bindings, pytest suites, or wheel packaging.
{%- endif %}
- **Never** store secrets or machine-specific paths in `pyproject.toml` or `metadata.json`.
- **Never** pin a dependency on another Module to a tag or branch; use a full commit SHA.
- **Never** delete `build/`, `build-native/`, or `install/` directories without asking.
