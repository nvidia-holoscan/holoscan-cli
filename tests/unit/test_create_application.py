# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Coverage for the packaged application template and application registration."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import create
from holoscan_cli.utils.holohub import replace_placeholders

# Quotes and backslashes must survive as JSON string values in metadata.json.
DESCRIPTION = r'Detect "in-body" frames in C:\data'
AUTHOR = 'Ada "Q" Lovelace'
AFFILIATION = "Example Organization"

SOURCE_PROJECT_REGISTRATIONS = """\
# SPDX-FileCopyrightText: Copyright (c) 2026 Example Organization.
# SPDX-License-Identifier: Apache-2.0

# Keep applications in alphabetical order.
add_holoscan_application(alpha)
add_holoscan_application(zulu)
"""

MODULE_REGISTRATIONS = """\
# Add one add_holohub_application() call per application; declare operator
# dependencies via DEPENDS OPERATORS so they auto-enable when the app is built.
add_holohub_application(my_sensor_pipeline
    DEPENDS OPERATORS my_sensor_op
)
"""

COMMON_FILES = {"CMakeLists.txt", "README.md", "metadata.json", "tests/CMakeLists.txt"}
CPP_FILES = COMMON_FILES | {"cpp/CMakeLists.txt", "cpp/main.cpp"}
PYTHON_FILES = COMMON_FILES | {"python/CMakeLists.txt", "python/my_app.py"}


