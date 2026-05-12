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

logging.getLogger("docker.api.build").setLevel(logging.WARNING)
logging.getLogger("docker.auth").setLevel(logging.WARNING)
logging.getLogger("docker.utils.config").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG_CONFIG_FILENAME = "logging.json"

# Dispatch contract for the consolidation prototype:
# native packaged-app commands (`package`, `hap-run`, `version`, `nics`) stay
# owned by this argparse entry point. Source-project commands listed in
# PROJECT_COMMANDS are forwarded to the ported HoloHub project CLI before
# argparse parses them; the placeholder subparsers below exist only so
# top-level `--help` enumerates them. A legacy `holoscan run <image-like>`
# invocation is rewritten to `hap-run` with a deprecation warning.
PROJECT_COMMANDS = {
    "autocompletion_list": "list source-project names for shell completion",
    "build": "build a source project",
    "build-container": "build a source-project development container",
    "clear-cache": "clear source-project build, data, and install caches",
    "create": "create a new source project from a template",
    "env-check": "run source-project environment health checks",
    "env-info": "display source-project environment information",
    "install": "install a built source project",
    "lint": "run source-project linting tools",
    "list": "list discovered source projects",
    "modes": "list modes for a source project",
    "run": "build and run a source project",
    "run-container": "launch a source-project development container",
    "setup": "install source-project development dependencies",
    "status": "show source-project environment and build status",
    "test": "test a source project",
    "vscode": "launch VS Code for a source project dev container",
}
HAP_RUN_FLAGS = {
    "--address",
    "--driver",
    "--input",
    "-i",
    "--output",
    "-o",
    "--fragments",
    "-f",
    "--worker",
    "--worker-address",
    "--rm",
    "--config",
    "--name",
    "--health-check",
    "--network",
    "-n",
    "--nic",
    "--use-all-nics",
    "--render",
    "-r",
    "--quiet",
    "-q",
    "--shm-size",
    "--terminal",
    "--device",
    "--gpus",
    "--uid",
    "--gid",
}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    from .packager.package_command import create_package_parser
    from .runner.run_command import create_run_parser

    if argv is None:
        argv = sys.argv
    argv = list(argv)  # copy argv for manipulation to avoid side-effects

    # We have intentionally not set the default using `default="INFO"` here so that the default
    # value from here doesn't override the value in `LOG_CONFIG_FILENAME` unless the user indends
    # to do so. If the user doesn't use this flag to set log level, this argument is set to "None"
    # and the logging level specified in `LOG_CONFIG_FILENAME` is used.

    command_name = os.path.basename(argv[0])
    program_name = "holoscan" if command_name == "__main__.py" else command_name
    parent_parser = argparse.ArgumentParser()

    parent_parser.add_argument(
        "-l",
        "--log-level",
        dest="log_level",
        type=str.upper,
        choices=["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"],
        help="set the logging level (default: INFO)",
    )

    parser = argparse.ArgumentParser(
        parents=[parent_parser],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        add_help=False,
        prog=program_name,
    )

    subparser = parser.add_subparsers(dest="command")

    create_package_parser(subparser, "package", parents=[parent_parser])

    if program_name == "monai-deploy":
        # Keep MONAI Deploy's historical packaged-image run spelling.
        create_run_parser(subparser, "run", parents=[parent_parser])
    else:
        # `holoscan run` is now reserved for source projects. Existing HAP/MAP
        # image execution is available as `holoscan hap-run`.
        create_run_parser(subparser, "hap-run", parents=[parent_parser])

    subparser.add_parser(
        "version",
        formatter_class=argparse.HelpFormatter,
        parents=[parent_parser],
        add_help=False,
    )
    subparser.add_parser(
        "nics",
        formatter_class=argparse.HelpFormatter,
        parents=[parent_parser],
        add_help=False,
    )
    if program_name != "monai-deploy":
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
        log_config_path (str): A path to logging config file.
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


def _run_arg_looks_like_hap(argv: list[str]) -> bool:
    if len(argv) < 3 or argv[1] != "run":
        return False
    for arg in argv[2:]:
        flag = arg.split("=", 1)[0]
        if flag in HAP_RUN_FLAGS:
            return True
    image = argv[2]
    return "/" in image or ":" in image or image.startswith(("nvcr.io", "docker.io"))


def _dispatch_project_cli(argv: list[str]) -> bool:
    """Forward source-project commands to the ported project CLI.

    Mutates ``argv`` in place when a legacy ``run <image>`` invocation needs to
    be rewritten to ``hap-run`` so the caller can continue with the native
    argparse flow without re-scanning argv.
    """
    if _program_name(argv) == "monai-deploy":
        return False

    command = argv[1] if len(argv) > 1 else None
    if command not in PROJECT_COMMANDS:
        return False

    if _run_arg_looks_like_hap(argv):
        print(
            "WARNING: `holoscan run <image>` is deprecated for packaged "
            "application images; use `holoscan hap-run <image>` instead.",
            file=sys.stderr,
        )
        argv[1] = "hap-run"
        return False

    from .project.cli import main as project_main

    project_main(argv)
    return True


def _execute_package_command(args: argparse.Namespace) -> None:
    from .packager.packager import execute_package_command

    execute_package_command(args)


def _execute_run_command(args: argparse.Namespace) -> None:
    from .runner.runner import execute_run_command

    execute_run_command(args)


def _execute_version_command(args: argparse.Namespace) -> None:
    from .version.version import execute_version_command

    execute_version_command(args)


def _execute_nics_command(args: argparse.Namespace) -> None:
    from .nics.nics import execute_nics_command

    execute_nics_command(args)


def main(argv: Optional[list[str]] = None):
    if argv is None:
        argv = sys.argv
    argv = list(argv)

    if _dispatch_project_cli(argv):
        return

    args = parse_args(argv)

    set_up_logging(args.log_level)

    if args.command == "package":
        _execute_package_command(args)

    elif args.command in {"run", "hap-run"}:
        _execute_run_command(args)

    elif args.command == "version":
        _execute_version_command(args)

    elif args.command == "nics":
        _execute_nics_command(args)


if __name__ == "__main__":
    main()
