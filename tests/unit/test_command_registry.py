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

"""Unit tests for the command registry helpers.

These pin the public behavior of :mod:`holoscan_cli.commands.registry` so
agents and downstream wrappers can rely on the same lookups.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from holoscan_cli.commands import info, registry


def test_project_command_names_are_ordered_as_registered():
    expected = [spec.name for spec in registry.PROJECT_COMMANDS]
    assert registry.project_command_names() == expected


def test_project_command_help_returns_short_help_text():
    assert registry.project_command_help() == {
        spec.name: spec.short_help for spec in registry.PROJECT_COMMANDS
    }


def test_help_for_returns_subparser_help_text():
    """``help_for`` returns the per-subcommand help, not the top-level short_help."""
    spec = registry.PROJECT_COMMANDS[0]
    assert registry.help_for(spec.name) == spec.help
    assert registry.help_for(spec.name) != spec.short_help or spec.help == spec.short_help


def test_help_for_raises_keyerror_for_unknown_commands():
    with pytest.raises(KeyError):
        registry.help_for("definitely-not-a-command")


def test_commands_in_group_filters_by_group():
    workspace = list(registry.commands_in_group("workspace"))
    assert {spec.name for spec in workspace} == {
        "create",
        "lint",
        "setup",
        "clear-cache",
        "vscode",
    }


def test_commands_in_group_returns_empty_for_unknown_group():
    assert list(registry.commands_in_group("nope")) == []


def test_project_commands_by_name_keys_match_specs():
    by_name = registry.PROJECT_COMMANDS_BY_NAME
    for spec in registry.PROJECT_COMMANDS:
        assert by_name[spec.name] is spec
    assert set(by_name) == {spec.name for spec in registry.PROJECT_COMMANDS}


def test_autocompletion_command_list_comes_from_registry(capsys):
    cli = SimpleNamespace(
        projects=[
            {"project_name": "z_project"},
            {"project_name": "a_project"},
        ]
    )

    info.handle_autocompletion_list(cli, SimpleNamespace())

    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["a_project", "z_project"]
    for command in registry.project_command_names():
        assert command in lines
    assert "cpp" in lines
    assert "python" in lines
