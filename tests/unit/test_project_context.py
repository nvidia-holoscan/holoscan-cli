# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from holoscan_cli.project_context import (
    ProjectContextError,
    ProjectVersionError,
    _is_container,
    activate_project_context,
    discover_project_context,
    enforce_project_requirement,
    get_running_cli_version,
    parse_cli_requirement,
)


def _write_module(
    root: Path,
    *,
    required_version: str | None = None,
    full_layout: bool = True,
    launcher: str | None = None,
    pyproject: str | None = None,
) -> Path:
    root.mkdir(parents=True)
    metadata = {
        "module": {
            "name": "holoscan-my-sensor",
            "namespace": {"python": "holoscan.my_sensor"},
            "holoscan_sdk": {"minimum_required_version": "4.6.0"},
            "dockerfile": "Dockerfile",
        }
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    if pyproject is not None:
        (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    if full_layout:
        (root / "applications").mkdir()
        (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    if required_version is not None:
        (root / "requirements-cli.txt").write_text(
            f"# generated\nholoscan-cli=={required_version}\n", encoding="utf-8"
        )
    if launcher:
        (root / launcher).write_text("#!/bin/sh\n", encoding="utf-8")
    return root


def _subprocess_env() -> dict[str, str]:
    source = Path(__file__).resolve().parents[2] / "src"
    return {**os.environ, "PYTHONPATH": str(source)}


def _track_absent_env(monkeypatch, names) -> None:
    """Let monkeypatch restore keys that production activation sets directly."""
    for name in names:
        monkeypatch.setenv(name, "__pytest_restore_absent__")
        os.environ.pop(name)


def test_requirement_parser_accepts_comments_and_one_exact_pin(tmp_path):
    requirement = tmp_path / "requirements-cli.txt"
    requirement.write_text(
        "# resolver hint\n\n  holoscan-cli==5.0.0a123+branch.1  \n", encoding="utf-8"
    )

    assert parse_cli_requirement(requirement) == "5.0.0a123+branch.1"


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "holoscan-cli>=4.6\n",
        "holoscan-cli[create]==4.6.0\n",
        "holoscan-cli @ git+https://example.invalid/repo\n",
        "--extra-index-url https://example.invalid\nholoscan-cli==4.6.0\n",
        "holoscan-cli==4.6.0; python_version > '3.10'\n",
        "holoscan-cli==4.6.0\nholoscan-cli==4.6.1\n",
    ],
)
def test_requirement_parser_rejects_non_contract_content(tmp_path, contents):
    requirement = tmp_path / "requirements-cli.txt"
    requirement.write_text(contents, encoding="utf-8")

    with pytest.raises(ProjectContextError):
        parse_cli_requirement(requirement)


def test_full_module_is_discovered_from_descendant(tmp_path):
    root = _write_module(
        tmp_path / "holoscan-my-sensor", required_version=get_running_cli_version()
    )
    descendant = root / "applications" / "pipeline" / "python"
    descendant.mkdir(parents=True)

    context = discover_project_context(cwd=descendant, environ={})

    assert context.root == root
    assert context.is_standalone_module
    assert context.repo_prefix == "my_sensor"
    assert context.container_prefix == "my-sensor"
    assert context.base_sdk_version == "4.6.0"


def test_metadata_only_nested_module_does_not_steal_holohub_root(tmp_path):
    holohub = tmp_path / "holohub"
    (holohub / "applications").mkdir(parents=True)
    (holohub / "holohub").write_text("#!/bin/sh\n", encoding="utf-8")
    nested = _write_module(
        holohub / "modules" / "holoscan-my-sensor",
        required_version=get_running_cli_version(),
        full_layout=False,
    )

    implicit = discover_project_context(cwd=nested, environ={})
    explicit = discover_project_context(cwd=tmp_path, explicit_root=nested, environ={})

    assert implicit.root == holohub
    assert implicit.kind == "source"
    assert explicit.root == nested
    assert explicit.is_standalone_module


def test_explicit_project_root_precedes_environment(tmp_path):
    selected = _write_module(tmp_path / "selected", required_version=get_running_cli_version())
    other = tmp_path / "other"
    other.mkdir()

    context = discover_project_context(
        cwd=tmp_path,
        explicit_root=selected,
        environ={"HOLOSCAN_CLI_ROOT": str(other)},
    )

    assert context.root == selected
    assert context.discovery == "project-root"


def test_invalid_explicit_project_root_is_specific(tmp_path):
    with pytest.raises(ProjectContextError, match="--project-root"):
        discover_project_context(cwd=tmp_path, explicit_root=tmp_path / "missing", environ={})


def test_module_profile_sets_defaults_but_preserves_explicit_environment(tmp_path, monkeypatch):
    root = _write_module(tmp_path / "module", required_version=get_running_cli_version())
    context = discover_project_context(cwd=root, environ={})
    _track_absent_env(monkeypatch, context.profile_environment())
    monkeypatch.setenv("HOLOSCAN_CLI_DATA_DIR", "/explicit/data")
    monkeypatch.delenv("HOLOSCAN_CLI_PATH_PREFIX", raising=False)

    activate_project_context(context)

    assert os.environ["HOLOSCAN_CLI_ROOT"] == str(root)
    assert os.environ["HOLOSCAN_CLI_BUILD_PARENT_DIR"] == str(root / "build")
    assert os.environ["HOLOSCAN_CLI_DATA_DIR"] == "/explicit/data"
    assert os.environ["HOLOSCAN_CLI_REPO_PREFIX"] == "my_sensor"
    assert os.environ["HOLOSCAN_CLI_CONTAINER_PREFIX"] == "my-sensor"
    assert os.environ["HOLOSCAN_CLI_SEARCH_PATH"].startswith("metadata.json,applications")
    assert "HOLOSCAN_CLI_PATH_PREFIX" not in os.environ


def test_pyproject_config_replaces_wrapper_defaults(tmp_path, monkeypatch):
    root = _write_module(
        tmp_path / "module",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1
repo-prefix = "holoscan_5_0_ea_samples"
container-prefix = "holoscan-5-0-ea-samples"
workspace-name = "holoscan-5-0-ea-samples"
hostname-prefix = "holoscan-5-0-ea-samples"
search-path = ["."]
build-type = "Release"
ctest-script = "cmake/project.ctest"
cuda = 13

[tool.holoscan.sdk]
version = "5.0.0"
search = ["../sdk/install-{arch}"]
allow-parent-search = true
mount-read-only = true

[tool.holoscan.sdk.base-images]
x86_64 = "sdk-build-x86_64:fixed"
aarch64 = "sdk-build-aarch64:fixed"
""",
    )
    (root / "cmake").mkdir()
    (root / "cmake" / "project.ctest").write_text("# test\n", encoding="utf-8")
    sdk = root.parent / "sdk" / "install-aarch64"
    cmake_dir = sdk / "lib" / "cmake" / "holoscan"
    cmake_dir.mkdir(parents=True)
    (cmake_dir / "holoscan-config.cmake").write_text("# config\n", encoding="utf-8")
    monkeypatch.setattr("holoscan_cli.project_context.platform.machine", lambda: "arm64")

    context = discover_project_context(cwd=root, environ={})

    assert context.project_config_path == root / "pyproject.toml"
    assert context.project_config_schema_version == 1
    assert context.target_arch == "aarch64"
    assert context.target_arch_source == "host"
    assert context.repo_prefix == "holoscan_5_0_ea_samples"
    assert context.container_prefix == "holoscan-5-0-ea-samples"
    assert context.workspace_name == "holoscan-5-0-ea-samples"
    assert context.base_sdk_version == "5.0.0"
    assert context.base_image == "sdk-build-aarch64:fixed"
    assert context.default_cuda_version == "13"
    assert context.sdk_root == sdk.resolve()
    assert context.sdk_root_source.endswith("tool.holoscan.sdk.search[0]")
    assert context.sdk_mount_read_only
    assert context.ctest_script == "cmake/project.ctest"
    assert context.build_type == "Release"

    _track_absent_env(monkeypatch, context.profile_environment())
    activate_project_context(context)

    assert os.environ["HOLOSCAN_CLI_BASE_IMAGE"] == "sdk-build-aarch64:fixed"
    assert os.environ["HOLOSCAN_CLI_BASE_IMAGE_FORMAT"] == "{base_image}"
    assert os.environ["HOLOSCAN_CLI_DEFAULT_CUDA_VERSION"] == "13"
    assert os.environ["HOLOSCAN_CLI_DEFAULT_HSDK_DIR"] == str(sdk.resolve())
    assert os.environ["HOLOSCAN_SDK_ROOT"] == str(sdk.resolve())
    assert os.environ["holoscan_ROOT"] == str(sdk.resolve())
    assert os.environ["HOLOSCAN_CLI_CTEST_SCRIPT"] == "cmake/project.ctest"
    assert os.environ["CMAKE_BUILD_TYPE"] == "Release"
    assert os.environ["HOLOSCAN_CLI_TARGET_ARCH"] == "aarch64"
    assert os.environ["HOLOSCAN_CLI_SDK_MOUNT_READ_ONLY"] == "1"


def test_unknown_pyproject_config_field_fails_closed(tmp_path):
    root = _write_module(
        tmp_path / "module",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1
cdua = 13
""",
    )

    with pytest.raises(ProjectContextError, match="unknown field.*cdua"):
        discover_project_context(cwd=root, environ={})


def test_pyproject_config_requires_supported_schema_version(tmp_path):
    root = _write_module(
        tmp_path / "module",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 999
""",
    )

    with pytest.raises(ProjectContextError, match="unsupported.*schema-version 999"):
        discover_project_context(cwd=root, environ={})


def test_invalid_explicit_sdk_root_fails_instead_of_falling_back(tmp_path):
    root = _write_module(
        tmp_path / "module",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1

[tool.holoscan.sdk]
search = ["../sdk/install-{arch}"]
allow-parent-search = true
""",
    )
    sdk = root.parent / "sdk" / "install-x86_64" / "lib" / "cmake" / "holoscan"
    sdk.mkdir(parents=True)
    (sdk / "holoscan-config.cmake").write_text("# config\n", encoding="utf-8")

    with pytest.raises(ProjectContextError, match="HOLOSCAN_SDK_ROOT.*not a valid"):
        discover_project_context(
            cwd=root,
            environ={"HOLOSCAN_SDK_ROOT": str(root.parent / "missing")},
        )


def test_explicit_sdk_parent_selects_arch_and_configured_cuda_without_shell(tmp_path):
    root = _write_module(
        tmp_path / "module",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1
cuda = 13
""",
    )
    sdk_root = tmp_path / "sdk"
    sdk = sdk_root / "install-cu13-x86_64"
    cmake_dir = sdk / "lib" / "cmake" / "holoscan"
    cmake_dir.mkdir(parents=True)
    (cmake_dir / "holoscan-config.cmake").write_text("# config\n", encoding="utf-8")

    context = discover_project_context(
        cwd=root,
        environ={"HOLOSCAN_SDK_ROOT": str(sdk_root)},
    )

    assert context.sdk_root == sdk.resolve()
    assert context.sdk_root_source == "HOLOSCAN_SDK_ROOT"


def test_committed_sdk_search_rejects_absolute_and_unbounded_paths(tmp_path):
    absolute = _write_module(
        tmp_path / "absolute",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1

[tool.holoscan.sdk]
search = ["/opt/nvidia/holoscan"]
""",
    )
    with pytest.raises(ProjectContextError, match="must be relative"):
        discover_project_context(cwd=absolute, environ={})

    unbounded = _write_module(
        tmp_path / "nested" / "unbounded",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1

[tool.holoscan.sdk]
search = ["../../sdk"]
allow-parent-search = true
""",
    )
    with pytest.raises(ProjectContextError, match="outside its allowed boundary"):
        discover_project_context(cwd=unbounded, environ={})


def test_target_arch_environment_selects_an_explicit_image_profile(tmp_path):
    root = _write_module(
        tmp_path / "module",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1

[tool.holoscan.sdk.base-images]
x86_64 = "sdk-build-x86_64:fixed"
aarch64 = "sdk-build-aarch64:fixed"
""",
    )

    context = discover_project_context(
        cwd=root,
        environ={"HOLOSCAN_CLI_TARGET_ARCH": "arm64"},
    )

    assert context.target_arch == "aarch64"
    assert context.target_arch_source == "HOLOSCAN_CLI_TARGET_ARCH"
    assert context.base_image == "sdk-build-aarch64:fixed"


def test_project_config_rejects_image_reference_with_shell_whitespace(tmp_path):
    root = _write_module(
        tmp_path / "module",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1

[tool.holoscan.sdk.base-images]
x86_64 = "sdk-build-x86_64:fixed --pull"
aarch64 = "sdk-build-aarch64:fixed"
""",
    )

    with pytest.raises(ProjectContextError, match="image reference without whitespace"):
        discover_project_context(cwd=root, environ={})


def test_container_recursion_resolves_the_stable_sdk_mount(tmp_path, monkeypatch):
    root = _write_module(
        tmp_path / "module",
        required_version=get_running_cli_version(),
        pyproject="""
[tool.holoscan]
schema-version = 1
""",
    )
    mounted_sdk = Path("/workspace/holoscan-sdk")
    monkeypatch.setattr(
        "holoscan_cli.project_context._resolve_sdk_installation",
        lambda path, _arch, _cuda=None: mounted_sdk if path == mounted_sdk else None,
    )

    context = discover_project_context(
        cwd=root,
        environ={"HOLOSCAN_CLI_BUILD_LOCAL": "1"},
    )

    assert context.sdk_root == mounted_sdk
    assert context.sdk_root_source == "container:/workspace/holoscan-sdk"


def test_host_requirement_mismatch_has_install_guidance(tmp_path):
    root = _write_module(tmp_path / "module", required_version="999.0.0")
    context = discover_project_context(cwd=root, environ={}, running_version="1.0.0")

    with pytest.raises(ProjectVersionError) as exc_info:
        enforce_project_requirement(context, in_container=False)

    message = str(exc_info.value)
    assert "requires holoscan-cli==999.0.0" in message
    assert "python" in message.lower()
    assert "-m pip install -r" in message


def test_container_requirement_mismatch_never_installs(tmp_path):
    root = _write_module(tmp_path / "module", required_version="999.0.0")
    context = discover_project_context(cwd=root, environ={}, running_version="1.0.0")

    with pytest.raises(ProjectVersionError) as exc_info:
        enforce_project_requirement(context, in_container=True)

    message = str(exc_info.value)
    assert "Rebuild the development image" in message
    assert "will not install or modify" in message
    assert "pip install" not in message


def test_container_guidance_uses_cli_recursion_marker(monkeypatch):
    monkeypatch.delenv("HOLOSCAN_CLI_BUILD_LOCAL", raising=False)
    assert not _is_container()

    monkeypatch.setenv("HOLOSCAN_CLI_BUILD_LOCAL", "1")
    assert _is_container()

    monkeypatch.setenv("HOLOSCAN_CLI_BUILD_LOCAL", "false")
    assert not _is_container()


def test_launcher_file_does_not_disable_module_contract(tmp_path):
    root = _write_module(tmp_path / "module", launcher="holohub")
    context = discover_project_context(cwd=root, environ={}, running_version="1.0.0")

    with pytest.raises(ProjectVersionError, match="missing requirements-cli.txt"):
        enforce_project_requirement(context)

    assert context.is_module
    assert context.is_standalone_module


def test_main_and_registry_imports_preserve_profile_barrier():
    blocked = (
        "holoscan_cli.cli",
        "holoscan_cli.container.core",
        "holoscan_cli.utils.holohub",
    )
    script = (
        "import sys; import holoscan_cli.__main__; import holoscan_cli.commands.registry; "
        f"blocked={blocked!r}; "
        "assert not [name for name in blocked if name in sys.modules]"
    )

    subprocess.run([sys.executable, "-c", script], check=True, env=_subprocess_env())


def test_project_root_must_precede_subcommand(tmp_path):
    root = _write_module(tmp_path / "module", required_version=get_running_cli_version())

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            "list",
            "--project-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )

    assert proc.returncode == 2
    assert "global option" in proc.stderr
    assert "before 'list'" in proc.stderr


def test_fresh_dispatch_activates_profile_before_cli_import(tmp_path):
    root = _write_module(tmp_path / "module", required_version=get_running_cli_version())

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            "--project-root",
            str(root),
            "list",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )
    payload = json.loads(proc.stdout)

    module = next(project for project in payload["projects"] if project["project_type"] == "module")
    assert module["source_folder"] == str(root)


def test_version_reports_mismatch_without_blocking(tmp_path):
    root = _write_module(tmp_path / "module", required_version="999.0.0")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            "--project-root",
            str(root),
            "version",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )
    payload = json.loads(proc.stdout)

    assert payload["required_version"] == "999.0.0"
    assert payload["version_match"] is False
    assert payload["project"]["target_arch_source"] == "host"


def test_project_root_equals_form_works_for_native_version(tmp_path):
    root = _write_module(tmp_path / "module", required_version=get_running_cli_version())

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            f"--project-root={root}",
            "version",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )

    assert json.loads(proc.stdout)["project_root"] == str(root)


@pytest.mark.parametrize(
    "tail,error",
    [
        (["--project-root", "version"], "requires a non-empty directory path"),
        (
            ["--project-root", "one", "--project-root", "two", "version"],
            "specified only once",
        ),
    ],
)
def test_project_root_missing_and_duplicate_values_are_targeted(tmp_path, tail, error):
    proc = subprocess.run(
        [sys.executable, "-m", "holoscan_cli", *tail],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )

    assert proc.returncode == 2
    assert error in proc.stderr


def test_project_help_is_available_during_version_mismatch(tmp_path):
    root = _write_module(tmp_path / "module", required_version="999.0.0")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            "--project-root",
            str(root),
            "list",
            "--help",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )

    assert proc.returncode == 0
    assert "requires holoscan-cli" not in proc.stderr


def test_lifecycle_command_fails_before_work_on_version_mismatch(tmp_path):
    root = _write_module(tmp_path / "module", required_version="999.0.0")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            "--project-root",
            str(root),
            "list",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )

    assert proc.returncode == 1
    assert "requires holoscan-cli==999.0.0" in proc.stderr
    assert '"projects"' not in proc.stdout


def test_create_ignores_enclosing_requirement_before_source_version_validation(tmp_path):
    root = _write_module(tmp_path / "module", required_version="999.0.0")
    child_output = tmp_path / "children"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "holoscan_cli",
            "create",
            "Child Module",
            "--interactive",
            "false",
            "--dryrun",
            "--directory",
            str(child_output),
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=root,
    )

    assert proc.returncode == 1
    assert "cannot generate an installable Module contract" in proc.stderr
    assert "requires holoscan-cli==999.0.0" not in proc.stderr
    assert not child_output.exists()
