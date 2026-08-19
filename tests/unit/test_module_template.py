# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rendering coverage for the standalone Module Cookiecutter template."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cookiecutter.exceptions import FailedHookException
from cookiecutter.main import cookiecutter

from holoscan_cli.commands.create import copy_cmake_support

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


TEMPLATE = Path(__file__).resolve().parents[2] / "src" / "holoscan_cli" / "templates" / "module"
CMAKE_SUPPORT = TEMPLATE.parents[1] / "cmake"
CMAKE_SUPPORT_FILES = (
    "Config.cmake.in",
    "HoloHubConfigHelpers.cmake",
    "holohub_configure_deb.cmake",
    "pybind11_add_holohub_module.cmake",
    "pybind11/__init__.py",
    "pydoc/macros.hpp",
)


def _render(tmp_path: Path, **context: object) -> Path:
    config_file = tmp_path / "cookiecutter-config.json"
    config_file.write_text(
        json.dumps(
            {
                "cookiecutters_dir": str(tmp_path / ".cookiecutters"),
                "replay_dir": str(tmp_path / ".cookiecutter-replay"),
            }
        ),
        encoding="utf-8",
    )
    values: dict[str, object] = {
        "project_name": "My Sensor",
        "language": "python",
        "holoscan_version": "5.0.0",
        "_holoscan_cli_version": "5.0.0a10",
    }
    values.update(context)
    project = Path(
        cookiecutter(
            str(TEMPLATE),
            no_input=True,
            output_dir=str(tmp_path),
            extra_context=values,
            config_file=str(config_file),
        )
    )
    copy_cmake_support(project)
    return project


@pytest.mark.parametrize("language", ["cpp", "python"])
def test_template_renders_a_self_contained_module(tmp_path: Path, language: str):
    project = _render(tmp_path, language=language)

    assert project.name == "holoscan-my-sensor"
    assert not (project / "holohub").exists()
    requirement_lines = [
        line
        for line in (project / "requirements-cli.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert requirement_lines == ["holoscan-cli==5.0.0a10"]
    for relative in (
        ".dockerignore",
        ".github/workflows/scripts/check_copyright.py",
        ".github/workflows/scripts/gitutils.py",
    ):
        assert (project / relative).is_file(), relative
    for relative in CMAKE_SUPPORT_FILES:
        generated = project / "cmake" / relative
        assert generated.read_bytes() == (CMAKE_SUPPORT / relative).read_bytes()

    metadata = json.loads((project / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["module"]["operator_names"] == ["MySensorOp"]

    pyproject = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert "holoscan" not in pyproject["tool"]
    assert pyproject["dependency-groups"]["dev"] == [
        "holoscan-cli==5.0.0a10",
        "pytest>=8.2",
    ]

    operator = project / "operators" / "my_sensor_op"
    if language == "cpp":
        assert (operator / "my_sensor_op.cpp").is_file()
        assert not (operator / "my_sensor_op.py").exists()
    else:
        assert (operator / "my_sensor_op.py").is_file()
        assert not (operator / "my_sensor_op.cpp").exists()


@pytest.mark.parametrize(
    "context",
    [
        {"language": "rust"},
        {"project_name": "My/Sensor"},
        {"module_slug": "bad-slug"},
        {"module_slug": "class"},
        {"module_repo_name": "sensor"},
        {"operator_slug": "bad-op"},
        {"_license": "MIT"},
    ],
)
def test_template_rejects_invalid_context(tmp_path: Path, context: dict[str, object]):
    with pytest.raises(FailedHookException):
        _render(tmp_path, **context)


def test_cpp_export_declares_its_public_holoscan_dependency(tmp_path: Path):
    project = _render(tmp_path, language="cpp")

    operator_cmake = (project / "operators/my_sensor_op/CMakeLists.txt").read_text(encoding="utf-8")
    package_config = (project / "cmake/Config.cmake.in").read_text(encoding="utf-8")
    assert "target_link_libraries(my_sensor_op PUBLIC holoscan::core)" in operator_cmake
    assert "find_dependency(holoscan REQUIRED COMPONENTS core)" in package_config
