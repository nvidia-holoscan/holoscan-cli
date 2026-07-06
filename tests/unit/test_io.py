# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess

from holoscan_cli.utils import io


def test_run_command_as_root_when_already_root_runs_directly(monkeypatch):
    monkeypatch.setattr(io.os, "geteuid", lambda: 0)
    seen = {}

    def fake_run(cmd, check=True, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(io.subprocess, "run", fake_run)

    io.run_command(["apt-get", "update"], as_root=True)

    assert seen["cmd"] == ["apt-get", "update"]  # no sudo prepended as root


def test_run_command_preserves_environment_for_elevated_application(monkeypatch, capsys):
    monkeypatch.setattr(io.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(io.shutil, "which", lambda _: "/usr/bin/sudo")
    seen = {}
    app_env = {
        "PATH": "/home/user/bin:/usr/bin",
        "PYTHONPATH": "/workspace/python",
        "LD_PRELOAD": "/opt/lib/libcamera.so",
        "API_TOKEN": "not-on-the-command-line",
    }

    def fake_run(cmd, check=True, **kwargs):
        seen["cmd"] = cmd
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(io.subprocess, "run", fake_run)

    io.run_command(
        ["python3", "app.py"],
        as_root=True,
        preserve_env={"PATH", "PYTHONPATH", "LD_PRELOAD"},
        env=app_env,
    )

    assert seen["cmd"] == [
        "/usr/bin/sudo",
        "-H",
        "/usr/bin/env",
        "LD_PRELOAD=/opt/lib/libcamera.so",
        "PATH=/home/user/bin:/usr/bin",
        "PYTHONPATH=/workspace/python",
        "python3",
        "app.py",
    ]
    assert seen["env"] is app_env
    assert all("not-on-the-command-line" not in arg for arg in seen["cmd"])
    assert "PATH=<preserved>" in capsys.readouterr().out
