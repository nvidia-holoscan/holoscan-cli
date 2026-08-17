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
import stat
import subprocess
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from holoscan_cli import __version__
from holoscan_cli.commands.registry import help_for
from holoscan_cli.container import HoloscanContainer
from holoscan_cli.metadata.utils import get_schema_path
from holoscan_cli.utils.io import Color, fatal

LEGACY_MODULE_TEMPLATE = Path("modules/template")
CREATE_TEMPLATE_ENV = "HOLOSCAN_CLI_CREATE_TEMPLATE"
LOCAL_SOURCE_VERSION = "0.0.0+local"


@dataclass(frozen=True)
class _TargetState:
    """Validated state of a prospective project destination."""

    kind: str
    git_identity: Optional[tuple[int, int, int, int, int]] = None


class _MaterializationError(RuntimeError):
    """Staged output could not be copied without replacing an existing path."""


def _scaffold_cli_version(*, is_module: bool) -> str:
    """Return an installable version for a generated Module contract."""
    if is_module and __version__ == LOCAL_SOURCE_VERSION:
        fatal(
            "holoscan create cannot generate an installable Module contract from an "
            "uninstalled source tree (version 0.0.0+local). Build and install a wheel, or "
            "install the checkout into an isolated environment with distribution metadata, "
            "then retry."
        )
    return __version__


def register_create_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``create`` subcommand.

    Direct ``holoscan create`` uses the packaged Module template. Source-project
    wrappers can select a different default with ``HOLOSCAN_CLI_CREATE_TEMPLATE``;
    an explicit ``--template`` always wins.
    """
    parser = subparsers.add_parser("create", help=help_for("create"))
    parser.add_argument("project", help="Name of the project to create")
    parser.add_argument(
        "--template",
        default=None,
        help=(
            "Path to the template directory to use "
            "(default: the standard packaged Holoscan Module template)"
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


def _packaged_module_template() -> AbstractContextManager[Path]:
    """Materialize the bundled Module template as a filesystem directory."""
    template = importlib.resources.files("holoscan_cli.templates").joinpath("module")
    return importlib.resources.as_file(template)


def _resolve_explicit_template(cli, value: str) -> Path:
    """Resolve a caller/wrapper-selected template against the project root."""
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        requested = Path(cli.HOLOHUB_ROOT) / requested
    return requested.resolve()


def _template_context(template_dir: Path) -> dict:
    """Read the cookiecutter context used to classify a template."""
    context_path = template_dir / "cookiecutter.json"
    try:
        with context_path.open("r", encoding="utf-8") as context_file:
            context = json.load(context_file)
    except FileNotFoundError:
        fatal(f"Template directory {template_dir} is missing cookiecutter.json")
    except json.JSONDecodeError as exc:
        fatal(f"Template context {context_path} is not valid JSON: {exc}")
    except OSError as exc:
        fatal(f"Could not read template context {context_path}: {exc}")
    if not isinstance(context, dict):
        fatal(f"Template context {context_path} must contain a JSON object")
    return context


def _is_module_template(template_context: dict) -> bool:
    """Identify Module templates by their public cookiecutter variables."""
    return {"module_slug", "module_repo_name"}.issubset(template_context)


def _parse_extra_context(values: Optional[list[str]]) -> dict[str, str]:
    context: dict[str, str] = {}
    for ctx_var in values or []:
        try:
            key, value = ctx_var.split("=", 1)
        except ValueError:
            fatal(f"Invalid context variable format: {ctx_var}. Expected key=value")
        context[key] = value
    return context


def _project_slug(project_name: str) -> str:
    return project_name.lower().replace(" ", "_").replace("-", "_")


def _output_folder(project: str, context: dict, is_module: bool) -> str:
    """Predict cookiecutter's output folder for collision checks and dry runs."""
    if not is_module:
        return str(context.get("project_slug") or _project_slug(project))

    if context.get("module_repo_name"):
        return str(context["module_repo_name"])
    module_slug = str(
        context.get("module_slug") or _project_slug(str(context.get("project_name") or project))
    )
    return f"holoscan-{module_slug.replace('_', '-')}"


def _intended_project_dir(output_dir: Path, output_folder: str) -> Path:
    """Require cookiecutter's output to be one direct child of the parent."""
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
    return output_dir / folder


def _ensure_output_parent(output_dir: Path) -> None:
    """Create the requested output parent or fail with a path-specific remedy."""
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


