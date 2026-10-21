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


def _validate_generated_metadata(project: Path) -> None:
    script = project / ".github/workflows/scripts/validate_metadata.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


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
    assert "pure-Python Modules return in a later release" in err
    assert "--language cpp python" in err
    assert not (tmp_path / "output").exists()


def test_custom_module_template_rejects_multiple_languages(cli, tmp_path, capsys):
    _write_template(tmp_path, "modules/template", module=True)

    with pytest.raises(SystemExit):
        create.handle_create(
            cli,
            _args(
                template="modules/template",
                language=["cpp", "python"],
                directory=tmp_path / "output",
            ),
        )

    assert "custom templates take one language" in capsys.readouterr().err


@pytest.mark.parametrize("language", [["cpp"], ["cpp", "python"], ["python,cpp", "cpp"]])
def test_packaged_template_receives_normalized_languages(cli, tmp_path, capsys, language):
    create.handle_create(cli, _args(language=language, directory=tmp_path / "output"))

    expected = "cpp,python" if any("python" in value for value in language) else "cpp"
    assert f"  language: {expected}\n" in capsys.readouterr().out


@pytest.mark.parametrize("language", [["rust"], [","]])
def test_create_rejects_unknown_languages(cli, tmp_path, capsys, language):
    with pytest.raises(SystemExit):
        create.handle_create(cli, _args(language=language, directory=tmp_path / "output"))

    assert "--language" in capsys.readouterr().err


def test_create_manages_the_python_bindings_context(cli, tmp_path, capsys):
    with pytest.raises(SystemExit):
        create.handle_create(
            cli,
            _args(context=["__python_bindings=yes"], directory=tmp_path / "output"),
        )

    assert "'__python_bindings' is managed by holoscan create" in capsys.readouterr().err


def test_custom_module_template_allows_python_language(cli, tmp_path, capsys):
    selected = _write_template(tmp_path, "modules/template", module=True)

    create.handle_create(
        cli,
        _args(template="modules/template", language="python", directory=tmp_path / "output"),
    )

    assert f"Template: {selected}" in capsys.readouterr().out


