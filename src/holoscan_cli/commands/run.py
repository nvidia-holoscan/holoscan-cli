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

"""``holoscan run`` — build and run a source project locally or in a container."""

import argparse
import os
import shlex
import shutil
from pathlib import Path

from holoscan_cli.commands.build import build_project_locally
from holoscan_cli.commands.registry import help_for
from holoscan_cli.metadata.utils import normalize_language
from holoscan_cli.utils.docker import get_entrypoint_command_args
from holoscan_cli.utils.holohub import (
    build_holohub_path_mapping,
    check_skip_builds,
    replace_placeholders,
    update_env,
)
from holoscan_cli.utils.io import fatal, format_cmd, run_command


def _local_build_command(cli_command, args, mode_name, language):
    command = f"{cli_command} build {args.project}"
    if mode_name and getattr(args, "mode", None) is not None:
        command += f" {mode_name}"
    command += " --local"
    if args.build_type:
        command += f" --build-type {args.build_type}"
    if getattr(args, "with_operators", None):
        command += f' --build-with "{args.with_operators}"'
    if getattr(args, "pkg_generator", None):
        command += f" --pkg-generator {args.pkg_generator}"
    if language:
        command += f" --language {language}"
    if getattr(args, "parallel", None):
        command += f" --parallel {args.parallel}"
    if args.verbose:
        command += " --verbose"
    for configure_arg in getattr(args, "configure_args", None) or []:
        command += f" --configure-args={shlex.quote(configure_arg)}"
    return command


def _builder_docker_opts(docker_opts):
    tokens = shlex.split(docker_opts or "")
    filtered = []
    options_with_value = {"--cidfile", "--name", "--restart", "--user", "-u"}
    standalone_options = {"--detach", "--rm", "-d"}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in options_with_value:
            index += 2
            continue
        if token in standalone_options or any(
            token.startswith(f"{option}=") for option in options_with_value | standalone_options
        ):
            index += 1
            continue
        if token.startswith("-u") and not token.startswith("--"):
            index += 1
            continue
        short_options = token[1:]
        if (
            token.startswith("-")
            and not token.startswith("--")
            and "d" in short_options
            and set(short_options) <= {"d", "i", "t", "P"}
        ):
            short_options = short_options.replace("d", "")
            if short_options:
                filtered.append(f"-{short_options}")
            index += 1
            continue
        filtered.append(token)
        index += 1
    filtered.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    return shlex.join(filtered)


