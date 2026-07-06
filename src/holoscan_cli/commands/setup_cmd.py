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

"""``holoscan setup`` — install host packages and named setup scripts.

The module is named ``setup_cmd.py`` (rather than the bare ``setup.py``
that would shadow the legacy setuptools build script) so reviewers and
IDEs do not confuse it for a packaging file.
"""

import argparse
import filecmp
import os
import sys
from pathlib import Path

from holoscan_cli.commands.registry import help_for
from holoscan_cli.utils.holohub import get_holohub_setup_scripts_dir
from holoscan_cli.utils.host_setup import (
    install_packages_if_missing,
    setup_cmake,
    setup_cuda_dependencies,
    setup_ngc_cli,
    setup_python_dev,
    setup_sccache,
)
from holoscan_cli.utils.io import Color, fatal, format_cmd, run_command


def _build_script_env() -> dict:
    """Environment for running a setup script.

    Puts the project's Python on ``PATH`` so a bare ``pip``/``python`` in the
    script resolves to it — the active venv when the user has one, otherwise the
    wrapper-managed venv (i.e. wherever the CLI itself is running).
    """
    env = os.environ.copy()
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
    # A stale PYTHONHOME breaks whichever python/pip the prepended PATH resolves.
    env.pop("PYTHONHOME", None)
    if sys.prefix != sys.base_prefix:  # running inside a venv
        env["VIRTUAL_ENV"] = sys.prefix
    else:
        env.pop("VIRTUAL_ENV", None)
    return env


def register_setup_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``setup`` subcommand."""
    parser = subparsers.add_parser("setup", help=help_for("setup"))
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--list-scripts",
        action="store_true",
        help="List all setup scripts found in the HOLOSCAN_CLI_SETUP_SCRIPTS_DIR directory. "
        + "Run scripts directly or with `holoscan setup --scripts <script_name>`.",
    )
    parser.add_argument(
        "--scripts",
        action="append",
        help="Named dependency installation scripts to run. Can be specified multiple times. "
        + "Searches in the directory path specified by the HOLOSCAN_CLI_SETUP_SCRIPTS_DIR environment variable. "
        + "Omit to install default recommended packages for Holoscan SDK development.",
    )
    parser.set_defaults(func=lambda args: handle_setup(cli, args))
    return parser


def handle_setup(cli, args: argparse.Namespace) -> None:
    """Handle setup command"""

    if args.list_scripts:
        setup_scripts_dir = get_holohub_setup_scripts_dir()
        print(format_cmd(f"Listing setup scripts available in {setup_scripts_dir}"))
        print(Color.green("Use with `holoscan setup --scripts <script_name>`"))
        for script in setup_scripts_dir.glob("*.sh"):
            print(f"  {script.stem}")
        sys.exit(0)

    if args.scripts:
        # Scripts run as the invoking user, in the project's Python environment,
        # with sudo available — authors write plain `sudo apt-get ...` / `pip install ...`.
        # A script that needs sudo prompts on its first `sudo`, and sudo caches the
        # credential; pip-only scripts never prompt at all.
        script_env = _build_script_env()
        for script in args.scripts:
            if any(sep in script for sep in ("/", "\\")):
                fatal(f"Invalid script name '{script}': path separators are not allowed")
            script_path = get_holohub_setup_scripts_dir().resolve() / f"{script}.sh"
            if not script_path.exists():
                fatal(f"Script {script}.sh not found in {get_holohub_setup_scripts_dir()}")
            run_command(["bash", str(script_path)], dry_run=args.dryrun, env=script_env)
        sys.exit(0)

    if not args.scripts:
        # The first `as_root` command prompts for sudo; sudo caches the credential
        # for the rest of the run. Nothing prompts when everything is installed.
        install_packages_if_missing(
            ["wget", "xvfb", "git", "unzip", "ffmpeg", "ninja-build", "libv4l-dev"],
            dry_run=args.dryrun,
        )

        setup_cuda_dependencies(dry_run=args.dryrun)
        setup_cmake(dry_run=args.dryrun)
        setup_python_dev(dry_run=args.dryrun)
        setup_ngc_cli(dry_run=args.dryrun)
        setup_sccache(dry_run=args.dryrun)

        # Wrappers that ship a bash completion script under
        # utilities/<wrapper>_autocomplete (HoloHub, Isaac OS, …) get it
        # installed into /etc/bash_completion.d/ so users can `source` it.
        # Skip silently when the source isn't present — the consolidated
        # CLI doesn't ship its own completion script.
        utilities_dir = Path(cli.HOLOHUB_ROOT) / "utilities"
        autocomplete_sources = (
            sorted(utilities_dir.glob("*_autocomplete")) if utilities_dir.is_dir() else []
        )
        dest_folder = Path("/etc/bash_completion.d")
        installed: list[Path] = []
        if autocomplete_sources and dest_folder.exists():
            for source in autocomplete_sources:
                dest = dest_folder / source.name
                if dest.exists() and filecmp.cmp(source, dest, shallow=False):
                    continue
                run_command(
                    ["cp", str(source), str(dest_folder)], dry_run=args.dryrun, as_root=True
                )
                installed.append(dest)

        if not args.dryrun:
            for dest in installed:
                print(Color.blue(f"\nTo enable {dest.name} in your current shell session:"))
                print(f"  source {dest}")
                print("Or add it to your shell profile:")
                print(f"  echo '. {dest}' >> ~/.bashrc")
                print("  source ~/.bashrc")

            print(Color.green(f"Setup via `{cli.script_name} setup` is ready."))
