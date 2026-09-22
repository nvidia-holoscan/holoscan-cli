# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from holoscan_cli.metadata.utils import MAX_METADATA_BYTES, read_metadata
from holoscan_cli.project_context import discover_project_context, set_active_project_context


def _application(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "metadata.json").write_text(
        json.dumps(
            {
                "application": {
                    "name": "Example",
                    "holoscan_sdk": {"minimum_required_version": "4.6.0"},
                }
            }
        ),
        encoding="utf-8",
    )
    return root


def _list(root, **overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOLOSCAN_CLI_")}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"), **overrides)
    result = subprocess.run(
        [sys.executable, "-S", "-m", "holoscan_cli", "--project-root", str(root), "list", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["projects"]


def test_standalone_discovery_and_override(tmp_path):
    root = _application(tmp_path / "my_app")
    _application(root / "build/copied_app")
    child = root / "src"
    child.mkdir()
    assert discover_project_context(cwd=child, environ={}).root == root
    assert [p["name"] for p in _list(root)] == ["my_app"]
    assert [p["name"] for p in _list(root, HOLOSCAN_CLI_SEARCH_PATH="build")] == ["copied_app"]


def test_container_preserves_standalone_name(tmp_path, monkeypatch):
    from holoscan_cli.container import HoloscanContainer

    root = _application(tmp_path / "my_app")
    set_active_project_context(discover_project_context(cwd=root, environ={}))
    monkeypatch.setattr(HoloscanContainer, "HOLOHUB_ROOT", root)
    args = HoloscanContainer({"metadata": {}}).get_environment_args()
    assert "HOLOSCAN_CLI_APP_NAME=my_app" in args
    renamed = _application(tmp_path / "renamed_mount")
    assert _list(renamed, HOLOSCAN_CLI_APP_NAME="my_app")[0]["name"] == "my_app"


@pytest.mark.parametrize(
    "contents",
    [
        "{}",
        "[]",
        '{"application": null}',
        '{"application": {}}',
        '{"application": {"name": "unrelated"}}',
        "{invalid",
    ],
)
def test_unrelated_or_malformed_metadata_is_not_discovered(tmp_path, contents):
    (tmp_path / "metadata.json").write_text(contents, encoding="utf-8")
    assert _list(tmp_path) == []


@pytest.mark.parametrize("kind", ["large", "fifo", "symlink", "nested", "invalid_utf8"])
def test_unsafe_metadata_is_rejected_in_root_and_component_discovery(tmp_path, kind):
    path = tmp_path / "metadata.json"
    if kind == "large":
        with path.open("wb") as file:
            file.truncate(MAX_METADATA_BYTES + 1)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "symlink":
        target = tmp_path / "target.json"
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
    elif kind == "nested":
        path.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
    else:
        path.write_bytes(b"\xff")
    # Both paths run in subprocesses with timeouts, so a blocking open fails the test.
    assert _list(tmp_path) == []
    assert _list(tmp_path, HOLOSCAN_CLI_SEARCH_PATH=".") == []


def test_metadata_read_stays_bounded_if_stat_underreports_size(tmp_path, monkeypatch):
    from types import SimpleNamespace

    path = tmp_path / "metadata.json"
    path.write_bytes(b" " * MAX_METADATA_BYTES + b"{}")
    actual_stat = path.stat()
    monkeypatch.setattr(
        os, "fstat", lambda fd: SimpleNamespace(st_mode=actual_stat.st_mode, st_size=0)
    )
    with pytest.raises(ValueError, match="1 MiB limit"):
        read_metadata(path)


@pytest.mark.parametrize("name", ["", "..", "../other"])
def test_name_override_cannot_escape_build_directory(tmp_path, name):
    root = _application(tmp_path / "my_app")
    with pytest.raises(ValueError, match="HOLOSCAN_CLI_APP_NAME"):
        discover_project_context(cwd=root, environ={"HOLOSCAN_CLI_APP_NAME": name})
