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

"""``holoscan install`` — install a built source project (locally or in a container)."""

import argparse
import os
import shlex

from holoscan_cli.commands.build import build_project_locally
from holoscan_cli.commands.registry import help_for
from holoscan_cli.utils.docker import get_entrypoint_command_args
from holoscan_cli.utils.holohub import build_holohub_path_mapping, check_skip_builds, update_env
from holoscan_cli.utils.io import Color, run_command


def register_install_parser(
    cli, subparsers, *, container_build, container_run
) -> argparse.ArgumentParser:
    """Register the ``install`` subcommand."""
    parser = subparsers.add_parser(
        "install", help=help_for("install"), parents=[container_build, container_run]
    )
    parser.add_argument("project", help="Project to install")
    parser.add_argument("mode", nargs="?", help="Mode to install (optional)")
    parser.add_argument(
        "--local", action="store_true", help="Install locally instead of in container"
    )
    parser.add_argument(
        "--build-type",
        help="Build type (debug, release, rel-debug). "
        "If not specified, uses CMAKE_BUILD_TYPE environment variable or defaults to 'release'",
    )
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    parser.add_argument(
        "--build-with",
        dest="with_operators",
        help="Optional operators that should be built, separated by semicolons (;)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print extra output")
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--parallel", help="Number of parallel build jobs (e.g. --parallel $(($(nproc)-1)))"
    )
    parser.add_argument(
        "--no-docker-build", action="store_true", help="Skip building the container"
    )
    parser.add_argument(
        "--configure-args",
        action="append",
        help="Additional configuration arguments for cmake "
        "example: --configure-args='-DCUSTOM_OPTION=ON' --configure-args='-Dtest=ON'",
    )
    parser.set_defaults(func=lambda args: handle_install(cli, args))
    return parser


def handle_install(cli, args: argparse.Namespace) -> None:
    """Handle install command"""
    from holoscan_cli.cli import in_container_cli_command

    # Handle mode-specific configuration (if project has modes)
    project_data = cli.find_project(args.project, language=args.language)
    mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
    cli.validate_mode(mode_name, mode_config)

    # Ensure mode_config is a dictionary
    mode_config = mode_config if mode_config is not None else {}

    # Check if build should be skipped
    skip_docker_build, _ = check_skip_builds(args)

    if mode_config:
        print(f"Installing {args.project} in '{mode_name}' mode")

    # Apply mode-specific build configuration
    build_args = cli.get_effective_build_config(args, mode_config)

    # Get mode-specific build environment variables
    build_mode_env = mode_config.get("env", {}).copy()
    update_env(build_mode_env, mode_config.get("build", {}).get("env", {}))

    # Check if local mode is requested
    is_local_mode = (
        args.local
        or os.environ.get("HOLOSCAN_CLI_BUILD_LOCAL")
        or build_mode_env.get("HOLOSCAN_CLI_BUILD_LOCAL")
    )

    if is_local_mode:
        # Build and install locally
        build_dir, project_data = build_project_locally(
            cli,
            project_name=args.project,
            language=args.language if hasattr(args, "language") else None,
            build_type=args.build_type,
            with_operators=build_args.get("with_operators"),
            dryrun=args.dryrun,
            parallel=getattr(args, "parallel", None),
            configure_args=build_args.get("configure_args"),
            extra_env=build_mode_env,
        )

        # Build path mapping
        path_mapping = build_holohub_path_mapping(
            holohub_root=cli.HOLOHUB_ROOT,
            project_data=project_data,
            build_dir=build_dir,
            data_dir=cli.DEFAULT_DATA_DIR,
            prefix=cli.prefix,
            verbose=args.dryrun,
        )

        # Apply build mode environment variables
        install_env = os.environ.copy()
        if build_mode_env:
            update_env(
                install_env, build_mode_env, path_mapping, verbose=(args.verbose or args.dryrun)
            )

        # Install the project
        run_command(["cmake", "--install", str(build_dir)], dry_run=args.dryrun, env=install_env)
        if not args.dryrun:
            print(f"{Color.green('Successfully installed')} {args.project}")
    else:
        # Install in container
        container = cli.make_project_container(
            project_name=args.project,
            language=getattr(args, "language", None),
        )
        container.dryrun = args.dryrun
        container.verbose = args.verbose
        if not skip_docker_build:
            container.build(
                docker_file=args.docker_file,
                base_img=args.base_img,
                img=args.img,
                no_cache=args.no_cache,
                build_args=build_args.get("build_args"),
                cuda_version=getattr(args, "cuda", None),
                extra_scripts=getattr(args, "extra_scripts", []),
            )
        else:
            if hasattr(args, "cuda") and args.cuda is not None:
                container.cuda_version = args.cuda

        install_cmd = f"{in_container_cli_command()} install {args.project} --local"
        if args.build_type:
            install_cmd += f" --build-type {args.build_type}"
        if getattr(args, "language", None):
            install_cmd += f" --language {args.language}"
        if getattr(args, "with_operators", None):
            install_cmd += f' --build-with "{args.with_operators}"'
        if getattr(args, "parallel", None):
            install_cmd += f" --parallel {args.parallel}"
        if args.verbose:
            install_cmd += " --verbose"
        if getattr(args, "configure_args", None):
            for configure_arg in args.configure_args:
                install_cmd += f" --configure-args={shlex.quote(configure_arg)}"

        img = getattr(args, "img", None) or container.image_name
        docker_opts = build_args.get("docker_opts", "")
        docker_opts_extra, extra_args = get_entrypoint_command_args(
            img, install_cmd, docker_opts, dry_run=args.dryrun
        )
        if docker_opts_extra:
            docker_opts = f"{docker_opts} {docker_opts_extra}".strip()
        container.run(
            img=getattr(args, "img", None),
            local_sdk_root=getattr(args, "local_sdk_root", None),
            enable_x11=getattr(args, "enable_x11", True),
            ssh_x11=getattr(args, "ssh_x11", False),
            use_tini=getattr(args, "init", False),
            persistent=getattr(args, "persistent", False),
            nsys_profile=getattr(args, "nsys_profile", False),
            nsys_location=getattr(args, "nsys_location", ""),
            as_root=getattr(args, "as_root", False),
            docker_opts=docker_opts,
            add_volumes=getattr(args, "add_volume", None),
            enable_mps=getattr(args, "mps", False),
            extra_args=extra_args,
        )
