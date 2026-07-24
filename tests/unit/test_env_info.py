# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from holoscan_cli import system_check as system_check_module
from holoscan_cli.commands import info as info_cmd
from holoscan_cli.utils import env_info


def test_collectors_print_available_host_tooling(tmp_path, monkeypatch, capsys):
    responses = {
        ("git", "branch", "--show-current"): "feature/module-cli",
        ("git", "rev-parse", "HEAD"): "abcdef0123456789",
        ("git", "status", "--porcelain"): " M README.md",
        ("docker", "--version"): "Docker version 26.1.0",
        ("docker", "info", "--format", "{{.ServerVersion}}"): "26.1.0",
        ("nvidia-ctk", "--version"): "NVIDIA Container Toolkit 1.16.2",
        (
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ): "NVIDIA H100, 550.54, 81559",
        ("nvcc", "--version"): "Cuda compilation tools, release 13.0, V13.0.0",
        ("which", "nvcc"): "/usr/local/cuda/bin/nvcc",
        ("sccache", "--version"): "sccache 0.8.2",
    }

    def fake_run_info_command(cmd):
        return responses.get(tuple(cmd))

    monkeypatch.setattr(env_info, "run_info_command", fake_run_info_command)
    monkeypatch.setattr(env_info.shutil, "which", lambda name: "/usr/bin/sccache")
    monkeypatch.setenv("HOLOSCAN_CLI_DOCKER_EXE", "docker")
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "true")
    monkeypatch.setenv("HOLOSCAN_CLI_PINNED_VERSION", "4.4.1")
    monkeypatch.setenv("CONDA_PREFIX", "/opt/conda/envs/holoscan")
    monkeypatch.setenv("SCCACHE_BUCKET", "holoscan-cache")
    monkeypatch.setenv("HOLOSCAN_INPUT_PATH", "/data/input")
    root = tmp_path / "repo"
    root.mkdir()

    env_info.collect_holohub_info(root, tmp_path / "build", tmp_path / "data", Path("/sdk"))
    env_info.collect_git_info(root)
    env_info.collect_env_info()

    out = capsys.readouterr().out
    assert "HOLOSCAN_CLI_ROOT" in out
    assert "Branch: feature/module-cli Commit: abcdef01" in out
    assert "Modified: [' M README.md']" in out
    assert "Docker version 26.1.0" in out
    assert "NVIDIA Container Toolkit 1.16.2" in out
    assert "GPU 0: NVIDIA H100" in out
    assert "NVCC: Cuda compilation tools, release 13.0, V13.0.0" in out
    assert "sccache 0.8.2" in out
    assert "SCCACHE_BUCKET: holoscan-cache" in out
    assert "HOLOSCAN_CLI_PINNED_VERSION: 4.4.1" in out
    assert "CONDA_PREFIX: /opt/conda/envs/holoscan" in out
    assert "HOLOSCAN_INPUT_PATH: /data/input" in out


def test_collectors_print_unavailable_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(env_info, "run_info_command", lambda cmd: None)
    monkeypatch.setattr(env_info.shutil, "which", lambda name: None)
    monkeypatch.delenv("HOLOSCAN_CLI_ENABLE_SCCACHE", raising=False)
    for key in list(os.environ):
        if key.startswith("SCCACHE_"):
            monkeypatch.delenv(key, raising=False)

    env_info.collect_git_info(tmp_path / "missing")
    env_info.collect_docker_info()
    env_info.collect_cuda_gpu_info()
    env_info.collect_sccache_info()

    out = capsys.readouterr().out
    assert "Source-project root directory does not exist" in out
    assert "Docker not available" in out
    assert "NVIDIA GPU/CUDA not available" in out
    assert "sccache binary: (not found in PATH)" in out
    assert "SCCACHE_* environment variables: (none set)" in out


# ---- env-check handler --------------------------------------------------------
#
# Closes the `FNDA:0` coverage gap on `handle_env_check`: only the underlying
# `system_check` helpers were unit-tested previously. These exercise the CLI
# command handler end-to-end with a stubbed `run_all_checks`.


