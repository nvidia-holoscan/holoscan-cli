# SPDX-FileCopyrightText: Copyright (c) 2023-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
import argparse
import json
import logging
import logging.config
import os
import sys
from pathlib import Path
from typing import Optional, Union

from .commands.registry import project_command_help
from .project_context import (
    ProjectContextError,
    activate_project_context,
    discover_project_context,
)

logging.getLogger("docker.api.build").setLevel(logging.WARNING)
logging.getLogger("docker.auth").setLevel(logging.WARNING)
logging.getLogger("docker.utils.config").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG_CONFIG_FILENAME = "logging.json"

# Dispatch contract for the source-project CLI:
# source-project commands listed in PROJECT_COMMANDS are forwarded to the
# project CLI before argparse consumes their command-specific flags. The
# placeholder subparsers below exist only so top-level `--help` enumerates
# the public command surface. `version` is the only native top-level command.
#
# PROJECT_COMMANDS is derived from holoscan_cli.commands.registry so the
# top-level help surface, the dispatch allow-list, and the per-command
# argparse help in holoscan_cli.cli cannot drift apart.
PROJECT_COMMANDS = project_command_help()

LOG_LEVELS = ["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]

# Subcommands removed since holoscan v4.3.0. Mapped to a one-line note
# explaining what each one did, so users typing the old command get a specific
# message instead of argparse's generic "invalid choice". Note: the pre-4.3.0
# `holoscan run` was the HAP/MAP packaged-image runner; since v4.3.0 the same
# name is reused for the HoloHub-style source-project runner, so it is not listed here.
REMOVED_COMMANDS: dict[str, str] = {
    "nics": "the HAP NIC diagnostic command",
}

REMOVED_COMMAND_FOOTER = (
    "Removed HAP/MAP commands are not available since holoscan v4.3.0. Pin "
    "holoscan-cli<=4.2.0 and holoscan<=4.2.0 if you still need that legacy command surface."
)


class DispatchUsageError(ValueError):
    """A top-level option is invalid or misplaced."""


# Top-level options consumed before the subcommand, mapped to the value each one
# expects. Used for both parsing and the "requires a ..." usage errors.
TOP_LEVEL_OPTIONS = {
    "-l": "logging level",
    "--log-level": "logging level",
    "--project-root": "directory path",
}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv
    argv = list(argv)  # copy argv for manipulation to avoid side-effects

    # We have intentionally not set the default using `default="INFO"` here so that the default
    # value from here doesn't override the value in `LOG_CONFIG_FILENAME` unless the user intends
    # to do so. If the user doesn't use this flag to set log level, this argument is set to "None"
    # and the logging level specified in `LOG_CONFIG_FILENAME` is used.

    program_name = _program_name(argv)
    parent_parser = argparse.ArgumentParser()

    parent_parser.add_argument(
        "-l",
        "--log-level",
        dest="log_level",
        type=str.upper,
        choices=LOG_LEVELS,
        help="set the logging level (default: INFO)",
    )

    parser = argparse.ArgumentParser(
        parents=[parent_parser],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        add_help=False,
        prog=program_name,
    )

    # Top-level alias for the `version` subcommand. Declared on `parser` rather
    # than `parent_parser` so it does not leak onto every subcommand.
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        dest="show_version",
        help="display the holoscan-cli package version",
    )
    parser.add_argument(
        "--project-root",
        metavar="PATH",
        help="use PATH as the source-project root (must appear before the subcommand)",
    )

    subparser = parser.add_subparsers(dest="command")

    version_parser = subparser.add_parser(
        "version",
        help="display the holoscan-cli package version",
        formatter_class=argparse.HelpFormatter,
        parents=[parent_parser],
        add_help=False,
    )
    version_parser.add_argument(
        "--json", action="store_true", help="Output version information as JSON"
    )
    for command, help_text in sorted(PROJECT_COMMANDS.items()):
        subparser.add_parser(
            command,
            help=help_text,
            formatter_class=argparse.HelpFormatter,
            parents=[parent_parser],
            add_help=False,
        )
    args = parser.parse_args(argv[1:])
    args.argv = argv  # save argv for later use in runpy

    # Print help if no command is specified
    if args.command is None and not args.show_version:
        parser.print_help()
        parser.exit()

    return args


