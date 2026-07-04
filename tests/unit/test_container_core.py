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

"""Unit tests for ``HoloscanContainer`` image naming + dockerfile resolution.

These pin two pieces of the container layer that were uncovered:

* ``image_name`` / ``image_names`` — the project-tag sanitizer and the
  branch-tag + sha-tag + legacy-tag dedup logic used by ``build`` to
  apply multiple ``-t`` tags on a single ``docker build``.
* ``dockerfile_path`` — the six-step fallback chain used by every
  container subcommand to pick a Dockerfile (metadata override,
  language-specific, source-folder, parent traversal, env, default).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from holoscan_cli.container import core as container_core
from holoscan_cli.container.core import HoloscanContainer

# ---- helpers ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_container_class_attrs(monkeypatch):
    """Pin HoloscanContainer class attrs so individual tests can assert against
    known container/image defaults irrespective of the user's env.
    """
    monkeypatch.setattr(HoloscanContainer, "REPO_PREFIX", "holohub", raising=False)
    monkeypatch.setattr(HoloscanContainer, "CONTAINER_PREFIX", "holohub", raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", "4.2.0", raising=False)
    monkeypatch.setattr(
        HoloscanContainer, "DEFAULT_BASE_IMAGE_NAME", "nvcr.io/x/holoscan", raising=False
    )
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_NAME", "nvcr.io/x/holoscan", raising=False)
    monkeypatch.setattr(
        HoloscanContainer,
        "BASE_IMAGE_FORMAT",
        "{base_image}:v{sdk_version}-{cuda_tag}",
        raising=False,
    )
    monkeypatch.setattr(
        HoloscanContainer,
        "DEFAULT_IMAGE_FORMAT",
        "{container_prefix}:ngc-v{sdk_version}-{cuda_tag}",
        raising=False,
    )


def _stub_container(tmp_path, project_metadata=None, language=None):
    """Build a HoloscanContainer that doesn't print 'No project provided'."""
    if project_metadata is None:
        project_metadata = {"metadata": {"language": "python"}}
    # Anchor HOLOHUB_ROOT (used for relative-path Dockerfile resolution) to
    # a writable tmp path so tests can drop fake Dockerfiles.
    HoloscanContainer.HOLOHUB_ROOT = tmp_path  # type: ignore[assignment]
    return HoloscanContainer(project_metadata=project_metadata, language=language)


# ---- get_project_name -------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Endoscopy Tool Tracking", "endoscopy-tool-tracking"),
        ("UPPER_case_NAME", "upper_case_name"),
        ("with/illegal/chars", "with-illegal-chars"),
        ("---leading-dashes", "leading-dashes"),
        ("collapse--multiple---dashes", "collapse-multiple-dashes"),
        ("", ""),
    ],
)
def test_get_project_name_sanitises(tmp_path, raw, expected, monkeypatch):
    c = _stub_container(tmp_path, project_metadata={"project_name": raw, "metadata": {}})
    assert c.get_project_name() == expected


def test_get_project_name_empty_when_no_metadata(tmp_path):
    HoloscanContainer.HOLOHUB_ROOT = tmp_path  # type: ignore[assignment]
    c = HoloscanContainer(project_metadata=None)
    assert c.get_project_name() == ""


# ---- image_name / image_names ----------------------------------------------


def test_image_name_falls_back_to_default_image_when_dockerfile_is_default(tmp_path, monkeypatch):
    """If the container is using the default Dockerfile, ``image_name`` must
    return the SDK-tagged default image (the same one ``build`` would emit
    from ``default_image``)."""
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    c = _stub_container(tmp_path, project_metadata=None)

    name = c.image_name
    # Default image format: "{container_prefix}:ngc-v{sdk_version}-{cuda_tag}"
    assert name.startswith("holohub:ngc-v4.2.0-cuda13")


def test_default_image_does_not_include_sdk_version_unless_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", None, raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_FORMAT", None, raising=False)
    monkeypatch.setattr(HoloscanContainer, "DEFAULT_IMAGE_FORMAT", None, raising=False)
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")
    c = _stub_container(tmp_path, project_metadata=None)

    assert c.image_name == "holohub:ngc-cuda13"


def test_default_base_image_requires_explicit_base_when_sdk_version_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", None, raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_FORMAT", None, raising=False)
    c = _stub_container(tmp_path, project_metadata=None)

    with pytest.raises(SystemExit):
        c.default_base_image()


def test_default_base_image_uses_explicit_base_image_without_sdk_version(tmp_path, monkeypatch):
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", None, raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_FORMAT", None, raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_NAME", "example.com/base:tag", raising=False)
    c = _stub_container(tmp_path, project_metadata=None)

    assert c.default_base_image() == "example.com/base:tag"


