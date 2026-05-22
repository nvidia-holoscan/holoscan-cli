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

# Subcommands removed in the source-project v1 cut. Mapped to a one-line note
# explaining what each one did, so users typing the old command get a specific
# message instead of argparse's generic "invalid choice". Note: the pre-v1
# `holoscan run` was the HAP/MAP packaged-image runner; in v1 the same name is
# reused for the HoloHub-style source-project runner, so it is not listed here.
REMOVED_COMMANDS: dict[str, str] = {
    "nics": "the HAP NIC diagnostic command",
}

REMOVED_COMMAND_FOOTER = (
    "Removed HAP/MAP commands are out of scope for holoscan-cli v1. Pin "
    "holoscan-cli<=4.2.0 if you still need that legacy command surface."
)


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

    subparser = parser.add_subparsers(dest="command")

    subparser.add_parser(
        "version",
        help="display the holoscan-cli package version",
        formatter_class=argparse.HelpFormatter,
        parents=[parent_parser],
        add_help=False,
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
    if args.command is None:
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


def _project_dispatch_argv(argv: list[str]) -> tuple[Optional[str], list[str], Optional[str]]:
    """Return command, argv with top-level options removed, and requested log level."""
    project_argv = [argv[0]]
    log_level = None
    index = 1

    while index < len(argv):
        arg = argv[index]
        if arg in {"-l", "--log-level"} and index + 1 < len(argv):
            log_level = argv[index + 1].upper()
            index += 2
            continue
        if arg.startswith("--log-level="):
            log_level = arg.split("=", 1)[1].upper()
            index += 1
            continue

        project_argv.extend(argv[index:])
        break

    command = project_argv[1] if len(project_argv) > 1 else None
    return command, project_argv, log_level


def _exit_if_removed_command(argv: list[str]) -> None:
    """Print a removal note and exit 2 if argv's first non-flag token names a
    removed subcommand. Runs before any parser so users typing the old name
    see why it's gone instead of argparse's bare "invalid choice".
    """
    command, _, _ = _project_dispatch_argv(argv)
    if command is None or command not in REMOVED_COMMANDS:
        return
    program = _program_name(argv)
    print(
        f"Error: '{program} {command}' was removed in holoscan-cli v1 — "
        f"{REMOVED_COMMANDS[command]} is no longer shipped.\n"
        f"{REMOVED_COMMAND_FOOTER}",
        file=sys.stderr,
    )
    sys.exit(2)


def _dispatch_project_cli(argv: list[str]) -> bool:
    """Forward source-project commands to the ported project CLI."""
    command, project_argv, log_level = _project_dispatch_argv(argv)
    if command not in PROJECT_COMMANDS:
        return False

    set_up_logging(log_level)

    from .cli import main as project_main

    project_main(project_argv)
    return True


def main(argv: Optional[list[str]] = None):
    if argv is None:
        argv = sys.argv
    argv = list(argv)

    _exit_if_removed_command(argv)

    if _dispatch_project_cli(argv):
        return

    args = parse_args(argv)

    set_up_logging(args.log_level)

    if args.command == "version":
        from .version.version import execute_version_command

        execute_version_command(args)


if __name__ == "__main__":
    main()
