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

import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from holoscan_cli.configuration import ConfigVectorLayers
from holoscan_cli.container import core as container_core
from holoscan_cli.container.core import HoloscanContainer
from holoscan_cli.project_context import ProjectContext, set_active_project_context

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


def test_tagged_environment_base_image_is_exact_even_with_sdk_version(tmp_path, monkeypatch):
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", "5.0.0", raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_FORMAT", None, raising=False)
    monkeypatch.setattr(
        HoloscanContainer, "BASE_IMAGE_NAME", "example.com/base:reviewed", raising=False
    )

    assert _stub_container(tmp_path).default_base_image("13") == "example.com/base:reviewed"


def test_untagged_environment_base_image_composes_with_sdk_version(tmp_path, monkeypatch):
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", "5.0.0", raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_FORMAT", None, raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_NAME", "example.com/base", raising=False)

    assert _stub_container(tmp_path).default_base_image("13") == "example.com/base:v5.0.0-cuda13"


@pytest.mark.parametrize("base_image", ["", "example.com/image bad"])
def test_configured_base_image_rejects_empty_or_whitespace(tmp_path, monkeypatch, base_image):
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_NAME", base_image, raising=False)

    with pytest.raises(SystemExit):
        _stub_container(tmp_path).default_base_image("13")


def test_standalone_module_reuses_its_resolved_sdk_installation(tmp_path):
    installation = tmp_path / "sdk" / "install-x86_64"
    context = ProjectContext(
        root=tmp_path,
        kind="module",
        discovery="test",
        target_arch="x86_64",
        sdk_root=installation,
        sdk_root_source="tool.holoscan.sdk.search[0]",
    )
    set_active_project_context(context)
    try:
        assert _stub_container(tmp_path).resolve_local_sdk_root(tmp_path / "sdk") == installation
    finally:
        set_active_project_context(None)


def test_standalone_module_rejects_an_unresolved_explicit_sdk_root(tmp_path):
    context = ProjectContext(
        root=tmp_path,
        kind="module",
        discovery="test",
        target_arch="x86_64",
    )
    set_active_project_context(context)
    try:
        with pytest.raises(SystemExit):
            _stub_container(tmp_path).resolve_local_sdk_root(tmp_path / "missing")
    finally:
        set_active_project_context(None)


def test_default_base_image_does_not_probe_host_when_unconfigured(tmp_path, monkeypatch):
    """When nothing is configured the method must fatal *without* probing the
    host GPU. Computing ``cuda_tag`` eagerly used to emit a spurious driver
    warning before the fatal."""
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", None, raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_IMAGE_FORMAT", None, raising=False)

    def _boom(*_args, **_kwargs):
        raise AssertionError("cuda_tag must not be computed on the fatal path")

    monkeypatch.setattr(container_core, "get_cuda_tag", _boom)
    c = _stub_container(tmp_path, project_metadata=None)

    with pytest.raises(SystemExit):
        c.default_base_image()


# ---- _format_image_template validation --------------------------------------


def test_format_image_template_fatals_on_unknown_field():
    """A mistyped placeholder is rejected with a fatal, not a raw KeyError."""
    with pytest.raises(SystemExit):
        HoloscanContainer._format_image_template("{bogus}", base_image="x")


def test_format_image_template_fatals_on_missing_value():
    """A referenced field whose value is unset (e.g. sdk_version) fatals."""
    with pytest.raises(SystemExit):
        HoloscanContainer._format_image_template(
            "{base_image}:v{sdk_version}-{cuda_tag}",
            base_image="x",
            sdk_version=None,
            cuda_tag="cuda13",
        )


def test_format_image_template_allows_escaped_braces():
    """Escaped ``{{...}}`` is a literal, not an ``sdk_version`` placeholder, so it
    must not trigger the missing-value fatal (regression for the old substring
    check)."""
    assert (
        HoloscanContainer._format_image_template("{base_image}:{{sdk_version}}", base_image="x")
        == "x:{sdk_version}"
    )


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


