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

"""``holoscan test`` — drive ctest for a source project (host or in-container).

The module is named ``test_cmd.py`` (rather than the bare ``test.py``
that would shadow the stdlib ``test`` package and confuse pytest
collection conventions) so the file's purpose is unambiguous.
"""

import argparse
import os

from holoscan_cli.commands.registry import help_for
from holoscan_cli.metadata.utils import normalize_language
from holoscan_cli.utils.holohub import (
    check_skip_builds,
    determine_project_prefix,
    is_env_request_local_build,
)
from holoscan_cli.utils.io import format_cmd, run_command


def register_test_parser(cli, subparsers, *, container_build) -> argparse.ArgumentParser:
    """Register the ``test`` subcommand."""
    parser = subparsers.add_parser("test", help=help_for("test"), parents=[container_build])
    parser.add_argument("project", nargs="?", help="Project to test")
    parser.add_argument("--local", action="store_true", help="Test locally instead of in container")
    parser.add_argument("--verbose", action="store_true", help="Print extra output")
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument("--clear-cache", action="store_true", help="Clear cache folders")
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    parser.add_argument("--site-name", help="Site name")
    parser.add_argument("--cdash-url", help="CDash URL")
    parser.add_argument("--platform-name", help="Platform name")
    parser.add_argument(
        "--cmake-options",
        action="append",
        help="CMake options, "
        "example: --cmake-options='-DCUSTOM_OPTION=ON' --cmake-options='-DDEBUG_MODE=1'",
    )
    parser.add_argument(
        "--ctest-options",
        action="append",
        help="CTest options, "
        "example: --ctest-options='-DGPU_TYPE=rtx4090' --ctest-options='-DDEBUG_MODE=ON'",
    )
    parser.add_argument("--no-xvfb", action="store_true", help="Do not use xvfb")
    parser.add_argument("--ctest-script", help="CTest script")
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Enable code coverage in CTest (adds coverage compile flags and runs ctest_coverage)",
    )
    parser.add_argument(
        "--no-docker-build", action="store_true", help="Skip building the container"
    )
    parser.add_argument(
        "--build-name-suffix",
        help="Suffix to use for ctest build name (defaulting to the image tag)",
    )
    parser.set_defaults(func=lambda args: handle_test(cli, args))
    return parser


def _ctest_script_arg(cli, args: argparse.Namespace, in_container: bool) -> str:
    """Render the ``ctest -S <script>`` argument with the right resolution context.

    When the ctest invocation will run inside a separate container (i.e. the
    host is recursing in via ``docker run ... bash -c "<ctest_cmd>"``), the
    host's ``HoloscanCLI.DEFAULT_CTEST_SCRIPT`` points at the host's
    ``site-packages`` and will not exist inside the container if the install
    prefix differs. Defer the resolution to runtime: use the
    ``HOLOSCAN_CLI_CTEST_SCRIPT`` value forwarded into the container when
    set (no in-container CLI install required), and only fall back to
    importing the in-container package for its bundled script. The host's
    local path (``--local`` on the host, or the in-container ``--local``
    recursion branch) keeps the direct host-resolved path.
    """
    if args.ctest_script:
        return f"-S {args.ctest_script}"
    if not in_container:
        return f"-S {cli.DEFAULT_CTEST_SCRIPT}"
    return (
        '-S "${HOLOSCAN_CLI_CTEST_SCRIPT:-'
        "$(python3 -c 'from holoscan_cli.cli import HoloscanCLI; "
        "print(HoloscanCLI.DEFAULT_CTEST_SCRIPT)')}\""
    )


def handle_test(cli, args: argparse.Namespace) -> None:
    """Handle test command"""
    skip_docker_build, _ = check_skip_builds(args)
    container = cli.make_project_container(
        project_name=args.project, language=args.language if hasattr(args, "language") else None
    )
    if args.clear_cache:
        from argparse import Namespace

        from holoscan_cli.commands.clear_cache import handle_clear_cache

        # Clear build/install artifacts only — forwarding the test namespace
        # (no build/data/install flags) would mean "clear everything",
        # including the downloaded data cache.
        handle_clear_cache(
            cli,
            Namespace(dryrun=args.dryrun, build=True, data=False, install=True),
        )

    container.dryrun = args.dryrun
    container.verbose = args.verbose

    is_local_mode = args.local or is_env_request_local_build()

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
        proj_prefix = determine_project_prefix(project_type)
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
        print(format_cmd(f"cd {cli.HOLOHUB_ROOT}", is_dryrun=args.dryrun))
        if not args.dryrun:
            os.chdir(cli.HOLOHUB_ROOT)

        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{env.get('PYTHONPATH', '')}:{cli.DEFAULT_SDK_DIR}/python/lib:{cli.HOLOHUB_ROOT}"
        )
        env["HOLOSCAN_CLI_DATA_PATH"] = str(cli.DEFAULT_DATA_DIR)
        env.setdefault("HOLOSCAN_INPUT_PATH", str(cli.DEFAULT_DATA_DIR))

        run_command(["bash", "-c", ctest_cmd], dry_run=args.dryrun, env=env)
        return

    container.run(
        img=getattr(args, "img", None),
        use_tini=True,
        docker_opts="--entrypoint=bash",
        as_root=getattr(args, "coverage", False),
        extra_args=["-c", ctest_cmd],
    )