def register_run_parser(
    cli, subparsers, *, container_build, container_run
) -> argparse.ArgumentParser:
    """Register the ``run`` subcommand."""
    parser = subparsers.add_parser(
        "run", help=help_for("run"), parents=[container_build, container_run]
    )
    parser.add_argument("project", help="Project to run")
    parser.add_argument("mode", nargs="?", help="Mode to run (optional)")
    parser.add_argument("--local", action="store_true", help="Run locally instead of in container")
    parser.add_argument("--verbose", action="store_true", help="Print extra output")
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    parser.add_argument(
        "--build-type",
        help="Build type (debug, release, rel-debug). "
        "If not specified, uses CMAKE_BUILD_TYPE environment variable or defaults to 'release'",
    )
    parser.add_argument(
        "--run-args",
        help="Additional arguments to pass to the application executable, "
        "example: --run-args=--flag or --run-args '-c config/file'",
    )
    parser.add_argument(
        "--build-with",
        dest="with_operators",
        help="Optional operators that should be built, separated by semicolons (;)",
    )
    parser.add_argument(
        "--parallel", help="Number of parallel build jobs (e.g. --parallel $(($(nproc)-1)))"
    )
    parser.add_argument(
        "--pkg-generator", default="DEB", help="Package generator for cpack (default: DEB)"
    )
    parser.add_argument(
        "--no-local-build",
        action="store_true",
        help="Skip building and just run the application",
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
    parser.set_defaults(func=lambda args: handle_run(cli, args))
    return parser


def handle_run(cli, args: argparse.Namespace) -> None:
    """Handle run command"""
    from holoscan_cli.cli import in_container_cli_command

    # Handle mode-specific configuration
    project_data = cli.find_project(args.project, language=args.language)
    mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
    cli.validate_mode(mode_name, mode_config)
    language = normalize_language(
        args.language if args.language else project_data.get("metadata", {}).get("language", None)
    )

    # Ensure mode_config is a dictionary
    mode_config = mode_config if mode_config is not None else {}

    # Print mode name if it was explicitly requested by user (not implicitly resolved)
    if mode_config:
        print(f"Running {args.project} in '{mode_name}' mode")

    # Get run configuration
    run_config = mode_config.get("run", project_data.get("metadata", {}).get("run", {}))

    if not run_config:
        fatal(f"Project '{args.project}' does not have a run configuration")

    # Get mode-specific build environment variables
    build_mode_env = mode_config.get("env", {}).copy()
    update_env(build_mode_env, mode_config.get("build", {}).get("env", {}))

    # Get mode-specific run environment variables
    run_mode_env = mode_config.get("env", {}).copy()
    update_env(run_mode_env, run_config.get("env", {}))

    # Check if builds should be skipped
    skip_docker_build, skip_local_build = check_skip_builds(args)

    # Check if local mode is requested
    is_local_mode = (
        args.local
        or os.environ.get("HOLOSCAN_CLI_BUILD_LOCAL")
        or build_mode_env.get("HOLOSCAN_CLI_BUILD_LOCAL")
        or run_mode_env.get("HOLOSCAN_CLI_BUILD_LOCAL")
    )

    # Apply mode-specific build configuration for build process
    build_args = cli.get_effective_build_config(args, mode_config)

    # Apply mode-specific run configuration
    run_args = cli.get_effective_run_config(args, mode_config)

    if is_local_mode:
        if args.docker_opts:
            fatal(
                "Container arguments were provided with `--docker-opts` but a non-containerized build was requested."
            )
        if skip_local_build:
            # Skip building; reuse previously resolved project_data and build directory
            build_dir = cli.DEFAULT_BUILD_PARENT_DIR / args.project
            if not build_dir.is_dir() and not args.dryrun:
                fatal(
                    f"The build directory {build_dir} for this application does not exist.\n"
                    f"Did you forget to build the application first? Try running:\n"
                    f"  {cli.script_name} build {args.project}"
                )
        else:
            build_dir, project_data = build_project_locally(
                cli,
                project_name=args.project,
                language=args.language if hasattr(args, "language") else None,
                build_type=args.build_type,
                with_operators=build_args.get("with_operators"),
                dryrun=args.dryrun,
                pkg_generator=getattr(args, "pkg_generator", "DEB"),
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

        # Set up run environment variables
        run_env = os.environ.copy()
        run_env["PYTHONPATH"] = (
            f"{run_env.get('PYTHONPATH', '')}:{cli.DEFAULT_SDK_DIR}/python/lib:{build_dir}/python/lib:{cli.HOLOHUB_ROOT}"
        )
        run_env["HOLOSCAN_CLI_DATA_PATH"] = str(cli.DEFAULT_DATA_DIR)
        run_env["HOLOSCAN_INPUT_PATH"] = run_env.get(
            "HOLOSCAN_INPUT_PATH", str(cli.DEFAULT_DATA_DIR)
        )
        # Apply mode environment variables (mode.run.env takes precedence over run.env)
        update_env(run_env, run_mode_env, path_mapping, verbose=(args.verbose or args.dryrun))

        # Process command template using the path mapping and environment variables
        cmd = replace_placeholders(run_config["command"], path_mapping)

        # Use effective run args (which may come from mode or CLI)
        effective_run_args = run_args.get("run_args")
        if effective_run_args:
            cmd_args = shlex.split(effective_run_args)
            if isinstance(cmd, str):  # Ensure cmd is a list of arguments
                cmd = shlex.split(cmd)
            cmd.extend(cmd_args)

        if language == "cpp":
            if not build_dir.is_dir() and not args.dryrun:
                fatal(
                    f"The build directory {build_dir} for this application does not exist.\n"
                    f"Did you forget to '{cli.script_name} build {args.project}'?"
                )

        workdir_spec = run_config.get("workdir", f"{cli.prefix}app_bin")
        if not workdir_spec:
            target_dir = Path(path_mapping.get(f"{cli.prefix}root", "."))
        elif workdir_spec in path_mapping:
            target_dir = Path(path_mapping[workdir_spec])
        else:
            target_dir = Path(replace_placeholders(str(workdir_spec), path_mapping, run_env))
        print(format_cmd("cd " + str(target_dir), is_dryrun=args.dryrun))
        if not args.dryrun:
            os.chdir(target_dir)

        # Print environment setup
        if args.verbose or args.dryrun:
            print(format_cmd("export PYTHONPATH=" + run_env["PYTHONPATH"], is_dryrun=args.dryrun))
            print(
                format_cmd(
                    "export HOLOSCAN_CLI_DATA_PATH=" + run_env["HOLOSCAN_CLI_DATA_PATH"],
                    is_dryrun=args.dryrun,
                )
            )
            print(
                format_cmd(
                    "export HOLOSCAN_INPUT_PATH=" + run_env["HOLOSCAN_INPUT_PATH"],
                    is_dryrun=args.dryrun,
                )
            )

        # Handle Nsight Systems profiling
        if args.nsys_profile:
            if (
                not shutil.which("nsys")
                and not os.path.isdir("/opt/nvidia/nsys-host")
                and not args.dryrun
            ):
                fatal(
                    "Nsight Systems CLI command 'nsys' not found. No Nsight installation from the host is also mounted."
                )
            nsys_cmd = "/opt/nvidia/nsys-host/bin/nsys" if not shutil.which("nsys") else "nsys"

            # Check perf_event_paranoid level
            if not args.dryrun:
                try:
                    with open("/proc/sys/kernel/perf_event_paranoid") as f:
                        if int(f.read()) > 2:
                            fatal(
                                "For Nsight Systems profiling the Linux operating system's perf_event_paranoid level must be 2 or less."
                            )
                except (IOError, ValueError):
                    pass

            cmd = f"{nsys_cmd} profile --trace=cuda,vulkan,nvtx,osrt {cmd}"

        cmd_to_run = cmd if isinstance(cmd, list) else shlex.split(cmd)
        as_root = getattr(args, "as_root", False)
        # sudo resets the environment; list every variable the elevated app
        # needs, including the project-declared run/mode env keys.
        root_env = {
            "PATH",
            "PYTHONPATH",
            "PYTHONHOME",
            "LD_LIBRARY_PATH",
            "LD_PRELOAD",
            "HOLOSCAN_CLI_DATA_PATH",
            "HOLOSCAN_INPUT_PATH",
            *run_mode_env,
        }
        run_command(
            cmd_to_run,
            env=run_env,
            dry_run=args.dryrun,
            as_root=as_root,
            preserve_env=root_env if as_root else None,
        )
    else:
        container = cli.make_project_container(
            project_name=args.project,
            language=args.language if hasattr(args, "language") else None,
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

        run_cmd = f"{in_container_cli_command()} run {args.project}"
        # Only add mode name if it was explicitly requested by user (not implicitly resolved)
        if mode_name and getattr(args, "mode", None) is not None:
            run_cmd += f" {mode_name}"
        if language:
            run_cmd += f" --language {language}"
        run_cmd += " --local"
        if args.verbose:
            run_cmd += " --verbose"
        if args.build_type:
            run_cmd += f" --build-type {args.build_type}"
        if getattr(args, "pkg_generator", None) and args.pkg_generator != "DEB":
            run_cmd += f" --pkg-generator {args.pkg_generator}"
        if args.nsys_profile:
            run_cmd += " --nsys-profile"
        if skip_local_build:
            run_cmd += " --no-local-build"
        if hasattr(args, "with_operators") and args.with_operators:
            run_cmd += f' --build-with "{args.with_operators}"'
        if hasattr(args, "run_args") and args.run_args:
            run_cmd += f" --run-args={shlex.quote(args.run_args)}"
        if getattr(args, "parallel", None):
            run_cmd += f" --parallel {args.parallel}"
        if getattr(args, "configure_args", None):
            for configure_arg in args.configure_args:
                run_cmd += f" --configure-args={shlex.quote(configure_arg)}"

        img = getattr(args, "img", None) or container.image_name
        docker_opts = build_args.get("docker_opts", "")
        as_root = getattr(args, "as_root", False)
        if as_root and not skip_local_build:
            build_cmd = _local_build_command(in_container_cli_command(), args, mode_name, language)
            builder_docker_opts = _builder_docker_opts(
                " ".join(filter(None, [container.DEFAULT_DOCKER_RUN_ARGS, docker_opts]))
            )
            builder_opts_extra, builder_extra_args = get_entrypoint_command_args(
                img, build_cmd, builder_docker_opts, dry_run=args.dryrun
            )
            if builder_opts_extra:
                builder_docker_opts = f"{builder_docker_opts} {builder_opts_extra}".strip()
            container.run(
                img=getattr(args, "img", None),
                local_sdk_root=getattr(args, "local_sdk_root", None),
                enable_x11=getattr(args, "enable_x11", True),
                ssh_x11=getattr(args, "ssh_x11", False),
                as_root=False,
                docker_opts=builder_docker_opts,
                include_default_run_args=False,
                add_volumes=getattr(args, "add_volume", None),
                extra_args=builder_extra_args,
            )
            run_cmd += " --no-local-build"

        docker_opts_extra, extra_args = get_entrypoint_command_args(
            img, run_cmd, docker_opts, dry_run=args.dryrun
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
            as_root=as_root,
            docker_opts=docker_opts,
            add_volumes=getattr(args, "add_volume", None),
            enable_mps=getattr(args, "mps", False),
            extra_args=extra_args,
        )
