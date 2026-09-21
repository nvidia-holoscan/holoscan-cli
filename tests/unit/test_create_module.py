# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused coverage for standalone Module creation."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import create


def _args(**overrides) -> argparse.Namespace:
    values = {
        "project": "My Mod",
        "template": None,
        "language": "cpp",
        "dryrun": True,
        "directory": None,
        "context": None,
        "interactive": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture()
def cli(tmp_path):
    return SimpleNamespace(HOLOHUB_ROOT=tmp_path, script_name="holoscan")


@pytest.fixture(autouse=True)
def installed_version(monkeypatch):
    if create.__version__ == create.LOCAL_SOURCE_VERSION:
        monkeypatch.setattr(create, "__version__", "5.0.0a9")


def _write_template(root: Path, relative: str, *, module: bool) -> Path:
    template = root / relative
    template.mkdir(parents=True)
    context = {"project_name": "Example", "project_slug": "example"}
    if module:
        context.update(
            module_slug="{{ cookiecutter.project_slug }}",
            module_repo_name="holoscan-{{ cookiecutter.module_slug }}",
        )
    (template / "cookiecutter.json").write_text(json.dumps(context), encoding="utf-8")
    return template


def test_direct_create_uses_packaged_template_inside_a_source_project(
    cli, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)

    create.handle_create(cli, _args())
    output = capsys.readouterr().out
    assert "Template: packaged Module template" in output
    assert f"Directory: {tmp_path / 'holoscan-my-mod'}" in output

    _write_template(tmp_path, "applications/template", module=False)
    create.handle_create(cli, _args())
    output = capsys.readouterr().out
    assert "Template: packaged Module template" in output
    assert f"Directory: {tmp_path / 'holoscan-my-mod'}" in output
    assert "applications/CMakeLists.txt" not in output


def test_wrapper_default_selects_application_template(cli, tmp_path, monkeypatch, capsys):
    application_template = _write_template(tmp_path, "applications/template", module=False)
    monkeypatch.setenv(create.CREATE_TEMPLATE_ENV, "applications/template")

    create.handle_create(cli, _args())

    output = capsys.readouterr().out
    assert f"Template: {application_template}" in output
    assert f"Directory: {tmp_path / 'applications/my_mod'}" in output
    assert "applications/CMakeLists.txt" in output


def test_explicit_template_beats_the_wrapper_default(cli, tmp_path, monkeypatch, capsys):
    _write_template(tmp_path, "applications/template", module=False)
    selected = _write_template(tmp_path, "custom/module", module=True)
    monkeypatch.setenv(create.CREATE_TEMPLATE_ENV, "applications/template")

    create.handle_create(
        cli,
        _args(template="custom/module", directory=tmp_path / "output"),
    )

    output = capsys.readouterr().out
    assert f"Template: {selected}" in output
    assert f"Directory: {tmp_path / 'output/holoscan-my-mod'}" in output


def test_create_rejects_an_unsafe_destination_name(cli, tmp_path, capsys):
    with pytest.raises(SystemExit):
        create.handle_create(
            cli,
            _args(directory=tmp_path / "output", context=["module_repo_name=../escaped"]),
        )

    assert "one directory name" in capsys.readouterr().err
    assert not (tmp_path / "escaped").exists()


def test_custom_module_template_gets_packaged_cmake(cli, tmp_path, monkeypatch):
    template = _write_template(tmp_path, "custom/module", module=True)
    output = tmp_path / "output"
    destination = output / "holoscan-my-mod"
    git_config = destination / ".git/config"
    git_config.parent.mkdir(parents=True)
    git_config.write_text("keep\n", encoding="utf-8")

    def generate(_cli, _template, **kwargs):
        project = kwargs["output_dir"] / destination.name
        (project / "cmake").mkdir(parents=True)
        (project / "cmake/custom.cmake").write_text("# custom\n", encoding="utf-8")
        return str(project)

    monkeypatch.setattr(create, "_run_cookiecutter", generate)
    monkeypatch.setattr(create, "validate_generated_metadata", lambda *_args: None)

    create.handle_create(
        cli,
        _args(template=str(template), dryrun=False, directory=output),
    )

    assert git_config.read_text(encoding="utf-8") == "keep\n"
    assert (destination / "cmake/custom.cmake").is_file()
    assert (destination / "cmake/HoloHubConfigHelpers.cmake").is_file()


def test_create_never_overwrites_an_existing_project(cli, tmp_path, monkeypatch):
    destination = tmp_path / "output/holoscan-my-mod"
    destination.mkdir(parents=True)
    marker = destination / "keep.txt"
    marker.write_text("keep\n", encoding="utf-8")
    monkeypatch.setattr(
        create,
        "_run_cookiecutter",
        lambda *_args, **_kwargs: pytest.fail("generation must not start"),
    )

    with pytest.raises(SystemExit):
        create.handle_create(cli, _args(dryrun=False, directory=destination.parent))

    assert marker.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_initialize_module_git_only_initializes_standalone_directory(tmp_path):
    standalone = tmp_path / "standalone"
    standalone.mkdir()
    assert create._initialize_module_git(standalone)
    assert (standalone / ".git").is_dir()

    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "."],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    nested = repository / "packages/module"
    nested.mkdir(parents=True)

    assert not create._initialize_module_git(nested)
    assert not (nested / ".git").exists()