def test_image_name_uses_project_tag_when_dockerfile_is_overridden(tmp_path, monkeypatch):
    """A project-specific Dockerfile must produce a project-tagged image
    even when ``--img`` is not supplied. Dockerfile detection is via
    ``dockerfile_path`` — drop a Dockerfile alongside the project's
    source_folder to trip strategy 3."""
    project_dir = tmp_path / "applications" / "endoscopy_tool_tracking"
    project_dir.mkdir(parents=True)
    (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    metadata = {
        "project_name": "Endoscopy Tool Tracking",
        "source_folder": str(project_dir),
        "metadata": {"language": "python"},
    }
    c = _stub_container(tmp_path, project_metadata=metadata)
    # CONTAINER_PREFIX + sanitized project name → "holohub:endoscopy-tool-tracking"
    assert c.image_name == "holohub:endoscopy-tool-tracking"


def test_image_names_dedupes_when_branch_equals_sha(tmp_path, monkeypatch):
    """``image_names`` must dedupe across (branch_tag, sha_tag, legacy_tag).
    When branch + sha are the same string, the deduper keeps the first."""
    monkeypatch.setattr(container_core, "get_current_branch_slug", lambda: "abc1234")
    monkeypatch.setattr(container_core, "get_git_short_sha", lambda: "abc1234")
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    c = _stub_container(tmp_path)

    names = c.image_names
    # No duplicates.
    assert len(names) == len(set(names))
    # Branch/SHA tag wins the first slot when they collide.
    assert names[0] == "holohub:abc1234"


def test_image_names_produces_branch_sha_and_legacy_tags(tmp_path, monkeypatch):
    """Distinct branch + sha + legacy default-image → three tags."""
    monkeypatch.setattr(container_core, "get_current_branch_slug", lambda: "feature-x")
    monkeypatch.setattr(container_core, "get_git_short_sha", lambda: "abcdef012345")
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    c = _stub_container(tmp_path)

    names = c.image_names
    assert "holohub:feature-x" in names
    assert "holohub:abcdef012345" in names
    # The third (legacy) tag is the format used by build for cache-friendliness.
    assert any(name.startswith("holohub:ngc-v4.2.0-cuda13") for name in names)


def test_image_names_uses_project_repo_when_project_set(tmp_path, monkeypatch):
    """When a project name is set, the repo segment becomes
    ``<container_prefix>-<project>``, not the bare prefix."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    monkeypatch.setattr(container_core, "get_current_branch_slug", lambda: "main")
    monkeypatch.setattr(container_core, "get_git_short_sha", lambda: "0123456789ab")

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    names = c.image_names
    assert "holohub-my_app:main" in names
    assert "holohub-my_app:0123456789ab" in names


# ---- dockerfile_path strategies ---------------------------------------------


def test_dockerfile_path_strategy_5_env_default(tmp_path, monkeypatch):
    """No project metadata → fall back to the
    ``HOLOSCAN_CLI_DEFAULT_DOCKERFILE`` value (resolved at class-load
    time, exposed as ``DEFAULT_DOCKERFILE``)."""
    fake_dockerfile = tmp_path / "MyDockerfile"
    fake_dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr(HoloscanContainer, "DEFAULT_DOCKERFILE", fake_dockerfile, raising=False)
    c = _stub_container(tmp_path, project_metadata=None)

    assert Path(c.dockerfile_path) == fake_dockerfile


def test_dockerfile_path_strategy_1_metadata_override_wins(tmp_path):
    """metadata.json:dockerfile takes priority over folder-search fallbacks."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    # Strategy-3 candidate at applications/my_app/Dockerfile.
    (project_dir / "Dockerfile").write_text("WRONG\n", encoding="utf-8")
    # Strategy-1 candidate explicitly named in metadata.
    explicit = project_dir / "WinningDockerfile"
    explicit.write_text("RIGHT\n", encoding="utf-8")

    metadata = {
        "project_name": "my_app",
        "source_folder": str(project_dir),
        "metadata": {
            "language": "python",
            "dockerfile": str(explicit),
        },
    }
    c = _stub_container(tmp_path, project_metadata=metadata)
    assert Path(c.dockerfile_path) == explicit


def test_dockerfile_path_strategy_2_language_specific(tmp_path):
    """A Dockerfile under ``<source_folder>/<language>/`` wins over the
    bare-source one."""
    project_dir = tmp_path / "applications" / "my_app"
    (project_dir / "python").mkdir(parents=True)
    # Strategy-3 candidate (lower priority).
    (project_dir / "Dockerfile").write_text("WRONG\n", encoding="utf-8")
    # Strategy-2 candidate (higher priority).
    lang_df = project_dir / "python" / "Dockerfile"
    lang_df.write_text("RIGHT\n", encoding="utf-8")

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    assert Path(c.dockerfile_path) == lang_df


def test_dockerfile_path_strategy_3_source_folder(tmp_path):
    """A Dockerfile directly in source_folder wins when no language one
    exists."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    df = project_dir / "Dockerfile"
    df.write_text("RIGHT\n", encoding="utf-8")

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    assert Path(c.dockerfile_path) == df


def test_dockerfile_path_strategy_4_parent_traversal(tmp_path):
    """When neither source_folder nor the language subdir has a Dockerfile,
    walk up to HOLOHUB_ROOT, returning the first Dockerfile found."""
    project_dir = tmp_path / "applications" / "deep" / "my_app"
    project_dir.mkdir(parents=True)
    # Drop a Dockerfile at applications/deep/Dockerfile — the parent of source_folder.
    parent_df = project_dir.parent / "Dockerfile"
    parent_df.write_text("RIGHT\n", encoding="utf-8")

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    assert Path(c.dockerfile_path) == parent_df


def test_dockerfile_path_strategy_6_default_when_no_match(tmp_path, monkeypatch):
    """No metadata Dockerfile, no folder Dockerfile, no parent Dockerfile →
    fall back to DEFAULT_DOCKERFILE."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    fake_default = tmp_path / "Dockerfile"
    fake_default.write_text("DEFAULT\n", encoding="utf-8")
    monkeypatch.setattr(HoloscanContainer, "DEFAULT_DOCKERFILE", fake_default, raising=False)

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    assert Path(c.dockerfile_path) == fake_default


def test_dockerfile_path_metadata_missing_path_falls_through(tmp_path, monkeypatch):
    """If metadata.json:dockerfile points at a non-existent file, the
    resolver must warn and fall through to the folder-search chain rather
    than returning a broken path."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    folder_df = project_dir / "Dockerfile"
    folder_df.write_text("FALLBACK\n", encoding="utf-8")

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {
                "language": "python",
                "dockerfile": str(project_dir / "does-not-exist"),
            },
        },
    )
    assert Path(c.dockerfile_path) == folder_df


# ---- build / run command assembly -------------------------------------------


def test_build_dryrun_emits_base_and_extra_script_layers(tmp_path, monkeypatch):
    """Dry-run container builds still assemble the full docker argv, including
    cache tags and named setup-script layers, without requiring Docker."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    dockerfile = project_dir / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    setup_dir = tmp_path / "utilities" / "setup"
    setup_dir.mkdir(parents=True)
    (setup_dir / "coverage.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (setup_dir / "Dockerfile.util").write_text("FROM scratch\n", encoding="utf-8")

    calls = []
    monkeypatch.setenv("HOLOSCAN_CLI_SETUP_SCRIPTS_DIR", str(setup_dir))
    monkeypatch.setenv("HOLOSCAN_CLI_SOURCE", "/tmp/cli-src")
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    monkeypatch.setattr(container_core, "get_compute_capacity", lambda: "90")
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")
    monkeypatch.setattr(container_core, "get_current_branch_slug", lambda: "feature-x")
    monkeypatch.setattr(container_core, "get_git_short_sha", lambda: "abcdef0")
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "DEFAULT_DOCKER_BUILD_ARGS",
        "--build-arg DEFAULT=1",
        raising=False,
    )
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kwargs: calls.append(cmd))

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True

    c.build(no_cache=True, build_args="--build-arg CUSTOM=1", extra_scripts=["coverage"])

    first = calls[0]
    assert first[:2] == ["docker", "build"]
    assert "--no-cache" in first
    assert "BASE_IMAGE=nvcr.io/x/holoscan:v4.2.0-cuda13" in first
    assert "GPU_TYPE=dgpu" in first
    assert "COMPUTE_CAPACITY=90" in first
    assert "--build-context" in first
    assert "holoscan-cli-src=/tmp/cli-src" in first
    assert "--build-arg" in first
    assert "DEFAULT=1" in first
    assert "CUSTOM=1" in first
    assert "-f" in first
    assert str(dockerfile) in first
    assert "holohub-my_app:feature-x-base" in first

    layer = calls[1]
    assert layer[:2] == ["docker", "build"]
    assert "BASE_IMAGE=holohub-my_app:feature-x" in layer
    assert "SCRIPT=utilities/setup/coverage.sh" in layer
    assert str(setup_dir / "Dockerfile.util") in layer
    assert "holohub-my_app:feature-x-coverage" in layer


