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

"""Read-only / informational subcommands.

Six small commands grouped by behavior — none of them mutate state, so
they share a file rather than each owning ~50-line modules:

* ``list``                 — list discovered source projects, grouped by type
* ``modes``                — list build/run modes from a project's metadata
* ``autocompletion_list``  — emit project + command names for shell completion
* ``env-info``             — print debug info about the current environment
* ``status``               — show environment, container, and build status
* ``env-check``            — run host system checks (GPU, CUDA, Docker, ...)

The ``status`` and ``env-check`` handlers delegate the heavy lifting to
:mod:`holoscan_cli.status` and :mod:`holoscan_cli.system_check` via lazy
imports so the CLI startup path stays cheap for other commands.
"""

import argparse
import sys
from collections import defaultdict

import holoscan_cli.util as holohub_cli_util
from holoscan_cli.commands.registry import help_for
from holoscan_cli.utils.io import Color

# ---- list --------------------------------------------------------------------


def register_list_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``list`` subcommand."""
    parser = subparsers.add_parser("list", help=help_for("list"))
    parser.set_defaults(func=lambda args: handle_list(cli, args))
    return parser


def handle_list(cli, args: argparse.Namespace) -> None:
    """Handle list command"""
    LIST_TYPES = [
        "application",
        "benchmark",
        "gxf_extension",
        "package",
        "operator",
        "tutorial",
        "workflow",
    ]
    grouped_metadata = defaultdict(list)
    for project in cli.projects:
        grouped_metadata[project.get("project_type", "")].append(project)

    for project_type in LIST_TYPES:
        if project_type not in grouped_metadata:
            continue
        print(f"\n{Color.white(f'== {project_type.upper()}S =================', bold=True)}\n")
        for project in sorted(grouped_metadata[project_type], key=lambda x: x["project_name"]):
            language = project.get("metadata", {}).get("language", "")
            language = f"({language})" if language else ""
            print(f'{project["project_name"]} {language}')

    print(f"\n{Color.white('=================================', bold=True)}\n")


# ---- modes -------------------------------------------------------------------


def register_modes_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``modes`` subcommand."""
    parser = subparsers.add_parser("modes", help=help_for("modes"))
    parser.add_argument("project", help="Project to list modes for")
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    parser.set_defaults(func=lambda args: handle_modes(cli, args))
    return parser


def handle_modes(cli, args: argparse.Namespace) -> None:
    """Handle modes command"""
    project_data = cli.find_project(args.project, language=args.language)
    modes = project_data.get("metadata", {}).get("modes", {})

    if not modes:
        print(f"No modes defined for {args.project}")
        return

    print(f"\n{Color.white(f'Available modes for {args.project}:', bold=True)}\n")

    for mode_name, mode_config in modes.items():
        description = mode_config.get("description", "No description")
        print(f"  {Color.green(mode_name, bold=True)} - {description}")
        requirements = mode_config.get("requirements", [])
        if requirements:
            req_list = ", ".join(requirements)
            print(f"    Requirements: {req_list}")

        print()  # Empty line between modes


# ---- autocompletion_list -----------------------------------------------------


def register_autocompletion_list_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``autocompletion_list`` subcommand."""
    parser = subparsers.add_parser("autocompletion_list", help=help_for("autocompletion_list"))
    parser.set_defaults(func=lambda args: handle_autocompletion_list(cli, args))
    return parser


def handle_autocompletion_list(cli, args: argparse.Namespace) -> None:
    """Handle autocompletion_list command - output project names and commands for bash completion"""
    project_names = set()
    for project in cli.projects:
        project_names.add(project["project_name"])
    for name in sorted(project_names):
        print(name)
    commands = [
        "build-container",
        "run-container",
        "build",
        "run",
        "list",
        "lint",
        "setup",
        "install",
        "create",
        "status",
        "env-check",
        "cpp",
        "python",
        "autocompletion_list",
    ]
    for cmd in commands:
        print(cmd)


# ---- env-info ----------------------------------------------------------------


def register_env_info_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``env-info`` subcommand."""
    parser = subparsers.add_parser("env-info", help=help_for("env-info"))
    parser.set_defaults(func=lambda args: handle_env_info(cli, args))
    return parser


def handle_env_info(cli, args: argparse.Namespace) -> None:
    """Handle env-info command to collect debugging information"""
    print(holohub_cli_util.format_cmd("Environment Information"))
    holohub_cli_util.collect_holohub_info(
        holohub_root=cli.HOLOHUB_ROOT,
        build_dir=cli.DEFAULT_BUILD_PARENT_DIR,
        data_dir=cli.DEFAULT_DATA_DIR,
        sdk_dir=cli.DEFAULT_SDK_DIR,
    )
    holohub_cli_util.collect_git_info(holohub_root=cli.HOLOHUB_ROOT)
    holohub_cli_util.collect_env_info()
    print(
        holohub_cli_util.format_cmd(
            "Complete (Before sharing, please review and remove sensitive information)"
        )
    )


# ---- status ------------------------------------------------------------------


def register_status_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``status`` subcommand."""
    parser = subparsers.add_parser("status", help=help_for("status"))
    parser.add_argument("--json", action="store_true", help="Output status as JSON")
    parser.set_defaults(func=lambda args: handle_status(cli, args))
    return parser


def handle_status(cli, args: argparse.Namespace) -> None:
    """Handle status command — show environment overview"""
    from holoscan_cli.status import (
        collect_build_info,
        collect_docker_disk_usage,
        collect_folder_info,
        collect_git_info,
        collect_image_info,
        collect_platform_info,
        format_status,
        format_status_json,
    )

    platform_info = collect_platform_info()
    git_info = collect_git_info(cli.HOLOHUB_ROOT)
    containers = collect_image_info()
    builds = collect_build_info(cli.DEFAULT_BUILD_PARENT_DIR)
    build_folders = collect_folder_info(
        cli._collect_cache_dirs(["build", "build-*"], cli.DEFAULT_BUILD_PARENT_DIR)
    )
    data_folders = collect_folder_info(
        cli._collect_cache_dirs(["data", "data-*"], cli.DEFAULT_DATA_DIR)
    )
    docker_disk = collect_docker_disk_usage()

    fmt_args = (
        platform_info,
        git_info,
        containers,
        builds,
        build_folders,
        data_folders,
        docker_disk,
    )
    if args.json:
        print(format_status_json(*fmt_args))
    else:
        print(format_status(*fmt_args))


# ---- env-check ---------------------------------------------------------------


def register_env_check_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``env-check`` subcommand."""
    parser = subparsers.add_parser("env-check", help=help_for("env-check"))
    parser.add_argument("--json", action="store_true", help="Output check results as JSON")
    parser.set_defaults(func=lambda args: handle_env_check(cli, args))
    return parser


def handle_env_check(cli, args: argparse.Namespace) -> None:
    """Handle env-check command to run system checks"""
    import time as _time

    from holoscan_cli.system_check import (
        format_results,
        format_results_json,
        run_all_checks,
    )

    t0 = _time.monotonic()
    results = run_all_checks()
    elapsed = _time.monotonic() - t0

    if args.json:
        print(format_results_json(results, elapsed))
    else:
        print(format_results(results, elapsed))

    # Exit 1 only on FAIL; warnings are informational
    if any(r.status == "FAIL" for r in results):
        sys.exit(1)
