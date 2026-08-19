# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for standalone Module creation."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import create


def _make_args(**overrides) -> argparse.Namespace:
    defaults = dict(
        project="My Mod",
        template=None,
        language="python",
        dryrun=True,
        directory=None,
        context=None,
        interactive=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture()
def fake_cli(tmp_path):
    return SimpleNamespace(HOLOHUB_ROOT=tmp_path, script_name="holoscan")


@pytest.fixture(autouse=True)
def installed_cli_metadata(monkeypatch):
    """Creation tests model an installed candidate rather than a PYTHONPATH checkout."""
    if create.__version__ == create.LOCAL_SOURCE_VERSION:
        monkeypatch.setattr(create, "__version__", "5.0.0a9")


def _write_template(root: Path, relative: str, *, module: bool) -> Path:
    template = root / relative
    template.mkdir(parents=True)
    context = {"project_name": "Example", "project_slug": "example"}
    if module:
        context.update(
            {
                "module_slug": "{{ cookiecutter.project_name }}",
                "module_repo_name": "holoscan-{{ cookiecutter.module_slug }}",
            }
        )
    (template / "cookiecutter.json").write_text(json.dumps(context), encoding="utf-8")
    return template


def _assert_generated_sources_and_metadata(project: Path) -> None:
    from holoscan_cli.metadata import metadata_validator

    for metadata_path in project.rglob("metadata.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        is_valid, message = metadata_validator.validate_json(metadata, metadata_path.parent)
        assert is_valid, f"{metadata_path}: {message}"

    for source_path in project.rglob("*.py"):
        relative = source_path.relative_to(project)
        if relative.parts[:2] == ("cmake", "pybind11"):
            # This helper is configured by CMake before becoming Python source.
            continue
        compile(source_path.read_text(encoding="utf-8"), str(source_path), "exec")


def test_default_uses_packaged_module_template_and_current_directory(
    fake_cli, tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    create.handle_create(fake_cli, _make_args())

    output = capsys.readouterr().out
    assert "Template: packaged Module template" in output
    assert f"Directory: {tmp_path / 'holoscan-my-mod'}" in output


def test_existing_source_project_application_template_remains_default(fake_cli, tmp_path, capsys):
    template = _write_template(tmp_path, "applications/template", module=False)

    create.handle_create(fake_cli, _make_args())

    output = capsys.readouterr().out
    assert f"Template: {template}" in output
    assert str(tmp_path / "applications" / "my_mod") in output
    assert "applications/CMakeLists.txt" in output


def test_module_create_rejects_uninstallable_source_only_version(
    fake_cli, tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(create, "__version__", create.LOCAL_SOURCE_VERSION)

    with pytest.raises(SystemExit):
        create.handle_create(fake_cli, _make_args())

    assert "cannot generate an installable Module contract" in capsys.readouterr().err


def test_missing_legacy_module_template_resolves_to_packaged_alias(fake_cli, tmp_path, capsys):
    output_parent = tmp_path / "output"

    create.handle_create(
        fake_cli,
        _make_args(template="modules/template", directory=output_parent),
    )

    output = capsys.readouterr().out
    assert "Template: packaged Module template" in output
    assert str(output_parent / "holoscan-my-mod") in output


def test_existing_legacy_module_template_wins_over_alias(fake_cli, tmp_path, capsys):
    template = _write_template(tmp_path, "modules/template", module=True)

    create.handle_create(
        fake_cli,
        _make_args(template="modules/template", directory=tmp_path / "output"),
    )

    output = capsys.readouterr().out
    assert f"Template: {template}" in output
    assert "packaged Module template" not in output


def test_wrapper_environment_selects_application_default(fake_cli, tmp_path, capsys, monkeypatch):
    template = _write_template(tmp_path, "wrapper/application-template", module=False)
    monkeypatch.setenv(create.CREATE_TEMPLATE_ENV, "wrapper/application-template")

    create.handle_create(fake_cli, _make_args())

    output = capsys.readouterr().out
    assert f"Template: {template}" in output
    assert str(tmp_path / "applications" / "my_mod") in output
    assert "applications/CMakeLists.txt" in output


def test_explicit_template_overrides_wrapper_environment(fake_cli, tmp_path, capsys, monkeypatch):
    _write_template(tmp_path, "applications/template", module=False)
    explicit = _write_template(tmp_path, "custom/module", module=True)
    monkeypatch.setenv(create.CREATE_TEMPLATE_ENV, "applications/template")

    create.handle_create(
        fake_cli,
        _make_args(template="custom/module", directory=tmp_path / "output"),
    )

    output = capsys.readouterr().out
    assert f"Template: {explicit}" in output
    assert str(tmp_path / "output" / "holoscan-my-mod") in output


def test_template_classification_uses_cookiecutter_context_not_path(tmp_path):
    module_template = _write_template(tmp_path, "looks-like-an-application", module=True)
    app_template = _write_template(tmp_path, "modules/not-a-module", module=False)

    assert create._is_module_template(create._template_context(module_template))
    assert not create._is_module_template(create._template_context(app_template))


def test_missing_explicit_template_is_fatal(fake_cli, tmp_path, capsys):
    missing = tmp_path / "missing-template"

    with pytest.raises(SystemExit):
        create.handle_create(fake_cli, _make_args(template=str(missing)))

    assert str(missing) in capsys.readouterr().err


def test_empty_explicit_template_is_fatal(fake_cli, capsys):
    with pytest.raises(SystemExit):
        create.handle_create(fake_cli, _make_args(template=""))

    assert "--template requires a non-empty" in capsys.readouterr().err


def test_dryrun_does_not_create_missing_output_parent(fake_cli, tmp_path):
    output_parent = tmp_path / "missing" / "nested"

    create.handle_create(fake_cli, _make_args(directory=output_parent))

    assert not output_parent.exists()


def test_create_makes_missing_output_parents(fake_cli, tmp_path, monkeypatch):
    output_parent = tmp_path / "missing" / "nested"

    def fake_generate(_cli, _template, *, interactive, context, output_dir):
        assert not interactive
        assert context["_holoscan_cli_version"] == create.__version__
        assert output_dir.parent == output_parent
        assert output_dir.name.startswith(".holoscan-my-mod.holoscan-create-")
        assert output_dir.is_dir()
        project = output_dir / "holoscan-my-mod"
        project.mkdir()
        return str(project)

    monkeypatch.setattr(create, "_run_cookiecutter", fake_generate)
    monkeypatch.setattr(create, "validate_generated_metadata", lambda *_args: None)

    create.handle_create(
        fake_cli,
        _make_args(dryrun=False, directory=output_parent),
    )

    assert (output_parent / "holoscan-my-mod").is_dir()


def test_existing_project_is_not_overwritten(fake_cli, tmp_path, monkeypatch, capsys):
    output_parent = tmp_path / "output"
    project = output_parent / "holoscan-my-mod"
    project.mkdir(parents=True)
    marker = project / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(create, "_run_cookiecutter", fail_if_called)

    with pytest.raises(SystemExit):
        create.handle_create(
            fake_cli,
            _make_args(dryrun=False, directory=output_parent),
        )

    assert not called
    assert marker.read_text(encoding="utf-8") == "keep"
    assert str(project) in capsys.readouterr().err


def _install_fake_generator(monkeypatch, *, filename: str = "generated.txt"):
    def fake_generate(_cli, _template, *, interactive, context, output_dir):
        del interactive, context
        project = output_dir / "holoscan-my-mod"
        project.mkdir()
        (project / filename).write_text("generated", encoding="utf-8")
        return str(project)

    monkeypatch.setattr(create, "_run_cookiecutter", fake_generate)
    monkeypatch.setattr(create, "validate_generated_metadata", lambda *_args: None)


def test_existing_empty_project_directory_is_populated(fake_cli, tmp_path, monkeypatch):
    output_parent = tmp_path / "output"
    project = output_parent / "holoscan-my-mod"
    project.mkdir(parents=True)
    _install_fake_generator(monkeypatch)
    initialized = []
    monkeypatch.setattr(
        create,
        "_initialize_module_git",
        lambda path: initialized.append(path) is None,
    )

    create.handle_create(fake_cli, _make_args(dryrun=False, directory=output_parent))

    assert (project / "generated.txt").read_text(encoding="utf-8") == "generated"
    assert initialized == [project]


def test_git_only_destination_is_populated_without_git_mutation(fake_cli, tmp_path, monkeypatch):
    output_parent = tmp_path / "output"
    project = output_parent / "holoscan-my-mod"
    git_dir = project / ".git"
    git_dir.mkdir(parents=True)
    marker = git_dir / "config"
    marker.write_bytes(b"remote configuration\n")
    before = (marker.read_bytes(), marker.stat().st_ino, git_dir.stat().st_ino)
    _install_fake_generator(monkeypatch)
    monkeypatch.setattr(
        create,
        "_initialize_module_git",
        lambda _path: pytest.fail("existing Git state must not be initialized"),
    )

    create.handle_create(fake_cli, _make_args(dryrun=False, directory=output_parent))

    after = (marker.read_bytes(), marker.stat().st_ino, git_dir.stat().st_ino)
    assert after == before
    assert (project / "generated.txt").is_file()


def test_precloned_git_head_index_and_remote_are_preserved(fake_cli, tmp_path, monkeypatch):
    output_parent = tmp_path / "output"
    project = output_parent / "holoscan-my-mod"
    project.mkdir(parents=True)
    subprocess.run(["git", "init", "."], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/review"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "ssh://example.invalid/module.git"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "read-tree", "--empty"], cwd=project, check=True, capture_output=True)
    git_dir = project / ".git"
    before = {name: (git_dir / name).read_bytes() for name in ("HEAD", "config", "index")}
    _install_fake_generator(monkeypatch)

    create.handle_create(fake_cli, _make_args(dryrun=False, directory=output_parent))

    after = {name: (git_dir / name).read_bytes() for name in before}
    assert after == before
    assert (project / "generated.txt").is_file()


def test_worktree_git_pointer_is_preserved(fake_cli, tmp_path, monkeypatch):
    output_parent = tmp_path / "output"
    project = output_parent / "holoscan-my-mod"
    project.mkdir(parents=True)
    git_pointer = project / ".git"
    git_pointer.write_text("gitdir: ../storage/worktree\n", encoding="utf-8")
    before = (git_pointer.read_bytes(), git_pointer.stat().st_ino)
    _install_fake_generator(monkeypatch)
    monkeypatch.setattr(
        create,
        "_initialize_module_git",
        lambda _path: pytest.fail("worktree Git state must not be initialized"),
    )

    create.handle_create(fake_cli, _make_args(dryrun=False, directory=output_parent))

    assert (git_pointer.read_bytes(), git_pointer.stat().st_ino) == before
    assert (project / "generated.txt").is_file()


def test_git_symlink_destination_is_rejected(fake_cli, tmp_path, monkeypatch):
    output_parent = tmp_path / "output"
    project = output_parent / "holoscan-my-mod"
    project.mkdir(parents=True)
    (project / ".git").symlink_to(tmp_path / "external-git", target_is_directory=True)
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(create, "_run_cookiecutter", fail_if_called)

    with pytest.raises(SystemExit):
        create.handle_create(fake_cli, _make_args(dryrun=False, directory=output_parent))

    assert not called
    assert (project / ".git").is_symlink()


def test_destination_change_during_generation_is_not_overwritten(tmp_path):
    destination = tmp_path / "project"
    destination.mkdir()
    initial_state = create._inspect_target(destination)
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "generated.txt").write_text("generated", encoding="utf-8")
    raced = destination / "raced.txt"
    raced.write_text("keep", encoding="utf-8")

    with pytest.raises(create._MaterializationError, match="changed during generation"):
        create._materialize_staged_project(staged, destination, initial_state)

    assert raced.read_text(encoding="utf-8") == "keep"
    assert not (destination / "generated.txt").exists()


def test_materialization_failure_rolls_back_only_created_paths(tmp_path, monkeypatch):
    destination = tmp_path / "project"
    destination.mkdir()
    initial_state = create._inspect_target(destination)
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "a.txt").write_text("a", encoding="utf-8")
    (staged / "b.txt").write_text("b", encoding="utf-8")
    calls = 0
    real_copy = create.shutil.copyfileobj

    def fail_second_copy(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated copy failure")
        return real_copy(source, target)

    monkeypatch.setattr(create.shutil, "copyfileobj", fail_second_copy)

    with pytest.raises(create._MaterializationError, match="simulated copy failure"):
        create._materialize_staged_project(staged, destination, initial_state)

    assert list(destination.iterdir()) == []


def test_dangling_project_symlink_is_not_overwritten(fake_cli, tmp_path):
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    project = output_parent / "holoscan-my-mod"
    project.symlink_to(tmp_path / "missing-target", target_is_directory=True)

    with pytest.raises(SystemExit):
        create.handle_create(fake_cli, _make_args(directory=output_parent))

    assert project.is_symlink()


def test_blocking_output_ancestor_has_actionable_error(fake_cli, tmp_path, capsys):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("block", encoding="utf-8")
    output_parent = blocker / "nested"

    with pytest.raises(SystemExit):
        create.handle_create(
            fake_cli,
            _make_args(dryrun=False, directory=output_parent),
        )

    error = capsys.readouterr().err
    assert str(output_parent) in error
    assert "Choose a writable --directory" in error


def test_output_parent_permission_error_is_actionable(tmp_path, capsys, monkeypatch):
    output_parent = tmp_path / "denied" / "nested"

    def deny_mkdir(_path, *, parents, exist_ok):
        assert parents
        assert exist_ok
        raise PermissionError("permission denied by test")

    monkeypatch.setattr(Path, "mkdir", deny_mkdir)

    with pytest.raises(SystemExit):
        create._ensure_output_parent(output_parent)

    error = capsys.readouterr().err
    assert str(output_parent) in error
    assert "permission denied by test" in error
    assert "Choose a writable --directory" in error


def test_context_can_override_predicted_module_repo_name(fake_cli, tmp_path, capsys):
    create.handle_create(
        fake_cli,
        _make_args(
            directory=tmp_path / "output",
            context=["module_repo_name=custom-repository"],
        ),
    )

    assert str(tmp_path / "output" / "custom-repository") in capsys.readouterr().out


@pytest.mark.parametrize("key", sorted(create.RESERVED_CONTEXT_KEYS))
def test_context_cannot_override_generated_cli_contract(fake_cli, tmp_path, capsys, key):
    with pytest.raises(SystemExit):
        create.handle_create(
            fake_cli,
            _make_args(directory=tmp_path / "output", context=[f"{key}=arbitrary"]),
        )

    assert "managed by holoscan create" in capsys.readouterr().err


def test_project_output_must_be_direct_child(fake_cli, tmp_path, capsys):
    output_parent = tmp_path / "output"

    with pytest.raises(SystemExit):
        create.handle_create(
            fake_cli,
            _make_args(
                directory=output_parent,
                context=["module_repo_name=../escaped"],
            ),
        )

    assert "one directory name" in capsys.readouterr().err
    assert not output_parent.exists()
    assert not (tmp_path / "escaped").exists()


def test_dryrun_omits_holoscan_version_when_not_configured(fake_cli, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(create.HoloscanContainer, "BASE_SDK_VERSION", None, raising=False)

    create.handle_create(fake_cli, _make_args(directory=tmp_path / "output"))

    assert "holoscan_version" not in capsys.readouterr().out


def test_parser_defaults_select_packaged_template_and_implicit_directory():
    parser = argparse.ArgumentParser()
    cli_stub = SimpleNamespace(HOLOHUB_ROOT=Path("/dev/null"), script_name="holoscan")
    subparsers = parser.add_subparsers()
    create.register_create_parser(cli_stub, subparsers)

    args = parser.parse_args(["create", "MyProj"])

    assert args.template is None
    assert args.directory is None


def test_missing_cookiecutter_points_to_create_extra(fake_cli, tmp_path, capsys, monkeypatch):
    def missing_cookiecutter(_module_name):
        raise ImportError

    monkeypatch.setattr(create.importlib, "import_module", missing_cookiecutter)

    with pytest.raises(SystemExit):
        create._run_cookiecutter(
            fake_cli,
            tmp_path,
            interactive=False,
            context={},
            output_dir=tmp_path,
        )

    assert "pip install 'holoscan-cli[create]'" in capsys.readouterr().err


def test_packaged_template_generates_self_contained_python_module(
    fake_cli, tmp_path, capsys, monkeypatch
):
    pytest.importorskip("cookiecutter")
    output_parent = tmp_path / "output"
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("HOLOSCAN_CLI_ROOT", raising=False)

    create.handle_create(
        fake_cli,
        _make_args(dryrun=False, directory=output_parent),
    )

    project = output_parent / "holoscan-my-mod"
    expected = [
        "cmake/HoloHubConfigHelpers.cmake",
        "cmake/holohub_configure_deb.cmake",
        "cmake/Config.cmake.in",
        "cmake/pybind11_add_holohub_module.cmake",
        "cmake/pybind11/__init__.py",
        "cmake/pydoc/macros.hpp",
        ".github/workflows/scripts/check_copyright.py",
        ".github/workflows/scripts/gitutils.py",
        "operators/my_mod_op/my_mod_op.py",
        "applications/my_mod_pipeline/python/my_mod_pipeline.py",
        "requirements-cli.txt",
        ".dockerignore",
    ]
    assert all((project / path).is_file() for path in expected)
    assert not (project / "holohub").exists()
    assert not (project / "holoscan").exists()
    active_requirements = [
        line
        for line in (project / "requirements-cli.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert active_requirements == [f"holoscan-cli=={create.__version__}"]
    pyproject = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert f'"holoscan-cli=={create.__version__}"' in pyproject
    assert '"pytest>=8.2"' in pyproject
    assert "[tool.holoscan]" not in pyproject
    assert not any(
        "./holohub" in path.read_text(encoding="utf-8", errors="ignore")
        for path in project.rglob("*")
        if path.is_file()
    )
    dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")
    # The CLI installs into the image interpreter, so the console script and the
    # Python that build/package hand to CMake are the same one.
    assert "python3 -m pip install" in dockerfile
    assert "-r /tmp/requirements-cli.txt" in dockerfile
    assert "/opt/holoscan-cli" not in dockerfile
    assert "holohub" not in dockerfile
    dockerignore = (project / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "requirements-cli.txt" not in dockerignore
    app_metadata = (project / "applications/my_mod_pipeline/python/metadata.json").read_text(
        encoding="utf-8"
    )
    assert "holohub_app_bin" in app_metadata
    assert "<holohub_app_source>" in app_metadata
    _assert_generated_sources_and_metadata(project)
    output = capsys.readouterr()
    assert "HoloHub root not found" not in output.out + output.err
    assert "Validated metadata.json" in output.out


@pytest.mark.parametrize(
    "version,expects_index_hint",
    [("4.6.0", False), ("4.6.0rc3", True), ("5.0.0a123", True)],
)
def test_generated_requirement_pins_runtime_and_hints_for_prereleases(
    fake_cli, tmp_path, monkeypatch, version, expects_index_hint
):
    pytest.importorskip("cookiecutter")
    monkeypatch.setattr(create, "__version__", version)
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)
    output_parent = tmp_path / "output"

    create.handle_create(
        fake_cli,
        _make_args(dryrun=False, directory=output_parent),
    )

    requirement = (output_parent / "holoscan-my-mod" / "requirements-cli.txt").read_text(
        encoding="utf-8"
    )
    active = [line for line in requirement.splitlines() if line and not line.startswith("#")]
    assert active == [f"holoscan-cli=={version}"]
    assert ("--extra-index-url https://pypi.nvidia.com" in requirement) is expects_index_hint


def test_packaged_template_generates_self_contained_cpp_module(fake_cli, tmp_path, monkeypatch):
    pytest.importorskip("cookiecutter")
    output_parent = tmp_path / "output"
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("HOLOSCAN_CLI_ROOT", raising=False)

    create.handle_create(
        fake_cli,
        _make_args(
            project="Cpp Mod",
            language="cpp",
            dryrun=False,
            directory=output_parent,
        ),
    )

    project = output_parent / "holoscan-cpp-mod"
    expected = [
        ".clang-format",
        "operators/cpp_mod_op/cpp_mod_op.cpp",
        "operators/cpp_mod_op/cpp_mod_op.hpp",
        "operators/cpp_mod_op/python/CMakeLists.txt",
        "operators/cpp_mod_op/python/_cpp_mod_op_bindings.cpp",
        "applications/cpp_mod_pipeline/cpp/metadata.json",
        "applications/cpp_mod_pipeline/cpp/cpp_mod_pipeline.cpp",
        "tests/cpp/CMakeLists.txt",
        "tests/cpp/test_operators.cpp",
    ]
    assert all((project / path).is_file() for path in expected)
    assert not any("{%" in path.name for path in project.rglob("*"))
    _assert_generated_sources_and_metadata(project)
