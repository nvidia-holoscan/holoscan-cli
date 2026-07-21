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

"""``holoscan build`` — build a source project locally or in a container.

Also exports ``build_project_locally``, the shared helper used by the
``build``, ``install`` and ``run`` commands to drive ``cmake`` directly
on the host (i.e. the ``--local`` branch of the project lifecycle
commands).
"""

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Optional

from holoscan_cli.commands.registry import help_for
from holoscan_cli.metadata.utils import normalize_language
from holoscan_cli.utils.cmake_manifest import write_external_operators_manifest
from holoscan_cli.utils.docker import get_entrypoint_command_args
from holoscan_cli.utils.external_resolver import (
    merge_deps,
    parse_module_dependencies,
    parse_module_sites,
)
from holoscan_cli.utils.holohub import (
    build_holohub_path_mapping,
    check_skip_builds,
    determine_project_prefix,
    get_buildtype_str,
    get_sccache_dir,
    is_env_request_local_build,
    update_env,
)
from holoscan_cli.utils.io import fatal, info, run_command, warn
from holoscan_cli.utils.text import get_env_bool


def make_local_build_command(
    cli_command: str,
    args: argparse.Namespace,
    mode_name: str | None,
    language: str | None,
) -> str:
    """Build the recursive local-build command used inside a container."""
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
    if getattr(args, "benchmark", False):
        command += " --benchmark"
    for configure_arg in getattr(args, "configure_args", None) or []:
        command += f" --configure-args={shlex.quote(configure_arg)}"
    return command


def register_build_parser(
    cli, subparsers, *, container_build, container_run
) -> argparse.ArgumentParser:
    """Register the ``build`` subcommand."""
    parser = subparsers.add_parser(
        "build", help=help_for("build"), parents=[container_build, container_run]
    )
    parser.add_argument("project", help="Project to build")
    parser.add_argument("mode", nargs="?", help="Mode to build (optional)")
    parser.add_argument(
        "--local", action="store_true", help="Build locally instead of in container"
    )
    parser.add_argument("--verbose", action="store_true", help="Print extra output")
    parser.add_argument(
        "--build-type",
        help="Build type (debug, release, rel-debug). "
        "If not specified, uses CMAKE_BUILD_TYPE environment variable or defaults to 'release'",
    )
    parser.add_argument(
        "--build-with",
        dest="with_operators",
        help="Optional operators that should be built, separated by semicolons (;)",
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--pkg-generator", default="DEB", help="Package generator for cpack (default: DEB)"
    )
    parser.add_argument(
        "--parallel", help="Number of parallel build jobs (e.g. --parallel $(($(nproc)-1)))"
    )
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Build for Holoscan Flow Benchmarking. Valid for applications/workflows only",
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
    parser.set_defaults(func=lambda args: handle_build(cli, args))
    return parser


