# SPDX-FileCopyrightText: Copyright (c) 2023-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
import importlib.metadata
import sys
from argparse import Namespace
from pathlib import Path

from holoscan_cli import __version__
from holoscan_cli.project_context import ProjectContext, get_active_project_context
from holoscan_cli.utils.json_output import dumps as json_dumps

PACKAGE_NAME = "holoscan-cli"


def get_package_version() -> str:
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return __version__


def collect_version_info(context: ProjectContext | None = None) -> dict:
    """Return the version fields shared by the prose and JSON renderers."""
    info = {
        "package": PACKAGE_NAME,
        "version": get_package_version(),
        "executable": str(Path(sys.argv[0]).resolve()),
        "module": str(Path(__file__).resolve()),
    }
    context = context or get_active_project_context()
    if context is not None and context.is_module:
        info.update(
            {
                "project_root": str(context.root),
                "requirements_file": (
                    str(context.requirements_path) if context.requirements_path else None
                ),
                "required_version": context.required_version,
                "version_match": context.version_match,
            }
        )
        if context.requirement_error:
            info["requirement_error"] = context.requirement_error
    return info


def execute_version_command(args: Namespace):
    info = collect_version_info(getattr(args, "project_context", None))
    project_error = getattr(args, "project_error", None)
    if project_error:
        info["project_error"] = project_error
    if getattr(args, "json", False):
        print(json_dumps(info))
        return
    print(f"Package:     {info['package']}")
    print(f"Version:     {info['version']}")
    print(f"Executable:  {info['executable']}")
    print(f"Module:      {info['module']}")
    if "project_root" in info:
        print(f"Project:     {info['project_root']}")
        print(f"Requirement: {info.get('required_version') or '(invalid or missing)'}")
        print(f"Version match: {info.get('version_match')}")
        if info.get("requirement_error"):
            print(f"Requirement error: {info['requirement_error']}")
    if info.get("project_error"):
        print(f"Project error: {info['project_error']}")
