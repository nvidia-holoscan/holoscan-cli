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

"""Development-container subcommands.

* ``build-container``  — build a source-project development container
* ``run-container``    — build (if needed) and launch a development container

Both commands delegate the actual docker work to
:class:`holoscan_cli.container.HoloscanContainer`; this module is the thin
parser + handler layer that resolves project metadata / mode config into
the kwargs that ``HoloscanContainer.build`` / ``HoloscanContainer.run``
expect. The plural ``containers.py`` filename is intentional — it keeps
the module distinct from the singular :mod:`holoscan_cli.container`
package while describing what these commands act on.
"""

import argparse
import os

from holoscan_cli.commands.registry import help_for
from holoscan_cli.container.parsers import add_docker_build_args
from holoscan_cli.utils.docker import (
    apply_container_cli_overrides,
    get_entrypoint_command_args,
    resolve_cli_docker_opts,
)
from holoscan_cli.utils.holohub import check_skip_builds
from holoscan_cli.utils.project import report_effective_configuration

# ---- build-container ---------------------------------------------------------


def register_build_container_parser(cli, subparsers, *, container_build) -> argparse.ArgumentParser:
    """Register the ``build-container`` subcommand."""
    parser = subparsers.add_parser(
        "build-container",
        help=help_for("build-container"),
        parents=[container_build],
    )
    parser.add_argument("project", nargs="?", help="Project to build container for")
    parser.add_argument("mode", nargs="?", help="Mode to build container for (optional)")
    parser.add_argument(
        "--verbose", action="store_true", help="Print variables passed to docker build command"
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    parser.set_defaults(func=lambda args: handle_build_container(cli, args))
    return parser


def handle_build_container(cli, args: argparse.Namespace) -> None:
    """Handle build-container command"""
    # Resolve mode for docker_build_args if a project with modes is specified
    build_args = args.build_args
    mode_name = None
    mode_config = {}
    mode_build_args = None
    if args.project:
        project_data = cli.find_project(args.project, language=getattr(args, "language", None))
        mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
        if mode_config:
            cli.validate_mode(mode_name, mode_config)
            effective = cli.get_effective_build_config(args, mode_config)
            build_args = effective.get("build_args") or build_args
            mode_build_args = effective.get("mode_build_args")
            if mode_name:
                print(f"Building container for {args.project} in '{mode_name}' mode")

    container = cli.make_project_container(
        project_name=args.project,
        language=args.language if hasattr(args, "language") else None,
    )
    apply_container_cli_overrides(args, container)
    container.dryrun = args.dryrun
    container.verbose = args.verbose
    report_effective_configuration(
        args,
        mode_name=mode_name,
        mode_config=mode_config,
        default_sdk_root=cli.DEFAULT_SDK_DIR,
        container=container,
        include_build=True,
    )
    container.build(
        docker_file=args.docker_file,
        base_img=args.base_img,
        img=args.img,
        no_cache=args.no_cache,
        build_args=build_args,
        mode_build_args=mode_build_args,
        cuda_version=getattr(args, "cuda", None),
        extra_scripts=getattr(args, "extra_scripts", []),
    )


# ---- run-container -----------------------------------------------------------


def register_run_container_parser(
    cli, subparsers, *, container_build, container_run
) -> argparse.ArgumentParser:
    """Register the ``run-container`` subcommand."""
    parser = subparsers.add_parser(
        "run-container",
        help=help_for("run-container"),
        parents=[container_build, container_run],
        epilog="Any arguments after ' -- ' are executed as a command inside the container",
    )
    parser.add_argument("project", nargs="?", help="Project to run container for")
    parser.add_argument("mode", nargs="?", help="Mode to run container for (optional)")
    parser.add_argument(
        "--verbose", action="store_true", help="Print variables passed to docker run command"
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    add_docker_build_args(parser)
    parser.set_defaults(func=lambda args: handle_run_container(cli, args))
    return parser


def handle_run_container(cli, args: argparse.Namespace) -> None:
    """Handle run-container command"""
    # Resolve mode for docker_build_args / docker_run_args if project with modes
    build_args = args.build_args
    mode_name = None
    mode_config = {}
    docker_opts = resolve_cli_docker_opts(args)
    mode_build_args = None
    mode_docker_opts = None
    if args.project:
        project_data = cli.find_project(args.project, language=getattr(args, "language", None))
        mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
        if mode_config:
            cli.validate_mode(mode_name, mode_config)
            effective_build = cli.get_effective_build_config(args, mode_config)
            build_args = effective_build.get("build_args") or build_args
            docker_opts = effective_build.get("docker_opts", docker_opts)
            mode_build_args = effective_build.get("mode_build_args")
            mode_docker_opts = effective_build.get("mode_docker_opts")
            if mode_name:
                print(f"Running container for {args.project} in '{mode_name}' mode")

    skip_docker_build, _ = check_skip_builds(args)
    container = cli.make_project_container(
        project_name=args.project, language=args.language if hasattr(args, "language") else None
    )
    apply_container_cli_overrides(args, container)
    container.dryrun = args.dryrun
    container.verbose = args.verbose
    report_effective_configuration(
        args,
        mode_name=mode_name,
        mode_config=mode_config,
        default_sdk_root=cli.DEFAULT_SDK_DIR,
        container=container,
        include_build=not skip_docker_build,
        include_run=True,
    )
    if not skip_docker_build:
        container.build(
            docker_file=args.docker_file,
            base_img=args.base_img,
            img=args.img,
            no_cache=args.no_cache,
            build_args=build_args,
            mode_build_args=mode_build_args,
            cuda_version=getattr(args, "cuda", None),
            extra_scripts=getattr(args, "extra_scripts", []),
        )
    docker_opts = container.compose_run_args(
        mode_docker_opts=mode_docker_opts,
        docker_opts=docker_opts,
    )
    run_image = container.resolve_run_image(args.img)
    trailing_args = getattr(args, "_trailing_args", [])
    if trailing_args:  # additional commands requires a bash entrypoint
        command = " ".join(os.path.expandvars(arg) for arg in trailing_args)
        docker_opts_extra, extra_args = get_entrypoint_command_args(
            run_image, command, docker_opts, dry_run=args.dryrun
        )
        if docker_opts_extra:
            docker_opts = f"{docker_opts} {docker_opts_extra}".strip()
        trailing_args = extra_args

    container.run(
        img=run_image,
        local_sdk_root=args.local_sdk_root,
        enable_x11=getattr(args, "enable_x11", True),
        ssh_x11=getattr(args, "ssh_x11", False),
        use_tini=args.init,
        persistent=args.persistent,
        nsys_profile=getattr(args, "nsys_profile", False),
        nsys_location=getattr(args, "nsys_location", ""),
        as_root=args.as_root,
        effective_docker_opts=docker_opts,
        forward_env=getattr(args, "forward_env", None),
        add_volumes=args.add_volume,
        enable_mps=getattr(args, "mps", False),
        extra_args=trailing_args,
    )
