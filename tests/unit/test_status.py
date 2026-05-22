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

"""Tests for ``holoscan_cli.status``.

``status.py`` was at 0% coverage after the consolidation. These tests
exercise the collectors and the format_* renderers that ``holoscan
status`` ultimately invokes, faking ``run_info_command`` so we can hand
in deterministic outputs instead of touching the host's real ``docker``
/ ``git`` / GPU state.
"""

import json
from pathlib import Path

import pytest

from holoscan_cli import status as project_status

# ---- collect_platform_info --------------------------------------------------


def test_collect_platform_info_uses_probes(monkeypatch):
    monkeypatch.setattr(project_status, "get_host_arch", lambda: "x86_64")
    monkeypatch.setattr(project_status, "get_host_gpu", lambda: "dGPU")
    monkeypatch.setattr(project_status, "get_gpu_name", lambda: "RTX 4090\nRTX 4090")
    monkeypatch.setattr(project_status, "get_default_cuda_version", lambda: "12.6")
    monkeypatch.setattr(project_status, "get_sdk_version", lambda _path: "3.4.0")

    info = project_status.collect_platform_info()

    assert info.arch == "x86_64"
    assert info.gpu_type == "dGPU"
    # Multi-line GPU name is truncated to the first line.
    assert info.gpu_name == "RTX 4090"
    assert info.cuda_version == "12.6"
    assert info.holoscan_version == "3.4.0"


def test_collect_platform_info_handles_missing_gpu(monkeypatch):
    """When no GPU is detected, ``gpu_name`` is ``None``."""
    monkeypatch.setattr(project_status, "get_host_arch", lambda: "aarch64")
    monkeypatch.setattr(project_status, "get_host_gpu", lambda: "unknown")
    monkeypatch.setattr(project_status, "get_gpu_name", lambda: None)
    monkeypatch.setattr(project_status, "get_default_cuda_version", lambda: "n/a")
    monkeypatch.setattr(project_status, "get_sdk_version", lambda _path: "n/a")

    info = project_status.collect_platform_info()
    assert info.gpu_name is None


# ---- collect_git_info -------------------------------------------------------


def test_collect_git_info_clean_repo(monkeypatch, tmp_path):
    outputs = {
        ("git", "-C", str(tmp_path), "branch", "--show-current"): "main",
        ("git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"): "abc1234",
        ("git", "-C", str(tmp_path), "status", "--porcelain"): "",
    }
    monkeypatch.setattr(project_status, "run_info_command", lambda cmd: outputs.get(tuple(cmd)))

    git = project_status.collect_git_info(tmp_path)
    assert git is not None
    assert git.branch == "main"
    assert git.commit == "abc1234"
    assert git.dirty is False
    assert git.modified_count == 0


def test_collect_git_info_dirty_with_modifications(monkeypatch, tmp_path):
    outputs = {
        ("git", "-C", str(tmp_path), "branch", "--show-current"): "feature",
        ("git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"): "deadbee",
        ("git", "-C", str(tmp_path), "status", "--porcelain"): " M file_a\n?? file_b\n",
    }
    monkeypatch.setattr(project_status, "run_info_command", lambda cmd: outputs.get(tuple(cmd)))

    git = project_status.collect_git_info(tmp_path)
    assert git.dirty is True
    assert git.modified_count == 2


def test_collect_git_info_returns_none_when_not_a_repo(monkeypatch, tmp_path):
    monkeypatch.setattr(project_status, "run_info_command", lambda _cmd: None)
    assert project_status.collect_git_info(tmp_path) is None


def test_collect_git_info_handles_detached_head(monkeypatch, tmp_path):
    """An empty branch-name response means HEAD is detached; status displays it as ``(detached)``."""
    outputs = {
        ("git", "-C", str(tmp_path), "branch", "--show-current"): "",
        ("git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"): "abc1234",
        ("git", "-C", str(tmp_path), "status", "--porcelain"): "",
    }
    monkeypatch.setattr(project_status, "run_info_command", lambda cmd: outputs.get(tuple(cmd)))
    git = project_status.collect_git_info(tmp_path)
    assert git.branch == "(detached)"


