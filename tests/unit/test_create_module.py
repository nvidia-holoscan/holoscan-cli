# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused coverage for standalone Module creation."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import create


def _args(**overrides) -> argparse.Namespace:
    values = {
        "project": "My Mod",
        "template": None,
        "language": "python",
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


@pytest.mark.parametrize(
    "language,generated_source",
    [
        ("python", "operators/my_mod_op/my_mod_op.py"),
        ("cpp", "operators/my_mod_op/my_mod_op.cpp"),
    ],
)
def test_packaged_template_creates_a_standalone_module(
    cli, tmp_path, monkeypatch, language, generated_source
):
    pytest.importorskip("cookiecutter")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)

    create.handle_create(
        cli,
        _args(language=language, dryrun=False, directory=tmp_path / "output"),
    )

    project = tmp_path / "output/holoscan-my-mod"
    requirement = (project / "requirements-cli.txt").read_text(encoding="utf-8")
    pyproject = (project / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")
    readme = (project / "README.md").read_text(encoding="utf-8")
    active_requirements = [
        line for line in requirement.splitlines() if line and not line.startswith("#")
    ]

    assert (project / generated_source).is_file()
    assert (project / "cmake/HoloHubConfigHelpers.cmake").is_file()
    assert active_requirements == [f"holoscan-cli=={create.__version__}"]
    assert "--extra-index-url https://pypi.nvidia.com" in requirement
    assert 'holoscan-cli = { index = "nvidia" }' in pyproject
    assert 'url = "https://pypi.nvidia.com"' in pyproject
    assert "explicit = true" in pyproject
    assert "--extra-index-url https://pypi.nvidia.com" in dockerfile
    assert "python3 -m venv .venv" in readme
    assert "uv sync --only-dev" in readme
    assert "uv run holoscan" not in readme
    assert not (project / "holohub").exists()
    assert not (project / "holoscan").exists()


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
