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

"""``holoscan create`` — scaffold a new project from a cookiecutter template."""

import argparse
import datetime
import importlib
import importlib.resources
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Optional, Union

from holoscan_cli import __version__
from holoscan_cli.commands.registry import help_for
from holoscan_cli.container import HoloscanContainer
from holoscan_cli.metadata.utils import get_schema_path
from holoscan_cli.utils.filesystem import (
    DirectoryMaterializationError,
    inspect_directory,
    materialize_tree,
)
from holoscan_cli.utils.io import Color, fatal
from holoscan_cli.utils.text import parse_key_value_pairs, to_snake_case

LEGACY_MODULE_TEMPLATE = Path("modules/template")
CREATE_TEMPLATE_ENV = "HOLOSCAN_CLI_CREATE_TEMPLATE"
LOCAL_SOURCE_VERSION = "0.0.0+local"
RESERVED_CONTEXT_KEYS = {"_holoscan_cli_version"}
PRESERVED_DESTINATION_ENTRIES = {".git"}


def register_create_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``create`` subcommand.

    Direct ``holoscan create`` uses the packaged Module template. Source-project
    wrappers can select their own default with ``HOLOSCAN_CLI_CREATE_TEMPLATE``;
    an explicit ``--template`` always wins.
    """
    parser = subparsers.add_parser("create", help=help_for("create"))
    parser.add_argument("project", help="Name of the project to create")
    parser.add_argument(
        "--template",
        default=None,
        help=(
            "Path to the template directory to use "
            "(default: HOLOSCAN_CLI_CREATE_TEMPLATE when set, otherwise the packaged "
            "Module template)"
        ),
    )
    parser.add_argument(
        "--language",
        choices=["cpp", "python"],
        default="cpp",
        help="Programming language for the project",
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=None,
        help=(
            "Output directory for the generated project "
            "(default: current directory for Module templates; "
            "applications/ for application templates)"
        ),
    )
    parser.add_argument(
        "--context",
        action="append",
        help=(
            "Additional cookiecutter context as key=value. Values are strings; repeat for "
            "multiple keys, for example --context description='My project description'."
        ),
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store",
        nargs="?",
        const=True,
        default=True,
        type=lambda x: x.lower() not in ("false", "no", "n", "0", "f"),
        help="Interactive mode for setting cookiecutter properties (use -i False to disable)",
    )
    parser.set_defaults(func=lambda args: handle_create(cli, args))
    return parser


# ---- private helpers ---------------------------------------------------------


def _initialize_module_git(project_dir: Path) -> bool:
    """Initialize a fresh standalone Module without touching existing Git state."""
    try:
        worktree = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=project_dir,
            check=False,
            capture_output=True,
        )
        if worktree.returncode == 0:
            return False
        subprocess.run(["git", "init", "."], cwd=project_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
            cwd=project_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=project_dir, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _run_cookiecutter(
    cli,
    template_dir: Path,
    *,
    interactive: bool,
    context: dict,
    output_dir: Path,
) -> str:
    """Generate a project while keeping creation dependencies optional."""
    try:
        cookiecutter_config = importlib.import_module("cookiecutter.config")
        cookiecutter_main = importlib.import_module("cookiecutter.main")
    except ImportError:
        template_setup_cmd = f"{cli.script_name} setup --scripts template"
        fatal(
            "cookiecutter is required to create new projects. "
            "Install it with `pip install 'holoscan-cli[create]'`, "
            f"or run `{template_setup_cmd}` for the HoloHub bash setup flow."
        )

    try:
        runtime_config = dict(cookiecutter_config.get_user_config())
        # Cookiecutter always records a replay file. Keep that implementation
        # detail inside the staging directory so creation works with a
        # read-only home and does not retain scaffold context after success.
        runtime_config["replay_dir"] = str(output_dir / ".cookiecutter-replay")
        return cookiecutter_main.cookiecutter(
            str(template_dir),
            no_input=not interactive,
            extra_context=context,
            output_dir=str(output_dir),
            default_config=runtime_config,
        )
    except Exception as exc:
        fatal(f"Failed to create project from template {template_dir} in {output_dir}: {exc}")
        raise AssertionError("fatal() returned unexpectedly")  # pragma: no cover


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


def validate_generated_metadata(
    cli, metadata_path: Path, schema_root: Optional[Union[str, Path]]
) -> None:
    """Validate metadata.json for the newly created project."""
    try:
        from holoscan_cli.metadata import metadata_validator
    except ImportError:
        template_setup_cmd = f"{cli.script_name} setup --scripts template"
        fatal(
            "Metadata validation requires the optional 'create' dependencies "
            "(jsonschema, referencing). Install them with "
            "`pip install 'holoscan-cli[create]'` "
            f"(or, inside a HoloHub checkout, `{template_setup_cmd}`) and retry."
        )
    if not schema_root:
        # No schema installed – skip validation.
        return
    if not metadata_path.exists():
        fatal(f"Generated project is missing metadata.json at {metadata_path}")
    try:
        with open(metadata_path, "r", encoding="utf-8") as metadata_file:
            metadata_contents = json.load(metadata_file)
    except json.JSONDecodeError as exc:
        fatal(f"Generated metadata.json is not valid ({exc}). File location: {metadata_path}")
    except OSError as exc:
        fatal(f"Failed to read metadata.json ({exc}). File location: {metadata_path}")
    is_valid, message = metadata_validator.validate_json(metadata_contents, str(schema_root))
    schema_file = get_schema_path(schema_root)
    if not is_valid:
        fatal(f"Generated metadata.json failed validation against {schema_file}:\n{message}")
    print(Color.green(f"Validated metadata.json against {schema_file}"))


def copy_cmake_support(project_dir: Path) -> None:
    """Vendor the CLI's packaged CMake support into a generated project."""
    resource = importlib.resources.files("holoscan_cli").joinpath("cmake")
    with importlib.resources.as_file(resource) as source:
        shutil.copytree(source, project_dir / "cmake", dirs_exist_ok=True)


