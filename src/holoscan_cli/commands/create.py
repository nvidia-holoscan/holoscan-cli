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
import json
from pathlib import Path
from typing import Optional

import holoscan_cli.util as holohub_cli_util
from holoscan_cli.commands.registry import help_for
from holoscan_cli.container import HoloHubContainer
from holoscan_cli.metadata.utils import get_schema_path
from holoscan_cli.utils.io import Color


def register_create_parser(cli, subparsers) -> argparse.ArgumentParser:
    """Register the ``create`` subcommand.

    The ``--template`` and ``--directory`` defaults are derived from
    ``cli.HOLOHUB_ROOT`` so wrapper scripts that override the project root
    (via ``HOLOHUB_ROOT`` env var) automatically pick up the right paths.
    """
    parser = subparsers.add_parser("create", help=help_for("create"))
    parser.add_argument("project", help="Name of the project to create")
    parser.add_argument(
        "--template",
        default=str(cli.HOLOHUB_ROOT / "applications" / "template"),
        help="Path to the template directory to use",
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
        default=cli.HOLOHUB_ROOT / "applications",
        help="Path to the directory to create the project in",
    )
    parser.add_argument(
        "--context",
        action="append",
        help='Additional context variables for cookiecutter in format key=value. \
            Example: --context description=\'My project desc\' \
                --context tags=[\\"tag1\\", \\"tag2\\"]',
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


# ---- handler -----------------------------------------------------------------


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
