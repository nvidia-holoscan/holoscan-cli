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
    assert "-DMODULE_test_module_fixture=ON" in cmake_args
    assert "-DBUILD_ALL=OFF" in cmake_args
    assert "-DPKG_" not in cmake_args
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
    assert "-DPKG_holoscan_smoke=ON" in cmake_args
    assert "-DMODULE_" not in cmake_args


def test_package_wheel_invokes_python_build(tmp_path, monkeypatch):
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
    calls = []
    monkeypatch.setattr(package_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))

    package_cmd.handle_package(cli, _args(project="test-module-fixture", pkg_generator="WHEEL"))

    assert len(calls) == 1
    wheel_args = [str(a) for a in calls[0]]
    assert wheel_args[:3] == [sys.executable, "-m", "build"]
    assert "--wheel" in wheel_args
    assert "--outdir" in wheel_args


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