def test_missing_cookiecutter_points_to_the_create_extra(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        create.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError),
    )

    with pytest.raises(SystemExit):
        create._run_cookiecutter(
            cli,
            tmp_path,
            interactive=False,
            context={},
            output_dir=tmp_path,
        )

    assert "pip install 'holoscan-cli[create]'" in capsys.readouterr().err


def test_module_template_rejects_python_language(cli, tmp_path, capsys):
    with pytest.raises(SystemExit):
        create.handle_create(cli, _args(language="python", directory=tmp_path / "output"))

    err = capsys.readouterr().err
    assert "not available for Holoscan SDK 5.0" in err
    assert "returns in a later release" in err
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("holoscan_version", ["4.1.0", "5.0", "latest"])
def test_module_template_rejects_pre_5_0_or_malformed_sdk_versions(
    cli, tmp_path, monkeypatch, capsys, holoscan_version
):
    pytest.importorskip("cookiecutter")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)

    with pytest.raises(SystemExit):
        create.handle_create(
            cli,
            _args(
                dryrun=False,
                directory=tmp_path / "output",
                context=[f"holoscan_version={holoscan_version}"],
            ),
        )

    assert "Hook script failed" in capsys.readouterr().err
    assert not (tmp_path / "output/holoscan-my-mod").exists()


