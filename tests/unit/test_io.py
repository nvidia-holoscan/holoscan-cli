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
        preserve_env={"PATH", "PYTHONPATH", "LD_PRELOAD", "API_TOKEN"},
        env=app_env,
    )

    # loader vars go via /usr/bin/env; the rest via --preserve-env, off the argv
    assert seen["cmd"] == [
        "/usr/bin/sudo",
        "-H",
        "--preserve-env=API_TOKEN",
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


def test_run_command_applies_owned_env_overlay_without_mutating_process_env(monkeypatch):
    monkeypatch.setenv("DOCKER_BUILDKIT", "0")
    monkeypatch.delenv("PLAN_ONLY", raising=False)
    seen = {}

    def fake_run(cmd, check=True, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(io.subprocess, "run", fake_run)

    io.run_command(
        ["docker", "build", "."],
        env_updates={"DOCKER_BUILDKIT": "1", "PLAN_ONLY": "enabled"},
    )

    assert seen["env"]["DOCKER_BUILDKIT"] == "1"
    assert seen["env"]["PLAN_ONLY"] == "enabled"
    assert io.os.environ["DOCKER_BUILDKIT"] == "0"
    assert "PLAN_ONLY" not in io.os.environ