def set_up_logging(level: Optional[str], config_path: Union[str, Path] = LOG_CONFIG_FILENAME):
    """Initializes the logger and sets up logging level.

    Args:
        level (str): A logging level (DEBUG, INFO, WARN, ERROR, CRITICAL).
        config_path (str): A path to logging config file.
    """
    # Default log config path
    log_config_path = Path(__file__).absolute().parent / LOG_CONFIG_FILENAME

    config_path = Path(config_path)

    # If a logging config file that is specified by `log_config_path` exists in the current folder,
    # it overrides the default one
    if config_path.exists():
        log_config_path = config_path

    config_dict = json.loads(log_config_path.read_bytes())

    if level is not None and "root" in config_dict:
        config_dict["root"]["level"] = level
    logging.config.dictConfig(config_dict)


def _program_name(argv: list[str]) -> str:
    command_name = os.path.basename(argv[0])
    return "holoscan" if command_name == "__main__.py" else command_name


def _project_dispatch_argv(
    argv: list[str],
) -> tuple[Optional[str], list[str], Optional[str], Optional[str]]:
    """Return command, stripped argv, log level, and explicit project root."""
    project_argv = [argv[0]]
    log_level = None
    project_root = None
    index = 1

    while index < len(argv):
        name, equals, inline_value = argv[index].partition("=")
        if name not in TOP_LEVEL_OPTIONS:
            project_argv.extend(argv[index:])
            break
        if equals:
            value, index = inline_value, index + 1
        elif index + 1 < len(argv):
            value, index = argv[index + 1], index + 2
        else:
            raise DispatchUsageError(f"{name} requires a {TOP_LEVEL_OPTIONS[name]}.")

        if name == "--project-root":
            if project_root is not None:
                raise DispatchUsageError("--project-root may be specified only once.")
            # A bare subcommand or another option here means the path was omitted.
            if not value or value.startswith("-") or value in {*PROJECT_COMMANDS, "version"}:
                raise DispatchUsageError("--project-root requires a non-empty directory path.")
            project_root = value
        else:
            # argparse never sees this prefix form, so apply its choices here.
            log_level = value.upper()
            if log_level not in LOG_LEVELS:
                raise DispatchUsageError(
                    f"{name} must be one of {', '.join(LOG_LEVELS)}; got {value!r}."
                )

    command = project_argv[1] if len(project_argv) > 1 else None
    for arg in project_argv[2:]:
        if arg == "--project-root" or arg.startswith("--project-root="):
            program = _program_name(argv)
            raise DispatchUsageError(
                f"--project-root is a global option; place it before {command!r}, for example: "
                f"{program} --project-root PATH {command}"
            )
    return command, project_argv, log_level, project_root


def _exit_if_removed_command(program: str, command: Optional[str]) -> None:
    """Explain a removed subcommand before argparse reports an invalid choice."""
    if command not in REMOVED_COMMANDS:
        return
    print(
        f"Error: '{program} {command}' was removed since holoscan v4.3.0 — "
        f"{REMOVED_COMMANDS[command]} is no longer shipped.\n"
        f"{REMOVED_COMMAND_FOOTER}",
        file=sys.stderr,
    )
    sys.exit(2)


def _dispatch_project_cli(
    command: Optional[str],
    project_argv: list[str],
    log_level: Optional[str],
    project_root: Optional[str],
) -> bool:
    """Forward source-project commands to the ported project CLI."""
    if command not in PROJECT_COMMANDS:
        return False

    # Creation must not inherit an enclosing project's defaults unless the
    # caller explicitly selects that project.
    if command != "create" or project_root is not None:
        context = discover_project_context(explicit_root=project_root)
        for warning in context.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        activate_project_context(context)

    set_up_logging(log_level)

    from .cli import main as project_main

    project_main(project_argv)
    return True


def _dispatch(argv: Optional[list[str]]) -> None:
    if argv is None:
        argv = sys.argv
    argv = list(argv)

    command, native_argv, log_level, project_root = _project_dispatch_argv(argv)

    _exit_if_removed_command(_program_name(argv), command)

    if _dispatch_project_cli(command, native_argv, log_level, project_root):
        return

    args = parse_args(native_argv)
    if log_level is not None:
        args.log_level = log_level
    args.project_root = project_root

    set_up_logging(args.log_level)

    if args.command == "version" or args.show_version:
        from .version.version import execute_version_command

        execute_version_command(args)


def main(argv: Optional[list[str]] = None):
    try:
        _dispatch(argv)
    except (DispatchUsageError, ProjectContextError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        # The CLI owns pre-launch work. After launch, exec removes this frame
        # and the application retains control of its signal handling and status.
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
