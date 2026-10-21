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
import configparser
import keyword
import os
import re
import shlex
import stat
import sys
import tempfile
from dataclasses import dataclass
from email.parser import Parser
from importlib.machinery import EXTENSION_SUFFIXES, PathFinder
from pathlib import Path

from holoscan_cli.commands.build import build_project_locally
from holoscan_cli.commands.registry import help_for
from holoscan_cli.container.parsers import (
    add_configure_args,
    add_docker_build_args,
    add_local_container_args,
)
from holoscan_cli.metadata.utils import MAX_METADATA_BYTES, read_metadata
from holoscan_cli.utils.docker import (
    apply_container_cli_overrides,
    get_entrypoint_command_args,
    resolve_cli_docker_opts,
)
from holoscan_cli.utils.holohub import (
    build_holohub_path_mapping,
    check_skip_builds,
    is_env_request_local_build,
    update_env,
)
from holoscan_cli.utils.io import Color, fatal, run_command, warn
from holoscan_cli.utils.project import (
    append_configure_args,
    report_effective_configuration,
    resolve_effective_build_type,
)


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
        help="Project to install (omit with --dev to register every discovered module)",
    )
    parser.add_argument("mode", nargs="?", help="Mode to install (optional)")
    add_local_container_args(parser, "Install")
    parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Build a standalone Module if needed and register its Python build, so "
            "`import holoscan.<module>` resolves to the live build tree without "
            "a wheel install. Container Python is the default; use --local for host Python."
        ),
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Used with --dev: remove the development registration or legacy dev hook.",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=None,
        help=(
            "Used with --dev: build directory containing Python metadata or legacy hooks. "
            "Default: most-recently-modified <build-parent>/*/ provider metadata or hook."
        ),
    )
    parser.add_argument("--site-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--build-type",
        help=(
            "Build type (debug, release, rel-debug). Precedence: this option, "
            "CMAKE_BUILD_TYPE, selected mode, then release"
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
    add_docker_build_args(parser)
    add_configure_args(parser)
    parser.set_defaults(func=lambda args: handle_install(cli, args))
    return parser


def handle_install(cli, args: argparse.Namespace) -> None:
    """Handle install command"""
    from holoscan_cli.cli import in_container_cli_command

    if args.dev:
        module_name = _standalone_module_name(cli)
        if (
            module_name
            and not getattr(args, "local", False)
            and not is_env_request_local_build()
            and getattr(args, "site_dir", None) is None
        ):
            _handle_install_dev_in_container(cli, args, module_name)
            return
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
        append_configure_args(install_tokens, args)
        install_cmd = shlex.join(install_tokens)

        img = container.resolve_run_image(getattr(args, "img", None))
        docker_opts = container.compose_run_args(
            mode_docker_opts=build_args.get("mode_docker_opts"),
            docker_opts=build_args.get("docker_opts", ""),
        )
        docker_opts_extra, extra_args = get_entrypoint_command_args(
            img, install_cmd, docker_opts, dry_run=args.dryrun
        )
        if docker_opts_extra:
            docker_opts = f"{docker_opts} {docker_opts_extra}".strip()
        container.run(
            limit_build_parallelism=True,
            img=img,
            local_sdk_root=getattr(args, "local_sdk_root", None),
            enable_x11=getattr(args, "enable_x11", True),
            ssh_x11=getattr(args, "ssh_x11", False),
            use_tini=getattr(args, "init", False),
            persistent=getattr(args, "persistent", False),
            nsys_profile=getattr(args, "nsys_profile", False),
            nsys_location=getattr(args, "nsys_location", ""),
            as_root=getattr(args, "as_root", False),
            effective_docker_opts=docker_opts,
            forward_env=getattr(args, "forward_env", None),
            add_volumes=getattr(args, "add_volume", None),
            enable_mps=getattr(args, "mps", False),
            extra_args=extra_args,
        )


def _dev_hook_slug(project: str) -> str:
    slug = project.replace("-", "_")
    if slug.startswith("holoscan_"):
        slug = slug[len("holoscan_") :]
    return slug


def _standalone_module_name(cli) -> str | None:
    """Return the identity of a standalone Module source root, if any."""
    root = getattr(cli, "HOLOHUB_ROOT", None)
    if root is None:
        return None
    try:
        metadata = read_metadata(Path(root) / "metadata.json")
    except (OSError, ValueError, RecursionError):
        return None
    module = metadata.get("module") if isinstance(metadata, dict) else None
    name = module.get("name") if isinstance(module, dict) else None
    return name if isinstance(name, str) and name else None


def _handle_install_dev_in_container(cli, args: argparse.Namespace, module_name: str) -> None:
    """Run the Module dev-hook operation in the default development container."""
    from holoscan_cli.cli import in_container_cli_command

    if args.project and _dev_hook_slug(args.project) != _dev_hook_slug(module_name):
        fatal(f"Module '{args.project}' is not the current standalone Module '{module_name}'.")

    if args.dryrun and not args.uninstall:
        print(
            f"In container: build '{module_name}' if its Python build is not ready, "
            "then register it."
        )

    container = cli.make_project_container(project_name=module_name)
    apply_container_cli_overrides(args, container)
    container.dryrun = args.dryrun
    container.verbose = args.verbose
    command = [*shlex.split(in_container_cli_command()), "install", "--dev", "--local"]
    if args.project:
        command.append(args.project)
    if args.uninstall:
        command.append("--uninstall")
    if args.dryrun:
        command.append("--dryrun")
    if args.verbose:
        command.append("--verbose")
    for option, value in (
        ("--build-type", resolve_effective_build_type(getattr(args, "build_type", None))),
        ("--language", getattr(args, "language", None)),
        ("--parallel", getattr(args, "parallel", None)),
    ):
        if value is not None:
            command.extend([option, str(value)])
    if getattr(args, "with_operators", None) is not None:
        command.append(f"--build-with={args.with_operators}")
    for configure_arg in getattr(args, "configure_args", None) or []:
        command.append(f"--configure-args={configure_arg}")
    if args.build_dir is not None and not args.uninstall:
        root = Path(cli.HOLOHUB_ROOT).resolve()
        build_dir = args.build_dir.resolve()
        try:
            relative = build_dir.relative_to(root)
        except ValueError:
            fatal(
                f"--build-dir {build_dir} is outside the Module source mount. "
                "Use --local for a host build directory."
            )
        command.extend(
            ["--build-dir", str(Path("/workspace") / container.WORKSPACE_NAME / relative)]
        )

    skip_docker_build, _ = check_skip_builds(args)
    if not skip_docker_build:
        container.build(
            docker_file=getattr(args, "docker_file", None),
            base_img=getattr(args, "base_img", None),
            img=getattr(args, "img", None),
            no_cache=getattr(args, "no_cache", False),
            build_args=getattr(args, "build_args", None),
            mode_build_args=None,
            cuda_version=getattr(args, "cuda", None),
            extra_scripts=getattr(args, "extra_scripts", []),
        )
    image = container.resolve_run_image(getattr(args, "img", None))
    docker_opts = container.compose_run_args(docker_opts=resolve_cli_docker_opts(args))
    docker_opts_extra, extra_args = get_entrypoint_command_args(
        image, shlex.join(command), docker_opts, dry_run=args.dryrun
    )
    if docker_opts_extra:
        docker_opts = f"{docker_opts} {docker_opts_extra}".strip()
    container.run(
        limit_build_parallelism=True,
        img=image,
        local_sdk_root=getattr(args, "local_sdk_root", None),
        enable_x11=getattr(args, "enable_x11", True),
        ssh_x11=getattr(args, "ssh_x11", False),
        use_tini=getattr(args, "init", False),
        persistent=getattr(args, "persistent", False),
        nsys_profile=getattr(args, "nsys_profile", False),
        nsys_location=getattr(args, "nsys_location", ""),
        as_root=getattr(args, "as_root", False),
        effective_docker_opts=docker_opts,
        forward_env=getattr(args, "forward_env", None),
        add_volumes=getattr(args, "add_volume", None),
        enable_mps=getattr(args, "mps", False),
        extra_args=extra_args,
    )


def _handle_install_dev(cli, args: argparse.Namespace) -> None:
    """Register or remove live Python builds, retaining legacy dev-hook support."""
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

    module_name = _standalone_module_name(cli)
    if args.build_dir is not None:
        search_dirs = [args.build_dir.resolve()]
        if not search_dirs[0].is_dir():
            fatal(f"--build-dir {search_dirs[0]} is not a directory.")
    else:
        build_parent = cli.DEFAULT_BUILD_PARENT_DIR
        search_dirs = (
            [d for d in build_parent.iterdir() if d.is_dir()] if build_parent.is_dir() else []
        )

    by_slug = _find_dev_sources(search_dirs, strict=args.build_dir is not None)
    module_slug = _dev_hook_slug(module_name) if module_name else None
    requested_slug = _dev_hook_slug(args.project) if args.project else module_slug
    if (
        module_name
        and requested_slug == module_slug
        and module_slug not in by_slug
        and args.build_dir is None
    ):
        build_dir, _ = build_project_locally(
            cli,
            project_name=module_name,
            language=getattr(args, "language", None),
            dryrun=dryrun,
            verbose=getattr(args, "verbose", False),
            build_type=getattr(args, "build_type", None),
            with_operators=getattr(args, "with_operators", None),
            parallel=getattr(args, "parallel", None),
            configure_args=getattr(args, "configure_args", None),
            local_sdk_root=getattr(args, "local_sdk_root", None),
        )
        if dryrun:
            print(f"Would build '{module_name}' and register its Python build from {build_dir}")
            return
        # Inspect the actual result, not an unrelated pre-existing build.
        search_dirs = [build_dir]
        by_slug = _find_dev_sources(search_dirs, strict=args.build_dir is not None)

    if args.project:
        target = _dev_hook_slug(args.project)
        if target in by_slug:
            by_slug = {target: by_slug[target]}
        else:
            fatal(
                f"No built Python development provider found for module '{args.project}'. "
                f"Looked under: {', '.join(str(d) for d in search_dirs)}. "
                "Enable and build Python bindings with the SDK metadata helper, "
                "or use a build with legacy staged hooks."
            )

    if not by_slug:
        if not search_dirs:
            fatal(
                f"No build directory at {cli.DEFAULT_BUILD_PARENT_DIR}. "
                "Run a Module build first, or pass --build-dir."
            )
        fatal(
            f"No built Python development providers or legacy staged hooks found under "
            f"{', '.join(str(d) for d in search_dirs)}. Enable and build Python bindings "
            "with holoscan_install_python_module_metadata(), or use legacy staged hooks."
        )

    if not dryrun:
        try:
            site_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            fatal(f"Cannot create site-packages directory {site_dir}: {exc}")

    for slug in sorted(by_slug):
        source = by_slug[slug]
        build_dir = source.build_dir
        if source.python_root is not None:
            _install_metadata_dev_source(source, site_dir, dryrun=dryrun)
            continue
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
            helper_text = (build_dir / helper_name).read_text(encoding="utf-8")
            host_build_path = (build_dir / "python" / "lib" / "holoscan").resolve()
            helper_text = "".join(
                (
                    f"_BUILD_PATH = {str(host_build_path)!r}\n"
                    if line.startswith("_BUILD_PATH = ")
                    else line
                )
                for line in helper_text.splitlines(keepends=True)
            )
            helper_dst.write_text(helper_text, encoding="utf-8")
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
                "Verify with: "
                f'python -c "import holoscan.{sole}; print(holoscan.{sole}.__file__)"'
            )
        else:
            print('Verify with: python -c "import holoscan; print(holoscan.__path__)"')
        print(f"To remove: {Path(cli.script_name).name} install --dev --uninstall")


@dataclass(frozen=True)
class _DevSource:
    slug: str
    build_dir: Path
    mtime: float
    python_root: Path | None = None
    built: bool = True


def _read_dev_metadata(path: Path) -> str:
    """Read bounded regular text without importing build-tree Python code."""
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags), "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise ValueError(f"{path} must be a regular file")
        content = file.read(MAX_METADATA_BYTES + 1)
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError(f"{path} exceeds the 1 MiB limit")
    return content.decode("utf-8")