# ---- collect_folder_info ----------------------------------------------------


def test_collect_folder_info_skips_non_dirs(tmp_path):
    real_dir = tmp_path / "build"
    real_dir.mkdir()
    (real_dir / "stuff.bin").write_bytes(b"x" * 1024)
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("hi")

    results = project_status.collect_folder_info([real_dir, not_a_dir])
    assert len(results) == 1
    assert results[0].path == str(real_dir)
    assert results[0].size_mb >= 0


def test_collect_folder_info_dedupes_resolved_paths(tmp_path):
    target = tmp_path / "build"
    target.mkdir()
    link = tmp_path / "build_alias"
    link.symlink_to(target)

    results = project_status.collect_folder_info([target, link])
    # Both paths resolve to the same target; only the first is kept.
    assert len(results) == 1


# ---- collect_image_info -----------------------------------------------------


def test_collect_image_info_filters_by_prefix(monkeypatch):
    docker_ps = "holohub-app:latest\timg_id_1"
    docker_images = (
        "img_id_1\tholohub-app:latest\t2 days ago\n"
        "img_id_2\tholohub-tool:dev\t1 week ago\n"
        "img_id_3\trandom/unrelated:1\t1 month ago"
    )

    def fake_run(cmd):
        if "ps" in cmd:
            return docker_ps
        if "images" in cmd:
            return docker_images
        return ""

    monkeypatch.setattr(project_status, "run_info_command", fake_run)
    monkeypatch.delenv("HOLOSCAN_CLI_REPO_PREFIX", raising=False)

    images = project_status.collect_image_info()
    names = [img.image for img in images]
    statuses = {img.image: img.status for img in images}
    assert "holohub-app:latest" in names
    assert "holohub-tool:dev" in names
    assert "random/unrelated:1" not in names
    assert statuses["holohub-app:latest"] == "Running"
    assert statuses["holohub-tool:dev"] == "Stopped"


def test_collect_image_info_empty_when_no_images(monkeypatch):
    monkeypatch.setattr(project_status, "run_info_command", lambda _cmd: None)
    assert project_status.collect_image_info() == []


# ---- collect_docker_disk_usage ----------------------------------------------


def test_collect_docker_disk_usage_summary(monkeypatch):
    monkeypatch.setattr(
        project_status,
        "run_info_command",
        lambda _cmd: "Images\t4.2GB\nContainers\t512MB\nLocal Volumes\t100MB",
    )
    summary = project_status.collect_docker_disk_usage()
    assert summary is not None
    assert "Images: 4.2GB" in summary
    assert "Containers: 512MB" in summary


def test_collect_docker_disk_usage_none_when_docker_missing(monkeypatch):
    monkeypatch.setattr(project_status, "run_info_command", lambda _cmd: None)
    assert project_status.collect_docker_disk_usage() is None


# ---- collect_build_info -----------------------------------------------------


def _make_build_dir(parent: Path, name: str, *, configured: bool = True, generator="make"):
    """Create a build subdirectory that mimics a cmake-configured tree."""
    d = parent / name
    d.mkdir()
    (d / "CMakeCache.txt").write_text("# cmake cache\n")
    if configured:
        if generator == "ninja":
            (d / "build.ninja").write_text("# ninja build file\n")
        else:
            (d / "Makefile").write_text("# Makefile\n")
    return d


def test_collect_build_info_lists_configured_dirs(tmp_path):
    build_root = tmp_path / "build"
    build_root.mkdir()
    _make_build_dir(build_root, "app_a")
    _make_build_dir(build_root, "app_b", generator="ninja")

    builds = project_status.collect_build_info(build_root)
    names = sorted(b.name for b in builds)
    assert names == ["app_a", "app_b"]
    assert all(b.status == "OK" for b in builds)