def _packaged_module_template() -> AbstractContextManager[Path]:
    """Extract the wheel's Module template to a real directory for the duration."""
    resource = importlib.resources.files("holoscan_cli.templates").joinpath("module")
    return importlib.resources.as_file(resource)


def _select_template(cli, template: Optional[str]) -> tuple[AbstractContextManager[Path], bool]:
    """Resolve the template directory and whether it is the packaged Module one.

    An explicit ``--template`` wins, then ``HOLOSCAN_CLI_CREATE_TEMPLATE``, then
    the packaged Module template. Relative paths resolve against the active
    source-project root so wrappers can set a project-relative default.
    """
    if template is not None and not str(template).strip():
        fatal("--template requires a non-empty directory path.")

    selected = template or os.environ.get(CREATE_TEMPLATE_ENV) or None
    if selected is None:
        return _packaged_module_template(), True

    resolved = Path(selected).expanduser()
    if not resolved.is_absolute():
        resolved = Path(cli.HOLOHUB_ROOT) / resolved
    resolved = resolved.resolve()
    # The in-tree HoloHub Module template now ships in the wheel; keep the old
    # path working for callers that still pass it.
    if Path(selected) == LEGACY_MODULE_TEMPLATE and not resolved.exists():
        return _packaged_module_template(), True
    if not resolved.is_dir():
        fatal(
            f"Template directory {resolved} does not exist or is not a directory. "
            "Choose an existing --template path and retry."
        )
    return nullcontext(resolved), False


# ---- handler -----------------------------------------------------------------


