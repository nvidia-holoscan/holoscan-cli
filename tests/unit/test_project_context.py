# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from holoscan_cli.project_context import (
    ProjectContextError,
    ProjectVersionError,
    activate_project_context,
    discover_project_context,
    enforce_project_requirement,
    get_running_cli_version,
    parse_cli_requirement,
)


def _module(
    root: Path,
    *,
    required_version: str | None = None,
    full_layout: bool = True,
    legacy_launcher: bool = False,
) -> Path:
    root.mkdir(parents=True)
    metadata = {
        "module": {
            "name": "holoscan-my-sensor",
            "namespace": {"python": "holoscan.my_sensor"},
            "holoscan_sdk": {"minimum_required_version": "4.6.0"},
            "dockerfile": "Dockerfile",
        }
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    if full_layout:
        (root / "applications").mkdir()
        (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    if required_version:
        (root / "requirements-cli.txt").write_text(
            f"# generated\nholoscan-cli=={required_version}\n",
            encoding="utf-8",
        )
    if legacy_launcher:
        (root / "holohub").write_text("#!/bin/sh\n", encoding="utf-8")
    return root


def _subprocess_env() -> dict[str, str]:
    source = Path(__file__).resolve().parents[2] / "src"
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("HOLOSCAN_CLI_")
    }
    environment["PYTHONPATH"] = str(source)
    return environment


@pytest.mark.parametrize(
    "contents,expected",
    [
        ("# comment\nholoscan-cli==5.0.0a1+dev.2\n", "5.0.0a1+dev.2"),
        ("holoscan-cli>=5\n", None),
        ("holoscan-cli[create]==5.0.0\n", None),
        ("holoscan-cli==5.0.0\nholoscan-cli==5.0.1\n", None),
    ],
)
def test_requirement_contract(tmp_path, contents, expected):
    requirement = tmp_path / "requirements-cli.txt"
    requirement.write_text(contents, encoding="utf-8")

    if expected is None:
        with pytest.raises(ProjectContextError):
            parse_cli_requirement(requirement)
    else:
        assert parse_cli_requirement(requirement) == expected


def test_module_discovery_and_profile(tmp_path, monkeypatch):
    root = _module(tmp_path / "module", required_version=get_running_cli_version())
    descendant = root / "applications/pipeline/python"
    descendant.mkdir(parents=True)

    context = discover_project_context(cwd=descendant, environ={})

    assert context.root == root
    assert context.is_standalone_module
    assert context.repo_prefix == "my_sensor"
    assert context.container_prefix == "my-sensor"
    assert context.base_sdk_version == "4.6.0"
    assert context.dockerfile == root / "Dockerfile"

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setenv("HOLOSCAN_CLI_DATA_DIR", "/custom/data")
    monkeypatch.delenv("HOLOSCAN_CLI_ROOT", raising=False)
    activate_project_context(context)
    assert os.environ["HOLOSCAN_CLI_ROOT"] == str(root)
    assert os.environ["HOLOSCAN_CLI_BUILD_PARENT_DIR"] == str(root / "build")
    assert os.environ["HOLOSCAN_CLI_DATA_DIR"] == "/custom/data"
    assert os.environ["HOLOSCAN_CLI_REPO_PREFIX"] == "my_sensor"


def test_source_project_precedes_a_nested_metadata_only_module(tmp_path):
    holohub = tmp_path / "holohub"
    app = holohub / "applications/example"
    app.mkdir(parents=True)
    (app / "metadata.json").write_text("{}\n", encoding="utf-8")
    nested = _module(
        holohub / "modules/holoscan-my-sensor",
        required_version=get_running_cli_version(),
        full_layout=False,
    )

    assert discover_project_context(cwd=nested, environ={}).root == holohub
    assert (
        discover_project_context(
            cwd=tmp_path,
            explicit_root=nested,
            environ={},
        ).root
        == nested
    )


def test_declared_roots_are_trusted_and_invalid_environment_falls_back(tmp_path):
    module = _module(tmp_path / "module", required_version=get_running_cli_version())
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

    assert (explicit.root, explicit.discovery) == (selected, "project-root")
    assert (environment.root, environment.discovery) == (selected, "environment")
    assert fallback.root == module
    assert fallback.warnings


@pytest.mark.parametrize(
    "in_container,expected,excluded",
    [
        (False, "pip install -r", "Rebuild the development image"),
        (True, "Rebuild the development image", "pip install"),
    ],
)
def test_version_mismatch_has_contextual_guidance(tmp_path, in_container, expected, excluded):
    root = _module(tmp_path / "module", required_version="999.0.0")
    context = discover_project_context(cwd=root, environ={}, running_version="1.0.0")

    with pytest.raises(ProjectVersionError) as error:
        enforce_project_requirement(context, in_container=in_container)

    assert expected in str(error.value)
    assert excluded not in str(error.value)


def test_legacy_module_launcher_has_no_version_lock(tmp_path):
    root = _module(tmp_path / "module", legacy_launcher=True)
    context = discover_project_context(cwd=root, environ={}, running_version="1.0.0")

    enforce_project_requirement(context)

    assert context.is_module
    assert not context.is_standalone_module


def test_lightweight_imports_do_not_load_project_cli_or_emit_warnings(tmp_path):
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


def test_dispatch_activates_a_standalone_module(tmp_path):
    root = _module(tmp_path / "module", required_version=get_running_cli_version())

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
