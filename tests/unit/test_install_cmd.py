# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from argparse import Namespace
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


def _sdk5_module_build(build_dir, slug="smoke"):
    """Lay out python/lib as an SDK 5 Module build with Python bindings writes it."""
    python_lib = build_dir / "python" / "lib"
    package = python_lib / f"holoscan_{slug}"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / f"_{slug}{EXTENSION_SUFFIXES[0]}").touch()
    dist_info = python_lib / f"holoscan_{slug}_cu13.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: holoscan-{slug}-cu13\nVersion: 0.1.0\n", encoding="utf-8"
    )
    (dist_info / "entry_points.txt").write_text(
        f"[holoscan.modules]\n{slug} = holoscan_{slug}\n", encoding="utf-8"
    )
    return python_lib


def test_install_dev_invalid_fifo_metadata_exits_without_hanging(tmp_path):
    root = tmp_path / "module"
    root.mkdir()
    os.mkfifo(root / "metadata.json")
    env = {key: value for key, value in os.environ.items() if not key.startswith("HOLOSCAN_CLI_")}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            "--project-root",
            str(root),
            "install",
            "--dev",
            "--local",
            "--uninstall",
            "--dryrun",
            "--site-dir",
            str(tmp_path / "site"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


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


def test_install_dev_links_sdk5_module_build_tree(tmp_path):
    python_lib = _sdk5_module_build(tmp_path / "build" / "holoscan-smoke")
    site_dir = tmp_path / "site"
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")

    install_cmd.handle_install(cli, _dev_args(project="holoscan-smoke", site_dir=site_dir))

    assert (site_dir / "holoscan-smoke-dev.pth").read_text(encoding="utf-8") == (
        f"{python_lib.resolve()}\n"
    )
    assert not (site_dir / "holoscan_smoke_dev.py").exists()
    # A fresh interpreter that processes the site directory finds the package and the
    # holoscan.modules entry point through which the SDK exposes holoscan.smoke.
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import importlib.metadata, site, sys; site.addsitedir(sys.argv[1]); "
            "import holoscan_smoke; print(holoscan_smoke.__file__); "
            "print([e.value for e in importlib.metadata.entry_points("
            "group='holoscan.modules', name='smoke')])",
            str(site_dir),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    module_file, entry_points = probe.stdout.splitlines()
    assert Path(module_file).is_relative_to(python_lib.resolve())
    assert entry_points == "['holoscan_smoke']"

    install_cmd.handle_install(
        cli, _dev_args(project="holoscan-smoke", site_dir=site_dir, uninstall=True)
    )
    assert not (site_dir / "holoscan-smoke-dev.pth").exists()


def test_install_dev_builds_fresh_sdk5_module_locally(tmp_path, monkeypatch):
    cli = _standalone_cli(tmp_path)
    site_dir = tmp_path / "site"
    calls = []

    def build_module(_cli, *, project_name, **kwargs):
        calls.append(project_name)
        build_dir = cli.DEFAULT_BUILD_PARENT_DIR / project_name
        _sdk5_module_build(build_dir)
        return build_dir, {}

    monkeypatch.setattr(install_cmd, "build_project_locally", build_module)
    args = _dev_args(local=True, site_dir=site_dir)
    install_cmd.handle_install(cli, args)
    install_cmd.handle_install(cli, args)

    assert calls == ["holoscan-smoke"]
    assert (site_dir / "holoscan-smoke-dev.pth").read_text(encoding="utf-8") == (
        f"{(cli.DEFAULT_BUILD_PARENT_DIR / 'holoscan-smoke/python/lib').resolve()}\n"
    )


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


def _metadata_build(build_dir, slug="smoke", *, built=True):
    python_root = build_dir / "python/lib"
    info = python_root / f"holoscan_{slug}_cu13.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: holoscan-{slug.replace('_', '-')}-cu13\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (info / "entry_points.txt").write_text(
        f"[holoscan.modules]\n{slug} = holoscan_{slug}\n", encoding="utf-8"
    )
    package = python_root / f"holoscan_{slug}"
    package.mkdir()
    (package / "__init__.py").write_text(
        "raise AssertionError('discovery must not import provider code')\n", encoding="utf-8"
    )
    if built:
        (package / f"_{slug}.abi3.so").touch()
    return python_root