def test_packaged_template_creates_a_standalone_module(cli, tmp_path, monkeypatch):
    pytest.importorskip("cookiecutter")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)

    create.handle_create(
        cli,
        _args(language="cpp", dryrun=False, directory=tmp_path / "output"),
    )

    project = tmp_path / "output/holoscan-my-mod"
    requirement = (project / "requirements-cli.txt").read_text(encoding="utf-8")
    pyproject = (project / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")
    readme = (project / "README.md").read_text(encoding="utf-8")
    app_cmake = (project / "applications/my_mod_pipeline/CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    active_requirements = [
        line for line in requirement.splitlines() if line and not line.startswith("#")
    ]

    operator_source = (project / "operators/my_mod_op/my_mod_op.cpp").read_text(encoding="utf-8")
    operator_header = (project / "operators/my_mod_op/my_mod_op.hpp").read_text(encoding="utf-8")
    application = (project / "applications/my_mod_pipeline/cpp/my_mod_pipeline.cpp").read_text(
        encoding="utf-8"
    )
    root_cmake = (project / "CMakeLists.txt").read_text(encoding="utf-8")
    metadata = json.loads((project / "metadata.json").read_text(encoding="utf-8"))
    deb = (project / "pkg/holoscan-my-mod/CMakeLists.txt").read_text(encoding="utf-8")
    developer = (project / "DEVELOPER.md").read_text(encoding="utf-8")

    assert (project / "cmake/HoloHubConfigHelpers.cmake").is_file()
    assert (project / "tests/cpp/test_operators.cpp").is_file()
    for removed in (
        "operators/my_mod_op/my_mod_op.py",
        "operators/my_mod_op/python",
        "applications/my_mod_pipeline/python",
        "python",
        "tests/python",
        "pytest.ini",
    ):
        assert not (project / removed).exists(), removed
    assert "holoscan::Operator<>" in operator_header
    assert "holoscan::Input<std::uint32_t> in;" in operator_header
    assert "HOLOSCAN_TRY(auto value, in.receive_data());" in operator_source
    assert "holoscan::compile(graph)" in application
    assert "holoscan::run_async(plan)" in application
    assert "cmake_minimum_required(VERSION 4.0)" in root_cmake
    assert "CMAKE_CXX_STANDARD 20" in root_cmake
    assert "find_package(holoscan 5.0 REQUIRED CONFIG COMPONENTS core)" in root_cmake
    assert metadata["module"]["language"] == ["C++"]
    assert metadata["module"]["namespace"] == {"cpp": "holoscan::my_mod"}
    assert metadata["module"]["holoscan_sdk"]["minimum_required_version"] == "5.0.0"
    assert "pypi" not in metadata["module"]["binary_packages"]
    assert metadata["module"]["dependencies"] == []
    assert '"provides_operators": ["FrameCounterOp"]' in developer
    assert "HOLOSCAN_CLI_LOCAL_HOLOSCAN_EXAMPLE_UTILS" in developer
    assert "target_link_libraries(my_mod_op PUBLIC holoscan::frame_counter)" in developer
    assert 'DEPENDS     "holoscan (>= 5.0.0)"' in deb
    assert "scikit-build" not in pyproject
    assert "pybind11" not in dockerfile
    assert "holoscan:v5.0.0-cuda13" in dockerfile
    assert "return in a later release" in readme
    for text in (operator_source, operator_header, application, readme, pyproject, dockerfile):
        assert "{{" not in text and "{%" not in text
    assert active_requirements == [f"holoscan-cli=={create.MODULE_TEMPLATE_CLI_VERSION}"]
    assert "--extra-index-url https://pypi.nvidia.com" in requirement
    assert 'requires-python = ">=3.11"' in pyproject
    assert 'holoscan-cli = { index = "nvidia" }' in pyproject
    assert f"holoscan-cli=={create.MODULE_TEMPLATE_CLI_VERSION}" in pyproject
    assert 'url = "https://pypi.nvidia.com"' in pyproject
    assert "explicit = true" in pyproject
    assert "package = false" in pyproject
    holoscan_config = tomllib.loads(pyproject)["tool"]["holoscan"]
    assert holoscan_config["cuda"] == 13
    assert holoscan_config["base-images"] == {
        "x86_64": "nvcr.io/nvidia/clara-holoscan/holoscan:v5.0.0-cuda13",
        "aarch64": "nvcr.io/nvidia/clara-holoscan/holoscan:v5.0.0-cuda13",
    }
    assert set(holoscan_config) == {"cuda", "base-images"}
    assert "--extra-index-url https://pypi.nvidia.com" in dockerfile
    assert "python3 -m venv .venv" in readme
    assert "uv run holoscan" in readme
    assert 'option(HOLOSCAN_MY_MOD_BUILD_CPP "Build C++ applications" ON)' in root_cmake
    assert "HOLOSCAN_MY_MOD_BUILD_PYTHON" not in root_cmake
    assert "if(HOLOSCAN_MY_MOD_BUILD_CPP)\n    add_subdirectory(cpp)\nendif()" in app_cmake
    assert not (project / "holohub").exists()
    assert not (project / "holoscan").exists()

    pre_commit = (project / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert (
        f'additional_dependencies: ["holoscan-cli[create]=={create.MODULE_TEMPLATE_CLI_VERSION}"]'
        in pre_commit
    )

    # A new scaffold must accept the development-install command before a build exists.
    env = dict(
        os.environ,
        HOLOSCAN_CLI_ROOT=str(project),
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
    )
    for name in ("HOLOSCAN_CLI_BUILD_LOCAL", "HOLOSCAN_CLI_IN_CONTAINER_CMD"):
        env.pop(name, None)
    preview = subprocess.run(
        [sys.executable, "-m", "holoscan_cli", "install", "--dev", "--dryrun"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "build 'holoscan-my-mod' if its dev hook is not staged" in preview.stdout
    assert "holoscan install --dev --local --dryrun" in preview.stdout
    assert not (project / "build").exists()


def test_parser_leaves_template_and_directory_contextual():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    create.register_create_parser(
        SimpleNamespace(HOLOHUB_ROOT=Path("/unused"), script_name="holoscan"),
        subparsers,
    )

    args = parser.parse_args(["create", "My Project"])

    assert args.template is None
    assert args.directory is None
