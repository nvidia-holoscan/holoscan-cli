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
from holoscan_cli.configuration import (
    append_config_vector_flags,
    apply_container_cli_overrides,
    report_effective_configuration,
)
from holoscan_cli.metadata.utils import normalize_language
from holoscan_cli.project_context import (
    activated_environment_source,
    get_active_project_context,
)
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
from holoscan_cli.utils.sdk import find_hsdk_build_rel_dir, is_valid_sdk_installation
from holoscan_cli.utils.text import get_env_bool


def make_local_build_command(
    cli_command: str,
    args: argparse.Namespace,
    mode_name: str | None,
    language: str | None,
    effective_build_type: str | None = None,
) -> str:
    """Build the recursive local-build command used inside a container."""
    command = [*shlex.split(cli_command), "build", str(args.project)]
    if mode_name and getattr(args, "mode", None) is not None:
        command.append(str(mode_name))
    command.append("--local")
    # Serialize the effective value, not only an explicit flag. Otherwise an
    # ambient/project CMAKE_BUILD_TYPE disappears at the container boundary.
    command.extend(
        [
            "--build-type",
            str(effective_build_type or get_buildtype_str(getattr(args, "build_type", None))),
        ]
    )
    if getattr(args, "with_operators", None) is not None:
        command.append(f"--build-with={args.with_operators}")
    if getattr(args, "pkg_generator", None):
        command.extend(["--pkg-generator", str(args.pkg_generator)])
    if language:
        command.extend(["--language", str(language)])
    if getattr(args, "parallel", None) is not None:
        command.extend(["--parallel", str(args.parallel)])
    if args.verbose:
        command.append("--verbose")
    if getattr(args, "benchmark", False):
        command.append("--benchmark")
    append_config_vector_flags(command, args)
    if getattr(args, "replace_configure_args", False):
        command.append("--replace-configure-args")
    for configure_arg in getattr(args, "configure_args", None) or []:
        command.append(f"--configure-args={configure_arg}")
    return shlex.join(command)


def resolve_local_sdk_dir(
    cli,
    local_sdk_root: Optional[str | Path] = None,
    environ: Optional[dict[str, str]] = None,
) -> Path:
    """Resolve an explicit local SDK root without falling through to lower layers."""
    source_environment = os.environ if environ is None else environ
    context = get_active_project_context()
    if context is not None and getattr(context, "is_standalone_module", False):
        if context.sdk_root is not None:
            return context.sdk_root
        if local_sdk_root is not None:
            source_label = f"--local-sdk-root {local_sdk_root}"
        elif (
            source_environment.get("HOLOSCAN_SDK_ROOT")
            and activated_environment_source("HOLOSCAN_SDK_ROOT") == "environment"
        ):
            source_label = f"HOLOSCAN_SDK_ROOT={source_environment['HOLOSCAN_SDK_ROOT']}"
        else:
            return Path(cli.DEFAULT_SDK_DIR)
        fatal(
            f"{source_label} does not contain a Holoscan SDK installation for "
            f"{context.target_arch or 'the selected architecture'}."
        )

    if local_sdk_root is None:
        local_sdk_root = source_environment.get("HOLOSCAN_SDK_ROOT")
        if local_sdk_root is None:
            return Path(cli.DEFAULT_SDK_DIR)
        source_label = f"HOLOSCAN_SDK_ROOT={local_sdk_root}"
    else:
        source_label = f"--local-sdk-root {local_sdk_root}"

    requested_root = Path(local_sdk_root).expanduser().resolve()
    build_dir = find_hsdk_build_rel_dir(requested_root)
    installation = Path(build_dir) if Path(build_dir).is_absolute() else requested_root / build_dir
    if not is_valid_sdk_installation(installation):
        fatal(
            f"{source_label} does not contain a Holoscan SDK "
            "installation (expected lib/cmake/holoscan directly or under an "
            "install-* or build-* directory)."
        )
    return installation


def resolve_effective_build_type(
    explicit_build_type: Optional[str], mode_environment: Optional[dict[str, str]] = None
) -> str:
    """Resolve CLI/process/mode/project build type before container recursion."""
    effective_environment = os.environ.copy()
    if mode_environment:
        update_env(
            effective_environment,
            mode_environment,
            overwrite=False,
            project_defaults_are_lower=True,
        )
    return get_buildtype_str(explicit_build_type, environ=effective_environment)


