# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from holoscan_cli.project_context import activate_project_context, discover_project_context


def _module(root: Path, *, full_layout: bool = True) -> Path:
    root.mkdir(parents=True)
    metadata = {
        "module": {
            "name": "holoscan-my-sensor",
            "namespace": {"python": "holoscan.my_sensor"},
            "holoscan_sdk": {"minimum_required_version": "4.6.0"},
        }
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    if full_layout:
        (root / "applications").mkdir()
    return root


def _subprocess_env() -> dict[str, str]:
    source = Path(__file__).resolve().parents[2] / "src"
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("HOLOSCAN_CLI_")
    }
    environment["PYTHONPATH"] = str(source)
    return environment


def test_module_discovery_and_activation(tmp_path, monkeypatch):
    root = _module(tmp_path / "module")
    (root / "holohub").write_text("#!/bin/sh\n", encoding="utf-8")
    descendant = root / "applications/pipeline/python"
    descendant.mkdir(parents=True)

    context = discover_project_context(cwd=descendant, environ={})

    assert context.root == root
    assert context.repo_prefix == "my_sensor"
    assert context.base_sdk_version == "4.6.0"

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setenv("HOLOSCAN_CLI_DATA_DIR", "/custom/data")
    monkeypatch.delenv("HOLOSCAN_CLI_ROOT", raising=False)
    activate_project_context(context)

    assert os.environ["HOLOSCAN_CLI_ROOT"] == str(root)
    assert os.environ["HOLOSCAN_CLI_BUILD_PARENT_DIR"] == str(root / "build")
    assert os.environ["HOLOSCAN_CLI_DATA_DIR"] == "/custom/data"
    assert os.environ["HOLOSCAN_CLI_REPO_PREFIX"] == "my_sensor"
    assert os.environ["HOLOSCAN_CLI_CONTAINER_PREFIX"] == "my-sensor"


def test_implicit_discovery_tolerates_malformed_module_metadata(tmp_path):
    root = tmp_path / "module"
    descendant = root / "nested/deep"
    descendant.mkdir(parents=True)
    (root / "metadata.json").write_text("{not json", encoding="utf-8")

    context = discover_project_context(cwd=descendant, environ={})

    assert context.root == root
    assert context.repo_prefix is None
    assert context.base_sdk_version is None
    assert len(context.warnings) == 1
    assert "Invalid Module metadata" in context.warnings[0]


def test_source_project_precedes_nested_module(tmp_path):
    source_root = tmp_path / "holohub"
    app = source_root / "applications/example"
    app.mkdir(parents=True)
    (app / "metadata.json").write_text("{}\n", encoding="utf-8")
    module = _module(source_root / "modules/holoscan-my-sensor", full_layout=False)

    assert discover_project_context(cwd=module, environ={}).root == source_root
    assert discover_project_context(explicit_root=module, environ={}).root == module


def test_root_precedence_and_invalid_environment_fallback(tmp_path):
    module = _module(tmp_path / "module")
    selected = tmp_path / "selected"
    selected.mkdir()

    explicit = discover_project_context(
        cwd=module,
        explicit_root=selected,
        environ={"HOLOSCAN_CLI_ROOT": str(module)},
    )
    environment = discover_project_context(
        cwd=module,
        environ={"HOLOSCAN_CLI_ROOT": str(selected)},
    )
    fallback = discover_project_context(
        cwd=module,
        environ={"HOLOSCAN_CLI_ROOT": str(tmp_path / "missing")},
    )

    assert explicit.root == selected
    assert environment.root == selected
    assert fallback.root == module
    assert fallback.warnings


def test_lightweight_import_does_not_load_project_cli(tmp_path):
    script = """
import sys
import holoscan_cli.__main__
import holoscan_cli.commands.registry
import holoscan_cli.utils.holohub
blocked = ('holoscan_cli.cli', 'holoscan_cli.container.core')
assert not any(name in sys.modules for name in blocked)
"""
    environment = _subprocess_env()
    environment["HOLOSCAN_CLI_ROOT"] = str(tmp_path / "missing")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_dispatch_activates_module_without_a_runtime_version_gate(tmp_path):
    root = _module(tmp_path / "module")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            "--project-root",
            str(root),
            "list",
            "--json",
        ],
        cwd=tmp_path,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    projects = json.loads(result.stdout)["projects"]
    module = next(project for project in projects if project["project_type"] == "module")
    assert module["source_folder"] == str(root)
