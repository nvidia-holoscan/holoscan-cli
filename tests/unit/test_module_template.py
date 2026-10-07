# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small contract checks for static files copied into generated Modules."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src/holoscan_cli"
TEMPLATE = ROOT / "templates/module"
CMAKE = ROOT / "cmake"


def _load_gitutils():
    path = TEMPLATE / "{{cookiecutter.module_repo_name}}/.github/workflows/scripts/gitutils.py"
    spec = importlib.util.spec_from_file_location("generated_gitutils", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cmake_support_keeps_export_and_pybind_contracts():
    operator = (
        TEMPLATE
        / "{{cookiecutter.module_repo_name}}/operators"
        / "{{cookiecutter.operator_slug}}/CMakeLists.txt"
    ).read_text(encoding="utf-8")
    config = (CMAKE / "Config.cmake.in").read_text(encoding="utf-8")
    pybind = (CMAKE / "pybind11_add_holohub_module.cmake").read_text(encoding="utf-8")
    deb = (CMAKE / "holohub_configure_deb.cmake").read_text(encoding="utf-8")
    initializer = (CMAKE / "pybind11/__init__.py.in").read_text(encoding="utf-8")

    assert "PUBLIC holoscan::core" in operator
    assert "target_link_libraries(holoscan_{{ cookiecutter.module_slug }} INTERFACE" in operator
    assert "find_dependency(holoscan REQUIRED)" in config
    assert "holoscan::pybind11" in pybind
    assert "${CMAKE_SUBMODULE_OUT_DIR}" in pybind
    assert "${CMAKE_BINARY_DIR}/${HOLOSCAN_INSTALL_LIB_DIR}" in pybind
    assert 'set(missingArgs "")' in deb
    compile(
        initializer.replace("@MODULE_NAME@", "example").replace("@MODULE_CLASS_NAME@", "ExampleOp"),
        "cmake/pybind11/__init__.py",
        "exec",
    )


def test_generated_gitutils_handles_untracked_files_and_safe_revisions(monkeypatch):
    gitutils = _load_gitutils()
    calls = []

    def git(*args):
        calls.append(args)
        if args[0] == "status":
            return " M tracked.py\0?? new file.py\0R  renamed.py\0old.py\0"
        if args[0] == "rev-parse":
            return f"{args[-1]}-sha"
        return "first.py\nsecond.py"

    monkeypatch.setattr(gitutils, "__git", git)

    assert gitutils.uncommitted_files() == ["tracked.py", "new file.py", "renamed.py"]
    assert gitutils.changed_files_between("base", "head") == ["first.py", "second.py"]
    assert any("--end-of-options" in call for call in calls)
    with pytest.raises(ValueError, match="Invalid Git revision"):
        gitutils.changed_files_between("--unsafe", "head")


def test_direct_cookiecutter_use_cannot_pin_an_arbitrary_cli_release():
    defaults = json.loads((TEMPLATE / "cookiecutter.json").read_text(encoding="utf-8"))
    assert defaults["_holoscan_cli_version"] == "0"


@pytest.mark.parametrize(
    "sdk_version,prefix", [("4.6.0", "/opt/nvidia/holoscan"), ("5.0.0", "/usr")]
)
def test_deb_install_prefix_follows_sdk_layout(tmp_path, sdk_version, prefix):
    cmake = shutil.which("cmake")
    if cmake is None:
        pytest.skip("CMake is required to configure the packaging helper")
    project = tmp_path / "project"
    project.mkdir()
    (project / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.24)\n"
        "project(example VERSION 1.0.0 LANGUAGES NONE)\n"
        f'set(holoscan_VERSION "{sdk_version}")\n'
        f'list(APPEND CMAKE_MODULE_PATH "{CMAKE.as_posix()}")\n'
        "include(holohub_configure_deb)\n"
        "holohub_configure_deb(NAME example DESCRIPTION Example VERSION 1.0.0 VENDOR NVIDIA\n"
        '  CONTACT "dev@example.com" DEPENDS "holoscan")\n',
        encoding="utf-8",
    )
    build = tmp_path / "build"
    result = subprocess.run(
        [cmake, "-S", str(project), "-B", str(build)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    config = (build / "pkg/CPackConfig-example.cmake").read_text(encoding="utf-8")
    assert f'set(CPACK_PACKAGING_INSTALL_PREFIX "{prefix}")' in config
