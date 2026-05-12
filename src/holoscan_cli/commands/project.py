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

"""Project-action subcommands: build, run, test, install.

All four follow the same shape:
  1. Resolve project metadata + mode config (cli.find_project,
     cli.resolve_mode, cli.validate_mode, cli.get_effective_*_config).
  2. Decide local-host vs in-container execution.
  3. Either run cmake/ctest directly on the host, or build the container
     and ``docker run`` a recursion that re-enters the CLI inside the
     container.

The shared ``build_project_locally`` helper and the ctest-script
resolver ``_ctest_script_arg`` live here because they're used only by
this group.
"""

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Optional

import holoscan_cli.util as holohub_cli_util
from holoscan_cli.metadata.utils import normalize_language
from holoscan_cli.utils.io import Color


def _ctest_script_arg(cli, args: argparse.Namespace, in_container: bool) -> str:
    """Render the ``ctest -S <script>`` argument with the right resolution context.

    When the ctest invocation will run inside a separate container (i.e. the
    host is recursing in via ``docker run ... bash -c "<ctest_cmd>"``), the
    host's ``HoloHubCLI.DEFAULT_CTEST_SCRIPT`` points at the host's
    ``site-packages`` and will not exist inside the container if the install
    prefix differs. Defer the resolution to runtime by emitting a Python
    one-liner the in-container shell evaluates; this honors any
    ``HOLOHUB_CTEST_SCRIPT`` value forwarded into the container and falls
    back to the in-container package's bundled script. The host's local path
    (``--local`` on the host, or the in-container ``--local`` recursion
    branch) keeps the direct host-resolved path.
    """
    if args.ctest_script:
        return f"-S {args.ctest_script}"
    if not in_container:
        return f"-S {cli.DEFAULT_CTEST_SCRIPT}"
    return (
        "-S \"$(python3 -c 'from holoscan_cli.cli import HoloHubCLI; "
        "print(HoloHubCLI.DEFAULT_CTEST_SCRIPT)')\""
    )