def _args(**overrides) -> argparse.Namespace:
    values = {
        "project": "my_app",
        "template": "application",
        "language": None,
        "dryrun": False,
        "directory": None,
        "context": [
            f"description={DESCRIPTION}",
            f"full_name={AUTHOR}",
            f"affiliation={AFFILIATION}",
        ],
        "interactive": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture(autouse=True)
def installed_version(monkeypatch):
    # Module creation needs an installed CLI version to pin.
    if create.__version__ == create.LOCAL_SOURCE_VERSION:
        monkeypatch.setattr(create, "__version__", "5.1.0a9")


def _create_pure_python_module(root: Path, monkeypatch) -> Path:
    monkeypatch.setattr(create, "_initialize_module_git", lambda _path: False)
    cli = SimpleNamespace(HOLOHUB_ROOT=root, script_name="holoscan")
    create.handle_create(
        cli,
        argparse.Namespace(
            project="My Mod",
            template=None,
            language="python",
            dryrun=False,
            directory=root,
            context=None,
            interactive=False,
        ),
    )
    return root / "holoscan-my-mod"


@pytest.fixture()
def project(tmp_path) -> Path:
    """A repository of applications that registers them in sorted order."""
    root = tmp_path / "project"
    (root / "applications").mkdir(parents=True)
    (root / "applications/CMakeLists.txt").write_text(
        SOURCE_PROJECT_REGISTRATIONS, encoding="utf-8"
    )
    return root


@pytest.fixture()
def cli(project):
    return SimpleNamespace(HOLOHUB_ROOT=project, script_name="holoscan")


def _generated_files(app: Path) -> set[str]:
    return {path.relative_to(app).as_posix() for path in app.rglob("*") if path.is_file()}


def _application_metadata(app: Path) -> dict:
    return json.loads((app / "metadata.json").read_text(encoding="utf-8"))["application"]


def test_dry_run_previews_the_application_and_its_registration(cli, project, capsys):
    create.handle_create(cli, _args(dryrun=True))

    output = capsys.readouterr().out
    assert "Template: packaged application template" in output
    assert f"Directory: {project / 'applications/my_app'}" in output
    assert "    add_holoscan_application(my_app)\n" in output
    assert not (project / "applications/my_app").exists()
    registrations = (project / "applications/CMakeLists.txt").read_text(encoding="utf-8")
    assert registrations == SOURCE_PROJECT_REGISTRATIONS


def test_cpp_application_is_created_and_registered_in_sorted_order(cli, project, capsys):
    pytest.importorskip("cookiecutter")

    create.handle_create(cli, _args())

    app = project / "applications/my_app"
    assert _generated_files(app) == CPP_FILES
    for name in CPP_FILES:
        text = (app / name).read_text(encoding="utf-8")
        assert "{{" not in text and "{%" not in text, name
    application = _application_metadata(app)
    assert application["name"] == "my_app"
    assert application["description"] == DESCRIPTION
    assert application["authors"] == [{"name": AUTHOR, "affiliation": AFFILIATION}]
    assert application["language"] == "C++"
    assert application["holoscan_sdk"]["minimum_required_version"] == "5.0.0"
    assert application["modes"]["ci"]["run"]["command"] == "./my_app --count 10 --period-ms 1"
    assert (project / "applications/CMakeLists.txt").read_text(encoding="utf-8") == (
        SOURCE_PROJECT_REGISTRATIONS.replace(
            "add_holoscan_application(zulu)",
            "add_holoscan_application(my_app)\nadd_holoscan_application(zulu)",
        )
    )
    output = capsys.readouterr().out
    assert f"- Implement the application in {app / 'cpp/main.cpp'}\n" in output
    assert "- Review the license headers in the generated source files\n" in output
    assert output.rstrip().endswith("   holoscan run my_app")


def test_python_application_is_created_as_a_standalone_project(tmp_path, monkeypatch, capsys):
    pytest.importorskip("cookiecutter")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    cli = SimpleNamespace(HOLOHUB_ROOT=work, script_name="holoscan")

    create.handle_create(cli, _args(language="python"))

    app = work / "my_app"
    assert _generated_files(app) == PYTHON_FILES
    assert not (work / "applications").exists()
    application = _application_metadata(app)
    assert application["language"] == "Python"
    command = application["modes"]["default"]["run"]["command"]
    assert command == "python3 '<holohub_app_source>/python/my_app.py' --count 100"
    # The CLI splits the command after inserting the application's path.
    source = "/home/dev/My Projects/my_app"
    assert shlex.split(replace_placeholders(command, {"holohub_app_source": source})) == [
        "python3",
        f"{source}/python/my_app.py",
        "--count",
        "100",
    ]
    tests = (app / "tests/CMakeLists.txt").read_text(encoding="utf-8")
    assert "COMMAND ${Python3_EXECUTABLE} ${script} --count 10 --period-ms 1" in tests
    assert "option(HOLOHUB_BUILD_PYTHON" in (app / "CMakeLists.txt").read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert f"- Implement the application in {app / 'python/my_app.py'}\n" in output
    assert f"   cd {app} && holoscan run my_app --local" in output


def test_application_in_a_module_uses_the_module_registration(tmp_path, capsys):
    pytest.importorskip("cookiecutter")
    module = tmp_path / "holoscan-my-sensor"
    (module / "applications").mkdir(parents=True)
    (module / "applications/CMakeLists.txt").write_text(MODULE_REGISTRATIONS, encoding="utf-8")
    cli = SimpleNamespace(HOLOHUB_ROOT=module, script_name="holoscan")

    create.handle_create(cli, _args())

    assert (module / "applications/my_app/metadata.json").is_file()
    registrations = (module / "applications/CMakeLists.txt").read_text(encoding="utf-8")
    assert registrations == MODULE_REGISTRATIONS + "add_holohub_application(my_app)\n"


def test_ctest_finds_the_tests_of_an_application_in_a_module(tmp_path, monkeypatch):
    """Configure a pure-Python Module, which needs no SDK, with a Python application."""
    pytest.importorskip("cookiecutter")
    cmake = shutil.which("cmake")
    ctest = shutil.which("ctest")
    python = sys.executable if sys.version_info >= (3, 12) else shutil.which("python3.12")
    if cmake is None or ctest is None or python is None:
        pytest.skip("CMake and Python 3.12 are required to configure the generated Module")
    module = _create_pure_python_module(tmp_path, monkeypatch)
    cli = SimpleNamespace(HOLOHUB_ROOT=module, script_name="holoscan")
    create.handle_create(cli, _args(language="python"))
    build = tmp_path / "build"

    def run(*command):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    run(
        cmake,
        "-S",
        str(module),
        "-B",
        str(build),
        f"-DPython_EXECUTABLE={python}",
        f"-DPython3_EXECUTABLE={python}",
    )
    tests = run(ctest, "--test-dir", str(build), "-N")
    assert "python.my_mod" in tests
    assert "my_app_pipeline" in tests
    assert "my_app_rejects_zero_count" in tests


def test_applications_folder_without_registrations_is_left_alone(tmp_path, capsys):
    pytest.importorskip("cookiecutter")
    root = tmp_path / "project"
    (root / "applications").mkdir(parents=True)
    cli = SimpleNamespace(HOLOHUB_ROOT=root, script_name="holoscan")

    create.handle_create(cli, _args(dryrun=True))
    assert "applications/CMakeLists.txt" not in capsys.readouterr().out

    create.handle_create(cli, _args())

    output = capsys.readouterr().out
    assert (root / "applications/my_app/metadata.json").is_file()
    assert not (root / "applications/CMakeLists.txt").exists()
    assert "Failed to add application" not in output


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # No registrations yet: use the packaged CMake support's command.
        ("", "add_holohub_application(my_app)\n"),
        (
            "# add_holoscan_application(other) is only a comment\n",
            "# add_holoscan_application(other) is only a comment\n"
            "add_holohub_application(my_app)\n",
        ),
        # Sorted, one per line: insert in order.
        (
            "add_holoscan_application(alpha)",
            "add_holoscan_application(alpha)\nadd_holoscan_application(my_app)\n",
        ),
        (
            "add_holoscan_application(zulu)\n",
            "add_holoscan_application(my_app)\nadd_holoscan_application(zulu)\n",
        ),
        (
            "add_holoscan_application(alpha)\nadd_holoscan_application(zulu)\n# end\n",
            "add_holoscan_application(alpha)\nadd_holoscan_application(my_app)\n"
            "add_holoscan_application(zulu)\n# end\n",
        ),
        # Unsorted or conditional registrations: append.
        (
            "add_holoscan_application(zulu)\nadd_holoscan_application(alpha)\n",
            "add_holoscan_application(zulu)\nadd_holoscan_application(alpha)\n"
            "add_holoscan_application(my_app)\n",
        ),
        (
            "if(ENABLE_ALPHA)\n  add_holohub_application(alpha)\nendif()\n",
            "if(ENABLE_ALPHA)\n  add_holohub_application(alpha)\nendif()\n"
            "add_holohub_application(my_app)\n",
        ),
        # Sorted but inside a condition: append after the block, never inside it.
        (
            "if(ENABLE_EXAMPLES)\nadd_holoscan_application(alpha)\n"
            "add_holoscan_application(zulu)\nendif()\n",
            "if(ENABLE_EXAMPLES)\nadd_holoscan_application(alpha)\n"
            "add_holoscan_application(zulu)\nendif()\nadd_holoscan_application(my_app)\n",
        ),
        # Calls in bracket comments are not registrations.
        (
            "#[[\nadd_holohub_application(my_app)\n]]\n"
            "add_holoscan_application(alpha)\nadd_holoscan_application(zulu)\n",
            "#[[\nadd_holohub_application(my_app)\n]]\n"
            "add_holoscan_application(alpha)\nadd_holoscan_application(my_app)\n"
            "add_holoscan_application(zulu)\n",
        ),
    ],
)
def test_registration_follows_the_existing_file(text, expected):
    (added,) = [line for line in expected.splitlines() if line not in text.splitlines()]

    assert create._application_registration(text, "my_app") == (expected, added)


