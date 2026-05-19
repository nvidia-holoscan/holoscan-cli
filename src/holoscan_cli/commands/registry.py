# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Single source of truth for the holoscan CLI subcommand surface.

Two layers of the package consume this registry:

* ``holoscan_cli.__main__`` builds a thin top-level parser that lists every
  source-project command for ``holoscan --help`` and forwards them to the
  full project CLI without consuming subcommand-specific flags.
* ``holoscan_cli.cli`` builds the real argparse subparsers by calling
  :func:`register_all`, which delegates to the ``register_<command>_parser``
  function in each per-command module under :mod:`holoscan_cli.commands`.

Both consumers read :data:`PROJECT_COMMANDS` here so that adding, renaming,
or removing a subcommand only requires editing one list (and adding/removing
the matching entry in :func:`register_all`). Each entry pairs a public
command name with two help strings — ``short_help`` for the top-level
``holoscan --help`` listing, and ``help`` for the per-subcommand
``holoscan <cmd> --help`` title.

The native ``version`` command is intentionally not included; it is the only
command implemented by ``holoscan_cli.__main__`` itself.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CommandSpec:
    """Stable metadata for a single ``holoscan`` source-project subcommand.

    Two help strings are kept on each spec because the top-level
    ``holoscan --help`` and the per-subcommand ``holoscan <cmd> --help``
    historically used different phrasings:

    * ``short_help`` is the source-project description that appears in the
      top-level command list rendered by ``holoscan_cli.__main__``.
    * ``help`` is the per-subcommand help title that appears when the user
      runs ``holoscan <cmd> --help`` and is also what argparse renders next
      to the subcommand name in the full parser's command listing.

    Centralising both strings here keeps the two help surfaces in sync.
    """

    name: str
    short_help: str
    help: str
    group: str  # "project" | "container" | "info" | "workspace"


# Ordered for predictable iteration; ``holoscan --help`` re-sorts alphabetically.
PROJECT_COMMANDS: tuple[CommandSpec, ...] = (
    # workspace-touching commands
    CommandSpec(
        "create",
        short_help="create a new source project from a template",
        help="Create a new Holoscan application",
        group="workspace",
    ),
    CommandSpec(
        "lint",
        short_help="run source-project linting tools",
        help="Run repository linting via pre-commit",
        group="workspace",
    ),
    CommandSpec(
        "setup",
        short_help="install source-project development dependencies",
        help="Install HoloHub recommended packages for development.",
        group="workspace",
    ),
    CommandSpec(
        "clear-cache",
        short_help="clear source-project build, data, and install caches",
        help="Clear cache folders",
        group="workspace",
    ),
    # container commands
    CommandSpec(
        "build-container",
        short_help="build a source-project development container",
        help="Build the development container",
        group="container",
    ),
    CommandSpec(
        "run-container",
        short_help="launch a source-project development container",
        help="Build and launch the development container",
        group="container",
    ),
    # project actions
    CommandSpec(
        "build",
        short_help="build a source project",
        help="Build a project",
        group="project",
    ),
    CommandSpec(
        "run",
        short_help="build and run a source project",
        help="Build and run a project",
        group="project",
    ),
    CommandSpec(
        "install",
        short_help="install a built source project",
        help="Install a project",
        group="project",
    ),
    CommandSpec(
        "test",
        short_help="test a source project",
        help="Test a project",
        group="project",
    ),
    # discovery / info
    CommandSpec(
        "list",
        short_help="list discovered source projects",
        help="List all available targets",
        group="info",
    ),
    CommandSpec(
        "modes",
        short_help="list modes for a source project",
        help="List available modes for an application",
        group="info",
    ),
    CommandSpec(
        "autocompletion_list",
        short_help="list source-project names for shell completion",
        help="List targets for autocompletion",
        group="info",
    ),
    CommandSpec(
        "env-info",
        short_help="display source-project environment information",
        help="Display environment debugging information",
        group="info",
    ),
    CommandSpec(
        "status",
        short_help="show source-project environment and build status",
        help="Show environment, container, and build status",
        group="info",
    ),
    CommandSpec(
        "env-check",
        short_help="run source-project environment health checks",
        help="Run system checks (GPU, CUDA, Docker, Holoscan SDK, disk, display, devices)",
        group="info",
    ),
)