def handle_test(cli, args: argparse.Namespace) -> None:
    """Handle test command"""
    skip_docker_build, _ = holohub_cli_util.check_skip_builds(args)
    container = cli._make_project_container(
        project_name=args.project, language=args.language if hasattr(args, "language") else None
    )
    if args.clear_cache:
        cli.handle_clear_cache(args)

    container.dryrun = args.dryrun
    container.verbose = args.verbose

    is_local_mode = bool(args.local or os.environ.get("HOLOHUB_BUILD_LOCAL"))

    if not is_local_mode and not skip_docker_build:
        build_args = args.build_args or ""
        extra_scripts = (getattr(args, "extra_scripts", None) or []).copy()

        # Configure coverage if enabled
        if getattr(args, "coverage", False):
            # Add COVERAGE build argument
            coverage_arg = "--build-arg COVERAGE=ON"
            build_args = f"{build_args} {coverage_arg}".strip()
            # Add coverage setup script
            if "coverage" not in extra_scripts:
                extra_scripts.append("coverage")

        container.build(
            docker_file=args.docker_file,
            base_img=args.base_img,
            img=args.img,
            no_cache=args.no_cache,
            build_args=build_args,
            cuda_version=getattr(args, "cuda", None),
            extra_scripts=extra_scripts,
        )
    else:
        if hasattr(args, "cuda") and args.cuda is not None:
            container.cuda_version = args.cuda

    xvfb = "" if args.no_xvfb else "xvfb-run -a"

    # TAG is used in CTest scripts by default
    if getattr(args, "build_name_suffix", None):
        tag = args.build_name_suffix
    elif is_local_mode:
        tag = "local"
    else:
        image_name = (
            (getattr(args, "img", None) or container.image_name)
            if skip_docker_build
            else (args.base_img or container.default_base_image())
        )
        tag = image_name.split(":")[-1]

    ctest_cmd = f"{xvfb} ctest "
    if args.project:
        project_metadata = container.project_metadata or {}
        project_name = project_metadata.get("project_name", args.project)
        project_type = project_metadata.get("project_type", "application")
        proj_prefix = holohub_cli_util.determine_project_prefix(project_type)
        ctest_cmd += f"-D{proj_prefix}={project_name} "
    ctest_cmd += f"-DTAG={tag} "

    # Aggregate configure options from CLI and language selection
    configure_opts: list[str] = []
    if args.cmake_options:
        configure_opts.extend(args.cmake_options)

    # Respect language selection by toggling build flags
    normalized_lang = None
    if hasattr(args, "language") and args.language:
        normalized_lang = normalize_language(args.language)
        if normalized_lang == "python":
            configure_opts.append("-DHOLOHUB_BUILD_PYTHON=ON")
            configure_opts.append("-DHOLOHUB_BUILD_CPP=OFF")
        elif normalized_lang == "cpp":
            configure_opts.append("-DHOLOHUB_BUILD_PYTHON=OFF")
            configure_opts.append("-DHOLOHUB_BUILD_CPP=ON")

    if configure_opts:
        cmake_opts = ";".join(configure_opts)
        ctest_cmd += f'-DCONFIGURE_OPTIONS="{cmake_opts}" '

    if getattr(args, "ctest_options", None):
        ctest_cmd += " ".join(args.ctest_options) + " "

    if args.cdash_url:
        ctest_cmd += f"-DCTEST_SUBMIT_URL={args.cdash_url} "

    if args.site_name:
        ctest_cmd += f"-DCTEST_SITE={args.site_name} "

    if args.platform_name:
        ctest_cmd += f"-DPLATFORM_NAME={args.platform_name} "

    if getattr(args, "coverage", False):
        ctest_cmd += "-DCOVERAGE=ON "

    ctest_cmd += _ctest_script_arg(cli, args, in_container=not is_local_mode) + " "

    if args.verbose:
        ctest_cmd += "-VV "

    if is_local_mode:
        print(holohub_cli_util.format_cmd(f"cd {cli.HOLOHUB_ROOT}", is_dryrun=args.dryrun))
        if not args.dryrun:
            os.chdir(cli.HOLOHUB_ROOT)

        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{env.get('PYTHONPATH', '')}:{cli.DEFAULT_SDK_DIR}/python/lib:{cli.HOLOHUB_ROOT}"
        )
        env["HOLOHUB_DATA_PATH"] = str(cli.DEFAULT_DATA_DIR)
        env.setdefault("HOLOSCAN_INPUT_PATH", str(cli.DEFAULT_DATA_DIR))

        holohub_cli_util.run_command(["bash", "-c", ctest_cmd], dry_run=args.dryrun, env=env)
        return

    container.run(
        img=getattr(args, "img", None),
        use_tini=True,
        docker_opts="--entrypoint=bash",
        as_root=getattr(args, "coverage", False),
        extra_args=["-c", ctest_cmd],
    )


