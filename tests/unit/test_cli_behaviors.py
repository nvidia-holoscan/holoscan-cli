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
from holoscan_cli.commands import run as run_cmd
from holoscan_cli.utils import holohub as holohub_utils
from holoscan_cli.utils.text import normalize_args_str

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "holohub_smoke"


def _copy_smoke_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "holohub_smoke"
    shutil.copytree(FIXTURE_ROOT, repo_root)
    return repo_root


def test_cli_dispatch_runs_smoke_app_locally_from_metadata(tmp_path, monkeypatch, capfd):
    if shutil.which("python") is None:
        pytest.skip("the smoke fixture command requires a python executable on PATH")

    original_run_command = run_cmd.run_command

    def run_without_replacement(cmd, **kwargs):
        # Keep this existing metadata smoke in-process. The real exec boundary
        # is covered by the external signal test.
        kwargs["replace_process"] = False
        return original_run_command(cmd, **kwargs)

    monkeypatch.setattr(run_cmd, "run_command", run_without_replacement)

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


@pytest.mark.parametrize(
    ("process_value", "mode_values", "expected"),
    [
        ("false", ["true", "true"], False),
        ("true", ["false", "false"], True),
        (None, ["true", "false"], False),
        (None, ["false", "true"], True),
    ],
)
def test_local_build_environment_uses_process_then_specific_mode_precedence(
    monkeypatch, process_value, mode_values, expected
):
    if process_value is None:
        monkeypatch.delenv("HOLOSCAN_CLI_BUILD_LOCAL", raising=False)
    else:
        monkeypatch.setenv("HOLOSCAN_CLI_BUILD_LOCAL", process_value)

    mode_envs = [{"HOLOSCAN_CLI_BUILD_LOCAL": value} for value in mode_values]

    assert holohub_utils.is_env_request_local_build(*mode_envs) is expected


@pytest.mark.parametrize(
    ("always_build", "docker_choice", "local_choice", "expected"),
    [
        ("false", None, None, (True, True)),
        ("false", False, None, (False, True)),
        ("true", True, None, (True, False)),
        ("true", False, False, (False, False)),
    ],
)
def test_skip_builds_uses_cli_tristate_over_environment(
    monkeypatch, always_build, docker_choice, local_choice, expected
):
    monkeypatch.setenv("HOLOSCAN_CLI_ALWAYS_BUILD", always_build)
    args = Namespace(no_docker_build=docker_choice, no_local_build=local_choice)

    assert holohub_utils.check_skip_builds(args) == expected


def test_mode_environment_is_a_default_but_self_references_compose():
    env = {"STATIC": "host", "PATH": "/host/bin"}

    holohub_utils.update_env(
        env,
        {
            "STATIC": "mode",
            "PATH": "/mode/bin:<PATH>",
            "MODE_ONLY": "enabled",
        },
        overwrite=False,
    )

    assert env == {
        "STATIC": "host",
        "PATH": "/mode/bin:/host/bin",
        "MODE_ONLY": "enabled",
    }


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
        "docker_opts": "",
        "mode_docker_opts": "--ipc=host --network=host",
        "build_args": "",
        "mode_build_args": "--build-arg MODE=dev",
        "configure_args": ["-DMODE=dev", "-DENABLE_TESTS=ON"],
        "include_default_build_args": True,
        "include_default_run_args": True,
    }
    assert run_config == {
        "run_args": "",
        "docker_opts": "",
        "mode_docker_opts": "--ipc=host --network=host",
        "include_default_run_args": True,
        "command": "python app.py",
        "workdir": ".",
    }


def test_effective_mode_config_preserves_cli_and_mode_argument_sources(capsys):
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
        "mode_docker_opts": "--ipc=host",
        "build_args": "--build-arg CLI=1",
        "mode_build_args": "--build-arg MODE=1",
        "configure_args": ["-DMODE=ON", "-DCLI=ON"],
        "include_default_build_args": True,
        "include_default_run_args": True,
    }
    assert run_config == {
        "run_args": "--frames 1",
        "docker_opts": "--cap-add SYS_PTRACE",
        "mode_docker_opts": "--ipc=host",
        "include_default_run_args": True,
        "command": "python app.py",
        "workdir": ".",
    }
    assert "overrides mode" in capsys.readouterr().err


