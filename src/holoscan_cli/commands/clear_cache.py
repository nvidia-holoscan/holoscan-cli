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

"""``holoscan clear-cache`` — delete build, data, and install cache directories."""

import argparse
import shutil
from pathlib import Path

from holoscan_cli.commands.registry import help_for
from holoscan_cli.utils.io import Color, resolve


def _is_safe_to_remove(path: Path, cli) -> bool:
    """Return ``True`` only when ``path`` is a cache directory we may delete.

    The candidate dirs come from env-overridable roots (e.g.
    ``HOLOSCAN_CLI_BUILD_PARENT_DIR=/``), so a bad value must never let
    :func:`shutil.rmtree` wipe an anchor (``/``, ``$HOME``, the repo root) or
    an ancestor of one; the path must also live under an approved cache root.
    """
    candidate = resolve(path)

    anchors = {resolve("/"), resolve(cli.HOLOHUB_ROOT)}
    try:
        anchors.add(resolve(Path.home()))
    except RuntimeError:
        pass  # home directory unresolvable; the remaining anchors still apply
    if candidate in anchors:
        return False
    for anchor in anchors:
        if anchor.is_relative_to(candidate):
            return False

    approved_roots = [
        resolve(cli.HOLOHUB_ROOT),
        resolve(cli.DEFAULT_BUILD_PARENT_DIR),
        resolve(cli.DEFAULT_DATA_DIR),
    ]
    return any(candidate.is_relative_to(root) for root in approved_roots)


def register_clear_cache_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``clear-cache`` subcommand."""
    parser = subparsers.add_parser("clear-cache", help=help_for("clear-cache"))
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument("--build", action="store_true", help="Clear build folders only")
    parser.add_argument("--data", action="store_true", help="Clear data folders only")
    parser.add_argument("--install", action="store_true", help="Clear install folders only")
    parser.set_defaults(func=lambda args: handle_clear_cache(cli, args))
    return parser


def handle_clear_cache(cli, args: argparse.Namespace) -> None:
    """Handle clear-cache command"""
    # Determine which folders to clear
    clear_build = getattr(args, "build", False)
    clear_data = getattr(args, "data", False)
    clear_install = getattr(args, "install", False)

    # If no flags are provided, clear all (backward compatibility)
    clear_all = not (clear_build or clear_data or clear_install)

    if args.dryrun:
        print(Color.blue("Would clear cache folders:"))
    else:
        print(Color.blue("Clearing cache..."))

    cache_dirs = []

    # Collect build folders if needed
    if clear_all or clear_build:
        cache_dirs.extend(
            cli.collect_cache_dirs(["build", "build-*"], cli.DEFAULT_BUILD_PARENT_DIR)
        )

    # Collect data folders if needed
    if clear_all or clear_data:
        cache_dirs.extend(cli.collect_cache_dirs(["data", "data-*"], cli.DEFAULT_DATA_DIR))

    # Collect install folders if needed
    if clear_all or clear_install:
        cache_dirs.extend(cli.collect_cache_dirs(["install", "install-*"]))

    for path in set(cache_dirs):
        if not (path.exists() and path.is_dir()):
            continue
        if not _is_safe_to_remove(path, cli):
            print(f"  {Color.red('Refusing to remove:')} {path} (outside approved cache roots)")
            continue
        if args.dryrun:
            print(f"  {Color.yellow('Would remove:')} {path}")
        else:
            print(f"  {Color.red('Removing:')} {path}")
            shutil.rmtree(path)
