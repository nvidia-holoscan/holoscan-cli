# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from argparse import Namespace

from holoscan_cli.configuration import (
    ConfigVectorLayers,
    apply_container_cli_overrides,
    get_config_vector_layers,
    report_effective_configuration,
    resolve_cli_docker_opts,
)
from holoscan_cli.project_context import (
    ProjectContext,
    activate_project_context,
    set_active_project_context,
)


def test_verbose_provenance_reports_sources_and_hides_opaque_values(tmp_path, monkeypatch, capsys):
    context = ProjectContext(
        root=tmp_path,
        kind="module",
        discovery="test",
        build_type="Release",
        default_cuda_version="13",
        default_cuda_version_source=f"{tmp_path}/pyproject.toml:tool.holoscan.cuda",
        docker_build_args="--build-arg PROJECT_SECRET=project-value",
        docker_run_args="--env PROJECT_TOKEN=project-value",
        forward_env="PROJECT_TOKEN",
    )
    activate_project_context(context)
    try:
        # Restore the bridged project values before clearing the active context;
        # otherwise pytest's environment rollback would resurrect an untracked
        # project value after set_active_project_context(None).
        with monkeypatch.context() as env_patch:
            env_patch.setenv("CMAKE_BUILD_TYPE", "Debug")
            env_patch.setenv(
                "HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS",
                "--build-arg ENV_SECRET=environment-value",
            )
            args = Namespace(
                verbose=True,
                mode="review",
                local=True,
                build_type=None,
                cuda=None,
                local_sdk_root=None,
                base_img=None,
                build_args="--build-arg CLI_SECRET=cli-value",
                replace_build_args=False,
                docker_opts=None,
                replace_docker_opts=False,
                forward_env=None,
                replace_forward_env=False,
                configure_args=["-DCLI_SECRET=cli-value"],
                replace_configure_args=False,
            )
            report_effective_configuration(
                args,
                mode_name="review",
                mode_config={
                    "build": {
                        "docker_build_args": ["--target", "review"],
                        "cmake_options": ["-DMODE_SECRET=mode-value"],
                    }
                },
                effective_build_type="Debug",
                is_local_mode=True,
                default_sdk_root="/opt/nvidia/holoscan",
                include_build=True,
                include_configure=True,
            )
    finally:
        set_active_project_context(None)

    output = capsys.readouterr().out
    assert "build type: Debug (environment (CMAKE_BUILD_TYPE))" in output
    assert "CUDA: 13 (project (tool.holoscan.cuda))" in output
    assert "project 2 + mode 2 + environment 2 + CLI 2" in output
    assert "CMake configure options: 2 entries" in output
    for secret in ("project-value", "environment-value", "cli-value", "mode-value"):
        assert secret not in output


def test_replace_provenance_names_the_reset_and_only_counts_cli(capsys):
    args = Namespace(
        verbose=True,
        cuda=None,
        local_sdk_root=None,
        base_img=None,
        build_args="--progress plain",
        replace_build_args=True,
    )

    report_effective_configuration(args, include_build=True)

    output = capsys.readouterr().out
    assert "Docker build options: 2 tokens (CLI 2)" in output
    assert "lower layers cleared by --replace-build-args" in output


def test_repeated_docker_opts_preserve_fragment_token_boundaries():
    value, replaced = resolve_cli_docker_opts(
        Namespace(
            docker_opts=["--env 'FIRST=value with spaces'", "--network=host"],
            replace_docker_opts=None,
        )
    )

    assert value == "--env 'FIRST=value with spaces' --network=host"
    assert replaced is False


def test_empty_additive_docker_opts_is_a_noop_not_a_clear():
    value, replaced = resolve_cli_docker_opts(Namespace(docker_opts=[""], replace_docker_opts=None))

    assert value == ""
    assert replaced is False


def test_atomic_docker_opts_replacement_accepts_following_additions():
    value, replaced = resolve_cli_docker_opts(
        Namespace(
            docker_opts=["--read-only"],
            replace_docker_opts="--network=none",
        )
    )

    assert value == "--network=none --read-only"
    assert replaced is True


def test_bare_docker_opts_replacement_clears_and_keeps_legacy_two_flag_spelling():
    value, replaced = resolve_cli_docker_opts(
        Namespace(
            docker_opts=["--network=none"],
            replace_docker_opts="",
        )
    )

    assert value == "--network=none"
    assert replaced is True


def test_config_vector_layer_policy_is_scoped_and_composable():
    assert get_config_vector_layers(Namespace()) == ConfigVectorLayers()
    assert get_config_vector_layers(Namespace(no_project_config=True)) == ConfigVectorLayers(
        project=False
    )
    assert get_config_vector_layers(Namespace(no_mode_config=True)) == ConfigVectorLayers(
        mode=False
    )
    assert get_config_vector_layers(Namespace(no_inherited_config=True)) == ConfigVectorLayers(
        project=False,
        mode=False,
        environment=False,
    )


def test_verbose_provenance_reports_suppressed_additive_layers(capsys):
    args = Namespace(
        verbose=True,
        cuda=None,
        local_sdk_root=None,
        docker_opts=["--env CLI=1"],
        replace_docker_opts=None,
        no_project_config=True,
        no_mode_config=False,
        no_inherited_config=False,
        forward_env=None,
        replace_forward_env=False,
    )

    report_effective_configuration(args, include_run=True)

    output = capsys.readouterr().out
    assert "additive configuration layers: project=ignored" in output
    assert "mode=active, environment=active (--no-project-config)" in output
    assert "Docker run options: 2 tokens (CLI 2)" in output


def test_base_image_provenance_resolves_the_effective_image_once(monkeypatch, capsys):
    monkeypatch.delenv("HOLOSCAN_CLI_BASE_IMAGE", raising=False)
    monkeypatch.delenv("HOLOSCAN_CLI_BASE_IMAGE_FORMAT", raising=False)

    class RecordingContainer:
        calls = 0

        def default_base_image(self, cuda):
            self.calls += 1
            assert cuda == "13"
            return "registry.example/sdk:v5.0.0-cuda13"

    container = RecordingContainer()
    args = Namespace(
        verbose=True,
        cuda="13",
        local_sdk_root=None,
        base_img=None,
        build_args=None,
        replace_build_args=False,
    )

    report_effective_configuration(args, container=container, include_build=True)

    assert container.calls == 1
    assert "base image: registry.example/sdk:v5.0.0-cuda13 (derived default)" in (
        capsys.readouterr().out
    )


def test_container_cli_cuda_is_applied_before_image_resolution():
    container = type("Container", (), {"cuda_version": "12"})()

    apply_container_cli_overrides(Namespace(cuda="13", no_mode_config=True), container)

    assert container.cuda_version == "13"
    assert container.config_layers == ConfigVectorLayers(mode=False)


def test_execution_provenance_uses_the_applicable_mode_environment(monkeypatch, capsys):
    monkeypatch.delenv("HOLOSCAN_CLI_BUILD_LOCAL", raising=False)
    args = Namespace(
        verbose=True,
        local=None,
        cuda=None,
        local_sdk_root=None,
    )

    report_effective_configuration(
        args,
        is_local_mode=True,
        location_mode_environment={"HOLOSCAN_CLI_BUILD_LOCAL": "1"},
    )

    assert "execution: local (selected mode)" in capsys.readouterr().out
