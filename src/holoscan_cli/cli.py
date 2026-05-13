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
import functools
import os
from pathlib import Path
from typing import List, Optional

import holoscan_cli.metadata.gather_metadata as metadata_util
import holoscan_cli.util as holohub_cli_util
from holoscan_cli.commands import registry as commands_registry
from holoscan_cli.container import HoloscanContainer
from holoscan_cli.container.parsers import get_build_argparse, get_run_argparse
from holoscan_cli.metadata.utils import (
    list_normalized_languages,
    normalize_language,
)
from holoscan_cli.util import Color


def in_container_cli_command() -> str:
    """Command used when the host CLI recurses into a container build/run/install.

    Returns the installed ``holoscan`` console script by default. Decoupled from
    ``HoloscanCLI.script_name`` so the in-container recursion is independent of how
    the user invoked the CLI on the host (e.g. via ``./holohub``, ``./i4h``, or
    ``python -m holoscan_cli``). Override via ``HOLOSCAN_CLI_IN_CONTAINER_CMD``
    when the container ships a different entry point (e.g. ``python3 -m
    holoscan_cli``).
    """
    return os.environ.get("HOLOSCAN_CLI_IN_CONTAINER_CMD", "holoscan")


class HoloscanCLI:
    """Command-line interface for HoloHub"""

    HOLOHUB_ROOT = holohub_cli_util.get_holohub_root()
    DEFAULT_BUILD_PARENT_DIR = Path(
        os.environ.get("HOLOSCAN_CLI_BUILD_PARENT_DIR", HOLOHUB_ROOT / "build")
    )
    DEFAULT_DATA_DIR = Path(os.environ.get("HOLOSCAN_CLI_DATA_DIR", HOLOHUB_ROOT / "data"))
    DEFAULT_SDK_DIR = os.environ.get("HOLOSCAN_CLI_DEFAULT_HSDK_DIR", "/opt/nvidia/holoscan")
    # Allow overriding the default CTest script path via environment variable
    DEFAULT_CTEST_SCRIPT = os.environ.get(
        "HOLOSCAN_CLI_CTEST_SCRIPT",
        str(Path(__file__).resolve().parent / "testing" / "holohub.container.ctest"),
    )

    def __init__(self, script_name: Optional[str] = None):
        self.script_name = script_name or os.environ.get("HOLOSCAN_CLI_CMD_NAME", "./holohub")
        self.parser = self._create_parser()
        # Cache for resolved projects to avoid duplicate lookups
        self._project_data: dict[tuple[str, str], dict] = {}
        self.prefix = holohub_cli_util.resolve_path_prefix(None)

    def _create_parser(self) -> argparse.ArgumentParser:
        """Create the argument parser with all supported commands.

        Subparser construction is delegated to per-command modules under
        :mod:`holoscan_cli.commands`; the wiring lives in
        :func:`holoscan_cli.commands.registry.register_all`. Help strings
        come from the registry so the top-level dispatch surface and the
        per-subparser help cannot drift.
        """
        parser = argparse.ArgumentParser(
            prog=self.script_name,
            description=(
                f"{self.script_name} CLI tool for managing Holoscan-based "
                "applications and containers"
            ),
        )
        subparsers = parser.add_subparsers(dest="command", required=True)

        # Cache subparsers so HoloscanCLI.run() can render targeted error
        # messages and Levenshtein-based suggestions.
        self.subparsers: dict[str, argparse.ArgumentParser] = commands_registry.register_all(
            self,
            subparsers,
            container_build=get_build_argparse(),
            container_run=get_run_argparse(),
        )

        return parser

    @functools.cached_property
    def projects(self) -> list[dict]:
        """All discovered source-project metadata, computed on first access.

        Walking the project search paths and parsing every ``metadata.json``
        costs tens-to-hundreds of small file reads on a populated HoloHub
        clone, so it's deferred off the ``__init__`` path. Commands that
        never touch project metadata (``status``, ``env-info``, ``env-check``,
        ``clear-cache``, ``setup``, ``vscode``, ``create``, ``lint``) don't
        pay the cost.
        """
        # Known exceptions: templates that don't represent a standalone project.
        EXCLUDE_PATHS = ["applications/holoviz/template", "applications/template"]
        app_paths = holohub_cli_util.get_component_search_paths(self.HOLOHUB_ROOT)
        return metadata_util.gather_metadata(app_paths, exclude_paths=EXCLUDE_PATHS)

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
        mode_name: Optional[str],
        mode_config: dict,
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

    def make_project_container(
        self, project_name: Optional[str] = None, language: Optional[str] = None
    ) -> HoloscanContainer:
        """Define a project container"""
        if not project_name:
            return HoloscanContainer(project_metadata=None)
        project_data = self.find_project(project_name=project_name, language=language)
        return HoloscanContainer(project_metadata=project_data, language=language)

    def collect_cache_dirs(self, patterns: list[str], default_dir=None) -> list:
        """Helper to collect cache directories matching patterns."""
        dirs = []
        if default_dir is not None:
            dirs.append(default_dir)
        for pattern in patterns:
            for path in HoloscanCLI.HOLOHUB_ROOT.glob(pattern):
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


#: Deprecated alias for :class:`HoloscanCLI`.
#:
#: ``HoloHubCLI`` was the canonical name through v1; new code should import
#: :class:`HoloscanCLI` directly. The alias is kept so downstream wrappers
#: and the in-container recursion in ``commands.test_cmd._ctest_script_arg``
#: (which spawns a fresh Python that ``from holoscan_cli.cli import
#: HoloHubCLI``) keep working across the deprecation window. Drop alongside
#: the rest of the HoloHub-name compatibility surface in the next minor
#: release.
HoloHubCLI = HoloscanCLI


def main(argv: Optional[List[str]] = None):
    script_name = None
    if argv and not os.environ.get("HOLOSCAN_CLI_CMD_NAME"):
        executable = Path(argv[0]).name
        script_name = "holoscan" if executable == "__main__.py" else executable
    cli = HoloscanCLI(script_name=script_name)
    cli.run(argv)


if __name__ == "__main__":
    main()
