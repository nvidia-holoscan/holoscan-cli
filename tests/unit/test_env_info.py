# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from holoscan_cli.commands import info as info_cmd
from holoscan_cli import system_check as system_check_module
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
    assert "elapsed_seconds" in data
    assert isinstance(data["elapsed_seconds"], (int, float))
    assert data["summary"]["ok"] == 2
    assert data["summary"]["fail"] == 0


def test_env_check_exits_one_when_any_check_fails(monkeypatch):
    """FAIL results must surface as non-zero exit so CI / shell pipelines
    can react. WARN-only results stay informational (exit 0)."""
    monkeypatch.setattr(
        system_check_module, "run_all_checks", lambda: _make_results(fail=True)
    )

    with pytest.raises(SystemExit) as excinfo:
        info_cmd.handle_env_check(None, argparse.Namespace(json=False))
    assert excinfo.value.code == 1


def test_env_check_does_not_exit_on_warn_only(monkeypatch, capsys):
    monkeypatch.setattr(
        system_check_module, "run_all_checks", lambda: _make_results(warn=True)
    )

    # Must not raise SystemExit.
    info_cmd.handle_env_check(None, argparse.Namespace(json=False))

    out = capsys.readouterr().out
    assert "warning" in out.lower()
