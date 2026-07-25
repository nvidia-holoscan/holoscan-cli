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

"""Contract tests for the holoscan CLI parser surface.

These tests pin behaviors that downstream wrappers and shell scripts rely
on (command names, top-level dispatch coverage, per-subcommand help) so
internal refactors cannot accidentally change the public CLI contract.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from holoscan_cli import cli as project_cli
from holoscan_cli.__main__ import PROJECT_COMMANDS, parse_args
from holoscan_cli.commands import registry

# ---- registry / dispatch consistency ----------------------------------------


def test_registry_drives_main_dispatch_surface():
    """``holoscan_cli.__main__.PROJECT_COMMANDS`` is derived from the registry."""
    expected = {spec.name: spec.short_help for spec in registry.PROJECT_COMMANDS}
    assert PROJECT_COMMANDS == expected


def test_registry_exposes_per_subcommand_help_for_every_command():
    """``help_for`` must cover every registered command."""
    for spec in registry.PROJECT_COMMANDS:
        assert registry.help_for(spec.name) == spec.help


def test_registry_command_names_are_unique():
    names = [spec.name for spec in registry.PROJECT_COMMANDS]
    assert len(names) == len(set(names))


def test_registry_groups_are_known():
    allowed = {"workspace", "container", "project", "info"}
    for spec in registry.PROJECT_COMMANDS:
        assert spec.group in allowed, f"{spec.name!r} has unknown group {spec.group!r}"


# ---- parser construction ----------------------------------------------------


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    """Construct ``HoloscanCLI`` without scanning the host filesystem."""
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", tmp_path)
    with patch.object(project_cli.metadata_util, "gather_metadata", return_value=[]):
        yield project_cli.HoloscanCLI(script_name="holoscan")


def test_full_parser_registers_every_command_in_the_registry(cli):
    registered = set(cli.subparsers)
    expected = {spec.name for spec in registry.PROJECT_COMMANDS}
    assert expected.issubset(registered), expected - registered


def test_full_parser_does_not_add_extra_commands(cli):
    """Catch accidentally-added subparsers that are not in the registry."""
    expected = {spec.name for spec in registry.PROJECT_COMMANDS}
    assert set(cli.subparsers) == expected


def test_holoscan_cli_default_script_name_is_holoscan(monkeypatch, tmp_path):
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", tmp_path)
    monkeypatch.delenv("HOLOSCAN_CLI_CMD_NAME", raising=False)
    with patch.object(project_cli.metadata_util, "gather_metadata", return_value=[]):
        cli = project_cli.HoloscanCLI()
    assert cli.script_name == "holoscan"


@pytest.mark.parametrize("command", sorted(spec.name for spec in registry.PROJECT_COMMANDS))
def test_each_subcommand_accepts_help_flag(cli, command, capsys):
    """``holoscan <command> --help`` exits 0 on every registered command."""
    with pytest.raises(SystemExit) as exc_info:
        cli.parser.parse_args([command, "--help"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out  # argparse printed help text


def test_package_accepts_no_docker_build_flag(cli):
    """``holoscan package`` exposes --no-docker-build like the other
    container-first commands (holohub#1596)."""
    args = cli.parser.parse_args(["package", "fixture", "--no-docker-build"])
    assert args.no_docker_build is True
    # Default stays False so check_skip_builds doesn't skip unexpectedly.
    args = cli.parser.parse_args(["package", "fixture"])
    assert args.no_docker_build is False


def _subparser_help_strings(parser):
    """Return ``{command_name: help}`` recorded on the parser's subparsers action.

    argparse exposes per-subcommand help via a private ``_choices_actions``
    list on the ``_SubParsersAction``. The structure is internal but stable
    across the supported Python versions and is also what argparse renders
    in help output, so reading it gives an exact, line-wrap-independent
    answer.
    """
    import argparse as _argparse

    for action in parser._actions:
        if isinstance(action, _argparse._SubParsersAction):
            return {choice.dest: choice.help for choice in action._choices_actions}
    raise AssertionError("Parser has no SubParsersAction")


@pytest.mark.parametrize("command", sorted(spec.name for spec in registry.PROJECT_COMMANDS))
def test_each_subparser_help_matches_registry(cli, command):
    """Subparser help titles must come from the registry."""
    help_strings = _subparser_help_strings(cli.parser)
    assert help_strings[command] == registry.help_for(command)


# ---- hand-off contract from __main__ to project CLI -------------------------


def test_main_dispatch_covers_every_registered_command():
    """Every registered command must be a recognized top-level dispatch target."""
    for spec in registry.PROJECT_COMMANDS:
        assert spec.name in PROJECT_COMMANDS


def test_version_is_not_a_project_command():
    """``version`` is intentionally implemented in __main__, not the project CLI."""
    assert "version" not in PROJECT_COMMANDS
    assert "version" not in {spec.name for spec in registry.PROJECT_COMMANDS}


# ---- naming compatibility aliases -------------------------------------------


def test_holohub_cli_alias_was_removed():
    """The ``HoloHubCLI`` deprecation alias is gone in this release."""
    from holoscan_cli import cli as project_cli

    assert not hasattr(project_cli, "HoloHubCLI")


def test_holohub_container_alias_was_removed():
    """The ``HoloHubContainer`` deprecation alias is gone in this release."""
    from holoscan_cli import container

    assert not hasattr(container, "HoloHubContainer")


# ---- ambiguous dash-prefixed argument hint -----------------------------------


@pytest.mark.parametrize(
    "ambiguous_args",
    [
        ["--run-args", "--local"],
        ["--build-args", "--no-cache"],
        ["--docker-opts", "--memory=4g"],
        ["--configure-args", "-DDEBUG=ON"],
    ],
)
def test_dash_prefix_hint_triggered_on_dash_value_args(ambiguous_args):
    """When a ``--run-args`` / ``--build-args`` / ``--docker-opts`` /
    ``--configure-args`` value starts with a dash, the CLI must surface
    the equals-format tip. Pre-consolidation
    `test_cli_ambiguous_dash_prefixed_arguments`."""
    cli = object.__new__(project_cli.HoloscanCLI)

    tip = cli._check_for_dash_prefix_issue(ambiguous_args)

    assert tip is not None
    assert "ambiguous dash-prefixed arguments" in tip
    assert "Use:" in tip
    assert f"{ambiguous_args[0]}={ambiguous_args[1]}" in tip


def test_dash_prefix_hint_silent_when_value_is_not_a_flag():
    """A non-dash value is unambiguous; the tip must stay quiet."""
    cli = object.__new__(project_cli.HoloscanCLI)
    assert cli._check_for_dash_prefix_issue(["--run-args", "config/file"]) is None


# ---- top-level ``--help`` surface (shell-probe contract) --------------------
#
# Downstream Dockerfiles and wrappers detect the *consolidated* CLI with a
# shell probe -- ``holoscan --help | grep -qw build``. It is reliable because
# the legacy packaging-only holoscan-cli (<= 4.2.0) exposes only
# ``package/run/version/nics``, while the consolidated CLI's top-level help
# enumerates every source-project command. These tests pin that contract so an
# internal refactor cannot silently break those probes.


def test_top_level_help_lists_every_source_project_command(capsys):
    """``holoscan --help`` enumerates every registered source-project command."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["holoscan", "--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out

    # Mirror ``grep -w <name>``: word-boundary match against the rendered help.
    missing = [
        spec.name
        for spec in registry.PROJECT_COMMANDS
        if not re.search(rf"\b{re.escape(spec.name)}\b", help_text)
    ]
    assert not missing, f"`holoscan --help` omits source-project commands: {missing}"


def test_build_token_discriminates_consolidated_from_legacy_cli(capsys):
    """``grep -qw build`` is a valid version check; ``grep -qw version`` is not.

    ``build`` is a source-project command unique to the consolidated CLI,
    whereas ``version`` is a native command the legacy holoscan-cli (<= 4.2.0)
    also ships -- so only a source-project command distinguishes the two.
    """
    assert "build" in PROJECT_COMMANDS
    assert "version" not in PROJECT_COMMANDS

    with pytest.raises(SystemExit):
        parse_args(["holoscan", "--help"])
    assert re.search(r"\bbuild\b", capsys.readouterr().out)


def test_help_grep_probe_succeeds_from_any_directory(tmp_path):
    """End-to-end check of the literal ``holoscan --help | grep -qw build`` probe.

    Invoked via ``python -m holoscan_cli`` (no console script required) from an
    unrelated working directory, proving the help surface is not project-context
    dependent -- exactly the conditions under which downstream wrappers run it.
    """
    import holoscan_cli

    src_dir = Path(holoscan_cli.__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(src_dir)}
    proc = subprocess.run(
        [sys.executable, "-m", "holoscan_cli", "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert re.search(r"\bbuild\b", proc.stdout), proc.stdout  # `grep -qw build`
