# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import setup_cmd


def test_build_script_env_uses_cli_virtualenv(monkeypatch):
    monkeypatch.setattr(setup_cmd.sys, "executable", "/tmp/cli-venv/bin/python")
    monkeypatch.setattr(setup_cmd.sys, "prefix", "/tmp/cli-venv")
    monkeypatch.setattr(setup_cmd.sys, "base_prefix", "/usr")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PYTHONHOME", "/unexpected/python-home")

    env = setup_cmd._build_script_env()

    assert env["PATH"].split(":", 1)[0] == "/tmp/cli-venv/bin"
    assert env["VIRTUAL_ENV"] == "/tmp/cli-venv"
    assert "PYTHONHOME" not in env


def test_build_script_env_removes_stale_virtualenv_for_system_python(monkeypatch):
    monkeypatch.setattr(setup_cmd.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(setup_cmd.sys, "prefix", "/usr")
    monkeypatch.setattr(setup_cmd.sys, "base_prefix", "/usr")
    monkeypatch.setenv("PATH", "/tmp/stale-venv/bin:/usr/bin:/bin")
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/stale-venv")

    env = setup_cmd._build_script_env()

    assert env["PATH"].split(":", 1)[0] == "/usr/bin"
    assert "VIRTUAL_ENV" not in env


def test_named_setup_script_runs_in_cli_environment(monkeypatch, tmp_path):
    setup_dir = tmp_path / "setup"
    setup_dir.mkdir()
    script = setup_dir / "template.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    script_env = {"PATH": "/tmp/cli-venv/bin:/usr/bin"}
    commands = []

    monkeypatch.setattr(setup_cmd, "get_holohub_setup_scripts_dir", lambda: setup_dir)
    monkeypatch.setattr(setup_cmd, "_build_script_env", lambda: script_env)
    monkeypatch.setattr(
        setup_cmd,
        "run_command",
        lambda cmd, **kwargs: commands.append((cmd, kwargs)),
    )

    with pytest.raises(SystemExit) as exc_info:
        setup_cmd.handle_setup(
            SimpleNamespace(),
            Namespace(list_scripts=False, scripts=["template"], dryrun=True),
        )

    assert exc_info.value.code == 0
    assert commands == [(["bash", str(script)], {"dry_run": True, "env": script_env})]


def test_default_setup_calls_each_helper_in_order(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        setup_cmd,
        "install_packages_if_missing",
        lambda packages, dry_run=False: calls.append(("packages", packages, dry_run)),
    )
    for name in (
        "setup_cuda_dependencies",
        "setup_cmake",
        "setup_python_dev",
        "setup_ngc_cli",
        "setup_sccache",
    ):
        monkeypatch.setattr(
            setup_cmd,
            name,
            lambda dry_run=False, helper=name: calls.append((helper, dry_run)),
        )

    setup_cmd.handle_setup(
        SimpleNamespace(HOLOHUB_ROOT=tmp_path, script_name="holoscan"),
        Namespace(list_scripts=False, scripts=None, dryrun=True),
    )

    assert calls[0][0] == "packages"
    assert calls[0][2] is True
    assert [call[0] for call in calls[1:]] == [
        "setup_cuda_dependencies",
        "setup_cmake",
        "setup_python_dev",
        "setup_ngc_cli",
        "setup_sccache",
    ]
    assert all(call[1] is True for call in calls[1:])