def handle_build(cli, args: argparse.Namespace) -> None:
    """Handle build command"""
    from holoscan_cli.cli import in_container_cli_command

    # Handle mode-specific configuration
    project_data = cli.find_project(args.project, language=args.language)
    mode_name, mode_config = cli.resolve_mode(project_data, getattr(args, "mode", None))
    cli.validate_mode(mode_name, mode_config)

    # Ensure mode_config is a dictionary
    mode_config = mode_config if mode_config is not None else {}

    # Check if build should be skipped
    skip_docker_build, _ = check_skip_builds(args)

    if mode_config:
        print(f"Building {args.project} in '{mode_name}' mode")

    # Apply mode-specific build configuration
    build_args = cli.get_effective_build_config(args, mode_config)

    # Get mode-specific build environment variables
    build_mode_env = mode_config.get("env", {}).copy()
    update_env(build_mode_env, mode_config.get("build", {}).get("env", {}))

    # Check if local mode is requested
    is_local_mode = args.local or is_env_request_local_build(build_mode_env)

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

        # Use the installed CLI entry point inside the container regardless of
        # how the host invoked us, so recursion does not depend on a wrapper
        # script being on the in-container PATH.
        build_cmd = make_local_build_command(
            in_container_cli_command(), args, mode_name, args.language
        )

        img = getattr(args, "img", None) or container.image_name
        docker_opts = build_args.get("docker_opts", "")
        docker_opts_extra, extra_args = get_entrypoint_command_args(
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
            run_command([str(patch_script), str(app_source_path)], dry_run=dryrun)
            print("Building for Holoscan Flow Benchmarking")
        else:
            fatal("--benchmark option is only available for applications/workflows")

    build_type = get_buildtype_str(build_type)
    build_dir = cli.DEFAULT_BUILD_PARENT_DIR / project_name
    build_dir.mkdir(parents=True, exist_ok=True)

    # Prepare environment with extra env vars first so that HOLOSCAN_CLI_LOCAL_*
    # overrides from the mode's env block are visible to the module resolvers.
    build_env = os.environ.copy()
    if extra_env:
        path_mapping = build_holohub_path_mapping(
            holohub_root=cli.HOLOHUB_ROOT,
            project_data=project_data,
            build_dir=build_dir,
            data_dir=cli.DEFAULT_DATA_DIR,
            prefix=cli.prefix,
            verbose=dryrun,
        )
        update_env(build_env, extra_env, path_mapping, verbose=dryrun)

    # Write external_operators_manifest.cmake before cmake configure so that
    # CMakeLists.txt:include(…OPTIONAL) picks it up and FetchContent_MakeAvailable
    # is called for any external modules whose operators end up enabled.
    sites_deps = parse_module_sites(
        cli.HOLOHUB_ROOT / "modules" / "module-sites.json",
        source_root=cli.HOLOHUB_ROOT,
        env=build_env,
    )
    # Only parse the project's own metadata.json when we know where it lives —
    # an empty source_folder would otherwise resolve to a cwd-relative
    # "metadata.json" and pick up an unrelated file.
    source_folder = project_data.get("source_folder")
    project_deps = (
        parse_module_dependencies(
            Path(source_folder) / "metadata.json", source_root=cli.HOLOHUB_ROOT, env=build_env
        )
        if source_folder
        else []
    )
    ext_deps = merge_deps(sites_deps, project_deps)
    manifest_path = build_dir / "external_operators_manifest.cmake"
    if dryrun:
        info(f"[dryrun] Would write {manifest_path}")
    else:
        write_external_operators_manifest(ext_deps, manifest_path)

    proj_prefix = determine_project_prefix(project_type)
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
    ]
    if project_type == "module":
        module_slug = project_name.replace("-", "_")
        cmake_args.append(f"-D{proj_prefix}_{module_slug}=ON")
        subprojects = project_data.get("metadata", {}).get("subprojects", {})
        ops = subprojects.get("operators", [])
        apps = subprojects.get("applications", [])
        parts = ([f"operators: {ops}"] if ops else []) + ([f"applications: {apps}"] if apps else [])
        detail = f": enabling {', '.join(parts)}" if parts else ""
        print(f"Building module '{project_name}'{detail}")
        for op in ops:
            cmake_args.append(f"-DOP_{op}=ON")
        for app in apps:
            cmake_args.append(f"-DAPP_{app}=ON")
    else:
        cmake_args.append(f"-D{proj_prefix}_{project_name}=ON")
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
    enable_sccache_val, enable_sccache = get_env_bool("HOLOSCAN_CLI_ENABLE_SCCACHE", default=False)
    info(f"HOLOSCAN_CLI_ENABLE_SCCACHE={enable_sccache_val}")
    if enable_sccache:
        if not sccache_bin:
            (warn if dryrun else fatal)(
                "HOLOSCAN_CLI_ENABLE_SCCACHE is enabled but 'sccache' was not found in PATH. "
                "Install it (e.g., `holoscan setup`) or disable sccache."
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
        build_env.setdefault("SCCACHE_DIR", get_sccache_dir(build_env))
        build_env.setdefault("SCCACHE_CACHE_SIZE", "20G")
        # Print SCCACHE environment variables
        info(f"Using sccache: {sccache_bin}")
        for key, value in build_env.items():
            if key.startswith("SCCACHE_"):
                info(f"{key}={value}")
    elif sccache_bin:
        warn(
            "Detected 'sccache' in PATH but HOLOSCAN_CLI_ENABLE_SCCACHE is disabled. "
            "Skipping sccache."
        )

    if configure_args:
        cmake_args.extend(os.path.expandvars(arg) for arg in configure_args)

    run_command(cmake_args, dry_run=dryrun, env=build_env)

    # Build the project with optional parallel jobs
    build_cmd = ["cmake", "--build", str(build_dir), "--config", build_type]
    # Determine the number of parallel jobs (user input > env var > CPU count):
    if parallel is not None:
        build_njobs = str(parallel)
    else:
        build_njobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL", str(os.cpu_count()))
    build_cmd.extend(["-j", build_njobs])

    run_command(build_cmd, dry_run=dryrun, env=build_env)

    # Print sccache stats
    if enable_sccache:
        stats_file = build_dir / "sccache-stats.txt"
        with open(stats_file, "w", encoding="utf-8") as f:
            run_command(
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
            info(f"Sccache stats (dry-run) would be written to {stats_file_rel}")
        else:
            info(f"Sccache stats written to {stats_file_rel}")

    # If this is a package, run cpack
    if project_type == "package":
        pkg_build_dir = build_dir / "pkg"
        if pkg_build_dir.exists():
            for cpack_config in pkg_build_dir.glob("CPackConfig-*.cmake"):
                run_command(
                    ["cpack", "--config", str(cpack_config), "-G", pkg_generator],
                    dry_run=dryrun,
                    env=build_env,
                )

    # Handle benchmark restoration after building
    if benchmark and app_source_path and project_type in ["application", "workflow", "benchmark"]:
        restore_script = (
            cli.HOLOHUB_ROOT / "benchmarks/holoscan_flow_benchmarking/restore_application.sh"
        )
        run_command([str(restore_script), str(app_source_path)], dry_run=dryrun)

    return build_dir, project_data
