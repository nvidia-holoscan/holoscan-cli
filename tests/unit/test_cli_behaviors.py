# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import shutil
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from holoscan_cli import cli as project_cli
from holoscan_cli.commands import clear_cache as clear_cache_cmd

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "holohub_smoke"


def _copy_smoke_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "holohub_smoke"
    shutil.copytree(FIXTURE_ROOT, repo_root)
    return repo_root


def test_cli_dispatch_runs_smoke_app_locally_from_metadata(tmp_path, monkeypatch, capfd):
    if shutil.which("python") is None:
        pytest.skip("the smoke fixture command requires a python executable on PATH")

    repo_root = _copy_smoke_repo(tmp_path)
    build_parent = tmp_path / "build"
    (build_parent / "smoke_app").mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", repo_root)
    monkeypatch.setattr(project_cli.HoloscanCLI, "DEFAULT_BUILD_PARENT_DIR", build_parent)
    monkeypatch.setattr(project_cli.HoloscanCLI, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setenv("HOLOSCAN_CLI_ROOT", str(repo_root))
    monkeypatch.setenv("HOLOSCAN_CLI_BUILD_PARENT_DIR", str(build_parent))
    monkeypatch.setenv("HOLOSCAN_CLI_DATA_DIR", str(data_dir))
    cli = project_cli.HoloscanCLI(script_name="holoscan")

    original_cwd = os.getcwd()
    try:
        cli.run(["holoscan", "run", "smoke_app", "--local", "--no-local-build"])
    finally:
        os.chdir(original_cwd)

    out = capfd.readouterr().out
    assert "smoke_app" in out


def test_clear_cache_deletes_only_selected_temp_cache_family(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    build_parent = tmp_path / "build"
    data_dir = tmp_path / "data"
    install_dir = repo_root / "install"
    sibling_build = repo_root / "build-extra"
    for path in (build_parent, data_dir, install_dir, sibling_build):
        path.mkdir(parents=True)
        (path / "sentinel").write_text("keep track\n", encoding="utf-8")

    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", repo_root)
    cli = object.__new__(project_cli.HoloscanCLI)
    cli.DEFAULT_BUILD_PARENT_DIR = build_parent
    cli.DEFAULT_DATA_DIR = data_dir

    clear_cache_cmd.handle_clear_cache(
        cli, Namespace(dryrun=False, build=True, data=False, install=False)
    )

    assert not build_parent.exists()
    assert not sibling_build.exists()
    assert data_dir.is_dir()
    assert install_dir.is_dir()


def test_clear_cache_without_flags_deletes_all_temp_cache_families(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    build_parent = tmp_path / "build"
    data_dir = tmp_path / "data"
    install_dir = repo_root / "install-custom"
    for path in (build_parent, data_dir, install_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", repo_root)
    cli = object.__new__(project_cli.HoloscanCLI)
    cli.DEFAULT_BUILD_PARENT_DIR = build_parent
    cli.DEFAULT_DATA_DIR = data_dir

    clear_cache_cmd.handle_clear_cache(
        cli, Namespace(dryrun=False, build=False, data=False, install=False)
    )

    assert not build_parent.exists()
    assert not data_dir.exists()
    assert not install_dir.exists()


def test_resolve_mode_requires_default_for_ambiguous_metadata():
    cli = object.__new__(project_cli.HoloscanCLI)
    project_data = {
        "metadata": {
            "modes": {
                "debug": {"run": {"command": "python app.py"}},
                "release": {"run": {"command": "python app.py"}},
            }
        }
    }

    with pytest.raises(SystemExit):
        cli.resolve_mode(project_data)


def test_effective_mode_config_applies_metadata_defaults():
    cli = object.__new__(project_cli.HoloscanCLI)
    args = Namespace(
        with_operators=None,
        build_args="",
        configure_args=None,
        docker_opts="",
        run_args="",
    )
    mode_config = {
        "build": {
            "depends": ["op_a", "", "op_b"],
            "docker_build_args": ["--build-arg", "MODE=dev"],
            "cmake_options": ["-DMODE=dev", "-DENABLE_TESTS=ON"],
        },
        "run": {
            "command": "python app.py",
            "workdir": ".",
            "docker_run_args": ["--ipc=host", "--network=host"],
        },
    }

    build_config = cli.get_effective_build_config(args, mode_config)
    run_config = cli.get_effective_run_config(args, mode_config)

    assert build_config == {
        "with_operators": "op_a;op_b",
        "docker_opts": "--ipc=host --network=host",
        "build_args": "--build-arg MODE=dev",
        "configure_args": ["-DMODE=dev", "-DENABLE_TESTS=ON"],
    }
    assert run_config == {
        "run_args": "",
        "docker_opts": "--ipc=host --network=host",
        "command": "python app.py",
        "workdir": ".",
    }


def test_effective_mode_config_preserves_cli_overrides(capsys):
    cli = object.__new__(project_cli.HoloscanCLI)
    args = Namespace(
        with_operators="cli_op",
        build_args="--build-arg CLI=1",
        configure_args=["-DCLI=ON"],
        docker_opts="--cap-add SYS_PTRACE",
        run_args="--frames 1",
    )
    mode_config = {
        "build": {
            "depends": ["mode_op"],
            "docker_build_args": "--build-arg MODE=1",
            "cmake_options": ["-DMODE=ON"],
        },
        "run": {
            "command": "python app.py",
            "workdir": ".",
            "docker_run_args": "--ipc=host",
        },
    }

    build_config = cli.get_effective_build_config(args, mode_config)
    run_config = cli.get_effective_run_config(args, mode_config)

    assert build_config == {
        "with_operators": "cli_op",
        "docker_opts": "--cap-add SYS_PTRACE",
        "build_args": "--build-arg CLI=1",
        "configure_args": ["-DCLI=ON"],
    }
    assert run_config == {
        "run_args": "--frames 1",
        "docker_opts": "--cap-add SYS_PTRACE",
        "command": "python app.py",
        "workdir": ".",
    }
    assert "overrides mode" in capsys.readouterr().err


def test_run_preserves_container_command_after_separator(monkeypatch, tmp_path):
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", tmp_path)
    with patch.object(project_cli.metadata_util, "gather_metadata", return_value=[]):
        cli = project_cli.HoloscanCLI(script_name="holoscan")
    captured = {}
    cli.subparsers["run-container"].set_defaults(func=lambda args: captured.update(vars(args)))

    cli.run(
        [
            "holoscan",
            "run-container",
            "--no-docker-build",
            "--img",
            "smoke:latest",
            "--",
            "echo",
            "hello world",
        ]
    )

    assert captured["img"] == "smoke:latest"
    assert captured["no_docker_build"] is True
    assert captured["_trailing_args"] == ["echo", "hello world"]
