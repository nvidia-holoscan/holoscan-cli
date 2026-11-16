# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for source-project path placeholders and the original HoloHub names."""

from pathlib import Path

import pytest

from holoscan_cli.utils import holohub, source_project


def test_environment_composition_defers_unknown_references(tmp_path, capsys):
    mode = {"CHAIN": "mode:<CHAIN>", "MODE_VALUE": "value"}
    source_project.update_env(
        mode,
        {
            "CHAIN": "nested:<CHAIN>",
            "APP": "<project_app_bin>",
            "INHERITED": "<HOST_VALUE>",
            "KNOWN": "<MODE_VALUE>",
        },
        preserve_unresolved=True,
    )
    assert mode["CHAIN"] == "nested:mode:<CHAIN>"
    assert mode["APP"] == "<project_app_bin>"
    assert mode["INHERITED"] == "<HOST_VALUE>"
    assert mode["KNOWN"] == "value"
    assert capsys.readouterr().err == ""

    environment = {"CHAIN": "host", "HOST_VALUE": "from-host"}
    source_project.update_env(
        environment, mode, {"project_app_bin": str(tmp_path)}, overwrite=False
    )
    assert environment["CHAIN"] == "nested:mode:host"
    assert environment["APP"] == str(tmp_path)
    assert environment["INHERITED"] == "from-host"


def test_final_environment_expansion_still_reports_missing_variables(capsys):
    environment = {"EXISTING": "value"}
    source_project.update_env(environment, {"UNKNOWN": "prefix:<MISSING>"})
    assert environment["UNKNOWN"] == "prefix:"
    assert "Placeholder <MISSING>" in capsys.readouterr().err


@pytest.mark.parametrize("prefix", ["holohub_", "myrepo_", "project_"])
def test_path_mapping_adds_project_names(tmp_path, prefix):
    root = tmp_path / "repo"
    project = {"source_folder": str(root / "applications" / "app"), "project_name": "app"}

    mapping = source_project.build_path_mapping(root, project, root / "build", prefix=prefix)

    for name in ("root", "data_dir", "app_source", "bin", "app_bin"):
        assert mapping[f"project_{name}"] == mapping[f"{prefix}{name}"]
    assert mapping["project_app_source"] == str(root / "applications" / "app")
    assert mapping["project_app_bin"] == str(root / "build" / "applications" / "app")
    assert source_project.build_path_mapping(root, prefix=prefix)["project_root"] == str(root)


def test_path_mapping_honors_environment_prefix_and_external_source(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLOSCAN_CLI_PATH_PREFIX", "myrepo")
    source_project.resolve_path_prefix.cache_clear()
    try:
        mapping = source_project.build_path_mapping(
            tmp_path / "repo",
            {"source_folder": str(tmp_path / "external"), "project_name": "app"},
            data_dir=tmp_path / "datasets",
        )
        assert (
            mapping["project_data_dir"] == mapping["myrepo_data_dir"] == str(tmp_path / "datasets")
        )
        assert (
            mapping["project_app_bin"]
            == mapping["myrepo_app_bin"]
            == str(tmp_path / "repo" / "build" / "app")
        )
    finally:
        source_project.resolve_path_prefix.cache_clear()


def test_path_mapping_rejects_conflicting_project_namespace(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        source_project.build_path_mapping(
            tmp_path,
            {"source_folder": str(tmp_path / "app")},
            tmp_path / "build",
            prefix="project_app_",
        )
    assert exc.value.code == 1
    assert "conflicts with <project_app_bin>" in capsys.readouterr().err


def test_root_cache_is_shared_with_holohub_alias(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "other").mkdir()
    monkeypatch.setenv("HOLOSCAN_CLI_ROOT", str(root))
    source_project.get_project_root.cache_clear()
    try:
        assert source_project.get_project_root() == root
        monkeypatch.setenv("HOLOSCAN_CLI_ROOT", str(tmp_path / "other"))
        assert holohub.get_holohub_root() == root
        holohub.get_holohub_root.cache_clear()
        assert source_project.get_project_root() == tmp_path / "other"
    finally:
        source_project.get_project_root.cache_clear()


@pytest.mark.parametrize("source", ["override", "repository", "bundled"])
def test_setup_script_lookup_preserves_precedence(tmp_path, monkeypatch, source):
    repo_setup = tmp_path / "utilities" / "setup"
    if source != "bundled":
        repo_setup.mkdir(parents=True)
    monkeypatch.setattr(source_project, "get_project_root", lambda: tmp_path)
    monkeypatch.delenv("HOLOSCAN_CLI_SETUP_SCRIPTS_DIR", raising=False)
    if source == "override":
        expected = tmp_path / "custom-setup"
        monkeypatch.setenv("HOLOSCAN_CLI_SETUP_SCRIPTS_DIR", str(expected))
    elif source == "repository":
        expected = repo_setup
    else:
        expected = Path(source_project.__file__).resolve().parent.parent / "setup_scripts"
    assert source_project.get_setup_scripts_dir() == expected
    assert holohub.get_holohub_setup_scripts_dir() == expected


def test_git_helpers_use_the_source_project_root(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(source_project, "get_project_root", lambda: tmp_path)

    def git_output(cmd, **kwargs):
        calls.append(kwargs["cwd"])
        return "abc123" if "--short=12" in cmd else "feature/source-project"

    monkeypatch.setattr(source_project, "run_info_command", git_output)
    assert source_project.get_git_short_sha() == "abc123"
    assert holohub.get_current_branch_slug() == "feature-source-project"
    assert calls == [str(tmp_path), str(tmp_path)]


def test_holohub_module_keeps_original_names(tmp_path):
    assert holohub.get_holohub_root is source_project.get_project_root
    assert holohub.get_holohub_setup_scripts_dir is source_project.get_setup_scripts_dir
    assert holohub.resolve_path_prefix is source_project.resolve_path_prefix
    assert holohub.update_env is source_project.update_env

    root = tmp_path / "repo"
    project = {"source_folder": str(root / "applications" / "app"), "project_name": "app"}
    build_dir = root / "build" / "app"
    # HoloHub's benchmarking tool passes holohub_root by keyword.
    mapping = holohub.build_holohub_path_mapping(
        holohub_root=root, project_data=project, build_dir=build_dir, prefix="holohub_"
    )

    assert mapping == source_project.build_path_mapping(root, project, build_dir, prefix="holohub_")
    assert mapping["holohub_app_bin"] == str(build_dir / "applications" / "app")