def test_build_display_hides_configured_raw_values_but_exec_argv_keeps_them(tmp_path, monkeypatch):
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    monkeypatch.setattr(container_core, "get_compute_capacity", lambda: "90")
    monkeypatch.setattr(
        container_core,
        "run_command",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )
    container = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    container.dryrun = True

    container.build(build_args="--build-arg TOKEN=secret-value")

    command, kwargs = calls[0]
    assert "TOKEN=secret-value" in command
    assert "TOKEN=secret-value" not in kwargs["display_override"]
    assert any("configured Docker build option" in token for token in kwargs["display_override"])


def test_run_assembles_docker_command_without_ctk_for_custom_runtime(tmp_path, monkeypatch):
    """A custom Docker runtime bypasses NVIDIA Container Toolkit validation."""
    project_dir = tmp_path / "applications" / "my_app"
    project_dir.mkdir(parents=True)
    (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    volume = tmp_path / "input-data"
    volume.mkdir()
    calls = []
    ctk_checks = []
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("HOLOSCAN_CLI_ENABLE_SCCACHE", raising=False)
    monkeypatch.setenv("NVIDIA_VISIBLE_DEVICES", "0")
    monkeypatch.setenv("NGC_CLI_API_KEY", "secret")
    monkeypatch.setattr(container_core, "get_image_pythonpath", lambda img, dryrun: "/image/python")
    monkeypatch.setattr(container_core, "get_group_id", lambda group: {"video": 44}.get(group))

    def record_command(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(container_core, "run_command", record_command)
    monkeypatch.setattr(container_core, "check_nvidia_ctk", lambda: ctk_checks.append(True))

    c = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    c.verbose = True

    c.run(
        img="custom:image",
        use_tini=True,
        persistent=False,
        as_root=False,
        docker_opts="--name smoke --cidfile /tmp/custom.cid --runtime runc",
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
    assert container_core.get_cli_arg_value(cmd, "--runtime") == "runc"
    assert not ctk_checks
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
    internal_cidfile = container_core.get_cli_arg_value(suppressed, "--cidfile")
    assert internal_cidfile is not None
    assert Path(internal_cidfile).name.startswith("holoscan-container-")
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


@pytest.mark.parametrize(
    (
        "project_field",
        "compose_method",
        "mode_kw",
        "cli_kw",
        "flag",
    ),
    [
        (
            "docker_build_args",
            "compose_build_args",
            "mode_build_args",
            "build_args",
            "--build-arg",
        ),
        (
            "docker_run_args",
            "compose_run_args",
            "mode_docker_opts",
            "docker_opts",
            "--env",
        ),
    ],
)
def test_docker_args_compose_project_mode_environment_cli_order(
    tmp_path,
    monkeypatch,
    project_field,
    compose_method,
    mode_kw,
    cli_kw,
    flag,
):
    context = SimpleNamespace(docker_build_args=None, docker_run_args=None)
    setattr(context, project_field, f"{flag} LAYER=project")
    monkeypatch.setattr(container_core, "get_active_project_context", lambda: context)
    env_name = (
        "HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS"
        if project_field == "docker_build_args"
        else "HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS"
    )
    monkeypatch.setenv(env_name, f"{flag} LAYER=environment")
    monkeypatch.setattr(container_core, "activated_environment_source", lambda _name: "environment")
    container = _stub_container(tmp_path)

    result = getattr(container, compose_method)(
        **{
            mode_kw: f"{flag} LAYER=mode",
            cli_kw: f"{flag} LAYER=cli",
        }
    )
    tokens = shlex.split(result)
    values = [tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token == flag]

    assert values == [
        "LAYER=project",
        "LAYER=mode",
        "LAYER=environment",
        "LAYER=cli",
    ]


@pytest.mark.parametrize(
    ("layers", "expected"),
    [
        (
            ConfigVectorLayers(project=False),
            ["LAYER=mode", "LAYER=environment", "LAYER=cli"],
        ),
        (
            ConfigVectorLayers(mode=False),
            ["LAYER=project", "LAYER=environment", "LAYER=cli"],
        ),
        (
            ConfigVectorLayers(project=False, mode=False, environment=False),
            ["LAYER=cli"],
        ),
    ],
)
def test_docker_run_args_honor_layer_scoped_suppression(tmp_path, monkeypatch, layers, expected):
    context = SimpleNamespace(docker_run_args="--env LAYER=project")
    monkeypatch.setattr(container_core, "get_active_project_context", lambda: context)
    monkeypatch.setenv("HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS", "--env LAYER=environment")
    monkeypatch.setattr(container_core, "activated_environment_source", lambda _name: "environment")
    container = _stub_container(tmp_path)
    container.config_layers = layers

    result = container.compose_run_args(
        mode_docker_opts="--env LAYER=mode",
        docker_opts="--env LAYER=cli",
    )
    tokens = shlex.split(result)
    values = [tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token == "--env"]

    assert values == expected


def test_forward_env_honors_project_and_environment_layer_suppression(tmp_path, monkeypatch):
    context = SimpleNamespace(forward_env="PROJECT_TOKEN")
    monkeypatch.setattr(container_core, "get_active_project_context", lambda: context)
    monkeypatch.setenv("HOLOSCAN_CLI_FORWARD_ENV", "ENV_TOKEN")
    monkeypatch.setattr(container_core, "activated_environment_source", lambda _name: "environment")
    container = _stub_container(tmp_path)
    container.config_layers = ConfigVectorLayers(project=False, environment=False)

    assert container.compose_forward_env(forward_env=["CLI_TOKEN"]) == ["CLI_TOKEN"]


@pytest.mark.parametrize(
    ("project_field", "default_attr", "compose_method", "project_args"),
    [
        (
            "docker_build_args",
            "DEFAULT_DOCKER_BUILD_ARGS",
            "compose_build_args",
            "--build-arg PROJECT_ONLY=1",
        ),
        (
            "docker_run_args",
            "DEFAULT_DOCKER_RUN_ARGS",
            "compose_run_args",
            "--env PROJECT_ONLY=1",
        ),
    ],
)
def test_active_project_does_not_reuse_import_time_project_default(
    tmp_path,
    monkeypatch,
    project_field,
    default_attr,
    compose_method,
    project_args,
):
    context = SimpleNamespace(docker_build_args=None, docker_run_args=None)
    setattr(context, project_field, project_args)
    monkeypatch.setattr(container_core, "get_active_project_context", lambda: context)
    monkeypatch.setattr(HoloscanContainer, default_attr, f"{project_args} STALE_IMPORT=1")

    tokens = shlex.split(getattr(_stub_container(tmp_path), compose_method)())

    assert tokens.count("PROJECT_ONLY=1") == 1
    assert "STALE_IMPORT=1" not in tokens


def test_reserved_raw_build_settings_fail_with_typed_guidance(tmp_path, monkeypatch, capsys):
    project_dir = _stub_build_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "detected")
    monkeypatch.setattr(container_core, "get_compute_capacity", lambda: "1.0")
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "DEFAULT_DOCKER_BUILD_ARGS",
        (
            "--build-arg BASE_IMAGE=lower:image --build-arg CUDA_MAJOR=12 "
            "--build-arg GPU_TYPE=explicit --build-arg COMPUTE_CAPACITY=9.0 "
            "--build-arg BASE_SDK_VERSION=explicit"
        ),
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

    with pytest.raises(SystemExit):
        c.build(base_img="cli:image", cuda_version="13")

    assert calls == []
    stderr = capsys.readouterr().err
    assert "BASE_IMAGE" in stderr and "--base-img" in stderr
    assert "CUDA_MAJOR" in stderr and "--cuda" in stderr
    assert "BASE_SDK_VERSION" in stderr and "tool.holoscan.sdk.version" in stderr


def test_detected_build_settings_can_still_be_overridden_raw(tmp_path, monkeypatch):
    project_dir = _stub_build_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "detected")
    monkeypatch.setattr(container_core, "get_compute_capacity", lambda: "1.0")
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "DEFAULT_DOCKER_BUILD_ARGS",
        "--build-arg GPU_TYPE=explicit --build-arg COMPUTE_CAPACITY=9.0",
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

    c.build(base_img="cli:image", cuda_version="13")

    values = [
        calls[0][index + 1] for index, token in enumerate(calls[0][:-1]) if token == "--build-arg"
    ]
    assert values.index("GPU_TYPE=detected") < values.index("GPU_TYPE=explicit")
    assert values.index("COMPUTE_CAPACITY=1.0") < values.index("COMPUTE_CAPACITY=9.0")


def test_replacing_build_args_suppresses_environment_and_project_defaults(tmp_path, monkeypatch):
    project_dir = _stub_build_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "DEFAULT_DOCKER_BUILD_ARGS",
        "--secret id=environment",
    )
    monkeypatch.setattr(
        container_core,
        "get_active_project_context",
        lambda: SimpleNamespace(docker_build_args="--secret id=project"),
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

    c.build(
        mode_build_args="--secret id=mode",
        build_args="--secret id=cli",
        include_default_build_args=False,
    )

    assert "id=cli" in calls[0]
    assert "id=project" not in calls[0]
    assert "id=mode" not in calls[0]
    assert "id=environment" not in calls[0]


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


def test_replacing_run_args_suppresses_environment_and_project_defaults(tmp_path, monkeypatch):
    project_dir = _stub_run_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(container_core, "run_command", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "DEFAULT_DOCKER_RUN_ARGS",
        "--privileged --pid=host",
    )
    monkeypatch.setattr(
        container_core,
        "get_active_project_context",
        lambda: SimpleNamespace(docker_run_args="--network=project"),
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

    c.run(
        img="custom:image",
        mode_docker_opts="--network=mode",
        docker_opts="--network=none",
        include_default_run_args=False,
    )

    assert "--network=none" in calls[0]
    assert "--privileged" not in calls[0]
    assert "--pid=host" not in calls[0]
    assert "--network=project" not in calls[0]
    assert "--network=mode" not in calls[0]


def test_typed_run_lifecycle_flags_follow_lower_raw_conflicts(tmp_path, monkeypatch):
    project_dir = _stub_run_env(tmp_path, monkeypatch)
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

    c.run(
        img="custom:image",
        use_tini=True,
        persistent=True,
        docker_opts="--rm --init=false",
        include_default_run_args=False,
    )

    cmd = calls[0]
    assert cmd.index("--rm") < cmd.index("--rm=false")
    assert cmd.index("--init=false") < cmd.index("--init")


def test_run_display_hides_configured_raw_values_but_exec_argv_keeps_them(tmp_path, monkeypatch):
    project_dir = _stub_run_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        container_core,
        "run_command",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )
    container = _stub_container(
        tmp_path,
        project_metadata={
            "project_name": "my_app",
            "source_folder": str(project_dir),
            "metadata": {"language": "python"},
        },
    )
    container.dryrun = True

    container.run(
        img="custom:image",
        docker_opts="--env TOKEN=secret-value",
        include_default_run_args=False,
        extra_args=["-c", "holoscan build app --configure-args=-DAPI_TOKEN=cmake-secret"],
    )

    command, kwargs = calls[0]
    assert "TOKEN=secret-value" in command
    assert any("cmake-secret" in token for token in command)
    assert "TOKEN=secret-value" not in kwargs["display_override"]
    assert all("cmake-secret" not in token for token in kwargs["display_override"])
    assert any("configured Docker run option" in token for token in kwargs["display_override"])
    assert any("configured CMake option hidden" in token for token in kwargs["display_override"])


def test_project_forward_env_uses_name_only_and_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "HOLOSCAN_CLI_FORWARD_ENV",
        "FORWARDED_SECRET,FORWARDED_SECRET",
    )
    monkeypatch.setenv("FORWARDED_SECRET", "do-not-print-me")
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "false")

    args = _stub_container(tmp_path).get_environment_args()

    assert args.count("FORWARDED_SECRET") == 1
    assert args[args.index("FORWARDED_SECRET") - 1] == "-e"
    assert all("do-not-print-me" not in arg for arg in args)