def test_effective_mode_config_explicit_replacement_clears_lower_argument_layers():
    cli = object.__new__(project_cli.HoloscanCLI)
    args = Namespace(
        with_operators=None,
        build_args="--build-arg CLI=1",
        configure_args=None,
        docker_opts="--network=none",
        run_args=None,
        replace_build_args=True,
        replace_docker_opts=True,
    )
    mode_config = {
        "build": {"docker_build_args": ["--target", "mode"]},
        "run": {"docker_run_args": ["--privileged", "--pid=host"]},
    }

    build_config = cli.get_effective_build_config(args, mode_config)
    run_config = cli.get_effective_run_config(args, mode_config)

    assert build_config == {
        "with_operators": None,
        "docker_opts": "--network=none",
        "mode_docker_opts": "",
        "build_args": "--build-arg CLI=1",
        "mode_build_args": "",
        "configure_args": None,
        "include_default_build_args": False,
        "include_default_run_args": False,
    }
    assert run_config == {
        "run_args": "",
        "docker_opts": "--network=none",
        "mode_docker_opts": "",
        "include_default_run_args": False,
    }


def test_replace_configure_args_drops_mode_options_and_keeps_cli_values():
    cli = object.__new__(project_cli.HoloscanCLI)
    args = Namespace(
        with_operators=None,
        build_args=None,
        configure_args=["-DCLI=ON"],
        docker_opts=None,
        replace_configure_args=True,
    )

    config = cli.get_effective_build_config(
        args,
        {"build": {"cmake_options": ["-DMODE=ON"]}},
    )

    assert config["configure_args"] == ["-DCLI=ON"]


def test_no_mode_config_suppresses_only_additive_mode_vectors():
    cli = object.__new__(project_cli.HoloscanCLI)
    args = Namespace(
        with_operators=None,
        build_args=None,
        configure_args=["-DCLI=ON"],
        docker_opts=["--env CLI=1"],
        replace_docker_opts=None,
        run_args=None,
        no_mode_config=True,
    )
    mode_config = {
        "build": {
            "docker_build_args": ["--target", "mode"],
            "cmake_options": ["-DMODE=ON"],
        },
        "run": {
            "command": "python app.py",
            "workdir": ".",
            "docker_run_args": ["--network=host"],
        },
    }

    build_config = cli.get_effective_build_config(args, mode_config)
    run_config = cli.get_effective_run_config(args, mode_config)

    assert build_config["mode_build_args"] == ""
    assert build_config["mode_docker_opts"] == ""
    assert build_config["configure_args"] == ["-DCLI=ON"]
    assert run_config["mode_docker_opts"] == ""
    assert run_config["command"] == "python app.py"
    assert run_config["workdir"] == "."


def test_atomic_docker_opts_replacement_keeps_following_additions():
    cli = object.__new__(project_cli.HoloscanCLI)
    args = Namespace(
        with_operators=None,
        build_args=None,
        configure_args=None,
        docker_opts=["--read-only"],
        replace_docker_opts="--network=none",
        run_args=None,
    )

    config = cli.get_effective_run_config(
        args,
        {"run": {"docker_run_args": ["--privileged"]}},
    )

    assert config["docker_opts"] == "--network=none --read-only"
    assert config["mode_docker_opts"] == ""
    assert config["include_default_run_args"] is False


def test_argument_normalization_cannot_reshape_tokens_from_environment(monkeypatch):
    monkeypatch.setenv("TOKEN_VALUE", 'value with spaces "and quotes"')

    assert normalize_args_str("--build-arg TOKEN=$TOKEN_VALUE") == (
        "--build-arg 'TOKEN=value with spaces \"and quotes\"'"
    )


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