def _git_identity(path: Path) -> tuple[int, int, int, int, int]:
    metadata = path.lstat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _inspect_target(path: Path, *, fatal_on_reject: bool = True) -> _TargetState:
    """Accept only missing, empty, or real ``.git``-only destinations."""

    def reject(message: str) -> None:
        if fatal_on_reject:
            fatal(message)
        raise _MaterializationError(message)

    if path.is_symlink():
        reject(
            f"Project destination {path} is a symlink and will not be populated. "
            "Choose a real empty directory or a missing destination."
        )
    if not path.exists():
        return _TargetState("missing")
    if not path.is_dir():
        reject(
            f"Project destination {path} is not a directory and will not be overwritten. "
            "Choose another project name or --directory."
        )

    try:
        entries = list(path.iterdir())
    except OSError as exc:
        reject(f"Could not inspect project destination {path}: {exc}")
    if not entries:
        return _TargetState("empty")
    if len(entries) == 1 and entries[0].name == ".git":
        git_path = entries[0]
        if git_path.is_symlink() or not (git_path.is_dir() or git_path.is_file()):
            reject(
                f"Project destination {path} contains an unsafe .git entry and will not be "
                "populated. Use a real Git directory or worktree pointer file."
            )
        return _TargetState("git-only", _git_identity(git_path))

    reject(
        f"Project directory {path} is non-empty and will not be overwritten. "
        "Only an empty directory or a directory containing only .git can be populated."
    )
    raise AssertionError("fatal() returned unexpectedly")  # pragma: no cover


def _remove_created_paths(paths: list[Path]) -> None:
    """Best-effort rollback that never recursively deletes destination data."""
    for path in reversed(paths):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except OSError:
            # A concurrent writer may have placed data in a directory we made.
            # Leaving it intact is safer than recursively deleting it.
            continue


def _copy_staged_tree(source: Path, destination: Path, created: list[Path]) -> None:
    """Copy one staged directory tree using no-replace filesystem operations."""
    for source_path in sorted(source.iterdir(), key=lambda path: path.name):
        destination_path = destination / source_path.name
        try:
            if source_path.is_symlink():
                destination_path.symlink_to(os.readlink(source_path))
                created.append(destination_path)
            elif source_path.is_dir():
                destination_path.mkdir()
                created.append(destination_path)
                _copy_staged_tree(source_path, destination_path, created)
                shutil.copystat(source_path, destination_path, follow_symlinks=False)
            elif source_path.is_file():
                with (
                    source_path.open("rb") as source_file,
                    destination_path.open("xb") as destination_file,
                ):
                    created.append(destination_path)
                    shutil.copyfileobj(source_file, destination_file)
                shutil.copystat(source_path, destination_path, follow_symlinks=False)
            else:
                raise _MaterializationError(
                    f"Generated project contains unsupported filesystem entry {source_path}."
                )
        except FileExistsError as exc:
            raise _MaterializationError(
                f"Destination path appeared while creating the project: {destination_path}. "
                "Nothing was overwritten."
            ) from exc
        except OSError as exc:
            raise _MaterializationError(
                f"Could not materialize {destination_path} without overwrite: {exc}"
            ) from exc


def _materialize_staged_project(
    staged_project: Path, destination: Path, initial_state: _TargetState
) -> None:
    """Populate a validated destination and roll back files created on failure."""
    try:
        current_state = _inspect_target(destination, fatal_on_reject=False)
    except _MaterializationError as exc:
        raise _MaterializationError(
            f"Project destination {destination} changed during generation; nothing was "
            "overwritten."
        ) from exc
    if current_state != initial_state:
        raise _MaterializationError(
            f"Project destination {destination} changed during generation; nothing was overwritten."
        )

    created: list[Path] = []
    try:
        if initial_state.kind == "missing":
            try:
                destination.mkdir()
            except FileExistsError as exc:
                raise _MaterializationError(
                    f"Project destination {destination} appeared during generation; "
                    "nothing was overwritten."
                ) from exc
            created.append(destination)
        _copy_staged_tree(staged_project, destination, created)
    except BaseException:
        _remove_created_paths(created)
        raise


def _initialize_module_git(project_dir: Path) -> bool:
    """Initialize and stage a new Module without touching pre-existing Git state."""
    if (project_dir / ".git").exists() or (project_dir / ".git").is_symlink():
        return False
    try:
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


def _is_prerelease(version: str) -> bool:
    """Classify the executing version while keeping ``packaging`` create-only."""
    try:
        packaging_version = importlib.import_module("packaging.version")
    except ImportError:
        fatal(
            "Creating a Module requires the optional creation dependencies. "
            "Install them with `pip install 'holoscan-cli[create]'`."
        )
    try:
        return bool(packaging_version.Version(version).is_prerelease)
    except packaging_version.InvalidVersion:
        fatal(f"The executing holoscan-cli version is not valid: {version!r}")
    raise AssertionError("fatal() returned unexpectedly")  # pragma: no cover


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
        cookiecutter_main = importlib.import_module("cookiecutter.main")
    except ImportError:
        template_setup_cmd = f"{cli.script_name} setup --scripts template"
        fatal(
            "cookiecutter is required to create new projects. "
            "Install it with `pip install 'holoscan-cli[create]'`, "
            f"or run `{template_setup_cmd}` for the HoloHub bash setup flow."
        )

    try:
        return cookiecutter_main.cookiecutter(
            str(template_dir),
            no_input=not interactive,
            extra_context=context,
            output_dir=str(output_dir),
        )
    except Exception as exc:
        fatal(f"Failed to create project from template {template_dir} " f"in {output_dir}: {exc}")
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


