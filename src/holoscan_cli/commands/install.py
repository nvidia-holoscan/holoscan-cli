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
from pathlib import Path

from holoscan_cli.commands.build import build_project_locally, resolve_effective_build_type
from holoscan_cli.commands.registry import help_for
from holoscan_cli.configuration import (
    append_config_vector_flags,
    apply_container_cli_overrides,
    report_effective_configuration,
)
from holoscan_cli.utils.docker import get_entrypoint_command_args
from holoscan_cli.utils.holohub import (
    build_holohub_path_mapping,
    check_skip_builds,
    is_env_request_local_build,
    update_env,
)
from holoscan_cli.utils.io import Color, fatal, run_command


def register_install_parser(
    cli, subparsers, *, container_build, container_run
) -> argparse.ArgumentParser:
    """Register the ``install`` subcommand."""
    parser = subparsers.add_parser(
        "install", help=help_for("install"), parents=[container_build, container_run]
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Project to install (omit with --dev to install every staged hook)",
    )
    parser.add_argument("mode", nargs="?", help="Mode to install (optional)")
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--local", dest="local", action="store_true", help="Install locally")
    location.add_argument(
        "--container", dest="local", action="store_false", help="Install in a container"
    )
    parser.set_defaults(local=None)
    parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Install the dev hook staged by a Holoscan Module build, so "
            "`import holoscan.<module>` resolves to the live build tree without "
            "a wheel install."
        ),
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Used with --dev: remove the previously installed dev hook.",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=None,
        help=(
            "Used with --dev: build directory whose staged dev hook should be installed. "
            "Default: most-recently-modified <build-parent>/*/ hook."
        ),
    )
    parser.add_argument("--site-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--build-type",
        help=(
            "Build type (debug, release, rel-debug). Precedence: this option, "
            "CMAKE_BUILD_TYPE, selected mode, pyproject.toml, then release"
        ),
    )
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    parser.add_argument(
        "--build-with",
        dest="with_operators",
        help=(
            "Complete operator selection, separated by semicolons (;). Replaces the "
            "selected mode's build.depends; use --build-with= to clear it"
        ),
    )
    parser.add_argument("--verbose", action="store_true", help="Print extra output")
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--parallel", help="Number of parallel build jobs (e.g. --parallel $(($(nproc)-1)))"
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
    parser.set_defaults(func=lambda args: handle_install(cli, args))
    return parser


