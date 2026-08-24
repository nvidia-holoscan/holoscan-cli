# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small contract checks for static files copied into generated Modules."""

import importlib.util
import json
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
    assert "find_dependency(holoscan REQUIRED COMPONENTS core)" in config
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
