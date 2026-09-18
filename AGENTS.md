# Working on Holoscan CLI

This file guides agents contributing to this CLI repository. For using the CLI
in another project, read [README.md](README.md),
[CLI_REFERENCE.md](CLI_REFERENCE.md), and [CONFIGURATION.md](CONFIGURATION.md),
then follow that project's own guidance. Generated modules have their own
`README.md` and `DEVELOPER.md`.

## Implementation and documentation

- Commands and parser definitions live in `src/holoscan_cli/commands/`;
  dispatch and mode resolution live in `cli.py`.
- Project configuration and container behavior have separate modules. Preserve
  documented precedence and downstream wrapper compatibility when editing them.
- The module template, schemas, CMake helpers, and CTest scripts ship in the
  package. Check installed-wheel behavior when changing these resources.
- Keep user-facing command behavior in the CLI reference and configuration
  guide. Keep contributor setup and validation in `CONTRIBUTING.md`.
- Update relevant documentation when behavior changes. Do not infer SDK
  compatibility or image selection from the CLI version number.

## Validation

Follow [local development](CONTRIBUTING.md#local-development) for setup and
checks. Run `pre-commit run --all-files` before committing. Run the affected
unit tests for code changes; use the installed-wheel smoke test for packaging
or console-entry-point changes. Documentation-only changes need command/source
verification and lint, not unrelated GPU workloads.

Preserve unrelated work and inspect formatter changes before staging them.
Keep generated environments, caches, and build outputs out of commits. Preview
CLI operations where supported and keep the same effect-bearing arguments for
the real run. Do not treat a dry run as permission to execute project code or
change host configuration. Sign off commits with `git commit -s`.