# ---- handler -----------------------------------------------------------------


def handle_create(cli, args: argparse.Namespace) -> None:
    """Scaffold a project from the packaged or caller-selected template."""
    selected_template = args.template or os.environ.get(CREATE_TEMPLATE_ENV)
    explicit_template: Optional[Path] = None
    use_packaged_template = selected_template is None

    if selected_template:
        explicit_template = _resolve_explicit_template(cli, selected_template)
        if Path(selected_template) == LEGACY_MODULE_TEMPLATE and not explicit_template.exists():
            use_packaged_template = True
        elif not explicit_template.is_dir():
            fatal(
                f"Template directory {explicit_template} does not exist or is not a directory. "
                "Choose an existing --template path and retry."
            )

    template_manager = (
        _packaged_module_template() if use_packaged_template else _PathContext(explicit_template)
    )
    with template_manager as template_dir:
        template_dir = Path(template_dir)
        template_defaults = _template_context(template_dir)
        is_module = _is_module_template(template_defaults)
        scaffold_cli_version = _scaffold_cli_version(is_module=is_module)

        context = {
            "project_name": args.project,
            "project_slug": _project_slug(args.project),
            "language": args.language.lower() if args.language else None,
            "year": datetime.datetime.now().year,
            "_holoscan_cli_version": scaffold_cli_version,
            "_holoscan_cli_prerelease": (
                _is_prerelease(scaffold_cli_version) if is_module else False
            ),
        }
        if HoloscanContainer.BASE_SDK_VERSION:
            context["holoscan_version"] = HoloscanContainer.BASE_SDK_VERSION
        context.update(_parse_extra_context(args.context))

        if args.directory is None:
            output_dir = (
                Path.cwd().resolve()
                if is_module
                else (Path(cli.HOLOHUB_ROOT) / "applications").resolve()
            )
        else:
            output_dir = Path(args.directory).expanduser().resolve()

        output_folder = _output_folder(args.project, context, is_module)
        intended_dir = _intended_project_dir(output_dir, output_folder)
        target_state = _inspect_target(intended_dir)

        if args.dryrun:
            print(Color.green("Would create project folder with these parameters (dryrun):"))
            template_label = "packaged Module template" if use_packaged_template else template_dir
            print(f"Template: {template_label}")
            print(f"Directory: {intended_dir}")
            if target_state.kind == "missing":
                print("Destination: would create a new project directory")
            else:
                print(f"Destination: would populate an existing {target_state.kind} directory")
            for key, value in context.items():
                print(f"  {key}: {value}")
            if not is_module and output_dir == Path(cli.HOLOHUB_ROOT) / "applications":
                print(Color.green("Would modify `applications/CMakeLists.txt`: "))
                print(f"    add_holohub_application({_project_slug(args.project)})")
            return

        _ensure_output_parent(output_dir)
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
            if staged_project.parent != staging_root or actual_slug != output_folder:
                fatal(
                    f"Template generated an unexpected project directory: {staged_project} "
                    f"(expected {staging_root / output_folder})"
                )

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
                _materialize_staged_project(staged_project, intended_dir, target_state)
            except _MaterializationError as exc:
                fatal(str(exc))

        project_dir = intended_dir
        metadata_path = project_dir / "metadata.json"
        main_file = project_dir / main_file_relative if main_file_relative is not None else None

        if not is_module and output_dir == (Path(cli.HOLOHUB_ROOT) / "applications").resolve():
            _add_to_cmakelists(cli, actual_slug)

        git_initialized = False
        if is_module and target_state.kind != "git-only":
            git_initialized = _initialize_module_git(project_dir)

        msg_next = ""
        if is_module:
            msg_next = (
                f"Possible next steps:\n"
                f"- Implement your operator in {project_dir}/operators/\n"
                f"- Update metadata.json: {metadata_path}\n"
                f"- Update project README\n"
                f"- Build and test with: holoscan run-container\n"
            )
        elif not is_module:
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


class _PathContext(AbstractContextManager[Path]):
    """Context-manager adapter for an existing template directory."""

    def __init__(self, path: Optional[Path]):
        if path is None:  # pragma: no cover - guarded by handle_create
            raise ValueError("template path is required")
        self.path = path

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None
