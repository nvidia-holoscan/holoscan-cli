# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import shlex
from argparse import Namespace
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import install as install_cmd


def _dev_args(**overrides):
    defaults = {
        "dev": True,
        "uninstall": False,
        "project": None,
        "build_dir": None,
        "site_dir": None,
        "dryrun": False,
        "local": False,
        "verbose": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def _standalone_cli(tmp_path):
    root = tmp_path / "holoscan-smoke"
    root.mkdir()
    (root / "metadata.json").write_text(
        json.dumps({"module": {"name": "holoscan-smoke"}}), encoding="utf-8"
    )
    return SimpleNamespace(
        HOLOHUB_ROOT=root,
        DEFAULT_BUILD_PARENT_DIR=root / "build",
        script_name="holoscan",
    )


def test_install_dev_copies_staged_hook_pair(tmp_path):
    build_dir = tmp_path / "build" / "smoke"
    site_dir = tmp_path / "site"
    build_dir.mkdir(parents=True)
    (build_dir / "holoscan_smoke_dev.py").write_text(
        '_BUILD_PATH = r"/workspace/smoke/build/python/lib/holoscan"\n', encoding="utf-8"
    )
    (build_dir / "holoscan-smoke-dev.pth").write_text(
        "import holoscan_smoke_dev\n", encoding="utf-8"
    )
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")

    install_cmd.handle_install(cli, _dev_args(project="holoscan-smoke", site_dir=site_dir))

    assert (site_dir / "holoscan_smoke_dev.py").read_text(
        encoding="utf-8"
    ) == f"_BUILD_PATH = {str(build_dir / 'python/lib/holoscan')!r}\n"
    assert (site_dir / "holoscan-smoke-dev.pth").exists()


def test_install_dev_uses_most_recent_hook_per_slug(tmp_path):
    old_dir = tmp_path / "build" / "old"
    new_dir = tmp_path / "build" / "new"
    site_dir = tmp_path / "site"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "holoscan_smoke_dev.py").write_text("# old\n", encoding="utf-8")
    (old_dir / "holoscan-smoke-dev.pth").write_text("import holoscan_smoke_dev\n", encoding="utf-8")
    (new_dir / "holoscan_smoke_dev.py").write_text("# new\n", encoding="utf-8")
    (new_dir / "holoscan-smoke-dev.pth").write_text("import holoscan_smoke_dev\n", encoding="utf-8")
    os.utime(old_dir / "holoscan_smoke_dev.py", (1, 1))
    os.utime(new_dir / "holoscan_smoke_dev.py", (2, 2))
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")

    install_cmd.handle_install(cli, _dev_args(project="smoke", site_dir=site_dir))

    assert (site_dir / "holoscan_smoke_dev.py").read_text(encoding="utf-8") == "# new\n"


def test_install_dev_uninstall_removes_hook_pair(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "holoscan-smoke-dev.pth").write_text(
        "import holoscan_smoke_dev\n", encoding="utf-8"
    )
    (site_dir / "holoscan_smoke_dev.py").write_text("# helper\n", encoding="utf-8")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")

    install_cmd.handle_install(
        cli, _dev_args(project="holoscan-smoke", site_dir=site_dir, uninstall=True)
    )

    assert not (site_dir / "holoscan-smoke-dev.pth").exists()
    assert not (site_dir / "holoscan_smoke_dev.py").exists()


def test_install_dev_builds_fresh_standalone_module_locally(tmp_path, monkeypatch):
    cli = _standalone_cli(tmp_path)
    site_dir = tmp_path / "site"
    calls = []

    def stage_hook(_cli, *, project_name, **kwargs):
        calls.append((project_name, kwargs["dryrun"]))
        build_dir = cli.DEFAULT_BUILD_PARENT_DIR / project_name
        build_dir.mkdir(parents=True)
        python_root = build_dir / "python/lib/holoscan"
        python_root.mkdir(parents=True)
        (build_dir / "holoscan_smoke_dev.py").write_text(
            f'_BUILD_PATH = r"{python_root}"\n', encoding="utf-8"
        )
        (build_dir / "holoscan-smoke-dev.pth").write_text(
            "import holoscan_smoke_dev\n", encoding="utf-8"
        )
        return build_dir, {}

    monkeypatch.setattr(install_cmd, "build_project_locally", stage_hook)
    args = _dev_args(local=True, site_dir=site_dir)
    install_cmd.handle_install(cli, args)
    install_cmd.handle_install(cli, args)

    assert calls == [("holoscan-smoke", False)]
    assert (site_dir / "holoscan-smoke-dev.pth").exists()