def test_collect_build_info_marks_unconfigured_as_fail(tmp_path):
    build_root = tmp_path / "build"
    build_root.mkdir()
    _make_build_dir(build_root, "broken", configured=False)

    builds = project_status.collect_build_info(build_root)
    assert builds[0].name == "broken"
    assert builds[0].status == "FAIL"


def test_collect_build_info_skips_hidden_and_non_cmake_dirs(tmp_path):
    build_root = tmp_path / "build"
    build_root.mkdir()
    (build_root / ".cache").mkdir()
    (build_root / "no_cmake").mkdir()

    builds = project_status.collect_build_info(build_root)
    assert builds == []


def test_collect_build_info_returns_empty_for_missing_root(tmp_path):
    assert project_status.collect_build_info(tmp_path / "does_not_exist") == []


# ---- format_status / format_status_json --------------------------------------


def _sample_inputs():
    platform = project_status.PlatformInfo(
        arch="x86_64",
        gpu_type="dGPU",
        gpu_name="RTX 4090",
        cuda_version="12.6",
        holoscan_version="3.4.0",
    )
    git = project_status.GitInfo(branch="main", commit="abc1234", dirty=True, modified_count=3)
    images = [
        project_status.ImageInfo(image="holohub-app:latest", created="2d ago", status="Running"),
        project_status.ImageInfo(image="holohub-tool:dev", created="1w ago", status="Stopped"),
    ]
    builds = [
        project_status.BuildInfo(name="app_a", status="OK", last_modified="5 min ago"),
        project_status.BuildInfo(name="app_b", status="FAIL", last_modified="1 hr ago"),
    ]
    build_folders = [project_status.FolderInfo(path="build", size_mb=1234.5)]
    data_folders = [project_status.FolderInfo(path="data", size_mb=42.0)]
    return platform, git, images, builds, build_folders, data_folders


def test_format_status_includes_all_sections():
    platform, git, images, builds, build_folders, data_folders = _sample_inputs()
    out = project_status.format_status(
        platform, git, images, builds, build_folders, data_folders, docker_disk="Images: 4GB"
    )
    assert "Platform" in out
    assert "x86_64" in out
    assert "RTX 4090" in out
    assert "Git" in out
    assert "main" in out and "abc1234" in out
    assert "3 modified" in out
    assert "Images" in out and "holohub-app:latest" in out
    assert "Docker disk" in out and "Images: 4GB" in out
    assert "Builds" in out and "app_a" in out and "app_b" in out
    assert "Build folders" in out and "Data folders" in out


def test_format_status_handles_empty_images_and_builds():
    platform, git, *_ = _sample_inputs()
    out = project_status.format_status(platform, git, [], [], [], [])
    assert "(none)" in out


def test_format_status_skips_git_when_none():
    platform, _git, images, builds, build_folders, data_folders = _sample_inputs()
    out = project_status.format_status(platform, None, images, builds, build_folders, data_folders)
    assert "Git:" not in out


def test_format_status_json_round_trips():
    platform, git, images, builds, build_folders, data_folders = _sample_inputs()
    out = project_status.format_status_json(
        platform,
        git,
        images,
        builds,
        build_folders,
        data_folders,
        docker_disk="Images: 4GB",
    )
    parsed = json.loads(out)
    assert parsed["platform"]["arch"] == "x86_64"
    assert parsed["git"]["commit"] == "abc1234"
    assert len(parsed["images"]) == 2
    assert len(parsed["builds"]) == 2
    assert parsed["docker_disk"] == "Images: 4GB"


def test_format_status_json_omits_git_when_none():
    platform, _git, images, builds, build_folders, data_folders = _sample_inputs()
    out = project_status.format_status_json(
        platform, None, images, builds, build_folders, data_folders
    )
    parsed = json.loads(out)
    assert parsed["git"] is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