def _metadata_dev_source(build_dir: Path, *, strict: bool) -> _DevSource | None:
    python_root = (build_dir / "python/lib").resolve()
    providers = []
    try:
        for info in sorted(python_root.glob("*.dist-info")):
            entries = info / "entry_points.txt"
            if not entries.exists():
                continue
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read_string(_read_dev_metadata(entries))
            if not parser.has_section("holoscan.modules"):
                continue
            for slug, target in parser.items("holoscan.modules"):
                if (
                    not re.fullmatch(r"[a-z][a-z0-9_]*", slug)
                    or keyword.iskeyword(slug)
                    or target.strip() != f"holoscan_{slug}"
                ):
                    raise ValueError(f"invalid holoscan.modules entry {slug!r} in {entries}")
                metadata = Parser().parsestr(_read_dev_metadata(info / "METADATA"))
                if not metadata.get("Name") or not metadata.get("Version"):
                    raise ValueError(f"missing distribution Name or Version in {info}")
                package = python_root / f"holoscan_{slug}"
                built = (package / "__init__.py").is_file() and any(
                    (package / f"_{slug}{suffix}").is_file() for suffix in EXTENSION_SUFFIXES
                )
                providers.append(
                    _DevSource(slug, build_dir, entries.stat().st_mtime, python_root, built)
                )
        if len(providers) > 1:
            raise ValueError(
                f"multiple Holoscan providers in {python_root}; use separate module builds "
                "so development registrations can be removed independently"
            )
    except (OSError, ValueError, configparser.Error) as exc:
        message = f"Invalid Python development metadata in {python_root}: {exc}"
        if strict:
            fatal(message)
        warn(f"{message}; skipping")
        return None
    return providers[0] if providers else None