@pytest.mark.parametrize(
    "text",
    [
        "add_holoscan_application(my_app)\n",
        "add_holohub_application(my_app\n    DEPENDS OPERATORS my_op\n)\n",
        "if(ENABLE)\n  add_holohub_application(my_app)\nendif()\n",
    ],
)
def test_registration_skips_a_registered_application(text):
    assert create._application_registration(text, "my_app") is None


def test_packaged_template_name_wins_over_a_directory_with_that_name(cli, project, capsys):
    custom = project / "application"
    custom.mkdir()
    (custom / "cookiecutter.json").write_text(
        json.dumps({"project_name": "x", "project_slug": "x"}), encoding="utf-8"
    )

    create.handle_create(cli, _args(dryrun=True))
    assert "Template: packaged application template" in capsys.readouterr().out

    create.handle_create(cli, _args(dryrun=True, template="./application"))
    assert f"Template: {custom}" in capsys.readouterr().out


def test_application_template_takes_one_language(cli, project, capsys):
    with pytest.raises(SystemExit):
        create.handle_create(cli, _args(language=["cpp", "python"]))

    assert "the packaged application template and custom templates take one language" in (
        capsys.readouterr().err
    )
    assert not (project / "applications/my_app").exists()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"context": ["holoscan_version=4.6.0"]}, "older than 5.0.0"),
        ({"context": ["holoscan_version=5.0"]}, "holoscan_version '5.0' must be"),
        ({"context": ["version=1.0"]}, "version '1.0' must be"),
        ({"context": ["language=rust"]}, "language 'rust' must be"),
        ({"context": ["description=first line\nsecond line"]}, "description must be a single"),
        ({"context": ["copyright_holder=Example\u2028Org"]}, "copyright_holder must be a single"),
        ({"project": "9lives"}, "project_slug '9lives' must be snake_case"),
    ],
)
def test_application_template_rejects_invalid_context(cli, project, capfd, overrides, message):
    pytest.importorskip("cookiecutter")

    with pytest.raises(SystemExit):
        create.handle_create(cli, _args(**overrides))

    assert message in capfd.readouterr().err
    assert sorted(path.name for path in (project / "applications").iterdir()) == ["CMakeLists.txt"]
    registrations = (project / "applications/CMakeLists.txt").read_text(encoding="utf-8")
    assert registrations == SOURCE_PROJECT_REGISTRATIONS


