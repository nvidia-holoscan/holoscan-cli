# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess

import pytest

from holoscan_cli import cli as project_cli
from holoscan_cli.container import core as container_core
from holoscan_cli.utils import holohub, io, sdk

_REAL_SUBPROCESS_RUN = subprocess.run


@pytest.fixture()
def plan_cli(tmp_path, monkeypatch):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", tmp_path)
    monkeypatch.setattr(container_core.HoloscanContainer, "HOLOHUB_ROOT", tmp_path)
    monkeypatch.setattr(container_core.HoloscanContainer, "DEFAULT_DOCKERFILE", dockerfile)
    monkeypatch.setattr(container_core.HoloscanContainer, "BASE_SDK_VERSION", None)
    monkeypatch.setattr(container_core.HoloscanContainer, "DEFAULT_DOCKER_BUILD_ARGS", "")
    monkeypatch.setattr(container_core.HoloscanContainer, "DOCKER_EXE", "docker")
    monkeypatch.delenv("HOLOSCAN_CLI_SOURCE", raising=False)
    monkeypatch.setattr(container_core, "get_host_gpu", lambda: "dgpu")
    monkeypatch.setattr(container_core, "get_compute_capacity", lambda: "90")
    monkeypatch.setattr(container_core, "get_default_cuda_version", lambda: "13")

    probe_calls = []

    def fake_subprocess_run(cmd, check=False, **kwargs):
        probe_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="buildx 0.20.0\n", stderr="")

    monkeypatch.setattr(io.subprocess, "run", fake_subprocess_run)
    cli = project_cli.HoloscanCLI(script_name="holoscan")
    return cli, dockerfile, probe_calls


def _argv(dockerfile, output_format):
    return [
        "holoscan",
        "build-container",
        "--docker-file",
        str(dockerfile),
        "--base-img",
        "example.com/base:latest",
        "--img",
        "example:plan",
        "--cuda",
        "13",
        "--dryrun",
        output_format,
    ]


def test_build_container_json_is_pure_and_actions_do_not_execute(plan_cli, capsys):
    cli, dockerfile, probe_calls = plan_cli

    cli.run(_argv(dockerfile, "--json"))

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1
    assert payload["scope"] == "current_cli_process"
    assert payload["complete"] is True
    assert [step["role"] for step in payload["steps"]] == ["probe", "action"]
    assert payload["steps"][0]["argv"] == ["docker", "buildx", "version"]
    action = payload["steps"][1]
    assert action["argv"][:2] == ["docker", "build"]
    assert "BASE_IMAGE=example.com/base:latest" in action["argv"]
    assert "GPU_TYPE=dgpu" in action["argv"]
    assert "COMPUTE_CAPACITY=90" in action["argv"]
    assert action["environment"]["set"] == {"DOCKER_BUILDKIT": "1"}
    assert probe_calls == [["docker", "buildx", "version"]]
    assert "No project provided" in captured.err
    assert "[dryrun]" not in captured.out