def _find_dev_sources(search_dirs: list[Path], *, strict: bool) -> dict[str, _DevSource]:
    by_slug = {}
    for build_dir in search_dirs:
        legacy = _find_dev_hooks([build_dir])
        modern = _metadata_dev_source(build_dir, strict=strict)
        if modern is not None:
            # Never revive an obsolete namespace hook for a modern provider.
            legacy.pop(modern.slug, None)
        candidates = [_DevSource(slug, path, mtime) for slug, (path, mtime) in legacy.items()]
        if modern is not None and modern.built:
            candidates.append(modern)
        for source in candidates:
            previous = by_slug.get(source.slug)
            if previous is None or (source.mtime, str(source.build_dir)) > (
                previous.mtime,
                str(previous.build_dir),
            ):
                by_slug[source.slug] = source
    return by_slug


def _install_metadata_dev_source(source: _DevSource, site_dir: Path, *, dryrun: bool) -> None:
    pth = site_dir / f"holoscan-{source.slug.replace('_', '-')}-dev.pth"
    helper = site_dir / f"holoscan_{source.slug}_dev.py"
    python_path = str(source.python_root)
    if "\n" in python_path or "\r" in python_path:
        fatal(f"Cannot represent Python build path in a .pth file: {python_path!r}")
    package_name = f"holoscan_{source.slug}"
    # A prior registration is still on this process's sys.path until restart.
    # Exclude that path when checking the registration that will replace it.
    replaced_root = None
    if pth.is_file():
        try:
            lines = _read_dev_metadata(pth).splitlines()
            if len(lines) == 1 and Path(lines[0]).is_absolute():
                replaced_root = Path(lines[0]).resolve()
        except (OSError, ValueError):
            pass
    # These entries survive replacement even when they also came from the .pth.
    persistent_roots = {
        Path(entry).resolve() for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep)
    }
    persistent_roots.add(Path.cwd())
    search_path = [
        entry
        for entry in sys.path
        if Path(entry).resolve() != source.python_root
        and (Path(entry).resolve() != replaced_root or Path(entry).resolve() in persistent_roots)
    ]
    conflict = PathFinder.find_spec(package_name, [str(site_dir)])
    if conflict is None:
        conflict = PathFinder.find_spec(package_name, search_path)
    if conflict is not None:
        fatal(
            f"Installed package '{package_name}' at {conflict.origin} would shadow the development "
            "build. Uninstall that package or use a clean Python environment, then retry."
        )
    if dryrun:
        print(f"Would register {python_path} in {pth}")
        if helper.exists():
            print(f"Would remove obsolete legacy helper {helper}")
        return
    try:
        with tempfile.TemporaryDirectory(dir=site_dir, prefix=f".{pth.name}.") as directory:
            temporary = Path(directory) / pth.name
            # Normal creation applies the umask without changing process-wide state.
            # The private directory protects the file until it is ready to replace.
            with temporary.open("x", encoding="utf-8") as file:
                file.write(python_path + "\n")
            os.replace(temporary, pth)
        helper.unlink(missing_ok=True)
    except OSError as exc:
        fatal(f"Failed to register Python build for '{source.slug}': {exc}")
    print(f"Registered {python_path} in {pth}")


def _find_dev_hooks(search_dirs: list[Path]) -> dict[str, tuple[Path, float]]:
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
    return by_slug
