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

"""Tests that exercise the in-tree HoloHub-style smoke fixture.

The fixture under ``tests/fixtures/holohub_smoke/`` is a deliberately
minimal source-project repo (one application with metadata.json and a
README, plus a ``holohub`` sentinel file) that lets release-validation
exercise ``holoscan list`` / ``find_project`` without depending on an
external HoloHub / Isaac OS / I4H checkout. The same fixture is reused
by ``.github/scripts/smoke_test.sh`` against an installed wheel.

These unit tests keep the fixture honest: any schema/format drift that
breaks ``find_project`` will be caught here before release.
"""

from pathlib import Path

import pytest

from holoscan_cli import cli as project_cli

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "holohub_smoke"


@pytest.fixture
def smoke_cli(monkeypatch):
    """Return a HoloscanCLI rooted at the smoke fixture."""
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", FIXTURE_ROOT)
    monkeypatch.setenv("HOLOSCAN_CLI_ROOT", str(FIXTURE_ROOT))
    cli = object.__new__(project_cli.HoloscanCLI)
    cli._project_data = {}
    return cli


def test_smoke_fixture_layout_intact():
    """The fixture must keep its expected layout — sentinel + application
    metadata — so the installed-wheel smoke test in CI keeps working."""
    assert (FIXTURE_ROOT / "holohub").is_file(), "missing sentinel `holohub` marker file"
    metadata = FIXTURE_ROOT / "applications" / "smoke_app" / "metadata.json"
    assert metadata.is_file(), f"missing fixture metadata: {metadata}"
    readme = FIXTURE_ROOT / "applications" / "smoke_app" / "README.md"
    assert readme.is_file(), f"missing fixture README: {readme}"


def test_smoke_fixture_metadata_validates_against_schema():
    """The fixture metadata.json must pass the application schema validator
    used by ``holoscan create``. Otherwise it stops being a representative
    HoloHub-style fixture."""
    import json

    from holoscan_cli.metadata import metadata_validator

    raw = json.loads((FIXTURE_ROOT / "applications" / "smoke_app" / "metadata.json").read_text())
    ok, msg = metadata_validator.validate_json(raw, "applications")
    assert ok, f"smoke fixture metadata fails application schema: {msg}"


def test_find_project_discovers_smoke_app(smoke_cli):
    """``find_project`` must locate the fixture project by name. This is the
    same call path that ``holoscan list`` / ``holoscan run`` use, so a
    successful find_project means the source-project surface is wired up."""
    project = smoke_cli.find_project("smoke_app")
    assert project["project_name"] == "smoke_app"
    assert project["project_type"] == "application"
    assert project["metadata"]["language"] == "python"
    assert project["metadata"]["name"] == "Smoke Test App"


def test_projects_lists_only_the_fixture(smoke_cli):
    """The fixture should yield exactly one project from ``projects``."""
    projects = smoke_cli.projects
    names = sorted(p["project_name"] for p in projects)
    assert names == ["smoke_app"], names


def test_find_project_unknown_name_exits(smoke_cli):
    """An unknown project name should call ``fatal`` which raises SystemExit."""
    # Suppress the auto-suggestion output so the test log stays clean.
    with pytest.raises(SystemExit):
        smoke_cli.find_project("does_not_exist")


def test_autocompletion_list_emits_fixture_project_and_commands(smoke_cli, capsys):
    """`handle_autocompletion_list` against the smoke fixture must list the
    fixture's project name followed by the dispatch command set used by
    shell completion. Pre-consolidation
    `test_holohub_autocompletion_list`."""
    from holoscan_cli.commands import info as info_cmd
    from types import SimpleNamespace

    info_cmd.handle_autocompletion_list(smoke_cli, SimpleNamespace())

    lines = capsys.readouterr().out.splitlines()
    assert "smoke_app" in lines
    # The dispatch table the wrapper completes against.
    for command in ("build", "run", "list", "install"):
        assert command in lines, f"missing `{command}` in autocompletion output: {lines}"
    assert "cpp" in lines
    assert "python" in lines


def test_smoke_fixture_root_envvar_honored(monkeypatch, tmp_path):
    """``HOLOSCAN_CLI_ROOT`` overrides the discovery walk; this is the seam
    CI's installed-wheel smoke test uses."""
    from holoscan_cli.utils import holohub as utils_holohub

    monkeypatch.setenv("HOLOSCAN_CLI_ROOT", str(FIXTURE_ROOT))
    assert utils_holohub._get_holohub_root() == FIXTURE_ROOT