def _make_results(*, fail: bool = False, warn: bool = False):
    results = [
        system_check_module.CheckResult(status="OK", name="GPU", message="ok"),
        system_check_module.CheckResult(status="OK", name="Docker", message="ok"),
    ]
    if warn:
        results.append(
            system_check_module.CheckResult(
                status="WARN", name="Disk", message="low", fix_suggestion="free space"
            )
        )
    if fail:
        results.append(
            system_check_module.CheckResult(
                status="FAIL", name="CUDA", message="absent", fix_suggestion="install cuda"
            )
        )
    return results


def test_env_check_text_emits_system_info_check_header(monkeypatch, capsys):
    """`holoscan env-check` prints the `System Info Check` banner used by
    downstream parsers (replaces the pre-consolidation `test_cli_env_check`)."""
    monkeypatch.setattr(system_check_module, "run_all_checks", lambda: _make_results())

    info_cmd.handle_env_check(None, argparse.Namespace(json=False))

    out = capsys.readouterr().out
    assert "System Info Check" in out
    assert "All checks passed" in out


def test_env_check_json_emits_elapsed_seconds_key(monkeypatch, capsys):
    """`env-check --json` must include a top-level `elapsed_seconds` field —
    machine-readable hook used by the pre-consolidation
    `test_cli_env_check_json` regression."""
    monkeypatch.setattr(system_check_module, "run_all_checks", lambda: _make_results())

    info_cmd.handle_env_check(None, argparse.Namespace(json=True))

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert "elapsed_seconds" in data
    assert isinstance(data["elapsed_seconds"], (int, float))
    assert data["summary"]["ok"] == 2
    assert data["summary"]["fail"] == 0


def test_env_check_exits_one_when_any_check_fails(monkeypatch):
    """FAIL results must surface as non-zero exit so CI / shell pipelines
    can react. WARN-only results stay informational (exit 0)."""
    monkeypatch.setattr(system_check_module, "run_all_checks", lambda: _make_results(fail=True))

    with pytest.raises(SystemExit) as excinfo:
        info_cmd.handle_env_check(None, argparse.Namespace(json=False))
    assert excinfo.value.code == 1


def test_env_check_does_not_exit_on_warn_only(monkeypatch, capsys):
    monkeypatch.setattr(system_check_module, "run_all_checks", lambda: _make_results(warn=True))

    # Must not raise SystemExit.
    info_cmd.handle_env_check(None, argparse.Namespace(json=False))

    out = capsys.readouterr().out
    assert "warning" in out.lower()