def test_build_dryrun_allows_bundled_extra_script_dir(tmp_path, monkeypatch):
    """Bundled setup scripts live outside the source project but can still
    serve as the Docker build context for extra-script layers."""
    root = tmp_path / "project"
    project_dir = root / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    dockerfile = project_dir / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    setup_dir = tmp_path / "package_setup"
    setup_dir.mkdir()
    (setup_dir / "coverage.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (setup_dir / "Dockerfile.util").write_text("FROM scratch\n", encoding="utf-8")

    calls = []
    monkeypatch.setenv("HOLOSCAN_CLI_SETUP_SCRIPTS_DIR", str(setup_dir))
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    monkeypatch.setattr(container_core, "get_compute_capacity", lambda: "90")
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")
    monkeypatch.setattr(container_core, "get_current_branch_slug", lambda: "feature-x")
    monkeypatch.setattr(container_core, "get_git_short_sha", lambda: "abcdef0")
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kwargs: calls.append(cmd))

    c = _stub_container(
        root,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True

    c.build(extra_scripts=["coverage"])

    layer = calls[1]
    assert "SCRIPT=coverage.sh" in layer
    assert str(setup_dir / "Dockerfile.util") in layer
    assert str(setup_dir) in layer


def test_build_dryrun_omits_base_sdk_version_when_not_configured(tmp_path, monkeypatch):
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    dockerfile = project_dir / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")

    calls = []
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", None, raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_FORMAT", None, raising=False)
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    monkeypatch.setattr(container_core, "get_compute_capacity", lambda: "90")
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kwargs: calls.append(cmd))

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True

    c.build(base_img="example.com/base:tag")

    first = calls[0]
    assert "BASE_IMAGE=example.com/base:tag" in first
    assert not any(arg.startswith("BASE_SDK_VERSION=") for arg in first)