def test_packaged_template_generates_python_bindings_for_cpp_python(cli, tmp_path, monkeypatch):
    pytest.importorskip("cookiecutter")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)

    create.handle_create(
        cli,
        _args(dryrun=False, language=["cpp", "python"], directory=tmp_path / "output"),
    )

    project = tmp_path / "output/holoscan-my-mod"
    extension = (project / "python/_my_mod.cpp").read_text(encoding="utf-8")
    python_cmake = (project / "python/CMakeLists.txt").read_text(encoding="utf-8")
    root_cmake = (project / "CMakeLists.txt").read_text(encoding="utf-8")
    tests_cmake = (project / "tests/CMakeLists.txt").read_text(encoding="utf-8")
    pyproject = (project / "pyproject.toml").read_text(encoding="utf-8")
    proxies = (project / "python/holoscan_my_mod/operators/__init__.py").read_text(encoding="utf-8")

    for generated in (
        "python/holoscan_my_mod/__init__.py",
        "python/holoscan_my_mod/py.typed",
        "tests/python/CMakeLists.txt",
        "tests/python/test_my_mod.py",
        "applications/my_mod_pipeline/python/my_mod_pipeline.py",
    ):
        assert (project / generated).is_file(), generated
    assert (
        "HOLOSCAN_REGISTER_OPERATOR(holoscan::my_mod::MyModOp,\n"
        '                           "holoscan.my_mod.MyModOp");'
    ) in extension
    assert "NB_MODULE(_my_mod, module)" in extension
    assert "nanobind (https://github.com/wjakob/nanobind)" in (project / "NOTICE").read_text(
        encoding="utf-8"
    )
    assert "nanobind_add_module(my_mod_python NB_STATIC STABLE_ABI" in python_cmake
    assert "set(_component holoscan-my_mod-python_libs)" in python_cmake
    assert "EXCLUDE_FROM_ALL" not in python_cmake
    assert (
        "holoscan_install_python_module_metadata(\n"
        "    MODULE my_mod\n"
        '    REQUIRES "holoscan-core-cu13>=5.0.0")'
    ) in python_cmake
    assert "set(HOLOSCAN_MY_MOD_BUILD_PYTHON ON\n" in root_cmake
    assert "option(HOLOSCAN_MY_MOD_BUILD_PYTHON" not in root_cmake
    assert 'option(HOLOSCAN_MY_MOD_BUILD_CPP "Build C++ applications" ON)' in root_cmake
    assert "if(HOLOSCAN_MY_MOD_BUILD_CPP)\n    add_subdirectory(cpp)\nendif()" in (
        project / "applications/my_mod_pipeline/CMakeLists.txt"
    ).read_text(encoding="utf-8")
    assert "if(PROJECT_IS_TOP_LEVEL AND NOT PKG_holoscan_my_mod)" in root_cmake
    assert root_cmake.index("find_package(Python 3.12") < root_cmake.index(
        "add_subdirectory(tests)"
    )
    assert "find_package(Python" not in python_cmake
    assert "GIT_TAG db4827f06f6f1680e5d4004c95fc8d69299dba8b" in python_cmake
    assert "if(HOLOSCAN_MY_MOD_BUILD_PYTHON)\n    add_subdirectory(python)" in tests_cmake
    assert '_registry_prefix = "holoscan.my_mod."' in proxies
    assert 'requires-python = ">=3.12"' in pyproject
    assert '"pytest",' in pyproject
    assert 'target-version = "py312"' in pyproject
    module = json.loads((project / "metadata.json").read_text(encoding="utf-8"))["module"]
    assert module["language"] == ["C++", "Python"]
    operator = json.loads(
        (project / "operators/my_mod_op/metadata.json").read_text(encoding="utf-8")
    )["operator"]
    assert operator["language"] == ["C++", "Python"]
    assert module["namespace"] == {"cpp": "holoscan::my_mod", "python": "holoscan_my_mod"}
    _validate_generated_metadata(project)
    apps = {
        lang: json.loads(
            (project / f"applications/my_mod_pipeline/{lang}/metadata.json").read_text(
                encoding="utf-8"
            )
        )["application"]
        for lang in ("cpp", "python")
    }
    assert apps["cpp"]["language"] == ["C++"]
    assert list(apps["cpp"]["modes"]) == ["default"]
    assert apps["python"]["name"] == apps["cpp"]["name"] == "my_mod_pipeline"
    assert apps["python"]["language"] == ["Python"]
    assert apps["python"]["modes"]["default"]["run"]["command"] == (
        "python3 <holohub_app_source>/my_mod_pipeline.py"
    )
    developer = (project / "DEVELOPER.md").read_text(encoding="utf-8")
    assert "├── python/" in developer
    assert "│       └── python/" in developer
    assert "    └── python/" in developer
    assert "PYTHONPATH=build/python/lib:$PYTHONPATH python3" in developer
    assert "C++ unit tests and the `tests/python` pytest suite" in developer


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


@pytest.mark.parametrize("project", ["Core", "vision", "Visualization", "inference"])
def test_module_template_rejects_sdk_module_names(cli, tmp_path, monkeypatch, capsys, project):
    pytest.importorskip("cookiecutter")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)

    with pytest.raises(SystemExit):
        create.handle_create(
            cli, _args(project=project, dryrun=False, directory=tmp_path / "output")
        )

    assert "Hook script failed" in capsys.readouterr().err
    assert not (tmp_path / "output" / f"holoscan-{project.lower()}").exists()


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
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    notice = (project / "NOTICE").read_text(encoding="utf-8")

    assert (project / "cmake/HoloHubConfigHelpers.cmake").is_file()
    assert notice.startswith("My Mod\nCopyright (c) ")
    assert "GoogleTest (https://github.com/google/googletest)" in notice
    assert "nanobind" not in notice
    assert "[NOTICE](NOTICE)" in readme
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
    assert "add_library(holoscan::my_mod ALIAS holoscan_my_mod)" in root_cmake
    assert "EXPORT_NAME my_mod" in root_cmake
    assert "install(TARGETS holoscan_my_mod" in root_cmake
    assert metadata["module"]["language"] == ["C++"]
    operator = json.loads(
        (project / "operators/my_mod_op/metadata.json").read_text(encoding="utf-8")
    )["operator"]
    assert operator["language"] == ["C++"]
    assert metadata["module"]["namespace"] == {"cpp": "holoscan::my_mod"}
    assert metadata["module"]["holoscan_sdk"]["minimum_required_version"] == "5.0.0"
    assert metadata["module"]["support_level"] == "community"
    assert "pypi" not in metadata["module"]["binary_packages"]
    assert metadata["module"]["dependencies"] == []
    _validate_generated_metadata(project)
    assert '"provides_operators": ["FrameCounterOp"]' in developer
    assert "HOLOSCAN_CLI_LOCAL_HOLOSCAN_EXAMPLE_UTILS" in developer
    assert "target_link_libraries(my_mod_op PUBLIC holoscan::frame_counter)" in developer
    assert 'DEPENDS     "holoscan (>= 5.0.0)"' in deb
    assert "scikit-build" not in pyproject
    assert "pybind11" not in dockerfile
    assert "holoscan:v5.0.0-cuda13" in dockerfile
    assert "return in a later release" in readme
    assert "holoscan build my_mod_pipeline" in agents
    assert "holoscan package holoscan-my-mod --pkg-generator DEB" in agents
    assert "pkg/holoscan-my-mod/CMakeLists.txt" in agents
    assert '--docker-opts="--runtime=runc"' in agents
    for text in (
        operator_source,
        operator_header,
        application,
        readme,
        pyproject,
        dockerfile,
        agents,
        notice,
    ):
        assert "{{" not in text and "{%" not in text
    assert active_requirements == [f"holoscan-cli=={create.__version__}"]
    assert "--extra-index-url https://pypi.nvidia.com" in requirement
    assert 'requires-python = ">=3.11"' in pyproject
    assert 'holoscan-cli = { index = "nvidia" }' in pyproject
    assert f"holoscan-cli=={create.__version__}" in pyproject
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
    assert f'additional_dependencies: ["holoscan-cli[create]=={create.__version__}"]' in pre_commit

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


