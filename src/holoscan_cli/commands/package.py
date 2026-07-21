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
import shutil
import sys
from pathlib import Path
from typing import Optional

from holoscan_cli.commands.registry import help_for
from holoscan_cli.utils.docker import get_entrypoint_command_args
from holoscan_cli.utils.holohub import check_skip_builds, get_buildtype_str
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
    parser.add_argument(
        "--local", action="store_true", help="Run packaging locally instead of in container"
    )
    parser.add_argument(
        "--build-type",
        type=str,
        default=None,
        choices=["debug", "release", "rel-debug"],
        help="Build type (default: release)",
    )
    parser.add_argument(
        "--pkg-generator",
        type=str,
        default="DEB",
        dest="pkg_generator",
        help="Comma-separated package generators: DEB, WHEEL (default: DEB)",
    )
    parser.add_argument("--language", choices=["cpp", "python"], default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--no-docker-build", action="store_true", help="Skip building the container"
    )
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
            module_name = module.get("name", cwd.name)
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

    is_local_mode = args.local or os.environ.get("HOLOSCAN_CLI_BUILD_LOCAL")

    if is_local_mode:
        project_data = _resolve_module_project(
            cli, args.project, language=getattr(args, "language", None)
        )
        _package_locally(cli, args, project_data)
        return

    container = cli.make_project_container(
        project_name=args.project,
        language=getattr(args, "language", None),
    )
    container.dryrun = args.dryrun
    container.verbose = getattr(args, "verbose", False)
    skip_docker_build, _ = check_skip_builds(args)
    if not skip_docker_build:
        container.build(
            docker_file=getattr(args, "docker_file", None),
            base_img=getattr(args, "base_img", None),
            img=getattr(args, "img", None),
            no_cache=getattr(args, "no_cache", False),
            cuda_version=getattr(args, "cuda", None),
            build_args=getattr(args, "build_args", ""),
            extra_scripts=getattr(args, "extra_scripts", []),
        )
    elif getattr(args, "cuda", None) is not None:
        container.cuda_version = args.cuda

    build_cmd = f"{in_container_cli_command()} package"
    if args.project:
        build_cmd += f" {args.project}"
    build_cmd += " --local"
    if getattr(args, "build_type", None):
        build_cmd += f" --build-type {args.build_type}"
    if getattr(args, "pkg_generator", None):
        build_cmd += f" --pkg-generator {args.pkg_generator}"
    if getattr(args, "language", None):
        build_cmd += f" --language {args.language}"
    if args.dryrun:
        build_cmd += " --dryrun"
    if getattr(args, "verbose", False):
        build_cmd += " --verbose"

    docker_opts = (getattr(args, "docker_opts", None) or "").strip()
    docker_opts_extra, extra_args = get_entrypoint_command_args(
        getattr(args, "img", None) or container.image_name,
        build_cmd,
        docker_opts,
        dry_run=args.dryrun,
    )
    if docker_opts_extra:
        docker_opts = (docker_opts + " " + docker_opts_extra).strip()
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


def _package_locally(cli, args: argparse.Namespace, project_data: dict) -> None:
    dryrun = args.dryrun
    generators = [g.strip().upper() for g in args.pkg_generator.split(",") if g.strip()]
    build_type = get_buildtype_str(getattr(args, "build_type", None))
    build_env = os.environ.copy()

    source_folder = Path(project_data["source_folder"])
    project_name = project_data["project_name"]
    package_slug = project_name.replace("-", "_")

    cpack_generators = [g for g in generators if g != "WHEEL"]
    want_wheel = "WHEEL" in generators

    if cpack_generators:
        build_dir = cli.DEFAULT_BUILD_PARENT_DIR / package_slug / "package"
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
            f"-DCMAKE_PREFIX_PATH={cli.DEFAULT_SDK_DIR}/lib",
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

        build_cmd = [
            "cmake",
            "--build",
            str(build_dir),
            "--config",
            build_type,
            "-j",
            str(os.cpu_count()),
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