def test_run_dryrun_assembles_docker_command_without_runtime_checks(tmp_path, monkeypatch):
    """Dry-run container launch covers docker-run argument composition while
    skipping NVIDIA runtime validation and the real docker command."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    volume = tmp_path / "input-data"
    volume.mkdir()
    calls = []
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("HOLOSCAN_CLI_ENABLE_SCCACHE", raising=False)
    monkeypatch.setenv("NVIDIA_VISIBLE_DEVICES", "0")
    monkeypatch.setenv("NGC_CLI_API_KEY", "secret")
    monkeypatch.setattr(container_core, "get_image_pythonpath", lambda img, dryrun: "/image/python")
    monkeypatch.setattr(container_core, "get_group_id", lambda group: {"video": 44}.get(group))
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kwargs: calls.append(cmd))

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True
    c.verbose = True

    c.run(
        img="custom:image",
        use_tini=True,
        persistent=False,
        as_root=False,
        docker_opts="--name smoke --cidfile /tmp/custom.cid",
        add_volumes=[str(volume)],
        nsys_profile=True,
        nsys_location="/opt/nsys",
        extra_args=["bash", "-lc", "echo ok"],
    )

    cmd = calls[0]
    assert cmd[:2] == ["docker", "run"]
    assert "--interactive" in cmd
    assert cmd.count("--cidfile") == 1
    assert "-u" in cmd
    assert f"{tmp_path}:/workspace/holohub" in cmd
    assert f"{volume}:/workspace/volumes/input-data" in cmd
    assert "NVIDIA_VISIBLE_DEVICES=0" in cmd
    assert "--init" in cmd
    assert "--rm" in cmd
    assert "--group-add" in cmd
    assert "--cap-add=SYS_ADMIN" in cmd
    assert "/opt/nsys:/opt/nvidia/nsys-host" in cmd
    assert (
        "PYTHONPATH=/image/python:/opt/nvidia/holoscan/python/lib:/workspace/holohub/benchmarks/holoscan_flow_benchmarking"
        in cmd
    )
    assert "NGC_CLI_API_KEY" in cmd
    assert "NGC_CLI_ORG=nvidia" in cmd
    assert "--name" in cmd
    assert "/tmp/custom.cid" in cmd
    assert cmd[-4:] == ["custom:image", "bash", "-lc", "echo ok"]


def test_run_default_args_suppression_and_as_root_user_override(tmp_path, monkeypatch):
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    calls = []
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(HoloscanContainer, "DEFAULT_DOCKER_RUN_ARGS", "--name default --detach")
    monkeypatch.setattr(container_core, "get_image_pythonpath", lambda img, dryrun: "")
    monkeypatch.setattr(container_core, "get_group_id", lambda group: None)
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kwargs: calls.append(cmd))
    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True

    c.run(img="custom:image", docker_opts="--network host", include_default_run_args=False)
    c.run(img="custom:image", as_root=True, docker_opts="--user 1234:1234")

    suppressed, elevated = calls
    assert "default" not in suppressed and "--detach" not in suppressed
    assert "--network" in suppressed
    image_index = elevated.index("custom:image")
    assert elevated[image_index - 2 : image_index] == ["--user", "0:0"]


# ---- build-args / cuda forwarding -------------------------------------------
#
# Each of the following pins one piece of build-time argument plumbing that
# the pre-consolidation HoloHub CTest suite exercised end-to-end. They live
# here as unit tests because the assertion is about CLI plumbing, not about
# a real HoloHub tree.


def _stub_build_env(tmp_path, monkeypatch):
    """Shared monkeypatching for the build-args / cuda assertions: drop the
    network / git / SDK probes so we can inspect the assembled `docker build`
    argv in isolation."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    monkeypatch.setattr(container_core, "get_compute_capacity", lambda: "90")
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "12")
    monkeypatch.setattr(container_core, "get_current_branch_slug", lambda: "main")
    monkeypatch.setattr(container_core, "get_git_short_sha", lambda: "deadbee")
    return project_dir


