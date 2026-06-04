# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sys
from argparse import Namespace
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import package as package_cmd


def _cli(tmp_path, project_data=None):
    def find_project(project_name, language=None):
        if project_data is None:
            raise AssertionError(f"unexpected project lookup: {project_name}, {language}")
        return project_data

    return SimpleNamespace(
        DEFAULT_BUILD_PARENT_DIR=tmp_path / "build",
        DEFAULT_SDK_DIR="/opt/nvidia/holoscan",
        HOLOHUB_ROOT=tmp_path / "repo",
        find_project=find_project,
    )


def _args(**overrides):
    defaults = {
        "project": None,
        "local": True,
        "build_type": None,
        "pkg_generator": "DEB",
        "language": None,
        "verbose": False,
        "dryrun": True,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


@pytest.fixture
def wheel_module(tmp_path):
    source = tmp_path / "repo" / "modules" / "test-module-fixture"
    source.mkdir(parents=True)
    (source / "pyproject.toml").write_text("[build-system]\nrequires=[]\n", encoding="utf-8")
    project_data = {
        "project_name": "test-module-fixture",
        "project_type": "module",
        "source_folder": source,
        "metadata": {"language": ["Python"]},
    }
    cli = _cli(tmp_path, project_data)
    cli.HOLOHUB_ROOT.mkdir(exist_ok=True)
    return cli


def test_package_deb_emits_module_cmake_flag_for_in_tree_module(tmp_path, monkeypatch):
    project_data = {
        "project_name": "test-module-fixture",
        "project_type": "module",
        "source_folder": tmp_path / "repo" / "modules" / "test-module-fixture",
        "metadata": {"language": ["C++", "Python"]},
    }
    cli = _cli(tmp_path, project_data)
    calls = []
    monkeypatch.setattr(package_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(package_cmd.shutil, "which", lambda _: None)

    package_cmd.handle_package(cli, _args(project="test-module-fixture", pkg_generator="DEB"))

    cmake_args = " ".join(str(a) for a in calls[0])
    # In-tree packaging needs BOTH MODULE_ (enter the module subdir) and PKG_
    # (activate the add_holohub_package cascade). See holohub#1582.
    assert "-DMODULE_test_module_fixture=ON" in cmake_args
    assert "-DPKG_test_module_fixture=ON" in cmake_args
    assert "-DBUILD_ALL=OFF" in cmake_args
    assert calls[2][0] == "cpack"


def test_package_deb_emits_pkg_flag_for_standalone_module(tmp_path, monkeypatch):
    module_dir = tmp_path / "standalone"
    module_dir.mkdir()
    (module_dir / "metadata.json").write_text(
        json.dumps({"module": {"name": "holoscan-smoke"}}),
        encoding="utf-8",
    )
    cli = _cli(tmp_path)
    cli.HOLOHUB_ROOT = module_dir
    calls = []
    monkeypatch.chdir(module_dir)
    monkeypatch.setattr(package_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(package_cmd.shutil, "which", lambda _: None)

    package_cmd.handle_package(cli, _args(pkg_generator="DEB"))

    cmake_args = " ".join(str(a) for a in calls[0])
    # Both flags are emitted unconditionally (holohub#1582); for a standalone
    # module repo MODULE_ is a harmless unused cache entry.
    assert "-DPKG_holoscan_smoke=ON" in cmake_args
    assert "-DMODULE_holoscan_smoke=ON" in cmake_args


def test_package_container_honors_no_docker_build_and_cuda(tmp_path, monkeypatch):
    """Container packaging skips the build for --no-docker-build and forwards
    --cuda to the container build args (holohub#1596, #1597)."""
    from unittest.mock import MagicMock

    import holoscan_cli.cli as cli_mod

    monkeypatch.delenv("HOLOSCAN_CLI_BUILD_LOCAL", raising=False)
    monkeypatch.setenv("HOLOSCAN_CLI_ALWAYS_BUILD", "1")

    project_data = {
        "project_name": "test-module-fixture",
        "project_type": "module",
        "source_folder": tmp_path / "repo" / "modules" / "test-module-fixture",
        "metadata": {"language": ["Python"]},
    }
    cli = _cli(tmp_path, project_data)
    monkeypatch.setattr(package_cmd, "get_entrypoint_command_args", lambda *a, **k: ("", []))
    monkeypatch.setattr(cli_mod, "in_container_cli_command", lambda: "holoscan")

    # --no-docker-build -> the container build is skipped, but --cuda is still
    # applied to the container so the in-container package build uses it.
    skip_container = MagicMock()
    skip_container.image_name = "img:tag"
    cli.make_project_container = lambda project_name, language=None: skip_container
    package_cmd.handle_package(
        cli,
        _args(project="test-module-fixture", local=False, no_docker_build=True, cuda="13"),
    )
    skip_container.build.assert_not_called()
    assert skip_container.cuda_version == "13"

    # Default (build runs) -> --cuda is forwarded to container.build().
    build_container = MagicMock()
    build_container.image_name = "img:tag"
    cli.make_project_container = lambda project_name, language=None: build_container
    package_cmd.handle_package(cli, _args(project="test-module-fixture", local=False, cuda="13"))
    build_container.build.assert_called_once()
    assert build_container.build.call_args.kwargs.get("cuda_version") == "13"


def test_package_wheel_invokes_python_build(wheel_module, monkeypatch):
    calls = []
    monkeypatch.setattr(package_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))

    package_cmd.handle_package(
        wheel_module, _args(project="test-module-fixture", pkg_generator="WHEEL")
    )

    assert len(calls) == 1
    wheel_args = [str(a) for a in calls[0]]
    assert wheel_args[:3] == [sys.executable, "-m", "build"]
    assert "--wheel" in wheel_args
    assert "--outdir" in wheel_args


def test_package_wheel_requires_python_build_for_real_run(wheel_module, monkeypatch, capsys):
    monkeypatch.setattr(package_cmd.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(
        package_cmd,
        "run_command",
        lambda *args, **kwargs: pytest.fail("build should fail before invoking python -m build"),
    )

    with pytest.raises(SystemExit) as excinfo:
        package_cmd.handle_package(
            wheel_module,
            _args(project="test-module-fixture", pkg_generator="WHEEL", dryrun=False),
        )

    assert excinfo.value.code == 1
    assert "Python package 'build' is not installed" in capsys.readouterr().err


def test_package_rejects_non_module_project(tmp_path):
    cli = _cli(
        tmp_path,
        {
            "project_name": "gst_to_holo",
            "project_type": "application",
            "source_folder": tmp_path / "repo" / "applications" / "gst_to_holo",
            "metadata": {"language": "cpp"},
        },
    )
    with pytest.raises(SystemExit):
        package_cmd.handle_package(cli, _args(project="gst_to_holo"))


def test_resolve_module_project_prefers_standalone_cwd_metadata(tmp_path, monkeypatch):
    module_dir = tmp_path / "external-module"
    module_dir.mkdir()
    (module_dir / "metadata.json").write_text(
        json.dumps({"module": {"name": "holoscan-smoke", "language": ["Python"]}}),
        encoding="utf-8",
    )
    cli = _cli(tmp_path)
    monkeypatch.chdir(module_dir)

    project_data = package_cmd._resolve_module_project(
        cli, project_arg="different-name", language=None
    )

    assert project_data == {
        "project_type": "module",
        "project_name": "holoscan-smoke",
        "source_folder": str(module_dir),
        "metadata": {"name": "holoscan-smoke", "language": ["Python"]},
    }


def test_resolve_module_project_falls_back_to_source_tree_when_cwd_metadata_invalid(
    tmp_path, monkeypatch
):
    module_dir = tmp_path / "broken-cwd"
    module_dir.mkdir()
    (module_dir / "metadata.json").write_text("{not json", encoding="utf-8")
    in_tree_module = {
        "project_name": "test-module-fixture",
        "project_type": "module",
        "source_folder": tmp_path / "repo" / "modules" / "test-module-fixture",
        "metadata": {"language": ["Python"]},
    }
    cli = _cli(tmp_path, in_tree_module)
    monkeypatch.chdir(module_dir)

    project_data = package_cmd._resolve_module_project(
        cli, project_arg="test-module-fixture", language="python"
    )

    assert project_data["project_name"] == "test-module-fixture"
