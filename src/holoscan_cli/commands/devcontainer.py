#!/usr/bin/env python3
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

"""Development-container subcommands: build-container and run-container.

Both delegate the actual docker work to :class:`HoloHubContainer`; this
module is the thin layer that resolves project metadata + mode config
into the kwargs that container.build / container.run expect.
"""

import argparse

import holoscan_cli.util as holohub_cli_util


def handle_build_container(cli, args: argparse.Namespace) -> None:
    """Handle build-container command"""
    # Resolve mode for docker_build_args if a project with modes is specified
    build_args = args.build_args
    if args.project:
        project_data = cli.find_project(args.project, language=getattr(args, "language", None))
        mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
        if mode_config:
            cli.validate_mode(
                args, mode_name, mode_config, project_data, getattr(args, "mode", None)
            )
            effective = cli.get_effective_build_config(args, mode_config)
            build_args = effective.get("build_args") or build_args
            if mode_name:
                print(f"Building container for {args.project} in '{mode_name}' mode")

    container = cli._make_project_container(
        project_name=args.project,
        language=args.language if hasattr(args, "language") else None,
    )
    container.dryrun = args.dryrun
    container.build(
        docker_file=args.docker_file,
        base_img=args.base_img,
        img=args.img,
        no_cache=args.no_cache,
        build_args=build_args,
        cuda_version=getattr(args, "cuda", None),
        extra_scripts=getattr(args, "extra_scripts", []),
    )


def handle_run_container(cli, args: argparse.Namespace) -> None:
    """Handle run-container command"""
    # Resolve mode for docker_build_args / docker_run_args if project with modes
    build_args = args.build_args
    docker_opts = args.docker_opts
    if args.project:
        project_data = cli.find_project(args.project, language=getattr(args, "language", None))
        mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
        if mode_config:
            cli.validate_mode(
                args, mode_name, mode_config, project_data, getattr(args, "mode", None)
            )
            effective_build = cli.get_effective_build_config(args, mode_config)
            build_args = effective_build.get("build_args") or build_args
            docker_opts = effective_build.get("docker_opts") or docker_opts
            if mode_name:
                print(f"Running container for {args.project} in '{mode_name}' mode")

    skip_docker_build, _ = holohub_cli_util.check_skip_builds(args)
    container = cli._make_project_container(
        project_name=args.project, language=args.language if hasattr(args, "language") else None
    )
    container.dryrun = args.dryrun
    container.verbose = args.verbose
    if not skip_docker_build:
        container.build(
            docker_file=args.docker_file,
            base_img=args.base_img,
            img=args.img,
            no_cache=args.no_cache,
            build_args=build_args,
            cuda_version=getattr(args, "cuda", None),
            extra_scripts=getattr(args, "extra_scripts", []),
        )
    else:
        if hasattr(args, "cuda") and args.cuda is not None:
            container.cuda_version = args.cuda

    trailing_args = getattr(args, "_trailing_args", [])
    if trailing_args:  # additional commands requires a bash entrypoint
        command = holohub_cli_util.normalize_args_str(trailing_args)
        docker_opts_extra, extra_args = holohub_cli_util.get_entrypoint_command_args(
            args.img or container.image_name, command, docker_opts, dry_run=args.dryrun
        )
        if docker_opts_extra:
            docker_opts = f"{docker_opts} {docker_opts_extra}".strip()
        trailing_args = extra_args

    container.run(
        img=args.img,
        local_sdk_root=args.local_sdk_root,
        enable_x11=getattr(args, "enable_x11", True),
        ssh_x11=getattr(args, "ssh_x11", False),
        use_tini=args.init,
        persistent=args.persistent,
        nsys_profile=getattr(args, "nsys_profile", False),
        nsys_location=getattr(args, "nsys_location", ""),
        as_root=args.as_root,
        docker_opts=docker_opts,
        add_volumes=args.add_volume,
        enable_mps=getattr(args, "mps", False),
        extra_args=trailing_args,
    )
