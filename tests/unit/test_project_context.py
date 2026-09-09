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
    activate_project_context,
    discover_project_context,
)


def _module(root: Path, *, full_layout: bool = True, pyproject: str | None = None) -> Path:
    root.mkdir(parents=True)
    metadata = {
        "module": {
            "name": "holoscan-my-sensor",
            "namespace": {"python": "holoscan.my_sensor"},
            "holoscan_sdk": {"minimum_required_version": "4.6.0"},
        }
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    if pyproject is not None:
        (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
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
    assert context.forward_env == ()

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


def test_module_pyproject_resolves_project_contract_and_nearby_sdk(
    tmp_path, monkeypatch, make_sdk_directory
):
    root = _module(
        tmp_path / "module",
        pyproject="""
[tool.holoscan]
cuda = 13
ctest-script = "ci/container.ctest"
forward-env = ["CI"]
docker-build-args = ["--build-arg", "PROJECT_FEATURE=ON"]
docker-run-args = ["--network=host"]

[tool.holoscan.base-images]
x86_64 = "example.test/holoscan:fixed"
""",
    )
    sdk = make_sdk_directory(tmp_path / "holoscan-sdk/public/install-x86_64")
    monkeypatch.setattr("holoscan_cli.project_context.platform.machine", lambda: "x86_64")

    context = discover_project_context(cwd=root, environ={})
    profile = context.profile_environment()

    assert context.base_image == "example.test/holoscan:fixed"
    assert context.sdk_root == sdk.resolve()
    assert context.cuda == "13"
    assert context.ctest_script == "ci/container.ctest"
    assert context.docker_build_args == "--build-arg PROJECT_FEATURE=ON"
    assert context.docker_run_args == "--network=host"
    assert context.forward_env == ("CI",)
    assert profile["HOLOSCAN_CLI_DEFAULT_CUDA_VERSION"] == "13"
    assert profile["HOLOSCAN_CLI_CTEST_SCRIPT"] == "ci/container.ctest"
    assert {
        "HOLOSCAN_CLI_FORWARD_ENV",
        "HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS",
        "HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS",
        "HOLOSCAN_CLI_BASE_IMAGE_FORMAT",
        "HOLOSCAN_CLI_DEFAULT_HSDK_DIR",
        "holoscan_ROOT",
    }.isdisjoint(profile)


def test_module_environment_resolves_4x_sdk_build_tree(tmp_path, monkeypatch, make_sdk_directory):
    root = _module(tmp_path / "module")
    sdk_root = tmp_path / "holoscan-sdk"
    build = sdk_root / "public/build-cu13-x86_64"
    (sdk_root / "public").mkdir(parents=True)
    (sdk_root / "public/VERSION").write_text("4.6.0\n", encoding="utf-8")
    make_sdk_directory(build, build=True)
    monkeypatch.setattr("holoscan_cli.project_context.platform.machine", lambda: "x86_64")

    context = discover_project_context(
        cwd=root,
        environ={
            "HOLOSCAN_SDK_ROOT": str(sdk_root),
            "HOLOSCAN_CLI_DEFAULT_CUDA_VERSION": "13",
        },
    )

    assert context.sdk_root == build.resolve()
    assert context.sdk_root_source == "HOLOSCAN_SDK_ROOT"
    assert context.warnings == ()


@pytest.mark.parametrize(
    ("pyproject", "error"),
    [
        ("[tool.holoscan]\ncdua = 13\n", "unknown field.*cdua"),
        ("[tool.holoscan]\ncuda = '13'\n", "cuda"),
        ("[tool.holoscan]\nctest-script = '../container.ctest'\n", "ctest-script"),
        ("[tool.holoscan]\nforward-env = ['HOME']\n", "forward-env"),
        ("[tool.holoscan]\ndocker-run-args = ['']\n", "docker-run-args"),
        ("[tool.holoscan]\nbase-images = 'x86_64'\n", "base-images must be a table"),
        (
            "[tool.holoscan.base-images]\n"
            "x86_64 = 'invalid image'\n"
            "aarch64 = 'invalid image'\n",
            "base-images",
        ),
    ],
)
def test_module_pyproject_rejects_unsafe_or_unknown_values(tmp_path, pyproject, error):
    root = _module(tmp_path / "module", pyproject=pyproject)

    with pytest.raises(ProjectContextError, match=error):
        discover_project_context(cwd=root, environ={})


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