def test_install_dev_registers_metadata_without_importing_or_copying_it(tmp_path):
    build = tmp_path / "build with spaces and ü"
    python_root = _metadata_build(build, "my_mod")
    site = tmp_path / "site"
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path, script_name="holoscan")
    args = _dev_args(project="holoscan-my-mod", build_dir=build, site_dir=site)

    install_cmd.handle_install(cli, args)
    install_cmd.handle_install(cli, args)

    assert (site / "holoscan-my-mod-dev.pth").read_text() == f"{python_root.resolve()}\n"
    assert sorted(p.name for p in site.iterdir()) == ["holoscan-my-mod-dev.pth"]
    assert (python_root / "holoscan_my_mod_cu13.dist-info/METADATA").exists()


def test_install_dev_prefers_metadata_and_migrates_legacy_registration(tmp_path):
    build = tmp_path / "build"
    python_root = _metadata_build(build)
    for directory in (build, tmp_path / "site"):
        directory.mkdir(exist_ok=True)
        (directory / "holoscan-smoke-dev.pth").write_text("import holoscan_smoke_dev\n")
        (directory / "holoscan_smoke_dev.py").write_text("# old namespace helper\n")
    site = tmp_path / "site"
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path, script_name="holoscan")

    install_cmd.handle_install(cli, _dev_args(project="smoke", build_dir=build, site_dir=site))

    assert (site / "holoscan-smoke-dev.pth").read_text() == f"{python_root.resolve()}\n"
    assert not (site / "holoscan_smoke_dev.py").exists()
    assert (build / "holoscan_smoke_dev.py").exists()


def test_install_dev_metadata_selection_and_explicit_override(tmp_path):
    builds = tmp_path / "builds"
    old, new = builds / "old", builds / "new"
    old_root, new_root = _metadata_build(old), _metadata_build(new)
    for root, timestamp in ((old_root, 1), (new_root, 2)):
        os.utime(root / "holoscan_smoke_cu13.dist-info/entry_points.txt", (timestamp, timestamp))
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=builds, script_name="holoscan")
    site = tmp_path / "site"

    install_cmd.handle_install(cli, _dev_args(project="smoke", site_dir=site))
    assert (site / "holoscan-smoke-dev.pth").read_text() == f"{new_root.resolve()}\n"
    install_cmd.handle_install(cli, _dev_args(project="smoke", build_dir=old, site_dir=site))
    assert (site / "holoscan-smoke-dev.pth").read_text() == f"{old_root.resolve()}\n"


@pytest.mark.parametrize("problem", ["malformed", "shared-providers"])
@pytest.mark.parametrize("project", [None, "smoke"])
@pytest.mark.parametrize("dryrun", [False, True])
def test_install_dev_skips_invalid_sibling_metadata(tmp_path, capsys, problem, project, dryrun):
    builds = tmp_path / "builds"
    good_root = _metadata_build(builds / "good")
    bad_root = _metadata_build(builds / "bad", "other")
    if problem == "malformed":
        (bad_root / "holoscan_other_cu13.dist-info/entry_points.txt").write_text("invalid INI\n")
    else:
        _metadata_build(builds / "bad", "another")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=builds, script_name="holoscan")
    site = tmp_path / "site"

    install_cmd.handle_install(cli, _dev_args(project=project, site_dir=site, dryrun=dryrun))

    output = capsys.readouterr()
    assert "Invalid Python development metadata" in output.err
    assert str(bad_root.resolve()) in output.err
    assert "skipping" in output.err
    if dryrun:
        assert f"Would register {good_root.resolve()}" in output.out
        assert not site.exists()
    else:
        assert (site / "holoscan-smoke-dev.pth").read_text() == f"{good_root.resolve()}\n"
        assert len(list(site.iterdir())) == 1