def test_clear_cache_dryrun_reports_would_remove_paths(tmp_path, monkeypatch, capsys):
    """`clear-cache --dryrun` previews the work it would do — the build
    directory should appear behind a `Would remove:` marker so users can
    confirm before the real run. Pre-consolidation `test_holohub_clear_cache`."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    build_parent = tmp_path / "build"
    data_dir = tmp_path / "data"
    install_dir = repo_root / "install"
    for path in (build_parent, data_dir, install_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", repo_root)
    cli = object.__new__(project_cli.HoloscanCLI)
    cli.DEFAULT_BUILD_PARENT_DIR = build_parent
    cli.DEFAULT_DATA_DIR = data_dir

    clear_cache_cmd.handle_clear_cache(
        cli, Namespace(dryrun=True, build=False, data=False, install=False)
    )

    # Nothing should be removed in dryrun.
    assert build_parent.is_dir()
    assert data_dir.is_dir()
    assert install_dir.is_dir()

    out = capsys.readouterr().out
    assert "Would remove:" in out
    assert str(build_parent) in out


def test_clear_cache_refuses_dangerous_roots(tmp_path, monkeypatch, capsys):
    """A bad cache root (e.g. ``HOLOSCAN_CLI_BUILD_PARENT_DIR=/``) must never
    let clear-cache rmtree an anchor (``/``, ``$HOME``, repo root) or an
    ancestor of one."""
    repo_root = tmp_path / "workspace" / "repo"
    repo_root.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", repo_root)
    cli = object.__new__(project_cli.HoloscanCLI)
    cli.DEFAULT_DATA_DIR = tmp_path / "data"

    for dangerous in (Path("/").resolve(), home, repo_root, repo_root.parent):
        cli.DEFAULT_BUILD_PARENT_DIR = dangerous
        with patch.object(clear_cache_cmd.shutil, "rmtree") as rmtree:
            clear_cache_cmd.handle_clear_cache(
                cli, Namespace(dryrun=False, build=True, data=False, install=False)
            )
        rmtree.assert_not_called()
        assert dangerous.is_dir()
    assert "Refusing to remove:" in capsys.readouterr().out


def test_clear_cache_survives_unresolvable_home(tmp_path, monkeypatch):
    """``Path.home()`` raising ``RuntimeError`` must not abort clear-cache."""

    def raise_home():
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", staticmethod(raise_home))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    build_parent = tmp_path / "build"
    build_parent.mkdir()

    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", repo_root)
    cli = object.__new__(project_cli.HoloscanCLI)
    cli.DEFAULT_BUILD_PARENT_DIR = build_parent
    cli.DEFAULT_DATA_DIR = tmp_path / "data"

    clear_cache_cmd.handle_clear_cache(
        cli, Namespace(dryrun=False, build=True, data=False, install=False)
    )

    assert not build_parent.exists()
    assert repo_root.is_dir()


def test_test_clear_cache_selects_build_install_only(monkeypatch):
    """`test --clear-cache` clears build/install artifacts but never data."""
    from holoscan_cli.commands import test_cmd

    captured = {}

    def fake_clear_cache(cli, args):
        captured.update(vars(args))
        raise SystemExit  # stop before the rest of handle_test runs

    monkeypatch.setattr(test_cmd, "check_skip_builds", lambda args: (True, True))
    monkeypatch.setattr("holoscan_cli.commands.clear_cache.handle_clear_cache", fake_clear_cache)
    cli = object.__new__(project_cli.HoloscanCLI)
    monkeypatch.setattr(cli, "make_project_container", lambda **kw: Namespace(dryrun=False))

    args = Namespace(project=None, language=None, clear_cache=True, dryrun=False, local=True)
    with pytest.raises(SystemExit):
        test_cmd.handle_test(cli, args)

    assert (captured["build"], captured["install"], captured["data"]) == (True, True, False)