def test_install_dev_fresh_module_dryrun_leaves_no_hook(tmp_path, monkeypatch, capsys):
    cli = _standalone_cli(tmp_path)
    site_dir = tmp_path / "site"
    calls = []

    def preview_build(_cli, *, project_name, dryrun, **_kwargs):
        calls.append((project_name, dryrun))
        return cli.DEFAULT_BUILD_PARENT_DIR / project_name, {}

    monkeypatch.setattr(install_cmd, "build_project_locally", preview_build)
    install_cmd.handle_install(cli, _dev_args(local=True, site_dir=site_dir, dryrun=True))

    assert calls == [("holoscan-smoke", True)]
    assert "Would build 'holoscan-smoke'" in capsys.readouterr().out
    assert not cli.DEFAULT_BUILD_PARENT_DIR.exists()
    assert not site_dir.exists()


def test_install_dev_routes_standalone_module_to_container(tmp_path, monkeypatch):
    cli = _standalone_cli(tmp_path)
    operations = []
    container = SimpleNamespace(
        WORKSPACE_NAME="smoke",
        image_name="smoke:dev",
        resolve_run_image=lambda img: img or "smoke:dev",
        compose_run_args=lambda **kwargs: kwargs.get("docker_opts") or "",
        build=lambda **kwargs: operations.append(("build", kwargs)),
        run=lambda **kwargs: operations.append(("run", kwargs)),
    )
    cli.make_project_container = lambda **kwargs: container
    monkeypatch.delenv("HOLOSCAN_CLI_BUILD_LOCAL", raising=False)
    monkeypatch.setattr(
        install_cmd,
        "get_entrypoint_command_args",
        lambda _img, command, _opts, **_kwargs: ("", ["/bin/bash", "-c", command]),
    )
    install_cmd.handle_install(
        cli,
        _dev_args(
            build_dir=cli.HOLOHUB_ROOT / "build/smoke",
            build_type="debug",
            configure_args=["-DDEBUG_MODE=ON"],
        ),
    )

    assert [name for name, _ in operations] == ["build", "run"]
    command = shlex.split(operations[1][1]["extra_args"][-1])
    assert command[:4] == ["holoscan", "install", "--dev", "--local"]
    assert command[command.index("--build-dir") + 1] == "/workspace/smoke/build/smoke"
    assert command[command.index("--build-type") + 1] == "Debug"
    assert "--configure-args=-DDEBUG_MODE=ON" in command

    operations.clear()
    install_cmd.handle_install(cli, _dev_args(uninstall=True, no_docker_build=True))
    assert [name for name, _ in operations] == ["run"]
    assert "install --dev --local --uninstall" in operations[0][1]["extra_args"][-1]

    with pytest.raises(SystemExit):
        install_cmd.handle_install(cli, _dev_args(build_dir=tmp_path / "outside"))
    assert operations[-1][0] == "run"


def test_install_requires_project_without_dev(tmp_path):
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")
    with pytest.raises(SystemExit):
        install_cmd.handle_install(cli, Namespace(dev=False, project=None))


def test_install_help_advertises_dev_uninstall_build_dir_flags():
    """`install --help` must advertise the dev-hook flags together
    (pre-consolidation `test_holohub_install_dev_help_advertises_flags`).
    Catches accidental removal of any of `--dev`, `--uninstall`,
    `--build-dir` from the install command's argparse."""
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    # The install subcommand inherits flags from the container_build/run
    # parent parsers; pass empty stubs so the formatter sees the
    # install-specific flags in isolation.
    container_build = argparse.ArgumentParser(add_help=False)
    container_run = argparse.ArgumentParser(add_help=False)
    install_cmd.register_install_parser(
        SimpleNamespace(),
        subparsers,
        container_build=container_build,
        container_run=container_run,
    )

    install_help = subparsers.choices["install"].format_help()

    assert "--dev" in install_help
    assert "--uninstall" in install_help
    assert "--build-dir" in install_help