@pytest.mark.parametrize("language", ["cpp", "python"])
def test_registered_application_configures_without_the_sdk(cli, project, tmp_path, language):
    """Configure the source project with the application's language scope disabled."""
    pytest.importorskip("cookiecutter")
    cmake = shutil.which("cmake")
    if cmake is None:
        pytest.skip("CMake is required to configure the generated application")
    (project / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.24)\n"
        "project(applications LANGUAGES NONE)\n"
        "function(add_holoscan_application NAME)\n"
        '  option(APP_${NAME} "Build ${NAME}" OFF)\n'
        "  if(APP_${NAME})\n"
        "    add_subdirectory(${NAME})\n"
        "  endif()\n"
        "endfunction()\n"
        "include(CTest)\n"
        "add_subdirectory(applications)\n",
        encoding="utf-8",
    )
    create.handle_create(cli, _args(language=language))
    build = tmp_path / "build"

    result = subprocess.run(
        [
            cmake,
            "-S",
            str(project),
            "-B",
            str(build),
            "-DAPP_my_app=ON",
            "-DHOLOHUB_BUILD_CPP=OFF",
            "-DHOLOHUB_BUILD_PYTHON=OFF",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (build / "applications/my_app").is_dir()


def test_standalone_python_application_registers_its_tests_without_the_sdk(tmp_path, monkeypatch):
    pytest.importorskip("cookiecutter")
    cmake = shutil.which("cmake")
    ctest = shutil.which("ctest")
    python = sys.executable if sys.version_info >= (3, 12) else shutil.which("python3.12")
    if cmake is None or ctest is None or python is None:
        pytest.skip("CMake and Python 3.12 are required to configure the generated application")
    monkeypatch.chdir(tmp_path)
    cli = SimpleNamespace(HOLOHUB_ROOT=tmp_path, script_name="holoscan")
    create.handle_create(cli, _args(language="python"))
    build = tmp_path / "build"

    def run(*command):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    run(cmake, "-S", str(tmp_path / "my_app"), "-B", str(build), f"-DPython3_EXECUTABLE={python}")
    tests = run(ctest, "--test-dir", str(build), "-N", "-L", "my_app")
    assert "my_app_pipeline" in tests
    assert "my_app_rejects_zero_count" in tests