def handle_install(cli, args: argparse.Namespace) -> None:
    """Handle install command"""
    from holoscan_cli.cli import in_container_cli_command

    if args.dev:
        _handle_install_dev(cli, args)
        return

    if not args.project:
        fatal("Project is required unless --dev is specified.")

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
        # Build and install locally
        build_dir, project_data = build_project_locally(
            cli,
            project_name=args.project,
            language=args.language if hasattr(args, "language") else None,
            build_type=args.build_type,
            with_operators=build_args.get("with_operators"),
            dryrun=args.dryrun,
            verbose=args.verbose,
            parallel=getattr(args, "parallel", None),
            configure_args=build_args.get("configure_args"),
            extra_env=build_mode_env,
            local_sdk_root=getattr(args, "local_sdk_root", None),
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
                install_env,
                build_mode_env,
                path_mapping,
                verbose=(args.verbose or args.dryrun),
                overwrite=False,
                project_defaults_are_lower=True,
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
        install_tokens = [
            *shlex.split(in_container_cli_command()),
            "install",
            str(args.project),
        ]
        if mode_name and getattr(args, "mode", None) is not None:
            install_tokens.append(str(mode_name))
        install_tokens.extend(["--local", "--build-type", effective_build_type])
        if getattr(args, "language", None):
            install_tokens.extend(["--language", str(args.language)])
        if getattr(args, "with_operators", None) is not None:
            install_tokens.append(f"--build-with={args.with_operators}")
        if getattr(args, "parallel", None) is not None:
            install_tokens.extend(["--parallel", str(args.parallel)])
        if args.verbose:
            install_tokens.append("--verbose")
        append_config_vector_flags(install_tokens, args)
        if getattr(args, "replace_configure_args", False):
            install_tokens.append("--replace-configure-args")
        if getattr(args, "configure_args", None):
            for configure_arg in args.configure_args:
                install_tokens.append(f"--configure-args={configure_arg}")
        install_cmd = shlex.join(install_tokens)

        img = container.resolve_run_image(getattr(args, "img", None))
        docker_opts = container.compose_run_args(
            mode_docker_opts=build_args.get("mode_docker_opts"),
            docker_opts=build_args.get("docker_opts", ""),
            include_default_run_args=build_args.get("include_default_run_args", True),
        )
        docker_opts_extra, extra_args = get_entrypoint_command_args(
            img, install_cmd, docker_opts, dry_run=args.dryrun
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


def _dev_hook_slug(project: str) -> str:
    slug = project.replace("-", "_")
    if slug.startswith("holoscan_"):
        slug = slug[len("holoscan_") :]
    return slug


def _handle_install_dev(cli, args: argparse.Namespace) -> None:
    """Install or remove staged Holoscan Module namespace dev hooks."""
    import shutil as _shutil
    import site as _site
    import sys as _sys
    import sysconfig as _sysconfig

    dryrun = getattr(args, "dryrun", False)
    site_dir_override = getattr(args, "site_dir", None)
    if site_dir_override is not None:
        site_dir = site_dir_override.resolve()
    else:
        if _sys.prefix != _sys.base_prefix:
            site_path = _sysconfig.get_path("purelib")
        else:
            site_path = _site.getusersitepackages()
        if not site_path:
            fatal("Could not determine site-packages directory.")
        site_dir = Path(site_path)

    if args.uninstall:
        if args.project:
            slugs = [_dev_hook_slug(args.project)]
        else:
            slugs = sorted(
                {
                    p.stem.removeprefix("holoscan-").removesuffix("-dev").replace("-", "_")
                    for p in site_dir.glob("holoscan-*-dev.pth")
                }
                | {
                    p.stem.removeprefix("holoscan_").removesuffix("_dev")
                    for p in site_dir.glob("holoscan_*_dev.py")
                }
            )
        if not slugs:
            print("No installed dev hooks found.")
            return
        for slug in slugs:
            kebab = slug.replace("_", "-")
            pth_dst = site_dir / f"holoscan-{kebab}-dev.pth"
            helper_dst = site_dir / f"holoscan_{slug}_dev.py"
            removed_any = False
            for path in (pth_dst, helper_dst):
                if path.exists():
                    if dryrun:
                        print(f"Would remove {path}")
                    else:
                        try:
                            path.unlink()
                        except OSError as exc:
                            fatal(f"Failed to remove {path}: {exc}")
                        print(f"Removed {path}")
                        removed_any = True
            if not removed_any and not dryrun:
                print(f"No dev hook installed for '{slug}'.")
        return

    if args.build_dir is not None:
        search_dirs = [args.build_dir.resolve()]
        if not search_dirs[0].is_dir():
            fatal(f"--build-dir {search_dirs[0]} is not a directory.")
    else:
        build_parent = cli.DEFAULT_BUILD_PARENT_DIR
        if not build_parent.is_dir():
            fatal(f"No build directory at {build_parent}. Run a build first, or pass --build-dir.")
        search_dirs = [d for d in build_parent.iterdir() if d.is_dir()]

    by_slug: dict[str, tuple[Path, float]] = {}
    for build_dir in search_dirs:
        for helper in build_dir.glob("holoscan_*_dev.py"):
            if not helper.is_file():
                continue
            slug = helper.stem.removeprefix("holoscan_").removesuffix("_dev")
            if not slug:
                continue
            pth = build_dir / f"holoscan-{slug.replace('_', '-')}-dev.pth"
            if not pth.exists():
                continue
            mtime = helper.stat().st_mtime
            if slug not in by_slug or by_slug[slug][1] < mtime:
                by_slug[slug] = (build_dir, mtime)

    if args.project:
        target = _dev_hook_slug(args.project)
        if target in by_slug:
            by_slug = {target: by_slug[target]}
        else:
            fatal(
                f"No staged dev hook found for module '{args.project}'. "
                f"Looked under: {', '.join(str(d) for d in search_dirs)}"
            )

    if not by_slug:
        fatal(
            f"No staged dev hooks (holoscan_*_dev.py) found under "
            f"{', '.join(str(d) for d in search_dirs)}. Run a build of a "
            "Holoscan Module, or an app that depends on one, first."
        )

    if not dryrun:
        try:
            site_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            fatal(f"Cannot create site-packages directory {site_dir}: {exc}")

    for slug in sorted(by_slug):
        build_dir, _ = by_slug[slug]
        kebab = slug.replace("_", "-")
        helper_name = f"holoscan_{slug}_dev.py"
        pth_name = f"holoscan-{kebab}-dev.pth"
        helper_dst = site_dir / helper_name
        pth_dst = site_dir / pth_name
        if dryrun:
            print(f"Would install {pth_dst} from {build_dir}")
            print(f"Would install {helper_dst} from {build_dir}")
            continue
        try:
            _shutil.copy2(build_dir / pth_name, pth_dst)
            _shutil.copy2(build_dir / helper_name, helper_dst)
        except OSError as exc:
            for path in (pth_dst, helper_dst):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            fatal(f"Failed to install dev hook for '{slug}': {exc}")
        print(f"Installed {pth_dst}")
        print(f"          {helper_dst}")
        print(f"  wiring `import holoscan.{slug}` to {build_dir}")

    if not dryrun:
        print()
        if len(by_slug) == 1:
            sole = next(iter(by_slug))
            print(
                f'Verify with: python -c "import holoscan.{sole}; print(holoscan.{sole}.__file__)"'
            )
        else:
            print('Verify with: python -c "import holoscan; print(holoscan.__path__)"')
        print(f"To remove: {Path(cli.script_name).name} install --dev --uninstall")