def build_project_locally(
    cli,
    project_name: str,
    language: Optional[str] = None,
    build_type: Optional[str] = None,
    with_operators: Optional[str] = None,
    dryrun: bool = False,
    pkg_generator: str = "DEB",
    parallel: Optional[str] = None,
    benchmark: bool = False,
    configure_args: Optional[list[str]] = None,
    extra_env: Optional[dict] = None,
) -> tuple[Path, dict]:
    """Helper to build a project locally (cmake + cmake --build)."""
    project_data = cli.find_project(project_name=project_name, language=language)
    project_type = project_data.get("project_type", "application")

    # Handle benchmark patching before building
    app_source_path = None
    if benchmark:
        if project_type in ["application", "workflow", "benchmark"]:
            app_source_path = project_data.get("source_folder", "")
            patch_script = (
                cli.HOLOHUB_ROOT / "benchmarks/holoscan_flow_benchmarking/patch_application.sh"
            )
            holohub_cli_util.run_command(
                [str(patch_script), str(app_source_path)], dry_run=dryrun
            )
            print("Building for Holoscan Flow Benchmarking")
        else:
            holohub_cli_util.fatal(
                "--benchmark option is only available for applications/workflows"
            )

    build_type = holohub_cli_util.get_buildtype_str(build_type)
    build_dir = cli.DEFAULT_BUILD_PARENT_DIR / project_name
    build_dir.mkdir(parents=True, exist_ok=True)

    # Prepare environment with extra env vars
    build_env = os.environ.copy()
    if extra_env:
        # Build path mapping
        path_mapping = holohub_cli_util.build_holohub_path_mapping(
            holohub_root=cli.HOLOHUB_ROOT,
            project_data=project_data,
            build_dir=build_dir,
            data_dir=cli.DEFAULT_DATA_DIR,
            prefix=cli.prefix,
            verbose=dryrun,
        )
        holohub_cli_util.update_env(build_env, extra_env, path_mapping, verbose=dryrun)

    proj_prefix = holohub_cli_util.determine_project_prefix(project_type)
    cmake_args = [
        "cmake",
        "-B",
        str(build_dir),
        "-S",
        str(cli.HOLOHUB_ROOT),
        "--no-warn-unused-cli",
        f"-DPython3_EXECUTABLE={sys.executable}",
        f"-DPython3_ROOT_DIR={os.path.dirname(os.path.dirname(sys.executable))}",
        f"-DCMAKE_BUILD_TYPE={build_type}",
        f"-DCMAKE_PREFIX_PATH={cli.DEFAULT_SDK_DIR}/lib",
        f"-DHOLOHUB_DATA_DIR:PATH={cli.DEFAULT_DATA_DIR}",
        f"-D{proj_prefix}_{project_name}=ON",
    ]
    # Add benchmark-specific CMake flags
    if benchmark:
        cmake_args.append(
            f"-DCMAKE_CXX_FLAGS=-I{cli.HOLOHUB_ROOT}/benchmarks/holoscan_flow_benchmarking"
        )

    # use -G Ninja if available
    if shutil.which("ninja"):
        cmake_args.extend(["-G", "Ninja"])
    # Add optional operators if specified
    if with_operators:
        cmake_args.append(f'-DHOLOHUB_BUILD_OPERATORS="{with_operators}"')

    if not language:
        language = normalize_language(project_data.get("metadata", {}).get("language", None))
    # Set build flags based on language
    if language == "python":
        cmake_args.append("-DHOLOHUB_BUILD_PYTHON=ON")
        cmake_args.append("-DHOLOHUB_BUILD_CPP=OFF")
    elif language == "cpp":
        cmake_args.append("-DHOLOHUB_BUILD_PYTHON=OFF")
        cmake_args.append("-DHOLOHUB_BUILD_CPP=ON")

    # Configure sccache
    sccache_bin = shutil.which("sccache")
    enable_sccache_val, enable_sccache = holohub_cli_util.get_env_bool(
        "HOLOHUB_ENABLE_SCCACHE", default=False
    )
    holohub_cli_util.info(f"HOLOHUB_ENABLE_SCCACHE={enable_sccache_val}")
    if enable_sccache:
        if not sccache_bin:
            (holohub_cli_util.warn if dryrun else holohub_cli_util.fatal)(
                "HOLOHUB_ENABLE_SCCACHE is enabled but 'sccache' was not found in PATH. "
                "Install it (e.g., `./holohub setup`) or disable sccache."
            )
        # Set CMake compiler launchers with -D
        if language != "python":
            cmake_args.extend(
                [
                    f"-DCMAKE_C_COMPILER_LAUNCHER={sccache_bin}",
                    f"-DCMAKE_CXX_COMPILER_LAUNCHER={sccache_bin}",
                    f"-DCMAKE_CUDA_COMPILER_LAUNCHER={sccache_bin}",
                ]
            )
        # Set default SCCACHE properties if not set
        build_env.setdefault("SCCACHE_DIR", holohub_cli_util.get_sccache_dir(build_env))
        build_env.setdefault("SCCACHE_CACHE_SIZE", "20G")
        # Print SCCACHE environment variables
        holohub_cli_util.info(f"Using sccache: {sccache_bin}")
        for key, value in build_env.items():
            if key.startswith("SCCACHE_"):
                holohub_cli_util.info(f"{key}={value}")
    elif sccache_bin:
        holohub_cli_util.warn(
            "Detected 'sccache' in PATH but HOLOHUB_ENABLE_SCCACHE is disabled. "
            "Skipping sccache."
        )

    if configure_args:
        cmake_args.extend(configure_args)

    holohub_cli_util.run_command(cmake_args, dry_run=dryrun, env=build_env)

    # Build the project with optional parallel jobs
    build_cmd = ["cmake", "--build", str(build_dir), "--config", build_type]
    # Determine the number of parallel jobs (user input > env var > CPU count):
    if parallel is not None:
        build_njobs = str(parallel)
    else:
        build_njobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL", str(os.cpu_count()))
    build_cmd.extend(["-j", build_njobs])

    holohub_cli_util.run_command(build_cmd, dry_run=dryrun, env=build_env)

    # Print sccache stats
    if enable_sccache:
        stats_file = build_dir / "sccache-stats.txt"
        with open(stats_file, "w", encoding="utf-8") as f:
            holohub_cli_util.run_command(
                ["sccache", "--show-stats"],
                dry_run=dryrun,
                env=build_env,
                stdout=f if not dryrun else None,
            )
        try:
            stats_file_rel = stats_file.relative_to(cli.HOLOHUB_ROOT)
        except ValueError:
            stats_file_rel = stats_file
        if dryrun:
            holohub_cli_util.info(
                f"Sccache stats (dry-run) would be written to {stats_file_rel}"
            )
        else:
            holohub_cli_util.info(f"Sccache stats written to {stats_file_rel}")

    # If this is a package, run cpack
    if project_type == "package":
        pkg_build_dir = build_dir / "pkg"
        if pkg_build_dir.exists():
            for cpack_config in pkg_build_dir.glob("CPackConfig-*.cmake"):
                holohub_cli_util.run_command(
                    ["cpack", "--config", str(cpack_config), "-G", pkg_generator],
                    dry_run=dryrun,
                    env=build_env,
                )

    # Handle benchmark restoration after building
    if (
        benchmark
        and app_source_path
        and project_type in ["application", "workflow", "benchmark"]
    ):
        restore_script = (
            cli.HOLOHUB_ROOT / "benchmarks/holoscan_flow_benchmarking/restore_application.sh"
        )
        holohub_cli_util.run_command(
            [str(restore_script), str(app_source_path)], dry_run=dryrun
        )

    return build_dir, project_data


