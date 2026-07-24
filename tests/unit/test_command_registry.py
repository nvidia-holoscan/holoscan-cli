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

import json
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


def test_list_prints_modules_with_languages_and_operators(capsys):
    cli = SimpleNamespace(
        projects=[
            {
                "project_type": "module",
                "project_name": "holoscan-gstreamer",
                "metadata": {
                    "language": ["C++", "Python"],
                    "operator_names": ["GstVideoRecorderOp"],
                },
            }
        ]
    )

    info.handle_list(cli, SimpleNamespace())

    out = capsys.readouterr().out
    assert "== MODULES" in out
    assert "holoscan-gstreamer (C++, Python) [GstVideoRecorderOp]" in out


@pytest.mark.parametrize(
    "metadata, expected",
    [
        ({"operator_names": ["GstVideoRecorderOp"]}, "[GstVideoRecorderOp]"),
        # Falls back to the legacy top-level ``operators`` field …
        ({"operators": ["gstreamer"]}, "[gstreamer]"),
        # … then to ``subprojects.operators`` (the build-gating list).
        ({"subprojects": {"operators": ["gstreamer"]}}, "[gstreamer]"),
    ],
)
def test_list_module_operator_display_fallbacks(capsys, metadata, expected):
    cli = SimpleNamespace(
        projects=[
            {
                "project_type": "module",
                "project_name": "holoscan-gstreamer",
                "metadata": metadata,
            }
        ]
    )

    info.handle_list(cli, SimpleNamespace())

    assert expected in capsys.readouterr().out


# ---- list --json / modes --json ----------------------------------------------


def test_list_json_emits_schema_and_project_fields(capsys):
    cli = SimpleNamespace(
        projects=[
            {
                "project_type": "module",
                "project_name": "holoscan-gstreamer",
                "source_folder": "/repo/operators/holoscan-gstreamer",
                "metadata": {
                    "language": ["C++", "Python"],
                    "modes": {"default": {}, "bench": {}},
                },
            },
            {
                "project_type": "application",
                "project_name": "smoke_app",
                "source_folder": "/repo/applications/smoke_app",
                "metadata": {"language": "python"},
            },
        ]
    )

    info.handle_list(cli, SimpleNamespace(json=True))

    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1
    # Sorted by (project_type, name): "application" sorts before "module".
    assert [p["name"] for p in data["projects"]] == ["smoke_app", "holoscan-gstreamer"]
    app, module = data["projects"]
    # A string ``language`` is normalized to a list.
    assert app["language"] == ["python"]
    assert module["source_folder"] == "/repo/operators/holoscan-gstreamer"
    assert module["language"] == ["C++", "Python"]
    # Mode names are sorted.
    assert module["modes"] == ["bench", "default"]


def test_modes_json_emits_resolved_modes(capsys):
    project = {
        "project_name": "smoke_app",
        "metadata": {
            "language": "python",
            "modes": {"default": {"description": "d", "requirements": ["gpu"]}},
        },
    }
    cli = SimpleNamespace(find_project=lambda name, language=None: project)

    info.handle_modes(cli, SimpleNamespace(project="smoke_app", language=None, json=True))

    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1
    assert data["project"] == "smoke_app"
    assert data["language"] == "python"
    assert data["modes"]["default"]["requirements"] == ["gpu"]


def test_modes_json_emits_empty_object_when_no_modes(capsys):
    cli = SimpleNamespace(find_project=lambda name, language=None: {"metadata": {}})

    info.handle_modes(cli, SimpleNamespace(project="x", language=None, json=True))

    data = json.loads(capsys.readouterr().out)
    assert data["modes"] == {}
