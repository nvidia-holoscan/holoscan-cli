# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess

import pytest

from holoscan_cli.utils import io


def test_run_command_dry_run_as_root_works_without_sudo(monkeypatch, capsys):
    """`setup --dryrun` must not fail on hosts without sudo: nothing executes."""
    monkeypatch.setattr(io.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(io.shutil, "which", lambda _: None)

    result = io.run_command(["apt-get", "update"], dry_run=True, as_root=True)

    assert result.returncode == 0
    out = capsys.readouterr().out
    assert "sudo apt-get update" in out
    assert "[dryrun]" in out


def test_run_command_as_root_without_sudo_fails_clearly(monkeypatch, capsys):
    monkeypatch.setattr(io.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(io.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit):
        io.run_command(["apt-get", "update"], as_root=True)

    assert "'sudo' is not available" in capsys.readouterr().err


def test_run_command_as_root_when_already_root_runs_directly(monkeypatch):
    monkeypatch.setattr(io.os, "geteuid", lambda: 0)
    seen = {}

    def fake_run(cmd, check=True, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(io.subprocess, "run", fake_run)

    io.run_command(["apt-get", "update"], as_root=True)

    assert seen["cmd"] == ["apt-get", "update"]  # no sudo prepended as root
