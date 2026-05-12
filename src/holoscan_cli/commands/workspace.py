#!/usr/bin/env python3
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

"""Workspace-touching subcommands: lint, setup, clear-cache, vscode, create.

Each of these acts on the developer's local workspace state rather than
on a specific project's build artifacts:

- lint reads workspace files and runs pre-commit hooks against them
- setup installs system + Python dev dependencies into the host
- clear-cache deletes workspace build/data/install directories
- vscode launches the editor against the workspace via a dev container
- create scaffolds a new project into the workspace from a template

The private helpers (pre-commit installation for lint, cookiecutter +
metadata validation for create, etc.) are bundled here as module-level
functions instead of methods on HoloHubCLI.
"""

import argparse
import datetime
import filecmp
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

import holoscan_cli.util as holohub_cli_util
from holoscan_cli.container import HoloHubContainer
from holoscan_cli.metadata.utils import get_schema_path
from holoscan_cli.utils.io import Color


# ---- lint --------------------------------------------------------------------


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

    cmd = [sys.executable, "-m", "pre_commit", "install-hooks"]
    holohub_cli_util.run_command(cmd, dry_run=dry_run, env=env)


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
            "`--fix` is a compatibility alias: pre-commit hooks already auto-fix "
            "where possible."
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


# ---- setup -------------------------------------------------------------------


def handle_setup(cli, args: argparse.Namespace) -> None:
    """Handle setup command"""

    if args.list_scripts:
        setup_scripts_dir = holohub_cli_util.get_holohub_setup_scripts_dir()
        print(
            holohub_cli_util.format_cmd(
                f"Listing setup scripts available in {setup_scripts_dir}"
            )
        )
        print(Color.green("Use with `./holohub setup --scripts <script_name>`"))
        for script in setup_scripts_dir.glob("*.sh"):
            print(f"  {script.stem}")
        sys.exit(0)

    if args.scripts:
        for script in args.scripts:
            if any(sep in script for sep in ("/", "\\")):
                holohub_cli_util.fatal(
                    f"Invalid script name '{script}': path separators are not allowed"
                )
            script_path = (
                holohub_cli_util.get_holohub_setup_scripts_dir().resolve() / f"{script}.sh"
            )
            if not script_path.exists():
                holohub_cli_util.fatal(
                    f"Script {script}.sh not found in {holohub_cli_util.get_holohub_setup_scripts_dir()}"
                )
            holohub_cli_util.run_command(["bash", str(script_path)], dry_run=args.dryrun)
        sys.exit(0)

    if not args.scripts:
        holohub_cli_util.install_packages_if_missing(
            ["wget", "xvfb", "git", "unzip", "ffmpeg", "ninja-build", "libv4l-dev"],
            dry_run=args.dryrun,
        )

        holohub_cli_util.setup_cuda_dependencies(dry_run=args.dryrun)
        holohub_cli_util.setup_cmake(dry_run=args.dryrun)
        holohub_cli_util.setup_python_dev(dry_run=args.dryrun)
        holohub_cli_util.setup_ngc_cli(dry_run=args.dryrun)
        holohub_cli_util.setup_sccache(dry_run=args.dryrun)

        source = f"{cli.HOLOHUB_ROOT}/utilities/holohub_autocomplete"
        dest_folder = "/etc/bash_completion.d"
        dest = f"{dest_folder}/holohub_autocomplete"
        if (
            not os.path.exists(dest) or not filecmp.cmp(source, dest, shallow=False)
        ) and os.path.exists(dest_folder):
            holohub_cli_util.run_command(["cp", source, dest_folder], dry_run=args.dryrun)

        if not args.dryrun:
            print(
                Color.blue("\nTo enable ./holohub autocomplete in your current shell session:")
            )
            print("  source /etc/bash_completion.d/holohub_autocomplete")
            print("Or add it to your shell profile:")
            print("  echo '. /etc/bash_completion.d/holohub_autocomplete' >> ~/.bashrc")
            print("  source ~/.bashrc")

            print(Color.green("Setup for HoloHub is ready. Happy Holocoding!"))


# ---- clear-cache -------------------------------------------------------------


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
            cli._collect_cache_dirs(["build", "build-*"], cli.DEFAULT_BUILD_PARENT_DIR)
        )

    # Collect data folders if needed
    if clear_all or clear_data:
        cache_dirs.extend(cli._collect_cache_dirs(["data", "data-*"], cli.DEFAULT_DATA_DIR))

    # Collect install folders if needed
    if clear_all or clear_install:
        cache_dirs.extend(cli._collect_cache_dirs(["install", "install-*"]))

    for path in set(cache_dirs):
        if path.exists() and path.is_dir():
            if args.dryrun:
                print(f"  {Color.yellow('Would remove:')} {path}")
            else:
                print(f"  {Color.red('Removing:')} {path}")
                shutil.rmtree(path)