def handle_create(cli, args: argparse.Namespace) -> None:
    """Scaffold a project from the packaged or caller-selected template."""
    template_manager, use_packaged_template = _select_template(cli, args.template)

    with template_manager as template_dir:
        template_dir = Path(template_dir)
        context_path = template_dir / "cookiecutter.json"
        try:
            template_defaults = json.loads(context_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            fatal(f"Template directory {template_dir} is missing cookiecutter.json")
        except json.JSONDecodeError as exc:
            fatal(f"Template context {context_path} is not valid JSON: {exc}")
        except OSError as exc:
            fatal(f"Could not read template context {context_path}: {exc}")
        if not isinstance(template_defaults, dict):
            fatal(f"Template context {context_path} must contain a JSON object")

        is_module = {"module_slug", "module_repo_name"}.issubset(template_defaults)
        if is_module and __version__ == LOCAL_SOURCE_VERSION:
            fatal(
                "holoscan create cannot generate an installable Module contract from an "
                "uninstalled source tree (version 0.0.0+local). Build and install a wheel, or "
                "install the checkout into an isolated environment with distribution metadata, "
                "then retry."
            )
        project_slug = to_snake_case(args.project)
        context = {
            "project_name": args.project,
            "project_slug": project_slug,
            "language": args.language.lower() if args.language else None,
            "year": datetime.datetime.now().year,
            "_holoscan_cli_version": __version__,
        }
        if HoloscanContainer.BASE_SDK_VERSION:
            context["holoscan_version"] = HoloscanContainer.BASE_SDK_VERSION
        try:
            extra_context = parse_key_value_pairs(args.context)
        except ValueError as exc:
            fatal(f"Invalid context variable format: {exc}")
        for key in extra_context:
            if key in RESERVED_CONTEXT_KEYS:
                fatal(
                    f"Cookiecutter context {key!r} is managed by holoscan create and cannot "
                    "be overridden."
                )
        context.update(extra_context)

        applications_dir = (Path(cli.HOLOHUB_ROOT) / "applications").resolve()
        if args.directory is None:
            output_dir = Path.cwd().resolve() if is_module else applications_dir
        else:
            output_dir = Path(args.directory).expanduser().resolve()
        # Applications registered in the source project's CMakeLists must be
        # added there; Modules and out-of-tree destinations never are.
        registers_application = not is_module and output_dir == applications_dir

        if not is_module:
            output_folder = str(context.get("project_slug") or project_slug)
        elif context.get("module_repo_name"):
            output_folder = str(context["module_repo_name"])
        else:
            module_slug = str(
                context.get("module_slug")
                or to_snake_case(str(context.get("project_name") or args.project))
            )
            output_folder = f"holoscan-{module_slug.replace('_', '-')}"

        folder = Path(output_folder)
        if (
            not output_folder
            or folder.is_absolute()
            or len(folder.parts) != 1
            or folder.name in {".", ".."}
        ):
            fatal(
                f"Invalid generated project directory name {output_folder!r}. "
                "Use a project name or context value that produces one directory name."
            )
        intended_dir = output_dir / folder
        try:
            target_state = inspect_directory(
                intended_dir, allowed_entries=PRESERVED_DESTINATION_ENTRIES
            )
        except DirectoryMaterializationError as exc:
            fatal(
                f"{exc} Choose a missing or empty destination, or one containing only a real .git "
                "file or directory."
            )

        if args.dryrun:
            print(Color.green("Would create project folder with these parameters (dryrun):"))
            template_label = "packaged Module template" if use_packaged_template else template_dir
            print(f"Template: {template_label}")
            print(f"Directory: {intended_dir}")
            if target_state.kind == "missing":
                print("Destination: would create a new project directory")
            else:
                target_kind = ".git-only" if target_state.entries else target_state.kind
                print(f"Destination: would populate an existing {target_kind} directory")
            for key, value in context.items():
                print(f"  {key}: {value}")
            if registers_application:
                print(Color.green("Would modify `applications/CMakeLists.txt`: "))
                print(f"    add_holohub_application({project_slug})")
            return

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            fatal(
                f"Could not create project output directory {output_dir}: {exc}. "
                "Choose a writable --directory or fix the blocking path and retry."
            )
        if not output_dir.is_dir():
            fatal(
                f"Project output path {output_dir} is not a directory. "
                "Choose another --directory or remove the blocking file and retry."
            )

        main_file_relative: Optional[Path] = None
        with tempfile.TemporaryDirectory(
            prefix=f".{output_folder}.holoscan-create-", dir=output_dir
        ) as staging_dir:
            staging_root = Path(staging_dir).resolve()
            generated_path = _run_cookiecutter(
                cli,
                template_dir,
                interactive=args.interactive,
                context=context,
                output_dir=staging_root,
            )

            staged_project = Path(generated_path).resolve()
            actual_slug = staged_project.name
            if staged_project.parent != staging_root:
                fatal(
                    f"Template generated a project outside its staging directory: "
                    f"{staged_project} (expected a direct child of {staging_root})"
                )
            if actual_slug != output_folder:
                # Interactive prompts may rename the project, so honor the
                # template's answer and re-check the destination it implies.
                intended_dir = output_dir / actual_slug
                try:
                    target_state = inspect_directory(
                        intended_dir, allowed_entries=PRESERVED_DESTINATION_ENTRIES
                    )
                except DirectoryMaterializationError as exc:
                    fatal(
                        f"{exc} Choose a missing or empty destination, or one containing only a "
                        "real .git file or directory."
                    )

            if is_module:
                try:
                    copy_cmake_support(staged_project)
                except OSError as exc:
                    fatal(f"Could not copy packaged CMake support into the Module: {exc}")

            staged_metadata = staged_project / "metadata.json"
            if is_module:
                schema_root: Optional[Union[str, Path]] = "modules"
            else:
                staged_source = staged_project / "src"
                staged_main = next(staged_source.glob(f"{actual_slug}.*"), None)
                if staged_main is not None:
                    main_file_relative = staged_main.relative_to(staged_project)
                schema_path = get_schema_path("applications")
                schema_root = "applications" if schema_path.exists() else None
            validate_generated_metadata(cli, staged_metadata, schema_root)

            try:
                materialize_tree(
                    staged_project,
                    intended_dir,
                    target_state,
                    allowed_entries=PRESERVED_DESTINATION_ENTRIES,
                )
            except DirectoryMaterializationError as exc:
                fatal(str(exc))

        project_dir = intended_dir
        metadata_path = project_dir / "metadata.json"
        main_file = project_dir / main_file_relative if main_file_relative is not None else None

        if registers_application:
            _add_to_cmakelists(cli, actual_slug)

        git_initialized = False
        if is_module and not target_state.entries:
            git_initialized = _initialize_module_git(project_dir)

        if is_module:
            msg_next = (
                f"Possible next steps:\n"
                f"- Implement your operator in {project_dir}/operators/\n"
                f"- Update metadata.json: {metadata_path}\n"
                f"- Update project README\n"
                f"- Follow the Quick Start in {project_dir / 'README.md'}\n"
            )
        else:
            msg_next = (
                f"Possible next steps:\n"
                f"- Add operators to {main_file}\n"
                f"- Update project metadata in {metadata_path}\n"
                f"- Review source code license files and headers "
                f"(e.g. {project_dir / 'LICENSE'})\n"
                f"- Build and run the application:\n"
                f"   {cli.script_name} run {actual_slug}"
            )

        print(
            Color.green(f"Successfully created new project: {args.project}"),
            f"\nDirectory: {project_dir}\n\n{msg_next}",
        )
        if git_initialized:
            print(
                Color.green("Initialized a Git repository on branch main and staged the scaffold.")
            )