# Lookup helpers -----------------------------------------------------------

PROJECT_COMMANDS_BY_NAME: dict[str, CommandSpec] = {spec.name: spec for spec in PROJECT_COMMANDS}


def project_command_names() -> list[str]:
    """Return every source-project command name, ordered as registered."""
    return [spec.name for spec in PROJECT_COMMANDS]


def project_command_help() -> dict[str, str]:
    """Return a mapping of command name to top-level (``short_help``) text.

    This is what :mod:`holoscan_cli.__main__` uses to render
    ``holoscan --help`` so the top-level surface lists the same commands the
    full project CLI accepts.
    """
    return {spec.name: spec.short_help for spec in PROJECT_COMMANDS}


def help_for(command: str) -> str:
    """Return the per-subcommand ``help`` string for ``command``.

    Raises :class:`KeyError` if ``command`` is not registered. The full parser
    in :mod:`holoscan_cli.cli` uses this so subparser help strings cannot
    drift from the registry.
    """
    return PROJECT_COMMANDS_BY_NAME[command].help


def commands_in_group(group: str) -> Iterable[CommandSpec]:
    """Yield every command registered under ``group``."""
    return (spec for spec in PROJECT_COMMANDS if spec.group == group)


# Parser wiring ------------------------------------------------------------
#
# Each entry in this table maps a registered command name to the
# ``register_<command>_parser`` function in its per-command module. The
# function receives ``(cli, subparsers, **kwargs)``; ``kwargs`` is the
# subset of shared parents (``container_build``, ``container_run``) that
# command needs for argparse ``parents=[...]``. Keeping the table here
# means :class:`holoscan_cli.cli.HoloscanCLI` only needs to call
# :func:`register_all` and never has to know which command lives in which
# module.


def register_all(
    cli,
    subparsers: argparse._SubParsersAction,
    *,
    container_build: argparse.ArgumentParser,
    container_run: argparse.ArgumentParser,
) -> dict[str, argparse.ArgumentParser]:
    """Register every source-project subcommand on ``subparsers``.

    Returns a ``{command_name: subparser}`` mapping that the caller stores
    on ``HoloscanCLI.subparsers`` for error reporting (Levenshtein-based
    suggestions on typos and per-command help hints).
    """
    # Imported lazily so simple ``from holoscan_cli.commands import registry``
    # consumers (e.g. ``__main__.py``) don't pull in every command module
    # just to read :data:`PROJECT_COMMANDS`.
    from holoscan_cli.commands import (
        build,
        clear_cache,
        containers,
        create,
        info,
        install,
        lint,
        run,
        setup_cmd,
        test_cmd,
    )

    registered: dict[str, argparse.ArgumentParser] = {}

    def add(register_fn, name: str, **kwargs) -> None:
        registered[name] = register_fn(cli, subparsers, **kwargs)

    # Workspace-touching commands.
    add(create.register_create_parser, "create")
    add(lint.register_lint_parser, "lint")
    add(setup_cmd.register_setup_parser, "setup")
    add(clear_cache.register_clear_cache_parser, "clear-cache")

    # Container build/run commands (both live in commands/containers.py).
    add(
        containers.register_build_container_parser,
        "build-container",
        container_build=container_build,
    )
    add(
        containers.register_run_container_parser,
        "run-container",
        container_build=container_build,
        container_run=container_run,
    )

    # Project actions (build/run/install share the container build+run parents,
    # test only takes container_build because it never forwards docker run flags).
    for register_fn, name in (
        (build.register_build_parser, "build"),
        (run.register_run_parser, "run"),
        (install.register_install_parser, "install"),
    ):
        add(register_fn, name, container_build=container_build, container_run=container_run)
    add(test_cmd.register_test_parser, "test", container_build=container_build)

    # Discovery / info commands (all six live in commands/info.py).
    for register_fn, name in (
        (info.register_list_parser, "list"),
        (info.register_modes_parser, "modes"),
        (info.register_autocompletion_list_parser, "autocompletion_list"),
        (info.register_env_info_parser, "env-info"),
        (info.register_status_parser, "status"),
        (info.register_env_check_parser, "env-check"),
    ):
        add(register_fn, name)

    return registered