# ---- vscode ------------------------------------------------------------------


def handle_vscode(cli, args: argparse.Namespace) -> None:
    """Builds a dev container and launches VS Code with proper devcontainer configuration."""
    if not shutil.which("code") and not args.dryrun:
        holohub_cli_util.fatal(
            "Please install VS Code to use VS Code Dev Container. "
            "Follow the instructions at https://code.visualstudio.com/Download"
        )

    skip_docker_build, _ = holohub_cli_util.check_skip_builds(args)
    container = cli._make_project_container(
        project_name=args.project, language=getattr(args, "language", None)
    )
    container.dryrun = args.dryrun
    container.verbose = args.verbose
    dev_container_tag = "holohub-dev-container"
    if args.project:
        dev_container_tag += f"-{args.project}"
    dev_container_tag += ":dev"

    if not skip_docker_build:
        print(f"Building base Dev Container {dev_container_tag}...")
        container.build(
            docker_file=args.docker_file,
            base_img=args.base_img,
            img=dev_container_tag,
            no_cache=args.no_cache,
            build_args=args.build_args,
            cuda_version=getattr(args, "cuda", None),
            extra_scripts=getattr(args, "extra_scripts", []),
        )
    else:
        if hasattr(args, "cuda") and args.cuda is not None:
            container.cuda_version = args.cuda
        print(f"Skipping build, using existing Dev Container {dev_container_tag}...")
    devcontainer_env_options = container.get_devcontainer_args(
        docker_opts=getattr(args, "docker_opts", None) or ""
    )

    devcontainer_content = holohub_cli_util.get_devcontainer_config(
        holohub_root=cli.HOLOHUB_ROOT, project_name=args.project, dry_run=args.dryrun
    )
    devcontainer_content = devcontainer_content.replace(
        "${localWorkspaceFolder}", str(cli.HOLOHUB_ROOT)
    )
    devcontainer_content = devcontainer_content.replace('//"<env>"', devcontainer_env_options)
    os.environ["HOLOHUB_BASE_IMAGE"] = dev_container_tag
    if args.project:
        os.environ["HOLOHUB_APP_NAME"] = args.project

    if not args.dryrun:
        tmpdir = tempfile.mkdtemp()
        workspace_name = cli.HOLOHUB_ROOT.name
        tmp_workspace = Path(tmpdir) / workspace_name
        tmp_workspace.mkdir()
        tmp_devcontainer = tmp_workspace / ".devcontainer"
        tmp_devcontainer.mkdir()
        devcontainer_json_dst = tmp_devcontainer / "devcontainer.json"
        with open(devcontainer_json_dst, "w") as f:
            f.write(devcontainer_content)
        print(f"Created temporary workspace: {tmp_devcontainer}")
    else:
        tmp_workspace = "<tmp_workspace>"
    holohub_cli_util.launch_vscode_devcontainer(str(tmp_workspace), dry_run=args.dryrun)


# ---- create ------------------------------------------------------------------


def _add_to_cmakelists(cli, project_name: str) -> None:
    """Add a new application to applications/CMakeLists.txt if it doesn't exist"""
    cmakelists_path = cli.HOLOHUB_ROOT / "applications" / "CMakeLists.txt"
    if not cmakelists_path.exists():
        return
    with open(cmakelists_path, "r") as f:
        lines = f.readlines()
    target_line = f"add_holohub_application({project_name})"
    if any(target_line in line.strip() for line in lines):
        return
    try:
        with open(cmakelists_path, "a") as f:
            f.write(f"add_holohub_application({project_name})\n")
    except Exception as e:
        print(Color.red(f"Failed to add application to applications/CMakeLists.txt: {str(e)}"))
        print(Color.red("Please add the application manually to applications/CMakeLists.txt"))