@pytest.mark.parametrize("umask,expected_mode", [(0o022, 0o644), (0o027, 0o640), (0o077, 0o600)])
def test_install_dev_registration_respects_umask(tmp_path, umask, expected_mode):
    build = tmp_path / "build"
    python_root = _metadata_build(build)
    site = tmp_path / "site"
    site.mkdir()
    # Isolate the process-wide umask and verify it is unchanged by registration.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); "
            "from holoscan_cli.commands.install import _DevSource, _install_metadata_dev_source; "
            "mask = int(sys.argv[4]); os.umask(mask); "
            "source = _DevSource('smoke', Path(sys.argv[2]), 0, Path(sys.argv[2])); "
            "_install_metadata_dev_source(source, Path(sys.argv[3]), dryrun=False); "
            "assert os.umask(mask) == mask",
            str(Path(install_cmd.__file__).resolve().parents[2]),
            str(python_root),
            str(site),
            str(umask),
        ],
        check=True,
    )

    pth = site / "holoscan-smoke-dev.pth"
    assert pth.stat().st_mode & 0o777 == expected_mode
    assert pth.read_text() == f"{python_root}\n"
    assert len(list(site.iterdir())) == 1


def test_install_dev_metadata_build_on_demand_uses_returned_directory(tmp_path, monkeypatch):
    cli = _standalone_cli(tmp_path)
    returned_build = tmp_path / "custom-build"
    calls = []

    def build(_cli, **kwargs):
        calls.append(kwargs)
        _metadata_build(returned_build)
        return returned_build, {}

    monkeypatch.setattr(install_cmd, "build_project_locally", build)
    site = tmp_path / "site"
    install_cmd.handle_install(
        cli,
        _dev_args(local=True, site_dir=site, language="python", configure_args=["-DFOO=ON"]),
    )

    assert len(calls) == 1
    assert calls[0]["language"] == "python"
    assert calls[0]["configure_args"] == ["-DFOO=ON"]
    assert (site / "holoscan-smoke-dev.pth").read_text() == (
        f"{returned_build.resolve()}/python/lib\n"
    )


def test_install_dev_metadata_preview_does_not_change_registration(tmp_path):
    build = tmp_path / "build"
    _metadata_build(build)
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path, script_name="holoscan")
    site = tmp_path / "site"
    args = _dev_args(project="smoke", build_dir=build, site_dir=site, dryrun=True)

    install_cmd.handle_install(cli, args)
    assert not site.exists()
    site.mkdir()
    (site / "holoscan-smoke-dev.pth").write_text("old registration\n")
    (site / "holoscan_smoke_dev.py").write_text("# keep during preview\n")
    install_cmd.handle_install(cli, args)
    assert (site / "holoscan-smoke-dev.pth").read_text() == "old registration\n"
    assert (site / "holoscan_smoke_dev.py").exists()


@pytest.mark.parametrize("layout", ["package", "module"])
def test_install_dev_rejects_installed_package_before_replacing_hook(tmp_path, layout):
    build = tmp_path / "build"
    _metadata_build(build)
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    if layout == "package":
        package = site_dir / "holoscan_smoke"
        package.mkdir()
        (package / "__init__.py").write_text("raise AssertionError('must not import')\n")
    else:
        (site_dir / "holoscan_smoke.py").write_text("raise AssertionError('must not import')\n")
    pth = site_dir / "holoscan-smoke-dev.pth"
    helper = site_dir / "holoscan_smoke_dev.py"
    pth.write_text("import holoscan_smoke_dev\n")
    helper.write_text("# original helper\n")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path, script_name="holoscan")
    for dryrun in (True, False):
        with pytest.raises(SystemExit):
            install_cmd.handle_install(
                cli, _dev_args(project="smoke", build_dir=build, site_dir=site_dir, dryrun=dryrun)
            )
        assert pth.read_text() == "import holoscan_smoke_dev\n"
        assert helper.read_text() == "# original helper\n"
        assert not list(site_dir.glob(".holoscan-*-dev.pth.*"))


def test_install_dev_metadata_failed_replace_preserves_old_registration(tmp_path):
    build = tmp_path / "build"
    _metadata_build(build)
    site = tmp_path / "site"
    site.mkdir()
    (site / "holoscan-smoke-dev.pth").write_text("import holoscan_smoke_dev\n")
    (site / "holoscan_smoke_dev.py").write_text("# old helper\n")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path, script_name="holoscan")

    with patch.object(install_cmd.os, "replace", side_effect=OSError("write denied")):
        with pytest.raises(SystemExit):
            install_cmd.handle_install(
                cli, _dev_args(project="smoke", build_dir=build, site_dir=site)
            )

    assert (site / "holoscan-smoke-dev.pth").read_text() == "import holoscan_smoke_dev\n"
    assert (site / "holoscan_smoke_dev.py").read_text() == "# old helper\n"
    assert len(list(site.iterdir())) == 2


