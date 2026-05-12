#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

# See cli_dev_guide.md for more information about the CLI and how to use it.
# See README.md for command and flag reference.

import sys

# Python version check - must be before other imports that use Python 3.10+ features
PYTHON_MIN_VERSION = (3, 10, 0)
if sys.version_info < PYTHON_MIN_VERSION:
    sys_major, sys_minor, sys_micro = sys.version_info[:3]
    print(
        f"Error: Python {'.'.join(map(str, PYTHON_MIN_VERSION))} or higher required, "
        f"found {sys_major}.{sys_minor}.{sys_micro}",
        file=sys.stderr,
    )
    sys.exit(1)

# ruff: noqa: E402  # Imports after python version check
import argparse
import os
from pathlib import Path
from typing import List, Optional

import holoscan_cli.metadata.gather_metadata as metadata_util
import holoscan_cli.util as holohub_cli_util
from holoscan_cli.commands import devcontainer as commands_devcontainer
from holoscan_cli.commands import info as commands_info
from holoscan_cli.commands import project as commands_project
from holoscan_cli.commands import workspace as commands_workspace
from holoscan_cli.container import HoloHubContainer
from holoscan_cli.container.parsers import get_build_argparse, get_run_argparse
from holoscan_cli.metadata.utils import (
    list_normalized_languages,
    normalize_language,
)
from holoscan_cli.util import Color


def in_container_cli_command() -> str:
    """Command used when the host CLI recurses into a container build/run/install.

    Returns the installed ``holoscan`` console script by default. Decoupled from
    ``HoloHubCLI.script_name`` so the in-container recursion is independent of how
    the user invoked the CLI on the host (e.g. via ``./holohub``, ``./i4h``, or
    ``python -m holoscan_cli``). Override via ``HOLOSCAN_CLI_IN_CONTAINER_CMD``
    when the container ships a different entry point (e.g. ``python3 -m
    holoscan_cli``).
    """
    return os.environ.get("HOLOSCAN_CLI_IN_CONTAINER_CMD", "holoscan")