def validate_generated_metadata(cli, metadata_path: Path, schema_root: Optional[Path]) -> None:
    """Validate metadata.json for the newly created project."""
    try:
        from holoscan_cli.metadata import metadata_validator
    except ImportError:
        template_setup_cmd = f"{cli.script_name} setup --scripts template"
        holohub_cli_util.fatal(
            "Template dependencies required for metadata validation are missing. "
            f"Please run `{template_setup_cmd}` and retry."
        )
    if not schema_root:
        # No schema installed – skip validation.
        return
    if not metadata_path.exists():
        holohub_cli_util.fatal(f"Generated project is missing metadata.json at {metadata_path}")
    try:
        with open(metadata_path, "r", encoding="utf-8") as metadata_file:
            metadata_contents = json.load(metadata_file)
    except json.JSONDecodeError as exc:
        holohub_cli_util.fatal(
            f"Generated metadata.json is not valid ({exc}). File location: {metadata_path}"
        )
    except OSError as exc:
        holohub_cli_util.fatal(
            f"Failed to read metadata.json ({exc}). File location: {metadata_path}"
        )
    is_valid, message = metadata_validator.validate_json(metadata_contents, str(schema_root))
    schema_file = get_schema_path(schema_root)
    if not is_valid:
        holohub_cli_util.fatal(
            f"Generated metadata.json failed validation against {schema_file}:\n{message}"
        )
    print(Color.green(f"Validated metadata.json against {schema_file}"))


def handle_create(cli, args: argparse.Namespace) -> None:
    """Handle create command"""
    # Ensure template directory exists
    template_dir = cli.HOLOHUB_ROOT / args.template
    if not template_dir.exists() and not args.dryrun:
        holohub_cli_util.fatal(f"Template directory {template_dir} does not exist")

    if not args.directory.exists() and not args.dryrun:
        holohub_cli_util.fatal(f"Project output directory {args.directory} does not exist")

    # Define minimal context with required fields
    context = {
        "project_name": args.project,
        "project_slug": args.project.lower().replace(" ", "_"),
        "language": args.language.lower() if args.language else None,  # Only set if provided
        "holoscan_version": HoloHubContainer.BASE_SDK_VERSION,
        "year": datetime.datetime.now().year,
    }

    # Add any additional context variables from command line
    if args.context:
        for ctx_var in args.context:
            try:
                key, value = ctx_var.split("=", 1)
                context[key] = value
            except ValueError:
                holohub_cli_util.fatal(
                    f"Invalid context variable format: {ctx_var}. Expected key=value"
                )

    # Print summary if dryrun
    if args.dryrun:
        print(Color.green("Would create project folder with these parameters (dryrun):"))
        print(f"Directory: {args.directory / context['project_slug']}")
        for key, value in context.items():
            print(f"  {key}: {value}")
        if args.directory == cli.HOLOHUB_ROOT / "applications":
            print(Color.green("Would modify `applications/CMakeLists.txt`: "))
            print(f"    add_holohub_application({context['project_slug']})")
        return

    try:
        import cookiecutter.main
    except ImportError:
        template_setup_cmd = f"{cli.script_name} setup --scripts template"
        holohub_cli_util.fatal(
            "cookiecutter is required to create new projects. "
            f"Please run `{template_setup_cmd}` to install template dependencies."
        )

    intended_dir = args.directory / context["project_slug"]
    if intended_dir.exists():
        holohub_cli_util.fatal(f"Project directory {intended_dir} already exists")

    try:
        # Let cookiecutter handle all file generation
        generated_path = cookiecutter.main.cookiecutter(
            str(template_dir),
            no_input=not args.interactive,
            extra_context=context,
            output_dir=str(args.directory),
        )
    except Exception as e:
        holohub_cli_util.fatal(f"Failed to create project: {str(e)}")

    # Add to CMakeLists.txt if in applications directory
    project_dir = Path(generated_path)
    actual_slug = project_dir.name

    if args.directory == cli.HOLOHUB_ROOT / "applications":
        _add_to_cmakelists(cli, actual_slug)

    # Get the actual project directory after cookiecutter runs
    metadata_path = project_dir / "metadata.json"
    src_dir = project_dir / "src"
    main_file = next(src_dir.glob(f"{actual_slug}.*"), None)
    schema_path = get_schema_path("applications")
    schema_root = "applications" if schema_path.exists() else None
    validate_generated_metadata(cli, metadata_path, schema_root)

    msg_next = ""
    if "applications" in args.template:
        msg_next = (
            f"Possible next steps:\n"
            f"- Add operators to {main_file}\n"
            f"- Update project metadata in {metadata_path}\n"
            f"- Review source code license files and headers (e.g. {project_dir / 'LICENSE'})\n"
            f"- Build and run the application:\n"
            f"   {cli.script_name} run {actual_slug}"
        )

    print(
        Color.green(f"Successfully created new project: {args.project}"),
        f"\nDirectory: {project_dir}\n\n{msg_next}",
    )