def test_cli_forward_env_can_replace_project_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLOSCAN_CLI_FORWARD_ENV", "PROJECT_TOKEN")
    monkeypatch.setenv("PROJECT_TOKEN", "project-secret")
    monkeypatch.setenv("CLI_TOKEN", "cli-secret")
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "false")

    args = _stub_container(tmp_path).get_environment_args(
        forward_env=["CLI_TOKEN"], include_default_forward_env=False
    )

    assert "CLI_TOKEN" in args
    assert "PROJECT_TOKEN" not in args
    assert all("secret" not in arg for arg in args)


def test_forward_env_accumulates_project_environment_and_cli_names(tmp_path, monkeypatch):
    monkeypatch.setattr(
        container_core,
        "get_active_project_context",
        lambda: SimpleNamespace(forward_env="PROJECT_TOKEN,SHARED_TOKEN"),
    )
    monkeypatch.setattr(container_core, "activated_environment_source", lambda _name: None)
    monkeypatch.setenv("HOLOSCAN_CLI_FORWARD_ENV", "ENV_TOKEN,SHARED_TOKEN")
    for name in ("PROJECT_TOKEN", "ENV_TOKEN", "CLI_TOKEN", "SHARED_TOKEN"):
        monkeypatch.setenv(name, "not-printed")
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "false")

    args = _stub_container(tmp_path).get_environment_args(forward_env=["CLI_TOKEN"])
    forwarded = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-e"]

    assert forwarded.index("PROJECT_TOKEN") < forwarded.index("ENV_TOKEN")
    assert forwarded.index("ENV_TOKEN") < forwarded.index("CLI_TOKEN")
    assert forwarded.count("SHARED_TOKEN") == 1
    assert all("not-printed" not in arg for arg in args)