def test_build_forwards_explicit_build_args_to_docker(tmp_path, monkeypatch):
    """`--build-args "--build-arg TEST=value"` must land verbatim in
    `docker build` (pre-consolidation `test_holohub_build_container_build_args`)."""
    project_dir = _stub_build_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True
    c.build(build_args="--build-arg TEST=value")

    cmd = calls[0]
    assert cmd[:2] == ["docker", "build"]
    assert "--build-arg" in cmd
    assert "TEST=value" in cmd


def test_default_docker_build_args_env_propagates_to_docker_build(tmp_path, monkeypatch):
    """`HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS` must merge into the `docker
    build` argv even when the caller passes nothing
    (pre-consolidation `test_holohub_default_docker_build_args_env`)."""
    project_dir = _stub_build_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "DEFAULT_DOCKER_BUILD_ARGS",
        "--build-arg DEFAULT_FLAG=abc",
        raising=False,
    )

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True
    c.build()

    cmd = calls[0]
    assert "--build-arg" in cmd
    assert "DEFAULT_FLAG=abc" in cmd


def test_cuda_version_arg_lands_as_cuda_major_build_arg(tmp_path, monkeypatch):
    """`--cuda 13` propagates to a `CUDA_MAJOR=13` build-arg
    (pre-consolidation `test_holohub_build_container_cuda_version`)."""
    project_dir = _stub_build_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True
    c.build(cuda_version="13")

    cmd = calls[0]
    assert "CUDA_MAJOR=13" in cmd


# ---- run-args / volume forwarding -------------------------------------------


def _stub_run_env(tmp_path, monkeypatch):
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("HOLOSCAN_CLI_ENABLE_SCCACHE", raising=False)
    monkeypatch.setattr(container_core, "get_image_pythonpath", lambda img, dryrun: "/p")
    monkeypatch.setattr(container_core, "get_group_id", lambda g: None)
    return project_dir


def test_add_volume_appears_as_v_mount_in_docker_run(tmp_path, monkeypatch):
    """`--add-volume /some/path` lands as `-v /some/path:/workspace/volumes/...`
    in `docker run` (pre-consolidation `test_holohub_run_container_add_volume`)."""
    project_dir = _stub_run_env(tmp_path, monkeypatch)
    volume = tmp_path / "extra"
    volume.mkdir()
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True
    c.run(img="custom:image", add_volumes=[str(volume)])

    cmd = calls[0]
    assert cmd[:2] == ["docker", "run"]
    expected_mount = f"{volume}:/workspace/volumes/extra"
    assert expected_mount in cmd
    # The mount must follow a `-v` arg.
    idx = cmd.index(expected_mount)
    assert cmd[idx - 1] == "-v"


def test_default_docker_run_args_env_propagates_to_docker_run(tmp_path, monkeypatch):
    """`HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS` must reach the `docker run`
    argv even with no caller-supplied `--docker-opts`
    (pre-consolidation `test_holohub_default_docker_run_args_env`)."""
    project_dir = _stub_run_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "DEFAULT_DOCKER_RUN_ARGS",
        "-e TEST_ENV=123",
        raising=False,
    )

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.dryrun = True
    c.run(img="custom:image")

    cmd = calls[0]
    assert "TEST_ENV=123" in cmd
