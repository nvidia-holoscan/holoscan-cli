# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess

import pytest

from holoscan_cli.utils import io


def test_run_command_display_override_hides_value_without_changing_execution(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(io.subprocess, "run", fake_run)

    io.run_command(
        ["tool", "--token", "secret-value"],
        display_override=["tool", "<configured options hidden>"],
    )

    assert calls == [["tool", "--token", "secret-value"]]
    output = capsys.readouterr().out
    assert "<configured options hidden>" in output
    assert "secret-value" not in output


@pytest.mark.parametrize("as_string", [False, True])
@pytest.mark.parametrize("dry_run,check", [(True, True), (False, True), (False, False)])
def test_run_command_redacts_failure_and_dryrun_output(
    monkeypatch, capsys, as_string, dry_run, check
):
    cmd = "tool --token secret-value" if as_string else ["tool", "--token", "secret-value"]
    display = "tool <hidden>" if as_string else ["tool", "<hidden>"]
    calls = []

    def fail_run(argv, *, check):
        calls.append(argv)
        if check:
            raise subprocess.CalledProcessError(7, argv)
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(io.subprocess, "run", fail_run)

    if check and not dry_run:
        with pytest.raises(SystemExit) as exc:
            io.run_command(cmd, dry_run=dry_run, check=check, display_override=display)
        assert exc.value.code == 7
    else:
        result = io.run_command(cmd, dry_run=dry_run, check=check, display_override=display)
        assert result.args == cmd
        assert result.returncode == (0 if dry_run else 7)

    assert calls == ([] if dry_run else [cmd])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "tool <hidden>" in output
    assert "secret-value" not in output
    if check and not dry_run:
        assert "Non-zero exit code running command: tool <hidden>" in output
        assert "Exit code: 7" in output


@pytest.mark.parametrize("display", ["tool <hidden>", ["tool", "<hidden>"], "", [], None])
def test_run_command_missing_sudo_respects_display_override(monkeypatch, capsys, display):
    monkeypatch.setattr(io.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(io.shutil, "which", lambda _: None)

    def unexpected_run(*args, **kwargs):
        pytest.fail("A command requiring sudo must not run when sudo is unavailable")

    monkeypatch.setattr(io.subprocess, "run", unexpected_run)
    cmd = ["tool", "--token", "secret-value"]

    with pytest.raises(SystemExit) as exc:
        io.run_command(cmd, as_root=True, display_override=display)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "'sudo' is not available" in output
    assert "Re-run it as an administrator, or install sudo." in output
    assert ("secret-value" in output) == (display is None)
    if display:
        assert "tool <hidden>" in output


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
