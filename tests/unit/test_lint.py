# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import sys
from types import SimpleNamespace

import pytest

from holoscan_cli import cli as project_cli
from holoscan_cli import util as project_util
from holoscan_cli.commands import lint as commands_lint


def _lint_cli(root, monkeypatch):
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", root)
    return object.__new__(project_cli.HoloscanCLI)


def test_holoscan_cli_root_discovery_from_subdirectory(tmp_path, monkeypatch):
    root = tmp_path / "holoscan-cli"
    subdir = root / "src" / "holoscan_cli" / "project"
    subdir.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'holoscan-cli'\n")

    monkeypatch.chdir(subdir)

    assert project_util._get_holohub_root() == root


def test_lint_dryrun_uses_pre_commit_all_files(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".pre-commit-config.yaml").write_text("repos: []\n")
    lint_cli = _lint_cli(root, monkeypatch)
    calls = []

    def fake_run_command(cmd, check=False, dry_run=False, env=None):
        calls.append({"cmd": cmd, "check": check, "dry_run": dry_run, "env": env})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(commands_lint.holohub_cli_util, "run_command", fake_run_command)

    args = argparse.Namespace(path=".", fix=False, install_dependencies=False, dryrun=True)
    with pytest.raises(SystemExit) as exc_info:
        commands_lint.handle_lint(lint_cli, args)

    assert exc_info.value.code == 0
    assert calls == [
        {
            "cmd": [
                sys.executable,
                "-m",
                "pre_commit",
                "run",
                "--show-diff-on-failure",
                "--all-files",
            ],
            "check": False,
            "dry_run": True,
            "env": calls[0]["env"],
        }
    ]


def test_lint_dryrun_limits_to_git_tracked_path(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    target = root / "src" / "holoscan_cli" / "__main__.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('hello')\n")
    lint_cli = _lint_cli(root, monkeypatch)
    calls = []

    def fake_run_command(cmd, check=False, dry_run=False, env=None):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(commands_lint.holohub_cli_util, "run_command", fake_run_command)
    monkeypatch.setattr(
        commands_lint.subprocess,
        "check_output",
        lambda *args, **kwargs: "src/holoscan_cli/__main__.py\n",
    )

    args = argparse.Namespace(
        path="src/holoscan_cli/__main__.py",
        fix=False,
        install_dependencies=False,
        dryrun=True,
    )
    with pytest.raises(SystemExit) as exc_info:
        commands_lint.handle_lint(lint_cli, args)

    assert exc_info.value.code == 0
    assert calls == [
        [
            sys.executable,
            "-m",
            "pre_commit",
            "run",
            "--show-diff-on-failure",
            "--files",
            "src/holoscan_cli/__main__.py",
        ]
    ]


def test_install_lint_deps_falls_back_to_pre_commit_package(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".pre-commit-config.yaml").write_text("repos: []\n")
    lint_cli = _lint_cli(root, monkeypatch)
    calls = []

    def fake_run_command(cmd, dry_run=False, env=None):
        calls.append({"cmd": cmd, "dry_run": dry_run, "env": env})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(commands_lint.holohub_cli_util, "run_command", fake_run_command)
    monkeypatch.setattr(commands_lint, "_running_in_virtual_env", lambda: True)

    commands_lint._install_lint_deps(lint_cli, dry_run=True, env={})

    assert calls[0]["cmd"] == [sys.executable, "-m", "pip", "install", "pre-commit"]
    assert calls[0]["dry_run"] is True
    assert calls[1]["cmd"] == [sys.executable, "-m", "pre_commit", "install-hooks"]
    assert calls[1]["dry_run"] is True