class HoloHubCLI:
    """Command-line interface for HoloHub"""

    HOLOHUB_ROOT = holohub_cli_util.get_holohub_root()
    DEFAULT_BUILD_PARENT_DIR = Path(
        os.environ.get("HOLOHUB_BUILD_PARENT_DIR", HOLOHUB_ROOT / "build")
    )
    DEFAULT_DATA_DIR = Path(os.environ.get("HOLOHUB_DATA_DIR", HOLOHUB_ROOT / "data"))
    DEFAULT_SDK_DIR = os.environ.get("HOLOHUB_DEFAULT_HSDK_DIR", "/opt/nvidia/holoscan")
    # Allow overriding the default CTest script path via environment variable
    DEFAULT_CTEST_SCRIPT = os.environ.get(
        "HOLOHUB_CTEST_SCRIPT",
        str(Path(__file__).resolve().parent / "testing" / "holohub.container.ctest"),
    )

    def __init__(self, script_name: Optional[str] = None):
        self.script_name = script_name or os.environ.get("HOLOHUB_CMD_NAME", "./holohub")
        self.parser = self._create_parser()
        # Cache for resolved projects to avoid duplicate lookups
        self._project_data: dict[tuple[str, str], dict] = {}
        self._collect_metadata()
        self.prefix = holohub_cli_util.resolve_path_prefix(None)

    def _create_parser(self) -> argparse.ArgumentParser:
        """Create the argument parser with all supported commands"""
        parser = argparse.ArgumentParser(
            prog=self.script_name,
            description=f"{self.script_name} CLI tool for managing Holoscan-based applications and containers",
        )
        subparsers = parser.add_subparsers(dest="command", required=True)

        # Store subparsers for error handling
        self.subparsers = {}

        # Common container arguments parent parsers
        container_build_argparse = get_build_argparse()
        container_run_argparse = get_run_argparse()
        # Add create command
        create = subparsers.add_parser("create", help="Create a new Holoscan application")
        self.subparsers["create"] = create
        create.add_argument("project", help="Name of the project to create")
        create.add_argument(
            "--template",
            default=str(HoloHubCLI.HOLOHUB_ROOT / "applications" / "template"),
            help="Path to the template directory to use",
        )
        create.add_argument(
            "--language",
            choices=["cpp", "python"],
            default="cpp",
            help="Programming language for the project",
        )
        create.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        create.add_argument(
            "--directory",
            type=Path,
            default=self.HOLOHUB_ROOT / "applications",
            help="Path to the directory to create the project in",
        )
        create.add_argument(
            "--context",
            action="append",
            help='Additional context variables for cookiecutter in format key=value. \
                Example: --context description=\'My project desc\' \
                    --context tags=[\\"tag1\\", \\"tag2\\"]',
        )
        create.add_argument(
            "-i",
            "--interactive",
            action="store",
            nargs="?",
            const=True,
            default=True,
            type=lambda x: x.lower() not in ("false", "no", "n", "0", "f"),
            help="Interactive mode for setting cookiecutter properties (use -i False to disable)",
        )
        create.set_defaults(func=lambda args: commands_workspace.handle_create(self, args))

        # build-container command
        build_container = subparsers.add_parser(
            "build-container",
            help="Build the development container",
            parents=[container_build_argparse],
        )
        self.subparsers["build-container"] = build_container
        build_container.add_argument("project", nargs="?", help="Project to build container for")
        build_container.add_argument(
            "mode", nargs="?", help="Mode to build container for (optional)"
        )
        build_container.add_argument(
            "--verbose", action="store_true", help="Print variables passed to docker build command"
        )
        build_container.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        build_container.add_argument(
            "--language", choices=["cpp", "python"], help="Specify language implementation"
        )
        build_container.set_defaults(
            func=lambda args: commands_devcontainer.handle_build_container(self, args)
        )

        # run-container command
        run_container = subparsers.add_parser(
            "run-container",
            help="Build and launch the development container",
            parents=[container_build_argparse, container_run_argparse],
            epilog="Any arguments after ' -- ' are executed as a command inside the container",
        )
        self.subparsers["run-container"] = run_container
        run_container.add_argument("project", nargs="?", help="Project to run container for")
        run_container.add_argument("mode", nargs="?", help="Mode to run container for (optional)")
        run_container.add_argument(
            "--verbose", action="store_true", help="Print variables passed to docker run command"
        )
        run_container.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        run_container.add_argument(
            "--language", choices=["cpp", "python"], help="Specify language implementation"
        )
        run_container.add_argument(
            "--no-docker-build", action="store_true", help="Skip building the container"
        )
        run_container.set_defaults(
            func=lambda args: commands_devcontainer.handle_run_container(self, args)
        )

        # build command
        build = subparsers.add_parser(
            "build",
            help="Build a project",
            parents=[container_build_argparse, container_run_argparse],
        )
        self.subparsers["build"] = build
        build.add_argument("project", help="Project to build")
        build.add_argument("mode", nargs="?", help="Mode to build (optional)")
        build.add_argument(
            "--local", action="store_true", help="Build locally instead of in container"
        )
        build.add_argument("--verbose", action="store_true", help="Print extra output")
        build.add_argument(
            "--build-type",
            help="Build type (debug, release, rel-debug). "
            "If not specified, uses CMAKE_BUILD_TYPE environment variable or defaults to 'release'",
        )
        build.add_argument(
            "--build-with",
            dest="with_operators",
            help="Optional operators that should be built, separated by semicolons (;)",
        )
        build.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        build.add_argument(
            "--pkg-generator", default="DEB", help="Package generator for cpack (default: DEB)"
        )
        build.add_argument(
            "--parallel", help="Number of parallel build jobs (e.g. --parallel $(($(nproc)-1)))"
        )
        build.add_argument(
            "--language", choices=["cpp", "python"], help="Specify language implementation"
        )
        build.add_argument(
            "--benchmark",
            action="store_true",
            help="Build for Holoscan Flow Benchmarking. Valid for applications/workflows only",
        )
        build.add_argument(
            "--no-docker-build", action="store_true", help="Skip building the container"
        )
        build.add_argument(
            "--configure-args",
            action="append",
            help="Additional configuration arguments for cmake "
            "example: --configure-args='-DCUSTOM_OPTION=ON' --configure-args='-Dtest=ON'",
        )
        build.set_defaults(func=lambda args: commands_project.handle_build(self, args))

        # run command
        run = subparsers.add_parser(
            "run",
            help="Build and run a project",
            parents=[container_build_argparse, container_run_argparse],
        )
        self.subparsers["run"] = run
        run.add_argument("project", help="Project to run")
        run.add_argument("mode", nargs="?", help="Mode to run (optional)")
        run.add_argument("--local", action="store_true", help="Run locally instead of in container")
        run.add_argument("--verbose", action="store_true", help="Print extra output")
        run.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        run.add_argument(
            "--language", choices=["cpp", "python"], help="Specify language implementation"
        )
        run.add_argument(
            "--build-type",
            help="Build type (debug, release, rel-debug). "
            "If not specified, uses CMAKE_BUILD_TYPE environment variable or defaults to 'release'",
        )
        run.add_argument(
            "--run-args",
            help="Additional arguments to pass to the application executable, "
            "example: --run-args=--flag or --run-args '-c config/file'",
        )

        run.add_argument(
            "--build-with",
            dest="with_operators",
            help="Optional operators that should be built, separated by semicolons (;)",
        )
        run.add_argument(
            "--parallel", help="Number of parallel build jobs (e.g. --parallel $(($(nproc)-1)))"
        )
        run.add_argument(
            "--pkg-generator", default="DEB", help="Package generator for cpack (default: DEB)"
        )
        run.add_argument(
            "--no-local-build",
            action="store_true",
            help="Skip building and just run the application",
        )
        run.add_argument(
            "--no-docker-build", action="store_true", help="Skip building the container"
        )
        run.add_argument(
            "--configure-args",
            action="append",
            help="Additional configuration arguments for cmake "
            "example: --configure-args='-DCUSTOM_OPTION=ON' --configure-args='-Dtest=ON'",
        )
        run.set_defaults(func=lambda args: commands_project.handle_run(self, args))

        # list command
        list_cmd = subparsers.add_parser("list", help="List all available targets")
        self.subparsers["list"] = list_cmd
        list_cmd.set_defaults(func=lambda args: commands_info.handle_list(self, args))

        # modes command
        modes = subparsers.add_parser("modes", help="List available modes for an application")
        self.subparsers["modes"] = modes
        modes.add_argument("project", help="Project to list modes for")
        modes.add_argument(
            "--language", choices=["cpp", "python"], help="Specify language implementation"
        )
        modes.set_defaults(func=lambda args: commands_info.handle_modes(self, args))

        # autocompletion_list command (for bash completion)
        autocomp_cmd = subparsers.add_parser(
            "autocompletion_list", help="List targets for autocompletion"
        )
        self.subparsers["autocompletion_list"] = autocomp_cmd
        autocomp_cmd.set_defaults(func=lambda args: commands_info.handle_autocompletion_list(self, args))

        # lint command
        lint = subparsers.add_parser("lint", help="Run repository linting via pre-commit")
        self.subparsers["lint"] = lint
        lint.add_argument("path", nargs="?", default=".", help="Path to lint")
        lint.add_argument("--fix", action="store_true", help="Fix linting issues")
        lint.add_argument(
            "--install-dependencies",
            action="store_true",
            help="Install linting dependencies (may require `sudo` privileges)",
        )
        lint.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        lint.set_defaults(func=lambda args: commands_workspace.handle_lint(self, args))

        # setup command
        setup = subparsers.add_parser(
            "setup", help="Install HoloHub recommended packages for development."
        )
        self.subparsers["setup"] = setup
        setup.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        setup.add_argument(
            "--list-scripts",
            action="store_true",
            help="List all setup scripts found in the HOLOHUB_SETUP_SCRIPTS_DIR directory. "
            + "Run scripts directly or with `./holohub setup --scripts <script_name>`.",
        )
        setup.add_argument(
            "--scripts",
            action="append",
            help="Named dependency installation scripts to run. Can be specified multiple times. "
            + "Searches in the directory path specified by the HOLOHUB_SETUP_SCRIPTS_DIR environment variable. "
            + "Omit to install default recommended packages for Holoscan SDK development.",
        )
        setup.set_defaults(func=lambda args: commands_workspace.handle_setup(self, args))

        # Add env-info command
        env_info = subparsers.add_parser(
            "env-info", help="Display environment debugging information"
        )
        self.subparsers["env-info"] = env_info
        env_info.set_defaults(func=lambda args: commands_info.handle_env_info(self, args))

        # Add status command
        status = subparsers.add_parser(
            "status", help="Show environment, container, and build status"
        )
        self.subparsers["status"] = status
        status.add_argument("--json", action="store_true", help="Output status as JSON")
        status.set_defaults(func=lambda args: commands_info.handle_status(self, args))

        # Add env-check command
        env_check = subparsers.add_parser(
            "env-check",
            help="Run system checks (GPU, CUDA, Docker, Holoscan SDK, disk, display, devices)",
        )
        self.subparsers["env-check"] = env_check
        env_check.add_argument("--json", action="store_true", help="Output check results as JSON")
        env_check.set_defaults(func=lambda args: commands_info.handle_env_check(self, args))

        # Add install command
        install = subparsers.add_parser(
            "install",
            help="Install a project",
            parents=[container_build_argparse, container_run_argparse],
        )
        self.subparsers["install"] = install
        install.add_argument("project", help="Project to install")
        install.add_argument("mode", nargs="?", help="Mode to install (optional)")
        install.add_argument(
            "--local", action="store_true", help="Install locally instead of in container"
        )
        install.add_argument(
            "--build-type",
            help="Build type (debug, release, rel-debug). "
            "If not specified, uses CMAKE_BUILD_TYPE environment variable or defaults to 'release'",
        )
        install.add_argument(
            "--language", choices=["cpp", "python"], help="Specify language implementation"
        )
        install.add_argument(
            "--build-with",
            dest="with_operators",
            help="Optional operators that should be built, separated by semicolons (;)",
        )
        install.add_argument("--verbose", action="store_true", help="Print extra output")
        install.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        install.add_argument(
            "--parallel", help="Number of parallel build jobs (e.g. --parallel $(($(nproc)-1)))"
        )
        install.add_argument(
            "--no-docker-build", action="store_true", help="Skip building the container"
        )
        install.add_argument(
            "--configure-args",
            action="append",
            help="Additional configuration arguments for cmake "
            "example: --configure-args='-DCUSTOM_OPTION=ON' --configure-args='-Dtest=ON'",
        )
        install.set_defaults(func=lambda args: commands_project.handle_install(self, args))

        # Add test command
        test = subparsers.add_parser(
            "test", help="Test a project", parents=[container_build_argparse]
        )
        self.subparsers["test"] = test
        test.add_argument("project", nargs="?", help="Project to test")
        test.add_argument(
            "--local", action="store_true", help="Test locally instead of in container"
        )
        test.add_argument("--verbose", action="store_true", help="Print extra output")
        test.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        test.add_argument("--clear-cache", action="store_true", help="Clear cache folders")
        test.add_argument(
            "--language", choices=["cpp", "python"], help="Specify language implementation"
        )
        test.add_argument("--site-name", help="Site name")
        test.add_argument("--cdash-url", help="CDash URL")
        test.add_argument("--platform-name", help="Platform name")
        test.add_argument(
            "--cmake-options",
            action="append",
            help="CMake options, "
            "example: --cmake-options='-DCUSTOM_OPTION=ON' --cmake-options='-DDEBUG_MODE=1'",
        )
        test.add_argument(
            "--ctest-options",
            action="append",
            help="CTest options, "
            "example: --ctest-options='-DGPU_TYPE=rtx4090' --ctest-options='-DDEBUG_MODE=ON'",
        )
        test.add_argument("--no-xvfb", action="store_true", help="Do not use xvfb")
        test.add_argument("--ctest-script", help="CTest script")
        test.add_argument(
            "--coverage",
            action="store_true",
            help="Enable code coverage in CTest (adds coverage compile flags and runs ctest_coverage)",
        )
        test.add_argument(
            "--no-docker-build", action="store_true", help="Skip building the container"
        )
        test.add_argument(
            "--build-name-suffix",
            help="Suffix to use for ctest build name (defaulting to the image tag)",
        )
        test.set_defaults(func=lambda args: commands_project.handle_test(self, args))

        # Add clear-cache command
        clear_cache = subparsers.add_parser("clear-cache", help="Clear cache folders")
        self.subparsers["clear-cache"] = clear_cache
        clear_cache.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        clear_cache.add_argument("--build", action="store_true", help="Clear build folders only")
        clear_cache.add_argument("--data", action="store_true", help="Clear data folders only")
        clear_cache.add_argument(
            "--install", action="store_true", help="Clear install folders only"
        )
        clear_cache.set_defaults(func=lambda args: commands_workspace.handle_clear_cache(self, args))

        # Add vscode command
        vscode = subparsers.add_parser(
            "vscode",
            help="Launch VS Code in Dev Container",
            parents=[container_build_argparse],
        )
        self.subparsers["vscode"] = vscode
        vscode.add_argument("project", nargs="?", help="Project to launch VS Code for")
        vscode.add_argument(
            "--language", choices=["cpp", "python"], help="Specify language implementation"
        )
        vscode.add_argument("--docker-opts", help="Additional options to pass to the Docker launch")
        vscode.add_argument(
            "--verbose", action="store_true", help="Print variables passed to docker run command"
        )
        vscode.add_argument(
            "--dryrun", action="store_true", help="Print commands without executing them"
        )
        vscode.add_argument(
            "--no-docker-build", action="store_true", help="Skip building the container"
        )
        vscode.set_defaults(func=lambda args: commands_workspace.handle_vscode(self, args))

        return parser

    def _collect_metadata(self) -> None:
        """Create an unstructured database of metadata for all projects"""

        EXCLUDE_PATHS = ["applications/holoviz/template", "applications/template"]
        # Known exceptions, such as template files that do not represent a standalone project

        app_paths = holohub_cli_util.get_component_search_paths(self.HOLOHUB_ROOT)
        self.projects = metadata_util.gather_metadata(app_paths, exclude_paths=EXCLUDE_PATHS)

    def find_project(self, project_name: str, language: Optional[str] = None) -> dict:
        """Find a project by name"""
        normalized_language = normalize_language(language)

        cache_key = (project_name, normalized_language)
        if cache_key in self._project_data:
            return self._project_data[cache_key]

        # Find all projects with the given name
        candidates = [p for p in self.projects if p.get("project_name") == project_name]
        if candidates:
            available_lang = []
            for p in candidates:
                for lang in list_normalized_languages(
                    p.get("metadata", {}).get("language", None), strict=True
                ):
                    available_lang.append(lang)
            available_lang = sorted(list(set(available_lang)))

            # Determine target language (if unspecified, prefer cpp then first available)
            if normalized_language:
                target_lang = normalized_language
            elif "python" in available_lang:
                target_lang = "python"
            else:
                target_lang = available_lang[0] if available_lang else ""
            # Warn if ambiguous and no language specified
            if not normalized_language and len(available_lang) > 1:
                msg = f"'{project_name}' has multiple languages: {', '.join(available_lang)}.\n"
                msg += f"Defaulting to '{target_lang}'. Use --language to select explicitly.\n\n"
                print(Color.green(msg))
            for p in candidates:
                if target_lang in list_normalized_languages(
                    p.get("metadata", {}).get("language", None), strict=True
                ):
                    self._project_data[cache_key] = p  # Return candidate matching target_lang
                    return p
            if normalized_language:  # If target_lang specified but not found
                holohub_cli_util.fatal(
                    f"Project '{project_name}' (language: {normalized_language}) not found. "
                    f"Available: {', '.join(available_lang) if available_lang else 'unknown'}"
                )
            # No language info or no match found; return first candidate
            fallback_candidate = candidates[0]
            fallback_lang = fallback_candidate.get("metadata", {}).get("language", None)
            if not fallback_lang:
                msg = f"Returning '{project_name}' with missing or unknown language metadata.\n"
                msg += "Consider specifying --language for more consistent results.\n"
                holohub_cli_util.warn(msg)
            self._project_data[cache_key] = fallback_candidate
            return self._project_data[cache_key]
        # If project not found, suggest similar names
        distances = [
            (
                p["project_name"],
                holohub_cli_util.levenshtein_distance(project_name, p["project_name"]),
                p.get("source_folder", ""),
                p.get("metadata", {}).get("language", ""),
            )
            for p in self.projects
        ]
        distances.sort(key=lambda x: x[1])  # Sort by distance
        closest_matches = [
            (name, folder, lang) for name, dist, folder, lang in distances[:3] if dist <= 3
        ]  # Show up to 3 matches
        msg = f"Project '{project_name}' (language: {normalized_language}) not found."
        if closest_matches:
            msg += "\nDid you mean:"
            for name, folder, lang in closest_matches:
                details = []
                if lang:
                    details.append(f"language: {lang}")
                if folder:
                    details.append(f"source: {folder}")
                msg += f"\n  '{name}'" + (f" ({', '.join(details)})" if details else "")
        holohub_cli_util.fatal(msg)
        return None

    def resolve_mode(self, project_data: dict, requested_mode: Optional[str] = None) -> tuple:
        """
        Resolve mode from metadata and validate
        Returns: (mode_name, mode_config) or (None, None) for legacy behavior
        """
        modes = project_data.get("metadata", {}).get("modes", {})
        if not modes:
            return None, None  # No modes defined - should use legacy behavior

        if requested_mode is None:
            # Validate that multiple modes have a default_mode specified
            application_metadata = project_data.get("metadata", {})
            if len(modes) > 1 and "default_mode" not in application_metadata:
                available = ", ".join(modes.keys())
                holohub_cli_util.fatal(
                    f"Multiple modes found ({available}) but no 'default_mode' specified. "
                    f"Please add a 'default_mode' field to specify which mode to use by default."
                )

            if "default_mode" in application_metadata:
                requested_mode = application_metadata["default_mode"]
                # Validate that default_mode references an existing mode
                if requested_mode not in modes:
                    available = ", ".join(modes.keys())
                    holohub_cli_util.fatal(
                        f"Invalid default_mode '{requested_mode}' in metadata among {available}"
                    )
            else:
                requested_mode = list(modes.keys())[0]
        if requested_mode not in modes:
            available = ", ".join(modes.keys())
            holohub_cli_util.fatal(
                f"Mode '{requested_mode}' not found. Available modes: {available}"
            )
        return requested_mode, modes[requested_mode]

    def validate_mode(
        self,
        args: argparse.Namespace,
        mode_name: Optional[str],
        mode_config: dict,
        project_data: dict,
        requested_mode: Optional[str],
    ) -> None:
        """Validate mode configuration"""
        if not mode_config:
            return  # No mode configuration to validate

        # Define valid keys for mode configuration
        valid_top_level_keys = ["description", "requirements", "build", "run", "env"]
        valid_build_keys = ["depends", "docker_build_args", "cmake_options", "env"]
        valid_run_keys = ["command", "workdir", "docker_run_args", "env"]

        # Check top-level keys
        for key in mode_config.keys():
            if key not in valid_top_level_keys:
                suggestions = self._suggest_command(key, valid_top_level_keys)
                msg = f"Unknown key '{key}' in mode '{mode_name}'"
                if suggestions:
                    msg += f". Did you mean '{suggestions[0]}'?"
                holohub_cli_util.warn(msg)

        # Check section keys (build and run)
        sections_to_validate = {"build": valid_build_keys, "run": valid_run_keys}
        for section_name, valid_keys in sections_to_validate.items():
            if section_name in mode_config and isinstance(mode_config[section_name], dict):
                for key in mode_config[section_name].keys():
                    if key not in valid_keys:
                        suggestions = self._suggest_command(key, valid_keys)
                        msg = f"Unknown key '{section_name}.{key}' in mode '{mode_name}'"
                        if suggestions:
                            msg += f". Did you mean '{suggestions[0]}'?"
                        holohub_cli_util.warn(msg)

    def get_effective_build_config(
        self,
        args: argparse.Namespace,
        mode_config: dict,
    ) -> dict:
        """
        Get effective build configuration combining CLI args and mode config.
        """
        config = {
            "with_operators": getattr(args, "with_operators", None),
            "docker_opts": getattr(args, "docker_opts", ""),
            "build_args": getattr(args, "build_args", ""),
            "configure_args": getattr(args, "configure_args", None),
        }
        if not mode_config:
            return config

        # Apply build configuration - CLI parameters always override mode settings when provided
        if "build" in mode_config:
            build_config = mode_config["build"]

            if "depends" in build_config:
                if config["with_operators"]:
                    mode_deps = [dep.strip() for dep in build_config["depends"] if dep.strip()]
                    msg = f"CLI args --build-with='{config['with_operators']}' "
                    msg += f"overrides mode depends: {', '.join(mode_deps)}"
                    holohub_cli_util.warn(msg)
                else:
                    mode_deps = [dep.strip() for dep in build_config["depends"] if dep.strip()]
                    config["with_operators"] = ";".join(mode_deps) if mode_deps else ""

            if "docker_build_args" in build_config:
                if config["build_args"]:
                    mode_args = holohub_cli_util.normalize_args_str(
                        build_config["docker_build_args"]
                    )
                    msg = f"CLI args --build-args='{config['build_args']}' "
                    msg += f"overrides mode --build-args: {mode_args}"
                    holohub_cli_util.warn(msg)
                else:
                    config["build_args"] = holohub_cli_util.normalize_args_str(
                        build_config["docker_build_args"]
                    )

            if "cmake_options" in build_config:
                if config["configure_args"]:
                    mode_opts = (
                        " ".join(build_config["cmake_options"])
                        if isinstance(build_config["cmake_options"], list)
                        else build_config["cmake_options"]
                    )
                    cli_opts = (
                        " ".join(config["configure_args"])
                        if isinstance(config["configure_args"], list)
                        else config["configure_args"]
                    )
                    msg = f"CLI args --configure-args='{cli_opts}' "
                    msg += f"overrides mode --configure-args: {mode_opts}"
                    holohub_cli_util.warn(msg)
                else:
                    config["configure_args"] = build_config["cmake_options"]

        if "run" in mode_config and "docker_run_args" in mode_config["run"]:
            if getattr(args, "docker_opts", ""):
                mode_opts = holohub_cli_util.normalize_args_str(
                    mode_config["run"]["docker_run_args"]
                )
                msg = f"CLI args --docker-opts='{getattr(args, 'docker_opts', '')}' "
                msg += f"overrides mode --docker-opts: {mode_opts}"
                holohub_cli_util.warn(msg)
            else:
                config["docker_opts"] = holohub_cli_util.normalize_args_str(
                    mode_config["run"]["docker_run_args"]
                )

        return config

    def get_effective_run_config(
        self,
        args: argparse.Namespace,
        mode_config: dict,
    ) -> dict:
        """Get effective run configuration combining CLI args and mode config without mutation"""
        config = {
            "run_args": getattr(args, "run_args", "") or "",
            "docker_opts": getattr(args, "docker_opts", ""),
        }

        if mode_config and "run" in mode_config:
            run_config = mode_config["run"]

            if "command" in run_config:
                config["command"] = run_config["command"]
            if "workdir" in run_config:
                config["workdir"] = run_config["workdir"]

            if "command" in run_config and getattr(args, "run_args", ""):
                msg = (
                    f"CLI args --run-args='{getattr(args, 'run_args', '')}' "
                    f"will be appended to mode command"
                )
                holohub_cli_util.warn(msg)

            if "docker_run_args" in run_config:
                if getattr(args, "docker_opts", ""):
                    mode_opts = holohub_cli_util.normalize_args_str(run_config["docker_run_args"])
                    msg = (
                        f"CLI args --docker-opts='{getattr(args, 'docker_opts', '')}' "
                        f"overrides mode --docker-opts: {mode_opts}"
                    )
                    holohub_cli_util.warn(msg)
                else:
                    config["docker_opts"] = holohub_cli_util.normalize_args_str(
                        run_config["docker_run_args"]
                    )
        return config

    def _make_project_container(
        self, project_name: Optional[str] = None, language: Optional[str] = None
    ) -> HoloHubContainer:
        """Define a project container"""
        if not project_name:
            return HoloHubContainer(project_metadata=None)
        project_data = self.find_project(project_name=project_name, language=language)
        return HoloHubContainer(project_metadata=project_data, language=language)

    def _collect_cache_dirs(self, patterns: list[str], default_dir=None) -> list:
        """Helper to collect cache directories matching patterns."""
        dirs = []
        if default_dir is not None:
            dirs.append(default_dir)
        for pattern in patterns:
            for path in HoloHubCLI.HOLOHUB_ROOT.glob(pattern):
                if path.is_dir() and path not in dirs:
                    dirs.append(path)
        return dirs

    def _suggest_command(self, invalid_value: str, valid_options: list[str]) -> list[str]:
        """Suggest similar values using Levenshtein distance."""
        distances = [
            (option, holohub_cli_util.levenshtein_distance(invalid_value, option))
            for option in valid_options
        ]
        distances.sort(key=lambda x: x[1])
        return [option for option, dist in distances[:2] if dist <= 2]  # Show up to 2 matches

    def _check_for_dash_prefix_issue(self, cmd_args: List[str]) -> Optional[str]:
        """
        Check if the parsing error is likely due to dash-prefixed arguments
        """
        DASH_VALUE_ARGS = ["--run-args", "--build-args", "--docker-opts", "--configure-args"]
        for i, arg in enumerate(cmd_args):
            if arg in DASH_VALUE_ARGS and "=" not in arg:
                if i + 1 < len(cmd_args) and cmd_args[i + 1].startswith("-"):
                    next_arg = cmd_args[i + 1]
                    return (
                        f"💡 Tip: ambiguous dash-prefixed arguments, use the equals format:\n"
                        f"   Instead of: {arg} {next_arg}\n"
                        f"   Use: {arg}={next_arg}"
                    )
        return None

    def run(self, argv: Optional[List[str]] = None) -> None:
        """Main entry point for the CLI"""

        trailing_docker_args = []  # Handle " -- " separator for run-container command forwarding
        if argv is None:
            argv = sys.argv
        argv = list(argv)
        cmd_args = argv[1:]  # Skip script name, return a copy of the args
        if len(cmd_args) >= 2 and cmd_args[0] == "run-container" and "--" in cmd_args:
            sep = cmd_args.index("--")
            cmd_args, trailing_docker_args = cmd_args[:sep], cmd_args[sep + 1 :]

        potential_command = cmd_args[0] if cmd_args else None
        dash_suggestion = None
        if potential_command and potential_command in self.subparsers:
            dash_suggestion = self._check_for_dash_prefix_issue(cmd_args)

        try:
            args = self.parser.parse_args(cmd_args)
            if trailing_docker_args:
                args._trailing_args = trailing_docker_args  # " -- " used for run-container command
        except SystemExit as e:
            if len(cmd_args) > 0 and e.code != 0:  # exit code is 0 => help was successfully shown
                if dash_suggestion:
                    print(f"\n{dash_suggestion}\n", file=sys.stderr)

                if potential_command and not potential_command.startswith("-"):
                    if potential_command in self.subparsers:
                        # Valid subcommand but parsing failed
                        print(f"\n💡 For more help with '{potential_command}':", file=sys.stderr)
                        print(f"  {self.script_name} {potential_command} --help\n", file=sys.stderr)
                        sys.exit(e.code if e.code is not None else 1)
                    else:  # Invalid subcommand - suggest similar ones
                        suggestions = self._suggest_command(
                            potential_command, list(self.subparsers.keys())
                        )
                        if suggestions:
                            print("\n💡 Did you mean:", file=sys.stderr)
                            for cmd in suggestions:
                                print(f"  {self.script_name} {cmd}", file=sys.stderr)
                            print(file=sys.stderr)
                        sys.exit(1)
            raise
        if hasattr(args, "func"):
            args.func(args)
        else:
            self.parser.print_help()
            sys.exit(1)


def main(argv: Optional[List[str]] = None):
    script_name = None
    if argv and not os.environ.get("HOLOHUB_CMD_NAME"):
        executable = Path(argv[0]).name
        script_name = "holoscan" if executable == "__main__.py" else executable
    cli = HoloHubCLI(script_name=script_name)
    cli.run(argv)


if __name__ == "__main__":
    main()
