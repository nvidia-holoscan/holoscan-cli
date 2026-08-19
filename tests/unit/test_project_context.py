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
    clean_environment = {
        name: value for name, value in os.environ.items() if not name.startswith("HOLOSCAN_CLI_")
    }
    return {**clean_environment, "PYTHONPATH": str(source)}


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


def test_unrecognized_environment_root_warns_and_falls_back_to_cwd(tmp_path):
    module = _write_module(tmp_path / "module", required_version=get_running_cli_version())
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()

    context = discover_project_context(
        cwd=module,
        environ={"HOLOSCAN_CLI_ROOT": str(arbitrary)},
    )

    assert context.root == module
    assert context.discovery == "ancestor"
    assert context.warnings == (
        f"Ignoring HOLOSCAN_CLI_ROOT={str(arbitrary)!r}: not a recognized Holoscan "
        "source-project or Module root; discovering from cwd.",
    )


def test_module_profile_sets_defaults_but_preserves_explicit_environment(tmp_path, monkeypatch):
    root = _write_module(tmp_path / "module", required_version=get_running_cli_version())
    context = discover_project_context(cwd=root, environ={})
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("HOLOSCAN_CLI_ROOT", raising=False)
    monkeypatch.setenv("HOLOSCAN_CLI_DATA_DIR", "/explicit/data")
    for name in (
        "HOLOSCAN_CLI_BUILD_PARENT_DIR",
        "HOLOSCAN_CLI_SEARCH_PATH",
        "HOLOSCAN_CLI_REPO_PREFIX",
        "HOLOSCAN_CLI_CONTAINER_PREFIX",
        "HOLOSCAN_CLI_WORKSPACE_NAME",
        "HOLOSCAN_CLI_HOSTNAME_PREFIX",
        "HOLOSCAN_CLI_BASE_SDK_VERSION",
        "HOLOSCAN_CLI_PATH_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)

    activate_project_context(context)

    assert os.environ["HOLOSCAN_CLI_ROOT"] == str(root)
    assert os.environ["HOLOSCAN_CLI_BUILD_PARENT_DIR"] == str(root / "build")
    assert os.environ["HOLOSCAN_CLI_DATA_DIR"] == "/explicit/data"
    assert os.environ["HOLOSCAN_CLI_REPO_PREFIX"] == "my_sensor"
    assert os.environ["HOLOSCAN_CLI_CONTAINER_PREFIX"] == "my-sensor"
    assert os.environ["HOLOSCAN_CLI_SEARCH_PATH"].startswith("metadata.json,applications")
    assert "HOLOSCAN_CLI_PATH_PREFIX" not in os.environ


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


def test_legacy_module_launcher_remains_unlocked(tmp_path):
    root = _write_module(tmp_path / "module", launcher="holohub")
    context = discover_project_context(cwd=root, environ={}, running_version="1.0.0")

    enforce_project_requirement(context)

    assert context.is_module
    assert context.legacy_launcher
    assert not context.is_standalone_module


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


def test_package_version_alias_does_not_discover_a_broken_project(tmp_path):
    (tmp_path / "metadata.json").write_text(
        json.dumps({"module": {"name": "broken", "namespace": []}}),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, "-m", "holoscan_cli", "--version"],
        check=True,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )

    assert "Version:" in proc.stdout
    assert "Project error:" not in proc.stdout
    assert proc.stderr == ""


def test_version_reports_project_discovery_error_as_data(tmp_path):
    (tmp_path / "metadata.json").write_text(
        json.dumps({"module": {"name": "broken", "namespace": []}}),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, "-m", "holoscan_cli", "version", "--json"],
        check=True,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=tmp_path,
    )

    payload = json.loads(proc.stdout)
    assert "invalid module.namespace" in payload["project_error"]
    assert "invalid module.namespace" in proc.stderr


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


def test_create_ignores_enclosing_module_requirement(tmp_path):
    root = _write_module(tmp_path / "module", required_version="999.0.0")
    child_output = tmp_path / "children"
    distribution_root = tmp_path / "installed-metadata"
    dist_info = distribution_root / "holoscan_cli-5.0.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: holoscan-cli\nVersion: 5.0.0\n",
        encoding="utf-8",
    )
    environment = _subprocess_env()
    environment["PYTHONPATH"] = os.pathsep.join((str(distribution_root), environment["PYTHONPATH"]))

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
        env=environment,
        cwd=root,
    )

    assert proc.returncode == 0
    assert "Would create project folder" in proc.stdout
    assert "requires holoscan-cli" not in proc.stderr
    assert not child_output.exists()