@pytest.mark.parametrize(
    ("configured", "message"),
    [
        ("VALID_NAME,NOT-A-NAME", "invalid environment variable name: 'NOT-A-NAME'"),
        ("HOME", "CLI-owned container environment invariant"),
    ],
)
def test_project_forward_env_rejects_invalid_effective_name(
    tmp_path, monkeypatch, capsys, configured, message
):
    monkeypatch.setenv("HOLOSCAN_CLI_FORWARD_ENV", configured)
    monkeypatch.setenv("VALID_NAME", "value")
    monkeypatch.setenv("HOME", "/host/home")

    with pytest.raises(SystemExit):
        _stub_container(tmp_path).get_environment_args()

    assert message in capsys.readouterr().err


def test_project_forward_env_deduplicates_enabled_sccache(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLOSCAN_CLI_FORWARD_ENV", "SCCACHE_BUCKET,SCCACHE_DIR,SCCACHE_BUCKET")
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "true")
    monkeypatch.setenv("SCCACHE_BUCKET", "holoscan-cache")
    monkeypatch.setenv("SCCACHE_DIR", "/host/sccache")

    args = _stub_container(tmp_path).get_environment_args()

    assert args.count("SCCACHE_BUCKET") == 1
    assert "SCCACHE_DIR" not in args
    assert args.count(f"SCCACHE_DIR={container_core.SCCACHE_CONTAINER_DIR}") == 1
    assert all("/host/sccache" not in arg for arg in args)


def test_project_forward_env_avoids_conflicting_sccache_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOLOSCAN_CLI_FORWARD_ENV", "SCCACHE_BUCKET")
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "false")
    monkeypatch.setenv("SCCACHE_BUCKET", "holoscan-cache")
    monkeypatch.setenv("SCCACHE_ENDPOINT", "cache.example.test")

    args = _stub_container(tmp_path).get_environment_args()
    stderr = capsys.readouterr().err

    assert args.count("SCCACHE_BUCKET") == 1
    assert "SCCACHE_ENDPOINT" in stderr
    assert "SCCACHE_BUCKET" not in stderr


@pytest.mark.parametrize("dryrun", [True, False])
def test_get_volume_args_only_creates_sccache_dir_for_real_run(tmp_path, monkeypatch, dryrun):
    sccache_dir = tmp_path / "sccache-cache"
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "true")
    monkeypatch.setenv("SCCACHE_DIR", str(sccache_dir))

    c = _stub_container(tmp_path)
    c.dryrun = dryrun
    args = c.get_volume_args(add_volumes=[], enable_mps=False)

    assert sccache_dir.exists() == (not dryrun)
    assert f"{sccache_dir}:{container_core.SCCACHE_CONTAINER_DIR}" in args