@pytest.mark.parametrize("problem", ["target", "malformed", "duplicate", "missing-version"])
def test_install_dev_rejects_invalid_metadata_before_writing(tmp_path, problem):
    build = tmp_path / "build"
    root = _metadata_build(build)
    info = root / "holoscan_smoke_cu13.dist-info"
    if problem == "target":
        (info / "entry_points.txt").write_text("[holoscan.modules]\nsmoke = wrong_package\n")
    elif problem == "malformed":
        (info / "entry_points.txt").write_text("not an INI file\n")
    elif problem == "duplicate":
        other = root / "other.dist-info"
        other.mkdir()
        (other / "entry_points.txt").write_text((info / "entry_points.txt").read_text())
        (other / "METADATA").write_text((info / "METADATA").read_text())
    else:
        (info / "METADATA").write_text("Name: holoscan-smoke-cu13\n")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path, script_name="holoscan")
    site = tmp_path / "site"

    with pytest.raises(SystemExit):
        install_cmd.handle_install(cli, _dev_args(project="smoke", build_dir=build, site_dir=site))
    assert not site.exists()


def test_install_dev_rejects_shared_provider_roots(tmp_path):
    build = tmp_path / "build"
    _metadata_build(build, "one")
    _metadata_build(build, "two")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path, script_name="holoscan")
    with pytest.raises(SystemExit):
        install_cmd.handle_install(
            cli, _dev_args(project="one", build_dir=build, site_dir=tmp_path / "site")
        )
    assert not (tmp_path / "site").exists()


def test_install_dev_incomplete_build_does_not_fall_back_to_legacy(tmp_path, capsys):
    build = tmp_path / "build"
    _metadata_build(build, built=False)
    (build / "holoscan-smoke-dev.pth").write_text("import holoscan_smoke_dev\n")
    (build / "holoscan_smoke_dev.py").write_text("# stale helper\n")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path, script_name="holoscan")
    with pytest.raises(SystemExit):
        install_cmd.handle_install(
            cli, _dev_args(project="smoke", build_dir=build, site_dir=tmp_path / "site")
        )
    assert "Enable and build Python bindings" in capsys.readouterr().err
    assert not (tmp_path / "site").exists()


def test_install_dev_pth_startup_replacement_and_independent_uninstall(tmp_path):
    environment = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(environment)], check=True)
    python = environment / "bin/python"
    site = Path(
        subprocess.check_output(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
        ).strip()
    )
    builds = tmp_path / "builds"
    roots = {}
    for name in ("one", "two"):
        roots[name] = _metadata_build(builds / name, name)
        (roots[name] / f"holoscan_{name}/__init__.py").write_text(f"VALUE = {name!r}\n")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=builds, script_name="holoscan")
    install_cmd.handle_install(cli, _dev_args(site_dir=site))
    child_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    child_env["PYTHONNOUSERSITE"] = "1"
    check = (
        "import importlib.metadata as m; import holoscan_one, holoscan_two; "
        "assert holoscan_one.VALUE == 'one'; assert holoscan_two.VALUE == 'two'; "
        "assert len(m.entry_points(group='holoscan.modules', name='one')) == 1"
    )
    subprocess.run([str(python), "-c", check], cwd=tmp_path, env=child_env, check=True)

    replacement = builds / "replacement"
    replacement_root = _metadata_build(replacement, "one")
    (replacement_root / "holoscan_one/__init__.py").write_text("VALUE = 'replacement'\n")
    install_cmd.handle_install(cli, _dev_args(project="one", build_dir=replacement, site_dir=site))
    subprocess.run(
        [str(python), "-c", check.replace("== 'one'", "== 'replacement'")],
        cwd=tmp_path,
        env=child_env,
        check=True,
    )
    replacement.rename(builds / "disappeared")
    install_cmd.handle_install(cli, _dev_args(project="one", site_dir=site, uninstall=True))
    subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.util as u, importlib.metadata as m; import holoscan_two; "
            "assert holoscan_two.VALUE == 'two'; assert u.find_spec('holoscan_one') is None; "
            "assert not m.entry_points(group='holoscan.modules', name='one')",
        ],
        cwd=tmp_path,
        env=child_env,
        check=True,
    )
    assert roots["one"].exists()
    assert (builds / "disappeared/python/lib/holoscan_one").exists()
