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

"""``holoscan lint`` — thin wrapper around ``pre-commit run`` for the project root."""

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

import holoscan_cli.util as holohub_cli_util
from holoscan_cli.commands.registry import help_for
from holoscan_cli.utils.io import Color


def register_lint_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``lint`` subcommand."""
    parser = subparsers.add_parser("lint", help=help_for("lint"))
    parser.add_argument("path", nargs="?", default=".", help="Path to lint")
    parser.add_argument("--fix", action="store_true", help="Fix linting issues")
    parser.add_argument(
        "--install-dependencies",
        action="store_true",
        help="Install linting dependencies (may require `sudo` privileges)",
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.set_defaults(func=lambda args: handle_lint(cli, args))
    return parser


# ---- private helpers ---------------------------------------------------------


def _running_in_virtual_env() -> bool:
    """Return True when Python is running inside a virtual environment."""
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix) or hasattr(sys, "real_prefix")


def _pre_commit_available() -> bool:
    """Return True when pre-commit is importable by the active Python."""
    result = subprocess.run(
        [sys.executable, "-m", "pre_commit", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _resolve_lint_target(cli, path_arg: Optional[str]) -> Path:
    """Resolve and validate the lint target relative to the project root."""
    root = cli.HOLOHUB_ROOT.resolve()
    if not path_arg:
        return root

    path = Path(path_arg)
    target = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not target.exists():
        holohub_cli_util.fatal(f"Lint path `{path_arg}` does not exist.")

    if not target.is_relative_to(root):
        holohub_cli_util.fatal(
            f"Lint path `{path_arg}` resolves outside the project root `{root}`."
        )

    return target


def _collect_lint_files(cli, target: Path) -> List[str]:
    """Collect git-tracked and unignored files for ``pre-commit run --files``."""
    root = cli.HOLOHUB_ROOT.resolve()
    target_arg = "." if target == root else str(target.relative_to(root))
    try:
        output = subprocess.check_output(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                target_arg,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        holohub_cli_util.fatal("`git` is not available; cannot resolve lint target files.")
    except subprocess.CalledProcessError:
        holohub_cli_util.fatal(
            f"Failed to enumerate lint files via `git ls-files` for `{target_arg}`."
        )
    return [line for line in output.splitlines() if line]


def _check_pre_commit_cache_writable(env: dict) -> None:
    """Fail early with a clear message if pre-commit's cache cannot be written."""
    cache_dir = Path(env.get("PRE_COMMIT_HOME") or Path.home() / ".cache" / "pre-commit")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache_dir, prefix=".holohub-write-test-"):
            pass
    except (PermissionError, OSError):
        quoted = shlex.quote(str(cache_dir))
        holohub_cli_util.fatal(
            f"pre-commit cache `{cache_dir}` is not writable by the current user "
            f"(typically caused by a previous `sudo pre-commit` run).\n"
            f"Fix it with one of:\n"
            f'  sudo chown -R "$(id -u):$(id -g)" {quoted}\n'
            f"  sudo rm -rf {quoted}"
        )


def _install_lint_deps(cli, dry_run: bool, env: dict) -> None:
    """Install pre-commit and prefetch hook environments."""
    print(holohub_cli_util.format_cmd("cd " + str(cli.HOLOHUB_ROOT), is_dryrun=dry_run))
    if not dry_run:
        os.chdir(cli.HOLOHUB_ROOT)

    pip_install_cmd = [sys.executable, "-m", "pip", "install"]
    if not _running_in_virtual_env():
        pip_install_cmd.append("--user")
    lint_requirements = cli.HOLOHUB_ROOT / "utilities" / "requirements.lint.txt"
    if lint_requirements.exists():
        pip_install_cmd.extend(["-r", str(lint_requirements)])
    else:
        pip_install_cmd.append("pre-commit")
    holohub_cli_util.run_command(
        pip_install_cmd,
        dry_run=dry_run,
        env=env,
    )
    if not (cli.HOLOHUB_ROOT / ".pre-commit-config.yaml").exists():
        holohub_cli_util.warn(
            "No `.pre-commit-config.yaml` found; skipping pre-commit hook prefetch."
        )
        return

    holohub_cli_util.run_command(
        [sys.executable, "-m", "pre_commit", "install-hooks"],
        dry_run=dry_run,
        env=env,
    )


# ---- handler -----------------------------------------------------------------


def handle_lint(cli, args: argparse.Namespace) -> None:
    """Handle lint command (thin wrapper around pre-commit).

    Delegates to ``pre-commit run`` using the hooks declared in
    ``.pre-commit-config.yaml`` at the project root. Downstream wrappers
    can intercept this subcommand to route to their own tooling.
    """
    env = os.environ.copy()
    if not _running_in_virtual_env():
        local_bin_path = Path.home() / ".local" / "bin"
        if str(local_bin_path) not in env.get("PATH", ""):
            env["PATH"] = str(local_bin_path) + ":" + env.get("PATH", "")
            holohub_cli_util.info(f"Added {local_bin_path} to PATH.")

    if holohub_cli_util.is_running_in_docker():
        env["PRE_COMMIT_HOME"] = str(cli.HOLOHUB_ROOT / ".cache" / "pre-commit")
        holohub_cli_util.info(f"Set PRE_COMMIT_HOME to {env['PRE_COMMIT_HOME']}")

    if args.install_dependencies:
        if not args.dryrun:
            _check_pre_commit_cache_writable(env)
        _install_lint_deps(cli, args.dryrun, env=env)
        return

    print(holohub_cli_util.format_cmd("cd " + str(cli.HOLOHUB_ROOT), is_dryrun=args.dryrun))
    if not args.dryrun:
        os.chdir(cli.HOLOHUB_ROOT)

    config_path = cli.HOLOHUB_ROOT / ".pre-commit-config.yaml"
    if not args.dryrun and not config_path.exists():
        holohub_cli_util.warn(
            "No `.pre-commit-config.yaml` found at the project root. "
            "Nothing configured for linting; we recommend setting up pre-commit "
            "(https://pre-commit.com/) and committing a config."
        )
        sys.exit(0)

    if not args.dryrun:
        _check_pre_commit_cache_writable(env)
        if not _pre_commit_available():
            holohub_cli_util.info("pre-commit is not installed; installing lint dependencies.")
            _install_lint_deps(cli, False, env=env)
            if not _pre_commit_available():
                holohub_cli_util.fatal(
                    "pre-commit was installed but is still not available on PATH. "
                    "Please check your Python environment."
                )

    if args.fix:
        holohub_cli_util.info(
            "`--fix` is a compatibility alias: pre-commit hooks already auto-fix " "where possible."
        )

    cmd: List[str] = [
        sys.executable,
        "-m",
        "pre_commit",
        "run",
        "--show-diff-on-failure",
    ]
    target = _resolve_lint_target(cli, args.path)
    if target == cli.HOLOHUB_ROOT.resolve():
        cmd.append("--all-files")
    else:
        files = _collect_lint_files(cli, target)
        if not files:
            holohub_cli_util.warn(f"No files found under {target}; nothing to lint.")
            sys.exit(0)
        cmd.append("--files")
        cmd.extend(files)

    result = holohub_cli_util.run_command(cmd, check=False, dry_run=args.dryrun, env=env)
    if not args.dryrun and result.returncode == 0:
        print(Color.green("Everything looks good!"))
    sys.exit(result.returncode)
