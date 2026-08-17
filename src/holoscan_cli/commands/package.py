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

"""``holoscan package`` - build distribution artifacts for Holoscan Modules."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Optional

from holoscan_cli.commands.build import resolve_local_sdk_dir
from holoscan_cli.commands.registry import help_for
from holoscan_cli.configuration import (
    append_config_vector_flags,
    apply_container_cli_overrides,
    report_effective_configuration,
    resolve_cli_docker_opts,
)
from holoscan_cli.metadata.utils import resolve_module_name
from holoscan_cli.utils.docker import get_entrypoint_command_args
from holoscan_cli.utils.holohub import (
    check_skip_builds,
    get_buildtype_str,
    is_env_request_local_build,
)
from holoscan_cli.utils.io import Color, fatal, run_command


def register_package_parser(
    cli, subparsers, *, container_build, container_run
) -> argparse.ArgumentParser:
    """Register the ``package`` subcommand."""
    parser = subparsers.add_parser(
        "package", help=help_for("package"), parents=[container_build, container_run]
    )
    parser.add_argument(
        "project",
        type=str,
        nargs="?",
        default=None,
        help="Module name to package (default: read ./metadata.json from cwd)",
    )
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--local", dest="local", action="store_true", help="Package locally")
    location.add_argument(
        "--container", dest="local", action="store_false", help="Package in a container"
    )
    parser.set_defaults(local=None)
    parser.add_argument(
        "--build-type",
        type=str,
        default=None,
        help=(
            "Build type (debug, release, rel-debug). Precedence: this option, "
            "CMAKE_BUILD_TYPE, standalone project configuration, then release"
        ),
    )
    parser.add_argument(
        "--pkg-generator",
        type=str,
        default="DEB",
        dest="pkg_generator",
        help="Comma-separated package generators: DEB, WHEEL (default: DEB)",
    )
    parser.add_argument("--language", choices=["cpp", "python"], default=None)
    parser.add_argument(
        "--parallel",
        help="Number of parallel build jobs (default: CMAKE_BUILD_PARALLEL_LEVEL or CPU count)",
    )
    parser.add_argument("--verbose", action="store_true")
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
    parser.add_argument("--dryrun", action="store_true", default=False)
    parser.set_defaults(func=lambda args: handle_package(cli, args))
    return parser


def _normalize_module_name(value: str) -> str:
    normalized = value.lower().replace("-", "_")
    if normalized.startswith("holoscan_"):
        normalized = normalized[len("holoscan_") :]
    return normalized


def _resolve_module_project(cli, project_arg: Optional[str], language: Optional[str]) -> dict:
    """Resolve a module from matching cwd metadata or the active source tree."""
    cwd = Path.cwd()
    cwd_meta = cwd / "metadata.json"
    if cwd_meta.exists():
        try:
            data = json.loads(cwd_meta.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = None
        if isinstance(data, dict) and "module" in data:
            module = data["module"]
            module_name = resolve_module_name(module, cwd.name)
            if project_arg is None or _normalize_module_name(project_arg) in {
                _normalize_module_name(module_name),
                _normalize_module_name(cwd.name),
            }:
                return {
                    "project_type": "module",
                    "project_name": module_name,
                    "source_folder": str(cwd),
                    "metadata": module,
                }

    if project_arg:
        project_data = cli.find_project(project_arg, language=language)
        project_type = project_data.get("project_type", "application")
        if project_type != "module":
            fatal(
                f"'holoscan package' only supports modules; "
                f"'{project_arg}' is type '{project_type}'"
            )
        return dict(project_data)

    fatal(
        "No project specified and no ./metadata.json found in the current working directory. "
        "Run from a module project root, or pass a module name as the first argument."
    )


def handle_package(cli, args: argparse.Namespace) -> None:
    """Configure a Holoscan Module and build package artifacts."""
    from holoscan_cli.cli import in_container_cli_command

    is_local_mode = args.local if args.local is not None else is_env_request_local_build()
    effective_build_type = get_buildtype_str(getattr(args, "build_type", None))

    if is_local_mode:
        report_effective_configuration(
            args,
            effective_build_type=effective_build_type,
            is_local_mode=True,
            default_sdk_root=cli.DEFAULT_SDK_DIR,
        )
        project_data = _resolve_module_project(
            cli, args.project, language=getattr(args, "language", None)
        )
        _package_locally(cli, args, project_data)
        return

    container = cli.make_project_container(
        project_name=args.project,
        language=getattr(args, "language", None),
    )
    apply_container_cli_overrides(args, container)
    container.dryrun = args.dryrun
    container.verbose = getattr(args, "verbose", False)
    skip_docker_build, _ = check_skip_builds(args)
    report_effective_configuration(
        args,
        effective_build_type=effective_build_type,
        is_local_mode=False,
        default_sdk_root=cli.DEFAULT_SDK_DIR,
        container=container,
        include_build=not skip_docker_build,
        include_run=True,
    )
    if not skip_docker_build:
        container.build(
            docker_file=getattr(args, "docker_file", None),
            base_img=getattr(args, "base_img", None),
            img=getattr(args, "img", None),
            no_cache=getattr(args, "no_cache", False),
            cuda_version=getattr(args, "cuda", None),
            build_args=getattr(args, "build_args", ""),
            extra_scripts=getattr(args, "extra_scripts", []),
            include_default_build_args=not getattr(args, "replace_build_args", False),
        )
    build_tokens = [*shlex.split(in_container_cli_command()), "package"]
    if args.project:
        build_tokens.append(str(args.project))
    build_tokens.extend(
        [
            "--local",
            "--build-type",
            effective_build_type,
        ]
    )
    requested_parallel = getattr(args, "parallel", None)
    effective_parallel = (
        requested_parallel
        if requested_parallel is not None
        else os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL")
    )
    if effective_parallel is not None:
        build_tokens.extend(["--parallel", str(effective_parallel)])
    if getattr(args, "pkg_generator", None):
        build_tokens.extend(["--pkg-generator", str(args.pkg_generator)])
    if getattr(args, "language", None):
        build_tokens.extend(["--language", str(args.language)])
    if args.dryrun:
        build_tokens.append("--dryrun")
    if getattr(args, "verbose", False):
        build_tokens.append("--verbose")
    append_config_vector_flags(build_tokens, args)
    build_cmd = shlex.join(build_tokens)

    cli_docker_opts, replace_docker_opts = resolve_cli_docker_opts(args)
    docker_opts = container.compose_run_args(
        docker_opts=cli_docker_opts,
        include_default_run_args=not replace_docker_opts,
    )
    run_image = container.resolve_run_image(getattr(args, "img", None))
    docker_opts_extra, extra_args = get_entrypoint_command_args(
        run_image,
        build_cmd,
        docker_opts,
        dry_run=args.dryrun,
    )
    if docker_opts_extra:
        docker_opts = (docker_opts + " " + docker_opts_extra).strip()
    container.run(
        img=run_image,
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


def _package_locally(cli, args: argparse.Namespace, project_data: dict) -> None:
    dryrun = args.dryrun
    generators = [g.strip().upper() for g in args.pkg_generator.split(",") if g.strip()]
    build_type = get_buildtype_str(getattr(args, "build_type", None))
    build_env = os.environ.copy()
    sdk_dir = resolve_local_sdk_dir(cli, getattr(args, "local_sdk_root", None))

    source_folder = Path(project_data["source_folder"])
    project_name = project_data["project_name"]
    package_slug = project_name.replace("-", "_")

    cpack_generators = [g for g in generators if g != "WHEEL"]
    want_wheel = "WHEEL" in generators

    if cpack_generators:
        build_dir = cli.DEFAULT_BUILD_PARENT_DIR / package_slug / "package"
        if not dryrun:
            build_dir.mkdir(parents=True, exist_ok=True)
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
            f"-DCMAKE_PREFIX_PATH={sdk_dir}/lib",
            # BUILD_ALL=OFF keeps unrelated subprojects out of this package.
            # MODULE_<slug>=ON enters the module subdir for in-tree HoloHub
            # builds (modules/CMakeLists.txt gates add_holohub_module() on it);
            # PKG_<slug>=ON then activates the target's add_holohub_package()
            # cascade, which FORCEs its OP_/APP_/EXT_ deps ON and emits the
            # CPack config. In-tree packaging needs BOTH. For standalone module
            # repos (where add_holohub_module() never runs because the module is
            # the top-level project) MODULE_<slug>=ON is a harmless unused entry.
            "-DBUILD_ALL=OFF",
            f"-DMODULE_{package_slug}=ON",
            f"-DPKG_{package_slug}=ON",
        ]
        if shutil.which("ninja"):
            cmake_args.extend(["-G", "Ninja"])
        run_command(cmake_args, dry_run=dryrun, env=build_env)

        parallel_jobs = getattr(args, "parallel", None)
        if parallel_jobs is None:
            parallel_jobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL")
        if parallel_jobs is None:
            parallel_jobs = os.cpu_count()
        build_cmd = [
            "cmake",
            "--build",
            str(build_dir),
            "--config",
            build_type,
            "-j",
            str(parallel_jobs),
        ]
        run_command(build_cmd, dry_run=dryrun, env=build_env)

        pkg_config_dir = build_dir / "pkg"
        cpack_configs = list(pkg_config_dir.glob("CPackConfig-*.cmake"))
        if not cpack_configs:
            if not dryrun:
                fatal(
                    f"Packaging '{project_name}' did not generate a CPack configuration. "
                    "Check that the module defines a package target."
                )
            bare = project_name.replace("_", "-").removeprefix("holoscan-")
            cpack_configs = [pkg_config_dir / f"CPackConfig-holoscan-{bare}.cmake"]
        for cpack_config in cpack_configs:
            for generator in cpack_generators:
                run_command(
                    ["cpack", "--config", str(cpack_config), "-G", generator],
                    dry_run=dryrun,
                    env=build_env,
                )

    if want_wheel:
        pyproject = source_folder / "pyproject.toml"
        if not pyproject.exists():
            fatal(
                f"Cannot build wheel: {pyproject} not found. The module needs "
                "a pyproject.toml with a [build-system] block."
            )
        if not dryrun and importlib.util.find_spec("build") is None:
            fatal(
                "Cannot build wheel: Python package 'build' is not installed. "
                "Install it in the active environment with `python -m pip install build`."
            )
        dist_dir = cli.DEFAULT_BUILD_PARENT_DIR / "dist"
        wheel_env = build_env.copy()
        wheel_env["PYTHONSAFEPATH"] = "1"
        wheel_cmd = [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(dist_dir),
            str(source_folder),
        ]
        run_command(wheel_cmd, dry_run=dryrun, env=wheel_env, cwd=str(source_folder.parent))
        if not dryrun:
            try:
                display_dir = dist_dir.relative_to(cli.HOLOHUB_ROOT)
            except ValueError:
                display_dir = dist_dir
            print(f"\n{Color.green('Wheel output directory:')} {display_dir}")