def test_build_container_plan_integrates_host_resolution_and_wrapper_defaults(
    tmp_path, monkeypatch, capsys
):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_cli.HoloscanCLI, "HOLOHUB_ROOT", tmp_path)
    monkeypatch.setattr(container_core.HoloscanContainer, "HOLOHUB_ROOT", tmp_path)
    monkeypatch.setattr(container_core.HoloscanContainer, "DEFAULT_DOCKERFILE", dockerfile)
    monkeypatch.setattr(container_core.HoloscanContainer, "BASE_SDK_VERSION", "4.5.0")
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "BASE_IMAGE_NAME",
        container_core.HoloscanContainer.DEFAULT_BASE_IMAGE_NAME,
    )
    monkeypatch.setattr(container_core.HoloscanContainer, "BASE_IMAGE_FORMAT", None)
    monkeypatch.setattr(container_core.HoloscanContainer, "DEFAULT_IMAGE_FORMAT", None)
    monkeypatch.setattr(container_core.HoloscanContainer, "CONTAINER_PREFIX", "wrapper")
    monkeypatch.setattr(
        container_core.HoloscanContainer,
        "DEFAULT_DOCKER_BUILD_ARGS",
        "--build-arg WRAPPER_FEATURE=enabled --progress=plain",
    )
    monkeypatch.setattr(container_core.HoloscanContainer, "DOCKER_EXE", "docker")
    monkeypatch.setattr(holohub, "HOLOHUB_ROOT", tmp_path)
    monkeypatch.setattr(sdk.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.delenv("HOLOSCAN_CLI_SOURCE", raising=False)

    outputs = {
        (
            "nvidia-smi",
            "--query-gpu=driver_version",
            "--format=csv,noheader",
        ): "580.126.20\n",
        ("git", "rev-parse", "--short=12", "HEAD"): "deadbeef1234\n",
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): "feature/plan\n",
        ("nvidia-smi", "--query-gpu=name", "--format=csv,noheader"): "NVIDIA H100\n",
        (
            "/usr/bin/nvidia-smi",
            "--query-gpu=compute_cap",
            "--format=csv,noheader",
        ): "9.0\n",
        ("docker", "buildx", "version"): "buildx 0.20.0\n",
    }
    probe_calls = []

    def fake_subprocess_run(cmd, check=False, **kwargs):
        probe_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=outputs[tuple(cmd)], stderr="")

    monkeypatch.setattr(io.subprocess, "run", fake_subprocess_run)
    cached = (sdk.get_gpu_name, sdk.get_host_gpu, sdk.get_default_cuda_version)
    for function in cached:
        function.cache_clear()
    try:
        project_cli.HoloscanCLI(script_name="holoscan").run(
            ["holoscan", "build-container", "--dryrun", "--json"]
        )
    finally:
        for function in cached:
            function.cache_clear()

    payload = json.loads(capsys.readouterr().out)
    assert probe_calls == [list(command) for command in outputs]
    assert [step["role"] for step in payload["steps"]] == ["probe"] * 6 + ["action"]
    action = payload["steps"][-1]
    assert "BASE_IMAGE=nvcr.io/nvidia/clara-holoscan/holoscan:v4.5.0-cuda13" in action["argv"]
    assert "GPU_TYPE=dgpu" in action["argv"]
    assert "COMPUTE_CAPACITY=9.0" in action["argv"]
    assert "CUDA_MAJOR=13" in action["argv"]
    assert "WRAPPER_FEATURE=enabled" in action["argv"]
    assert "--progress=plain" in action["argv"]
    assert "wrapper:feature-plan" in action["argv"]
    assert "wrapper:deadbeef1234" in action["argv"]
    assert payload["warnings"] == []


def test_shell_output_matches_json_replay(plan_cli, capsys):
    cli, dockerfile, _probe_calls = plan_cli
    cli.run(_argv(dockerfile, "--json"))
    payload = json.loads(capsys.readouterr().out)

    cli.run(_argv(dockerfile, "--shell"))
    shell = capsys.readouterr().out

    assert shell == payload["replay"]["script"]
    action_id = next(step["id"] for step in payload["steps"] if step["role"] == "action")
    assert f"# {action_id} (action): docker build\n" in shell
    assert "docker build \\\n" in shell
    checked = _REAL_SUBPROCESS_RUN(["bash", "-n"], input=shell, text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr


def test_buildx_failure_leaves_stdout_empty(plan_cli, monkeypatch, capsys):
    cli, dockerfile, _probe_calls = plan_cli

    def fail_buildx(cmd, check=False, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(io.subprocess, "run", fail_buildx)
    with pytest.raises(SystemExit) as exc_info:
        cli.run(_argv(dockerfile, "--json"))

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert captured.out == ""
    assert "docker buildx plugin is missing" in captured.err


def test_late_extra_script_failure_does_not_emit_partial_plan(plan_cli, capsys):
    cli, dockerfile, _probe_calls = plan_cli
    argv = _argv(dockerfile, "--json")
    argv[-1:-1] = ["--extra-scripts", "definitely-not-a-script"]

    with pytest.raises(SystemExit) as exc_info:
        cli.run(argv)

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert captured.out == ""
    assert "definitely-not-a-script.sh not found" in captured.err


def test_unreplayable_shell_plan_leaves_stdout_empty(plan_cli, capsys):
    cli, dockerfile, _probe_calls = plan_cli
    argv = _argv(dockerfile, "--shell")
    argv[-1:-1] = [
        "--build-args=--build-arg SERVICE_API_TOKEN=sentinel-secret",
    ]

    with pytest.raises(SystemExit) as exc_info:
        cli.run(argv)

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert captured.out == ""
    assert "redacted_literal" in captured.err
    assert "sentinel-secret" not in captured.err
