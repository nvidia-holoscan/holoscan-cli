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

from unittest.mock import patch

import pytest

from holoscan_cli import cli as project_cli
from holoscan_cli.__main__ import PROJECT_COMMANDS
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
    """Construct ``HoloHubCLI`` without scanning the host filesystem."""
    monkeypatch.setattr(project_cli.HoloHubCLI, "HOLOHUB_ROOT", tmp_path)
    with patch.object(project_cli.metadata_util, "gather_metadata", return_value=[]):
        yield project_cli.HoloHubCLI(script_name="holoscan")


def test_full_parser_registers_every_command_in_the_registry(cli):
    registered = set(cli.subparsers)
    expected = {spec.name for spec in registry.PROJECT_COMMANDS}
    assert expected.issubset(registered), expected - registered


def test_full_parser_does_not_add_extra_commands(cli):
    """Catch accidentally-added subparsers that are not in the registry."""
    expected = {spec.name for spec in registry.PROJECT_COMMANDS}
    assert set(cli.subparsers) == expected


@pytest.mark.parametrize("command", sorted(spec.name for spec in registry.PROJECT_COMMANDS))
def test_each_subcommand_accepts_help_flag(cli, command, capsys):
    """``holoscan <command> --help`` exits 0 on every registered command."""
    with pytest.raises(SystemExit) as exc_info:
        cli.parser.parse_args([command, "--help"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out  # argparse printed help text


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


def test_holoscan_cli_alias_is_holohub_cli():
    """The forward-looking ``HoloscanCLI`` alias must point at ``HoloHubCLI``."""
    from holoscan_cli.cli import HoloHubCLI, HoloscanCLI

    assert HoloscanCLI is HoloHubCLI


def test_holoscan_container_alias_is_holohub_container():
    """``HoloscanContainer`` is a forward-looking alias for ``HoloHubContainer``."""
    from holoscan_cli.container import HoloHubContainer, HoloscanContainer

    assert HoloscanContainer is HoloHubContainer