def test_env_info_json_round_trips(tmp_path, monkeypatch, capsys):
    """``env-info --json`` emits a single parseable document with the expected
    structured sections."""
    root = tmp_path / "repo"
    root.mkdir()
    root_str = str(root)
    responses = {
        ("git", "-C", root_str, "branch", "--show-current"): "main",
        ("git", "-C", root_str, "rev-parse", "HEAD"): "abcdef0123456789",
        ("git", "-C", root_str, "status", "--porcelain"): " M README.md\n?? new.txt",
        ("docker", "--version"): "Docker version 26.1.0",
        ("docker", "info", "--format", "{{.ServerVersion}}"): "26.1.0",
        ("nvidia-ctk", "--version"): "NVIDIA Container Toolkit 1.16.2",
        (
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ): "NVIDIA H100, 550.54, 81559",
        ("nvcc", "--version"): "Cuda compilation tools, release 13.0, V13.0.0",
        ("which", "nvcc"): "/usr/local/cuda/bin/nvcc",
        ("sccache", "--version"): "sccache 0.8.2",
    }
    monkeypatch.setattr(env_info, "run_info_command", lambda cmd: responses.get(tuple(cmd)))
    monkeypatch.setattr(env_info.shutil, "which", lambda name: "/usr/bin/sccache")
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "true")
    monkeypatch.setenv("HOLOSCAN_CLI_PINNED_VERSION", "4.4.1")

    cli = SimpleNamespace(
        HOLOHUB_ROOT=root,
        DEFAULT_BUILD_PARENT_DIR=tmp_path / "build",
        DEFAULT_DATA_DIR=tmp_path / "data",
        DEFAULT_SDK_DIR=Path("/opt/nvidia/holoscan"),
    )

    info_cmd.handle_env_info(cli, argparse.Namespace(json=True))

    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1
    assert data["cli"]["environment"] in {
        "wrapper-managed-venv",
        "conda",
        "virtualenv",
        "system",
    }
    assert data["source_project"]["root"] == root_str
    assert data["git"]["branch"] == "main"
    assert data["git"]["modified"] == [" M README.md", "?? new.txt"]
    assert data["docker"]["server_version"] == "26.1.0"
    assert data["docker"]["nvidia_container_toolkit"] == "NVIDIA Container Toolkit 1.16.2"
    assert data["cuda_gpu"]["gpus"][0]["name"] == "NVIDIA H100"
    assert data["cuda_gpu"]["gpus"][0]["memory_total_mb"] == "81559"
    assert data["sccache"]["enabled"] is True
    assert data["sccache"]["version"] == "sccache 0.8.2"
    assert data["environment_variables"]["holoscan_cli"]["HOLOSCAN_CLI_PINNED_VERSION"] == "4.4.1"


def test_env_info_json_nulls_unavailable_sections(tmp_path, monkeypatch, capsys):
    """Absent host tooling renders as JSON ``null``, not a crash or prose."""
    monkeypatch.setattr(env_info, "run_info_command", lambda cmd: None)
    monkeypatch.setattr(env_info.shutil, "which", lambda name: None)

    cli = SimpleNamespace(
        HOLOHUB_ROOT=tmp_path / "missing",
        DEFAULT_BUILD_PARENT_DIR=tmp_path / "build",
        DEFAULT_DATA_DIR=tmp_path / "data",
        DEFAULT_SDK_DIR=Path("/opt/nvidia/holoscan"),
    )

    info_cmd.handle_env_info(cli, argparse.Namespace(json=True))

    data = json.loads(capsys.readouterr().out)
    assert data["git"] is None
    assert data["docker"] is None
    assert data["cuda_gpu"] is None
    assert data["sccache"]["binary"] is None


def test_collect_cli_info_reports_managed_venv(monkeypatch, capsys):
    import sys

    venv = "/home/user/.local/share/Holoscan CLI/venv"
    monkeypatch.setenv("HOLOSCAN_CLI_VENV", venv)
    monkeypatch.delenv("HOLOSCAN_CLI_SOURCE", raising=False)
    monkeypatch.setattr(sys, "prefix", venv)

    env_info.collect_cli_info()

    out = capsys.readouterr().out
    assert "Holoscan CLI Information:" in out
    assert "Version:" in out
    assert "Package:" in out
    assert "Environment: wrapper-managed venv" in out
    assert f"Uninstall: rm -rf '{venv}'" in out


def test_collect_cli_info_reports_conda_environment(monkeypatch, capsys):
    import sys

    conda_prefix = "/opt/conda/envs/holoscan"
    monkeypatch.setenv("CONDA_PREFIX", conda_prefix)
    monkeypatch.delenv("HOLOSCAN_CLI_VENV", raising=False)
    monkeypatch.delenv("HOLOSCAN_CLI_SOURCE", raising=False)
    monkeypatch.setattr(sys, "prefix", conda_prefix)
    monkeypatch.setattr(sys, "base_prefix", conda_prefix)
    monkeypatch.setattr(sys, "executable", f"{conda_prefix}/bin/python")

    env_info.collect_cli_info()

    out = capsys.readouterr().out
    assert f"Environment: Conda environment ({conda_prefix})" in out
    assert f"Uninstall: {conda_prefix}/bin/python -m pip uninstall holoscan-cli" in out