def register_build_parser(
    cli, subparsers, *, container_build, container_run
) -> argparse.ArgumentParser:
    """Register the ``build`` subcommand."""
    parser = subparsers.add_parser(
        "build", help=help_for("build"), parents=[container_build, container_run]
    )
    parser.add_argument("project", help="Project to build")
    parser.add_argument("mode", nargs="?", help="Mode to build (optional)")
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--local", dest="local", action="store_true", help="Build locally")
    location.add_argument(
        "--container", dest="local", action="store_false", help="Build in a container"
    )
    parser.set_defaults(local=None)
    parser.add_argument("--verbose", action="store_true", help="Print extra output")
    parser.add_argument(
        "--build-type",
        help=(
            "Build type (debug, release, rel-debug). Precedence: this option, "
            "CMAKE_BUILD_TYPE, selected mode, pyproject.toml, then release"
        ),
    )
    parser.add_argument(
        "--build-with",
        dest="with_operators",
        help=(
            "Complete operator selection, separated by semicolons (;). Replaces the "
            "selected mode's build.depends; use --build-with= to clear it"
        ),
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
        help="Build for Holoscan Flow Benchmarking. Valid for applications and benchmarks only",
    )
    docker_build = parser.add_mutually_exclusive_group()
    docker_build.add_argument(
        "--no-docker-build",
        dest="no_docker_build",
        action="store_true",
        help="Skip building the container",
    )
    docker_build.add_argument(
        "--docker-build",
        dest="no_docker_build",
        action="store_false",
        help="Build the container even when HOLOSCAN_CLI_ALWAYS_BUILD disables it",
    )
    parser.set_defaults(no_docker_build=None)
    parser.add_argument(
        "--replace-configure-args",
        action="store_true",
        help="Ignore CMake configure arguments from the selected mode; use only --configure-args",
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
    effective_build_type = resolve_effective_build_type(args.build_type, build_mode_env)

    # Check if local mode is requested
    is_local_mode = (
        args.local if args.local is not None else is_env_request_local_build(build_mode_env)
    )

    if is_local_mode:
        report_effective_configuration(
            args,
            mode_name=mode_name,
            mode_config=mode_config,
            location_mode_environment=build_mode_env,
            effective_build_type=effective_build_type,
            is_local_mode=True,
            default_sdk_root=cli.DEFAULT_SDK_DIR,
            include_configure=True,
        )
        build_project_locally(
            cli,
            project_name=args.project,
            language=args.language if hasattr(args, "language") else None,
            build_type=args.build_type,
            with_operators=build_args.get("with_operators"),
            dryrun=args.dryrun,
            verbose=args.verbose,
            pkg_generator=getattr(args, "pkg_generator", "DEB"),
            parallel=getattr(args, "parallel", None),
            benchmark=getattr(args, "benchmark", False),
            configure_args=build_args.get("configure_args"),
            extra_env=build_mode_env,
            local_sdk_root=getattr(args, "local_sdk_root", None),
        )
    else:
        # Build in container
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
            location_mode_environment=build_mode_env,
            effective_build_type=effective_build_type,
            is_local_mode=False,
            default_sdk_root=cli.DEFAULT_SDK_DIR,
            container=container,
            include_build=not skip_docker_build,
            include_run=True,
            include_configure=True,
        )
        if not skip_docker_build:
            container.build(
                docker_file=args.docker_file,
                base_img=args.base_img,
                img=args.img,
                no_cache=args.no_cache,
                build_args=build_args.get("build_args"),
                mode_build_args=build_args.get("mode_build_args"),
                cuda_version=getattr(args, "cuda", None),
                extra_scripts=getattr(args, "extra_scripts", []),
                include_default_build_args=build_args.get("include_default_build_args", True),
            )
        # Use the installed CLI entry point inside the container regardless of
        # how the host invoked us, so recursion does not depend on a wrapper
        # script being on the in-container PATH.
        build_cmd = make_local_build_command(
            in_container_cli_command(),
            args,
            mode_name,
            args.language,
            effective_build_type,
        )

        img = container.resolve_run_image(getattr(args, "img", None))
        docker_opts = container.compose_run_args(
            mode_docker_opts=build_args.get("mode_docker_opts"),
            docker_opts=build_args.get("docker_opts", ""),
            include_default_run_args=build_args.get("include_default_run_args", True),
        )
        docker_opts_extra, extra_args = get_entrypoint_command_args(
            img, build_cmd, docker_opts, dry_run=args.dryrun
        )
        if docker_opts_extra:
            docker_opts = f"{docker_opts} {docker_opts_extra}".strip()
        container.run(
            img=img,
            local_sdk_root=getattr(args, "local_sdk_root", None),
            enable_x11=getattr(args, "enable_x11", True),
            ssh_x11=getattr(args, "ssh_x11", False),
            use_tini=getattr(args, "init", False),
            persistent=getattr(args, "persistent", False),
            nsys_profile=getattr(args, "nsys_profile", False),
            nsys_location=getattr(args, "nsys_location", ""),
            as_root=getattr(args, "as_root", False),
            docker_opts=docker_opts,
            include_default_run_args=False,
            forward_env=getattr(args, "forward_env", None),
            include_default_forward_env=not getattr(args, "replace_forward_env", False),
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
    verbose: bool = False,
    pkg_generator: str = "DEB",
    parallel: Optional[str] = None,
    benchmark: bool = False,
    configure_args: Optional[list[str]] = None,
    extra_env: Optional[dict] = None,
    local_sdk_root: Optional[str | Path] = None,
) -> tuple[Path, dict]:
    """Helper to build a project locally (cmake + cmake --build)."""
    project_data = cli.find_project(project_name=project_name, language=language)
    project_type = project_data.get("project_type", "application")

    # Handle benchmark patching before building
    app_source_path = None
    if benchmark:
        if project_type in ["application", "benchmark"]:
            app_source_path = project_data.get("source_folder", "")
            patch_script = (
                cli.HOLOHUB_ROOT / "benchmarks/holoscan_flow_benchmarking/patch_application.sh"
            )
            run_command([str(patch_script), str(app_source_path)], dry_run=dryrun)
            print("Building for Holoscan Flow Benchmarking")
        else:
            fatal("--benchmark option is only available for applications and benchmarks")

    build_dir = cli.DEFAULT_BUILD_PARENT_DIR / project_name
    if not dryrun:
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
        update_env(
            build_env,
            extra_env,
            path_mapping,
            verbose=(verbose or dryrun),
            overwrite=False,
            project_defaults_are_lower=True,
        )

    # Resolve layered build controls from the already-composed environment:
    # explicit CLI > process environment > mode defaults > built-in.
    build_type = get_buildtype_str(build_type, environ=build_env)
    sdk_dir = resolve_local_sdk_dir(cli, local_sdk_root, environ=build_env)

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
    ]
    resolved_cmake_args = [
        f"-DPython3_EXECUTABLE={sys.executable}",
        f"-DPython3_ROOT_DIR={os.path.dirname(os.path.dirname(sys.executable))}",
        f"-DCMAKE_BUILD_TYPE={build_type}",
        f"-DCMAKE_PREFIX_PATH={sdk_dir}/lib",
        f"-DHOLOHUB_DATA_DIR:PATH={cli.DEFAULT_DATA_DIR}",
    ]
    if project_type == "module":
        module_slug = project_name.replace("-", "_")
        resolved_cmake_args.append(f"-D{proj_prefix}_{module_slug}=ON")
        subprojects = project_data.get("metadata", {}).get("subprojects", {})
        ops = subprojects.get("operators", [])
        apps = subprojects.get("applications", [])
        parts = ([f"operators: {ops}"] if ops else []) + ([f"applications: {apps}"] if apps else [])
        detail = f": enabling {', '.join(parts)}" if parts else ""
        print(f"Building module '{project_name}'{detail}")
        for op in ops:
            resolved_cmake_args.append(f"-DOP_{op}=ON")
        for app in apps:
            resolved_cmake_args.append(f"-DAPP_{app}=ON")
    else:
        resolved_cmake_args.append(f"-D{proj_prefix}_{project_name}=ON")
    # Add benchmark-specific CMake flags
    if benchmark:
        resolved_cmake_args.append(
            f"-DCMAKE_CXX_FLAGS=-I{cli.HOLOHUB_ROOT}/benchmarks/holoscan_flow_benchmarking"
        )

    # use -G Ninja if available
    if shutil.which("ninja"):
        cmake_args.extend(["-G", "Ninja"])
    # Add optional operators if specified
    if with_operators:
        resolved_cmake_args.append(f'-DHOLOHUB_BUILD_OPERATORS="{with_operators}"')

    if not language:
        language = normalize_language(project_data.get("metadata", {}).get("language", None))
    # Set build flags based on language
    if language == "python":
        resolved_cmake_args.append("-DHOLOHUB_BUILD_PYTHON=ON")
        resolved_cmake_args.append("-DHOLOHUB_BUILD_CPP=OFF")
    elif language == "cpp":
        resolved_cmake_args.append("-DHOLOHUB_BUILD_PYTHON=OFF")
        resolved_cmake_args.append("-DHOLOHUB_BUILD_CPP=ON")

    # Configure sccache
    sccache_bin = shutil.which("sccache")
    enable_sccache_val, enable_sccache = get_env_bool(
        "HOLOSCAN_CLI_ENABLE_SCCACHE", default=False, environ=build_env
    )
    info(f"HOLOSCAN_CLI_ENABLE_SCCACHE={enable_sccache_val}")
    if enable_sccache:
        if not sccache_bin:
            (warn if dryrun else fatal)(
                "HOLOSCAN_CLI_ENABLE_SCCACHE is enabled but 'sccache' was not found in PATH. "
                "Install it (e.g., `holoscan setup`) or disable sccache."
            )
        # Set CMake compiler launchers with -D
        if language != "python":
            resolved_cmake_args.extend(
                [
                    f"-DCMAKE_C_COMPILER_LAUNCHER={sccache_bin}",
                    f"-DCMAKE_CXX_COMPILER_LAUNCHER={sccache_bin}",
                    f"-DCMAKE_CUDA_COMPILER_LAUNCHER={sccache_bin}",
                ]
            )
        # Set default SCCACHE properties if not set
        build_env.setdefault("SCCACHE_DIR", get_sccache_dir(build_env))
        build_env.setdefault("SCCACHE_CACHE_SIZE", "20G")
        # Print SCCACHE names only. Backends and endpoints may embed credentials,
        # and this output is commonly captured by CI logs.
        info(f"Using sccache: {sccache_bin}")
        for key in build_env:
            if key.startswith("SCCACHE_"):
                info(f"{key}=<configured>")
    elif sccache_bin:
        warn(
            "Detected 'sccache' in PATH but HOLOSCAN_CLI_ENABLE_SCCACHE is disabled. "
            "Skipping sccache."
        )

    raw_configure_start = len(cmake_args)
    if configure_args:
        cmake_args.extend(os.path.expandvars(arg) for arg in configure_args)
    raw_configure_end = len(cmake_args)
    # Typed CLI/environment/project values are resolved settings. Keep them
    # after the free-form mode/CLI extension vector so lower raw CMake entries
    # cannot overturn --build-type, --language, paths, or selected targets.
    cmake_args.extend(resolved_cmake_args)

    display_cmake_args = list(cmake_args)
    if raw_configure_end > raw_configure_start:
        entry_count = raw_configure_end - raw_configure_start
        display_cmake_args[raw_configure_start:raw_configure_end] = [
            f"<{entry_count} configured CMake option(s) hidden>"
        ]

    run_command(
        cmake_args,
        dry_run=dryrun,
        env=build_env,
        display_override=display_cmake_args,
    )

    # Build the project with optional parallel jobs
    build_cmd = ["cmake", "--build", str(build_dir), "--config", build_type]
    # Determine the number of parallel jobs (user input > env var > CPU count):
    if parallel is not None:
        build_njobs = str(parallel)
    else:
        build_njobs = build_env.get("CMAKE_BUILD_PARALLEL_LEVEL", str(os.cpu_count()))
    build_cmd.extend(["-j", build_njobs])

    run_command(build_cmd, dry_run=dryrun, env=build_env)

    # Print sccache stats
    if enable_sccache:
        stats_file = build_dir / "sccache-stats.txt"
        if dryrun:
            run_command(["sccache", "--show-stats"], dry_run=True, env=build_env)
        else:
            with open(stats_file, "w", encoding="utf-8") as f:
                run_command(
                    ["sccache", "--show-stats"],
                    env=build_env,
                    stdout=f,
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
    if benchmark and app_source_path and project_type in ["application", "benchmark"]:
        restore_script = (
            cli.HOLOHUB_ROOT / "benchmarks/holoscan_flow_benchmarking/restore_application.sh"
        )
        run_command([str(restore_script), str(app_source_path)], dry_run=dryrun)

    return build_dir, project_data