def handle_build(cli, args: argparse.Namespace) -> None:
    """Handle build command"""
    from holoscan_cli.cli import in_container_cli_command

    # Handle mode-specific configuration
    project_data = cli.find_project(args.project, language=args.language)
    mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
    cli.validate_mode(args, mode_name, mode_config, project_data, getattr(args, "mode", None))

    # Ensure mode_config is a dictionary
    mode_config = mode_config if mode_config is not None else {}

    # Check if build should be skipped
    skip_docker_build, _ = holohub_cli_util.check_skip_builds(args)

    if mode_config:
        print(f"Building {args.project} in '{mode_name}' mode")

    # Apply mode-specific build configuration
    build_args = cli.get_effective_build_config(args, mode_config)

    # Get mode-specific build environment variables
    build_mode_env = mode_config.get("env", {}).copy()
    holohub_cli_util.update_env(build_mode_env, mode_config.get("build", {}).get("env", {}))

    # Check if local mode is requested
    is_local_mode = (
        args.local
        or os.environ.get("HOLOHUB_BUILD_LOCAL")
        or build_mode_env.get("HOLOHUB_BUILD_LOCAL")
    )

    if is_local_mode:
        build_project_locally(
            cli,
            project_name=args.project,
            language=args.language if hasattr(args, "language") else None,
            build_type=args.build_type,
            with_operators=build_args.get("with_operators"),
            dryrun=args.dryrun,
            pkg_generator=getattr(args, "pkg_generator", "DEB"),
            parallel=getattr(args, "parallel", None),
            benchmark=getattr(args, "benchmark", False),
            configure_args=build_args.get("configure_args"),
            extra_env=build_mode_env,
        )
    else:
        # Build in container
        container = cli._make_project_container(
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

        # Build command with all necessary arguments. Use the installed CLI entry
        # point inside the container regardless of how the host invoked us, so the
        # recursion does not depend on a wrapper-script being on the in-container
        # PATH. See in_container_cli_command for the override hook.
        build_cmd = f"{in_container_cli_command()} build {args.project}"
        # Only add mode name if it was explicitly requested by user (not implicitly resolved)
        if mode_name and getattr(args, "mode", None) is not None:
            build_cmd += f" {mode_name}"
        build_cmd += " --local"
        if args.build_type:
            build_cmd += f" --build-type {args.build_type}"
        if args.with_operators:
            build_cmd += f' --build-with "{args.with_operators}"'
        if hasattr(args, "pkg_generator"):
            build_cmd += f" --pkg-generator {args.pkg_generator}"
        if hasattr(args, "language") and args.language:
            build_cmd += f" --language {args.language}"
        if getattr(args, "parallel", None):
            build_cmd += f" --parallel {args.parallel}"
        if args.verbose:
            build_cmd += " --verbose"
        if getattr(args, "benchmark", False):
            build_cmd += " --benchmark"
        if getattr(args, "configure_args", None):
            for configure_arg in args.configure_args:
                build_cmd += f" --configure-args={shlex.quote(configure_arg)}"

        img = getattr(args, "img", None) or container.image_name
        docker_opts = build_args.get("docker_opts", "")
        docker_opts_extra, extra_args = holohub_cli_util.get_entrypoint_command_args(
            img, build_cmd, docker_opts, dry_run=args.dryrun
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


def handle_run(cli, args: argparse.Namespace) -> None:
    """Handle run command"""
    from holoscan_cli.cli import in_container_cli_command

    # Handle mode-specific configuration
    project_data = cli.find_project(args.project, language=args.language)
    mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
    cli.validate_mode(args, mode_name, mode_config, project_data, getattr(args, "mode", None))
    language = normalize_language(
        args.language
        if args.language
        else project_data.get("metadata", {}).get("language", None)
    )

    # Ensure mode_config is a dictionary
    mode_config = mode_config if mode_config is not None else {}

    # Print mode name if it was explicitly requested by user (not implicitly resolved)
    if mode_config:
        print(f"Running {args.project} in '{mode_name}' mode")

    # Get run configuration
    run_config = mode_config.get("run", project_data.get("metadata", {}).get("run", {}))

    if not run_config:
        holohub_cli_util.fatal(f"Project '{args.project}' does not have a run configuration")

    # Get mode-specific build environment variables
    build_mode_env = mode_config.get("env", {}).copy()
    holohub_cli_util.update_env(build_mode_env, mode_config.get("build", {}).get("env", {}))

    # Get mode-specific run environment variables
    run_mode_env = mode_config.get("env", {}).copy()
    holohub_cli_util.update_env(run_mode_env, run_config.get("env", {}))

    # Check if builds should be skipped
    skip_docker_build, skip_local_build = holohub_cli_util.check_skip_builds(args)

    # Check if local mode is requested
    is_local_mode = (
        args.local
        or os.environ.get("HOLOHUB_BUILD_LOCAL")
        or build_mode_env.get("HOLOHUB_BUILD_LOCAL")
        or run_mode_env.get("HOLOHUB_BUILD_LOCAL")
    )

    # Apply mode-specific build configuration for build process
    build_args = cli.get_effective_build_config(args, mode_config)

    # Apply mode-specific run configuration
    run_args = cli.get_effective_run_config(args, mode_config)

    if is_local_mode:
        if args.docker_opts:
            holohub_cli_util.fatal(
                "Container arguments were provided with `--docker-opts` but a non-containerized build was requested."
            )
        if skip_local_build:
            # Skip building; reuse previously resolved project_data and build directory
            build_dir = cli.DEFAULT_BUILD_PARENT_DIR / args.project
            if not build_dir.is_dir() and not args.dryrun:
                holohub_cli_util.fatal(
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
        path_mapping = holohub_cli_util.build_holohub_path_mapping(
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
        run_env["HOLOHUB_DATA_PATH"] = str(cli.DEFAULT_DATA_DIR)
        run_env["HOLOSCAN_INPUT_PATH"] = run_env.get(
            "HOLOSCAN_INPUT_PATH", str(cli.DEFAULT_DATA_DIR)
        )
        # Apply mode environment variables (mode.run.env takes precedence over run.env)
        holohub_cli_util.update_env(
            run_env, run_mode_env, path_mapping, verbose=(args.verbose or args.dryrun)
        )

        # Process command template using the path mapping and environment variables
        cmd = holohub_cli_util.replace_placeholders(run_config["command"], path_mapping)

        # Use effective run args (which may come from mode or CLI)
        effective_run_args = run_args.get("run_args")
        if effective_run_args:
            cmd_args = shlex.split(effective_run_args)
            if isinstance(cmd, str):  # Ensure cmd is a list of arguments
                cmd = shlex.split(cmd)
            cmd.extend(cmd_args)

        if language == "cpp":
            if not build_dir.is_dir() and not args.dryrun:
                holohub_cli_util.fatal(
                    f"The build directory {build_dir} for this application does not exist.\n"
                    f"Did you forget to '{cli.script_name} build {args.project}'?"
                )

        workdir_spec = run_config.get("workdir", f"{cli.prefix}app_bin")
        if not workdir_spec:
            target_dir = Path(path_mapping.get(f"{cli.prefix}root", "."))
        elif workdir_spec in path_mapping:
            target_dir = Path(path_mapping[workdir_spec])
        else:
            target_dir = Path(workdir_spec)
        print(holohub_cli_util.format_cmd("cd " + str(target_dir), is_dryrun=args.dryrun))
        if not args.dryrun:
            os.chdir(target_dir)

        # Print environment setup
        if args.verbose or args.dryrun:
            print(
                holohub_cli_util.format_cmd(
                    "export PYTHONPATH=" + run_env["PYTHONPATH"], is_dryrun=args.dryrun
                )
            )
            print(
                holohub_cli_util.format_cmd(
                    "export HOLOHUB_DATA_PATH=" + run_env["HOLOHUB_DATA_PATH"],
                    is_dryrun=args.dryrun,
                )
            )
            print(
                holohub_cli_util.format_cmd(
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
                holohub_cli_util.fatal(
                    "Nsight Systems CLI command 'nsys' not found. No Nsight installation from the host is also mounted."
                )
            nsys_cmd = "/opt/nvidia/nsys-host/bin/nsys" if not shutil.which("nsys") else "nsys"

            # Check perf_event_paranoid level
            if not args.dryrun:
                try:
                    with open("/proc/sys/kernel/perf_event_paranoid") as f:
                        if int(f.read()) > 2:
                            holohub_cli_util.fatal(
                                "For Nsight Systems profiling the Linux operating system's perf_event_paranoid level must be 2 or less."
                            )
                except (IOError, ValueError):
                    pass

            cmd = f"{nsys_cmd} profile --trace=cuda,vulkan,nvtx,osrt {cmd}"

        cmd_to_run = cmd if isinstance(cmd, list) else shlex.split(cmd)
        holohub_cli_util.run_command(cmd_to_run, env=run_env, dry_run=args.dryrun)
    else:
        container = cli._make_project_container(
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
        docker_opts_extra, extra_args = holohub_cli_util.get_entrypoint_command_args(
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
            as_root=getattr(args, "as_root", False),
            docker_opts=docker_opts,
            add_volumes=getattr(args, "add_volume", None),
            enable_mps=getattr(args, "mps", False),
            extra_args=extra_args,
        )


def handle_install(cli, args: argparse.Namespace) -> None:
    """Handle install command"""
    from holoscan_cli.cli import in_container_cli_command

    # Handle mode-specific configuration (if project has modes)
    project_data = cli.find_project(args.project, language=args.language)
    mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
    cli.validate_mode(args, mode_name, mode_config, project_data, getattr(args, "mode", None))

    # Ensure mode_config is a dictionary
    mode_config = mode_config if mode_config is not None else {}

    # Check if build should be skipped
    skip_docker_build, _ = holohub_cli_util.check_skip_builds(args)

    if mode_config:
        print(f"Installing {args.project} in '{mode_name}' mode")

    # Apply mode-specific build configuration
    build_args = cli.get_effective_build_config(args, mode_config)

    # Get mode-specific build environment variables
    build_mode_env = mode_config.get("env", {}).copy()
    holohub_cli_util.update_env(build_mode_env, mode_config.get("build", {}).get("env", {}))

    # Check if local mode is requested
    is_local_mode = (
        args.local
        or os.environ.get("HOLOHUB_BUILD_LOCAL")
        or build_mode_env.get("HOLOHUB_BUILD_LOCAL")
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
        path_mapping = holohub_cli_util.build_holohub_path_mapping(
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
            holohub_cli_util.update_env(
                install_env, build_mode_env, path_mapping, verbose=(args.verbose or args.dryrun)
            )

        # Install the project
        holohub_cli_util.run_command(
            ["cmake", "--install", str(build_dir)], dry_run=args.dryrun, env=install_env
        )
        if not args.dryrun:
            print(f"{Color.green('Successfully installed')} {args.project}")
    else:
        # Install in container
        container = cli._make_project_container(
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
        docker_opts_extra, extra_args = holohub_cli_util.get_entrypoint_command_args(
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
