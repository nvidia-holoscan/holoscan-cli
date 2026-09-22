# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise standalone discovery through the dependency-free CLI dispatcher."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from holoscan_cli.project_context import discover_project_context, set_active_project_context

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/holohub_smoke/applications/smoke_app"


def _application(root):
    root.mkdir(parents=True)
    shutil.copyfile(FIXTURE / "metadata.json", root / "metadata.json")
    return root


def _cli(cwd, *args, env=None):
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("HOLOSCAN_CLI_")
    }
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, "-S", "-m", "holoscan_cli", *args],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("selection", ["cwd", "child", "explicit", "environment"])
def test_discovery_lists_only_the_root_application(tmp_path, selection):
    root = _application(tmp_path / "my_app")
    # A recursive cwd search would also find this copy.
    _application(root / "build/cache/copied_app")
    cwd, args, env = root, [], {}
    if selection == "child":
        cwd = root / "src/deep"
        cwd.mkdir(parents=True)
    elif selection == "explicit":
        cwd, args = tmp_path, ["--project-root", str(root)]
    elif selection == "environment":
        cwd, env = tmp_path, {"HOLOSCAN_CLI_ROOT": str(root)}

    result = _cli(cwd, *args, "list", "--json", env=env)

    assert result.returncode == 0, result.stderr
    projects = json.loads(result.stdout)["projects"]
    assert [(p["name"], p["source_folder"]) for p in projects] == [("my_app", str(root))]


@pytest.mark.parametrize("search_path", ["other", "other/metadata.json", ""])
def test_search_override_replaces_standalone_default(tmp_path, search_path):
    root = _application(tmp_path / "my_app")
    other = _application(root / "other")

    result = _cli(root, "list", "--json", env={"HOLOSCAN_CLI_SEARCH_PATH": search_path})

    assert result.returncode == 0, result.stderr
    projects = json.loads(result.stdout)["projects"]
    expected = [("other", str(other))] if search_path else []
    assert [(p["name"], p["source_folder"]) for p in projects] == expected


@pytest.mark.parametrize("metadata", [{}, {"operator": {}}, [], None, "unrelated"])
def test_unrelated_metadata_does_not_enable_discovery(tmp_path, metadata):
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    result = _cli(tmp_path, "list", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["projects"] == []


@pytest.mark.parametrize(
    ("metadata", "error"),
    [
        ({"application": None}, "application must be an object"),
        ({"application": {}}, "application.name"),
        ({"application": {"name": "App"}}, "application.holoscan_sdk.minimum_required_version"),
        ({"application": {}, "operator": {}}, "exactly one project type"),
    ],
)
def test_invalid_application_reports_metadata_error(tmp_path, metadata, error):
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    result = _cli(tmp_path, "list", "--json")
    assert result.returncode != 0
    assert error in result.stderr
    assert str(tmp_path / "metadata.json") in result.stderr
    assert "Traceback" not in result.stderr


def test_malformed_json_warns_without_a_traceback(tmp_path):
    (tmp_path / "metadata.json").write_text("{not json", encoding="utf-8")
    result = _cli(tmp_path, "list", "--json")
    assert "Invalid project metadata" in result.stderr
    assert "Traceback" not in result.stderr
    assert json.loads(result.stdout)["projects"] == []


def test_containing_source_repository_keeps_precedence(tmp_path):
    root = tmp_path / "repo"
    app = _application(root / "applications/my_app")
    _application(root / "applications/another_app")
    result = _cli(app, "list", "--json")
    assert result.returncode == 0, result.stderr
    assert {p["name"] for p in json.loads(result.stdout)["projects"]} == {"my_app", "another_app"}


def test_containing_module_keeps_precedence_without_conventional_layout(tmp_path):
    root = tmp_path / "module"
    app = _application(root / "custom/my_app")
    (root / "metadata.json").write_text(
        json.dumps({"module": {"name": "holoscan-parent"}}), encoding="utf-8"
    )
    context = discover_project_context(cwd=app, environ={})
    assert context.root == root
    assert context.is_module
    # An explicit root can still select the application.
    context = discover_project_context(explicit_root=app, environ={})
    assert context.root == app
    assert context.kind == "application"


def test_container_handoff_preserves_name_after_mount_rename(tmp_path, monkeypatch):
    from holoscan_cli.container import HoloscanContainer

    root = _application(tmp_path / "my_app")
    context = discover_project_context(cwd=root, environ={})
    set_active_project_context(context)
    monkeypatch.setattr(HoloscanContainer, "HOLOHUB_ROOT", root)
    container = HoloscanContainer({"metadata": {"language": "python"}})
    args = container.get_environment_args()
    forwarded = next(arg for arg in args if arg.startswith("HOLOSCAN_CLI_APP_NAME="))
    name, value = forwarded.split("=", 1)
    mounted_root = _application(tmp_path / "renamed_workspace")

    result = _cli(
        mounted_root,
        "list",
        "--json",
        env={name: value, "HOLOSCAN_CLI_SEARCH_PATH": "metadata.json"},
    )
    assert result.returncode == 0, result.stderr
    project = json.loads(result.stdout)["projects"][0]
    assert project["name"] == "my_app"
    assert project["source_folder"] == str(mounted_root)


@pytest.mark.parametrize("name", ["", ".", "..", "../other"])
def test_standalone_name_override_cannot_escape_build_directory(tmp_path, name):
    root = _application(tmp_path / "my_app")
    result = _cli(root, "list", "--json", env={"HOLOSCAN_CLI_APP_NAME": name})
    assert result.returncode != 0
    assert "HOLOSCAN_CLI_APP_NAME must be a directory name" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("name", ["my_app", "python"])
def test_standalone_build_and_run_previews_resolve_root_paths(tmp_path, name):
    root = _application(tmp_path / name)
    build = _cli(root, "build", name, "--local", "--dryrun", "--verbose")
    assert build.returncode == 0, build.stderr
    assert f"-S {root}" in build.stdout
    assert str(root / "build" / name) in build.stdout

    run = _cli(root, "run", name, "--local", "--dryrun", "--verbose")
    assert run.returncode == 0, run.stderr
    assert "smoke_app" in run.stdout
    assert str(root) in run.stdout
    assert not (root / "build").exists()
