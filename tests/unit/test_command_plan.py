# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.resources
import json
import os
import subprocess

import pytest
from jsonschema import Draft202012Validator

from holoscan_cli.command_plan import CommandPlanError, PlanRecorder
from holoscan_cli.utils import holohub, io, sdk


@pytest.fixture(autouse=True)
def _clear_host_probe_caches():
    cached = (sdk.get_gpu_name, sdk.get_host_gpu, sdk.get_default_cuda_version)
    for function in cached:
        function.cache_clear()
    yield
    for function in cached:
        function.cache_clear()


def _schema() -> dict:
    schema_path = importlib.resources.files("holoscan_cli").joinpath("command_plan.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate(payload: dict) -> None:
    Draft202012Validator(_schema()).validate(payload)


def test_process_plan_has_stable_steps_env_delta_and_replay(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    recorder = PlanRecorder()
    effective_env = dict(os.environ)
    effective_env["DOCKER_BUILDKIT"] = "1"

    recorder.record_process(["docker", "buildx", "version"], role="probe", check=True)
    action = recorder.record_process(
        ["docker", "build", "-t", "example:latest", "."],
        role="action",
        env=effective_env,
        explicit_env={"DOCKER_BUILDKIT": "1"},
        check=True,
    )

    payload = recorder.payload()
    _validate(payload)
    assert [step["id"] for step in payload["steps"]] == ["step-001", "step-002"]
    assert [step["role"] for step in payload["steps"]] == ["probe", "action"]
    assert action.private_argv == ["docker", "build", "-t", "example:latest", "."]
    assert payload["steps"][1]["environment"] == {
        "inherit": True,
        "set": {"DOCKER_BUILDKIT": "1"},
        "unset": [],
        "required": [],
    }
    assert "buildx version" not in payload["replay"]["script"]
    assert "DOCKER_BUILDKIT=1" in payload["replay"]["script"]
    checked = subprocess.run(
        ["bash", "-n"], input=payload["replay"]["script"], text=True, capture_output=True
    )
    assert checked.returncode == 0, checked.stderr


def test_schema_rejects_contradictory_replay_states():
    recorder = PlanRecorder()
    recorder.record_process(["docker", "build", "."], role="action", check=True)
    payload = recorder.payload()
    validator = Draft202012Validator(_schema())

    payload["replay"]["unavailable_reason"] = "contradictory"
    assert not validator.is_valid(payload)

    payload["replay"]["script"] = None
    payload["replay"]["unavailable_reason"] = None
    assert not validator.is_valid(payload)


def test_sensitive_docker_literal_is_redacted_but_xauthority_is_not(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recorder = PlanRecorder()
    step = recorder.record_process(
        [
            "docker",
            "run",
            "--env",
            "SERVICE_API_TOKEN=sentinel-secret",
            "--env",
            "XAUTHORITY=/tmp/xauth",
            "example:latest",
        ],
        role="action",
        check=True,
    )

    serialized = recorder.json_text()
    payload = json.loads(serialized)
    _validate(payload)
    assert "sentinel-secret" in step.private_argv[3]
    assert "sentinel-secret" not in serialized
    assert "SERVICE_API_TOKEN=<redacted>" in payload["steps"][0]["argv"]
    assert "XAUTHORITY=/tmp/xauth" in payload["steps"][0]["argv"]
    assert payload["replay"]["script"] is None
    assert payload["replay"]["unavailable_reason"] == "redacted_literal"


def test_bare_docker_environment_references_are_declared_without_leaking_values(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLAN_DEMO", "ordinary-value")
    monkeypatch.setenv("NGC_API_KEY", "sentinel-secret")
    recorder = PlanRecorder()
    recorder.record_process(
        [
            "docker",
            "build",
            "--build-arg",
            "PLAN_DEMO",
            "--build-arg",
            "NGC_API_KEY",
            ".",
        ],
        role="action",
        check=True,
    )

    serialized = recorder.json_text()
    payload = json.loads(serialized)
    assert payload["steps"][0]["environment"]["required"] == [
        "NGC_API_KEY",
        "PLAN_DEMO",
    ]
    assert payload["replay"]["required_environment"] == ["NGC_API_KEY", "PLAN_DEMO"]
    assert "ordinary-value" not in serialized
    assert "sentinel-secret" not in serialized
    assert "Set NGC_API_KEY" in payload["replay"]["script"]


def test_unset_bare_docker_environment_reference_fails_closed(monkeypatch):
    monkeypatch.delenv("PLAN_DEMO", raising=False)
    recorder = PlanRecorder()

    with pytest.raises(CommandPlanError, match="PLAN_DEMO"):
        recorder.record_process(
            ["docker", "build", "--build-arg", "PLAN_DEMO", "."],
            role="action",
            check=True,
        )


def test_owned_environment_overlay_satisfies_bare_docker_reference(monkeypatch):
    monkeypatch.delenv("PLAN_DEMO", raising=False)
    recorder = PlanRecorder()
    effective_env = dict(os.environ)
    effective_env["PLAN_DEMO"] = "owned-value"
    recorder.record_process(
        ["docker", "build", "--build-arg", "PLAN_DEMO", "."],
        role="action",
        env=effective_env,
        explicit_env={"PLAN_DEMO": "owned-value"},
        check=True,
    )

    payload = recorder.payload()
    assert payload["steps"][0]["environment"]["set"] == {"PLAN_DEMO": "owned-value"}
    assert payload["steps"][0]["environment"]["required"] == []
    assert "Set PLAN_DEMO" not in payload["replay"]["script"]
    assert "PLAN_DEMO=owned-value" in payload["replay"]["script"]


def test_empty_bare_docker_environment_reference_is_replayable(monkeypatch):
    monkeypatch.setenv("PLAN_DEMO", "")
    recorder = PlanRecorder()
    recorder.record_process(
        ["docker", "build", "--build-arg", "PLAN_DEMO", "."],
        role="action",
        check=True,
    )

    script = recorder.payload()["replay"]["script"]
    assert "${PLAN_DEMO?Set PLAN_DEMO" in script
    assert "${PLAN_DEMO:?" not in script


def test_run_command_records_action_without_printing_or_executing(monkeypatch, capsys):
    recorder = PlanRecorder()

    def unexpected_run(*args, **kwargs):
        raise AssertionError("an action subprocess executed during planning")

    monkeypatch.setattr(io.subprocess, "run", unexpected_run)
    with recorder.activate():
        result = io.run_command(
            ["docker", "build", "."],
            dry_run=True,
            env_updates={"DOCKER_BUILDKIT": "1"},
        )

    assert result.returncode == 0
    assert capsys.readouterr().out == ""
    assert recorder.steps[0].role == "action"
    assert recorder.steps[0].environment["set"]["DOCKER_BUILDKIT"] == "1"


def test_run_probe_executes_and_is_recorded(monkeypatch):
    recorder = PlanRecorder()
    calls = []

    def fake_run(cmd, check=False, **kwargs):
        calls.append((cmd, check, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr(io.subprocess, "run", fake_run)
    with recorder.activate():
        result = io.run_probe(
            ["docker", "buildx", "version"], check=True, capture_output=True, text=True
        )

    assert result.stdout == "ok\n"
    assert calls[0][0] == ["docker", "buildx", "version"]
    assert recorder.steps[0].role == "probe"
    assert recorder.steps[0].check is True


def test_unconfigured_probe_output_is_captured_during_planning(monkeypatch):
    recorder = PlanRecorder()
    seen = {}

    def fake_run(cmd, check=False, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"probe output", stderr=b"")

    monkeypatch.setattr(io.subprocess, "run", fake_run)
    with recorder.activate():
        io.run_probe(["host-probe"])

    assert seen["stdout"] is subprocess.PIPE
    assert seen["stderr"] is subprocess.PIPE


def test_shell_renderer_rejects_probe_only_plan():
    recorder = PlanRecorder()
    recorder.record_process(["docker", "buildx", "version"], role="probe", check=True)

    with pytest.raises(CommandPlanError, match="no action steps"):
        recorder.shell_text()


def test_replacement_subprocess_environment_fails_closed(monkeypatch):
    recorder = PlanRecorder()

    with recorder.activate(), pytest.raises(CommandPlanError, match="replacement subprocess"):
        io.run_command(
            ["docker", "build", "."],
            dry_run=True,
            env={"PATH": os.environ.get("PATH", "")},
        )


def test_host_resolvers_record_the_probes_that_select_build_arguments(monkeypatch, tmp_path):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(holohub, "HOLOHUB_ROOT", tmp_path)

    outputs = {
        ("nvidia-smi", "--query-gpu=name", "--format=csv,noheader"): "NVIDIA H100\n",
        (
            "/usr/bin/nvidia-smi",
            "--query-gpu=compute_cap",
            "--format=csv,noheader",
        ): "9.0\n",
        (
            "nvidia-smi",
            "--query-gpu=driver_version",
            "--format=csv,noheader",
        ): "580.126.20\n",
        ("git", "rev-parse", "--short=12", "HEAD"): "deadbeef1234\n",
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): "feature/plan\n",
    }

    def fake_run(cmd, check=False, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=outputs[tuple(cmd)], stderr="")

    monkeypatch.setattr(io.subprocess, "run", fake_run)
    recorder = PlanRecorder()
    with recorder.activate():
        assert sdk.get_host_gpu() == "dgpu"
        assert sdk.get_compute_capacity() == "9.0"
        assert sdk.get_default_cuda_version() == "13"
        assert holohub.get_git_short_sha() == "deadbeef1234"
        assert holohub.get_current_branch_slug() == "feature-plan"

    assert [step.role for step in recorder.steps] == ["probe"] * 5
    assert [step.private_argv for step in recorder.steps] == [list(command) for command in outputs]
    assert recorder.steps[-1].cwd == str(tmp_path)


def test_host_resolver_fallbacks_are_explicit_plan_warnings(monkeypatch):
    monkeypatch.setattr(sdk.shutil, "which", lambda _name: None)
    recorder = PlanRecorder()

    with recorder.activate():
        assert sdk.get_host_gpu() == "dgpu"
        assert sdk.get_compute_capacity() == "0.0"
        assert sdk.get_default_cuda_version() == "13"

    assert recorder.steps == []
    assert [warning["code"] for warning in recorder.warnings] == [
        "probe_fallback_used",
        "probe_fallback_used",
        "probe_fallback_used",
    ]