def test_generated_metadata_check_rejects_an_undeclared_operator_language(
    cli, tmp_path, monkeypatch
):
    pytest.importorskip("cookiecutter")
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)
    create.handle_create(cli, _args(dryrun=False, directory=tmp_path / "output"))
    project = tmp_path / "output/holoscan-my-mod"
    operator_path = project / "operators/my_mod_op/metadata.json"
    metadata = json.loads(operator_path.read_text(encoding="utf-8"))
    metadata["operator"]["language"] = ["C++", "Python"]
    operator_path.write_text(json.dumps(metadata), encoding="utf-8")

    script = project / ".github/workflows/scripts/validate_metadata.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 1
    assert (
        "metadata.json: module.language lacks 'Python', "
        "declared by operators/my_mod_op/metadata.json"
    ) in result.stderr


def test_generated_module_exports_a_linkable_aggregate(cli, tmp_path, monkeypatch):
    """Exercise the generated packaging with a small SDK and operator fixture."""
    cmake = shutil.which("cmake")
    if cmake is None:
        pytest.skip("CMake 4 is required for the installed-package smoke test")
    version = subprocess.check_output([cmake, "--version"], text=True).split()[2]
    if int(version.split(".")[0]) < 4:
        pytest.skip("CMake 4 is required for the installed-package smoke test")
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)
    create.handle_create(cli, _args(dryrun=False, directory=tmp_path / "output"))
    project = tmp_path / "output/holoscan-my-mod"
    operator = project / "operators/my_mod_op"
    (operator / "my_mod_op.hpp").write_text("int module_value();\n", encoding="utf-8")
    (operator / "my_mod_op.cpp").write_text(
        '#include "my_mod_op.hpp"\nint module_value() { return 42; }\n', encoding="utf-8"
    )
    (project / "applications/my_mod_pipeline/cpp/my_mod_pipeline.cpp").write_text(
        "int main() { return 0; }\n", encoding="utf-8"
    )
    with (project / "CMakeLists.txt").open("a", encoding="utf-8") as root:
        root.write(
            '\nif(NOT TARGET holoscan::my_mod)\nmessage(FATAL_ERROR "Missing alias")\nendif()\n'
            "get_target_property(links holoscan_my_mod INTERFACE_LINK_LIBRARIES)\n"
            "if(TARGET holoscan::my_mod_op)\n"
            'if(NOT "holoscan::my_mod_op" IN_LIST links)\n'
            'message(FATAL_ERROR "Enabled operator missing from aggregate")\nendif()\n'
            'elseif(links)\nmessage(FATAL_ERROR "Disabled operator linked")\nendif()\n'
        )
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    (sdk / "holoscanConfig.cmake").write_text(
        "if(NOT TARGET holoscan::core)\n"
        "add_library(holoscan::core INTERFACE IMPORTED)\nendif()\n",
        encoding="utf-8",
    )
    (sdk / "holoscanConfigVersion.cmake").write_text(
        'set(PACKAGE_VERSION "5.0.0")\nset(PACKAGE_VERSION_COMPATIBLE TRUE)\n',
        encoding="utf-8",
    )

    def run(*args):
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr

    run(
        cmake,
        "-S",
        str(project),
        "-B",
        str(tmp_path / "disabled"),
        f"-Dholoscan_DIR={sdk}",
        "-DBUILD_ALL=OFF",
        "-DMY_MOD_BUILD_TESTING=OFF",
    )
    build = tmp_path / "build"
    prefix = tmp_path / "install"
    run(
        cmake,
        "-S",
        str(project),
        "-B",
        str(build),
        f"-Dholoscan_DIR={sdk}",
        "-DBUILD_ALL=OFF",
        "-DPKG_holoscan_my_mod=ON",
        "-DMY_MOD_BUILD_TESTING=OFF",
    )
    # SDK 5 installs under /usr, so the Module's DEB must not use /opt/nvidia/holoscan.
    cpack = (build / "pkg/CPackConfig-holoscan-my-mod.cmake").read_text(encoding="utf-8")
    assert 'set(CPACK_PACKAGING_INSTALL_PREFIX "/usr")' in cpack
    run(cmake, "--build", str(build))
    run(cmake, "--install", str(build), "--prefix", str(prefix))
    for name in ("LICENSE", "NOTICE"):
        assert (prefix / "share/doc/holoscan-my-mod" / name).is_file(), name
    cpack = shutil.which("cpack")
    if cpack and shutil.which("dpkg-deb"):
        run(
            cpack,
            "--config",
            str(build / "pkg/CPackConfig-holoscan-my-mod.cmake"),
            "-B",
            str(build),
        )
        (deb,) = build.glob("holoscan-my-mod_*.deb")
        contents = subprocess.check_output(["dpkg-deb", "-c", str(deb)], text=True)
        for name in ("LICENSE", "NOTICE"):
            assert f"./usr/share/doc/holoscan-my-mod/{name}\n" in contents, name
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 4.0)\nproject(consumer LANGUAGES CXX)\n"
        "find_package(holoscan-my-mod CONFIG REQUIRED)\n"
        "if(NOT TARGET holoscan::my_mod_op)\n"
        'message(FATAL_ERROR "Missing individual operator target")\nendif()\n'
        "add_executable(consumer main.cpp)\n"
        "target_link_libraries(consumer PRIVATE holoscan::my_mod)\n",
        encoding="utf-8",
    )
    (consumer / "main.cpp").write_text(
        "#include <my_mod_op/my_mod_op.hpp>\nint main() { return module_value() != 42; }\n",
        encoding="utf-8",
    )
    consumer_build = tmp_path / "consumer-build"
    run(
        cmake,
        "-S",
        str(consumer),
        "-B",
        str(consumer_build),
        f"-DCMAKE_PREFIX_PATH={prefix}",
        f"-Dholoscan_DIR={sdk}",
    )
    run(cmake, "--build", str(consumer_build))
    run(str(consumer_build / "consumer"))


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
    assert args.language is None
    assert parser.parse_args(["create", "My Project", "--language", "cpp", "python"]).language == [
        "cpp",
        "python",
    ]
    with pytest.raises(SystemExit):
        parser.parse_args(["create", "My Project", "--python-bindings"])


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--language", "cpp", "my-sensor"], ["cpp"]),
        (["my-sensor", "--language", "cpp", "python"], ["cpp", "python"]),
        (["--language", "cpp", "python", "my-sensor"], ["cpp", "python"]),
        (["-i", "False", "--language", "cpp,python", "my-sensor"], ["cpp,python"]),
        (["my-sensor"], None),
    ],
)
def test_create_accepts_project_before_or_after_languages(cli, argv, expected):
    parser = argparse.ArgumentParser()
    create.register_create_parser(cli, parser.add_subparsers())
    args = parser.parse_args(["create", *argv])

    create._take_project_from_languages(args)

    assert args.project == "my-sensor"
    assert args.language == expected


@pytest.mark.parametrize("argv", [["--language", "cpp"], ["--language", "cpp,python"], []])
def test_create_requires_a_project_name(cli, capsys, argv):
    parser = argparse.ArgumentParser()
    create.register_create_parser(cli, parser.add_subparsers())
    args = parser.parse_args(["create", *argv])

    with pytest.raises(SystemExit):
        create.handle_create(cli, args)

    assert "holoscan create needs a project name" in capsys.readouterr().err


def test_create_still_rejects_unknown_language_before_project(cli, tmp_path, capsys):
    with pytest.raises(SystemExit):
        create.handle_create(
            cli,
            _args(project=None, language=["cpp", "rust", "my-sensor"], directory=tmp_path / "o"),
        )

    assert "Unsupported --language 'rust'" in capsys.readouterr().err
