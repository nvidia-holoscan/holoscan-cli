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

"""Tests for ``holoscan_cli.system_check``.

``system_check.py`` powers ``holoscan env-check``. Each ``check_*``
function probes a host facility (GPU, CUDA, Docker, SDK, etc.) and
returns a ``CheckResult`` with one of four statuses. The 0% coverage
came from the host coupling — these tests fake the probe outputs so
each branch (OK / WARN / FAIL / SKIP) gets exercised deterministically.
"""

import json
import subprocess
from types import SimpleNamespace

import pytest

from holoscan_cli import system_check


def _proc(returncode=0, stderr="", stdout=""):
    return SimpleNamespace(returncode=returncode, stderr=stderr, stdout=stdout)


# ---- check_gpu --------------------------------------------------------------


def test_check_gpu_no_gpu(monkeypatch):
    monkeypatch.setattr(system_check, "get_gpu_name", lambda: None)
    result = system_check.check_gpu()
    assert result.status == "FAIL"
    assert "No NVIDIA GPU" in result.message
    assert result.fix_suggestion is not None


def test_check_gpu_single_gpu_with_full_details(monkeypatch):
    monkeypatch.setattr(system_check, "get_gpu_name", lambda: "NVIDIA RTX 4090")
    monkeypatch.setattr(
        system_check,
        "run_info_command",
        lambda _cmd: "0, NVIDIA RTX 4090, 550.54.15, 8.9, 24576 MiB",
    )
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    result = system_check.check_gpu()
    assert result.status == "OK"
    assert "RTX 4090" in result.message
    assert "compute 8.9" in result.message
    assert "driver 550.54.15" in result.message


def test_check_gpu_multi_gpu_emits_details(monkeypatch):
    monkeypatch.setattr(system_check, "get_gpu_name", lambda: "NVIDIA RTX 4090")
    monkeypatch.setattr(
        system_check,
        "run_info_command",
        lambda _cmd: (
            "0, NVIDIA RTX 4090, 550.54.15, 8.9, 24576 MiB\n"
            "1, NVIDIA RTX 4090, 550.54.15, 8.9, 24576 MiB"
        ),
    )
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    result = system_check.check_gpu()
    assert result.status == "OK"
    assert "2 GPUs detected" in result.message
    assert "CUDA_VISIBLE_DEVICES=0,1" in result.message
    assert result.details is not None
    # Each GPU is one line in details.
    assert result.details.count("[0]") + result.details.count("[1]") == 2


def test_check_gpu_falls_back_when_nvidia_smi_query_empty(monkeypatch):
    monkeypatch.setattr(system_check, "get_gpu_name", lambda: "NVIDIA RTX 4090\nNVIDIA RTX 4090")
    monkeypatch.setattr(system_check, "run_info_command", lambda _cmd: None)
    result = system_check.check_gpu()
    assert result.status == "OK"
    assert result.message == "NVIDIA RTX 4090"


# ---- check_cuda -------------------------------------------------------------


def test_check_cuda_with_nvcc_in_path(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: "/usr/local/cuda/bin/nvcc")
    monkeypatch.setattr(
        system_check,
        "run_info_command",
        lambda _cmd: "nvcc: NVIDIA (R) Cuda compiler driver\nrelease 12.6, V12.6.85",
    )
    result = system_check.check_cuda()
    assert result.status == "OK"
    assert "12.6" in result.message


def test_check_cuda_with_nvcc_but_unreadable(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: "/usr/local/cuda/bin/nvcc")
    monkeypatch.setattr(system_check, "run_info_command", lambda _cmd: None)
    result = system_check.check_cuda()
    assert result.status == "WARN"


def test_check_cuda_no_nvcc_with_runtime(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_check, "_get_driver_cuda_version", lambda: "12")
    monkeypatch.setattr(system_check, "get_cuda_runtime_version", lambda: "12.4")
    result = system_check.check_cuda()
    assert result.status == "OK"
    assert "runtime 12.4" in result.message


def test_check_cuda_no_nvcc_no_runtime(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_check, "_get_driver_cuda_version", lambda: "12")
    monkeypatch.setattr(system_check, "get_cuda_runtime_version", lambda: None)
    result = system_check.check_cuda()
    assert result.status == "WARN"
    assert "nvcc not found" in result.message


# ---- check_docker -----------------------------------------------------------


def test_check_docker_not_installed_outside_container(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_check, "is_running_in_docker", lambda: False)
    monkeypatch.delenv("HOLOSCAN_CLI_DOCKER_EXE", raising=False)
    result = system_check.check_docker()
    assert result.status == "WARN"
    assert "not installed" in result.message


def test_check_docker_not_installed_inside_container_skips(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_check, "is_running_in_docker", lambda: True)
    result = system_check.check_docker()
    assert result.status == "SKIP"


def test_check_docker_permission_denied(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        system_check.subprocess,
        "run",
        lambda *a, **kw: _proc(returncode=1, stderr="permission denied"),
    )
    result = system_check.check_docker()
    assert result.status == "FAIL"
    assert "permission" in result.message.lower()


def test_check_docker_daemon_not_running(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        system_check.subprocess,
        "run",
        lambda *a, **kw: _proc(returncode=1, stderr="Cannot connect to the Docker daemon"),
    )
    result = system_check.check_docker()
    assert result.status == "FAIL"


def test_check_docker_timeout(monkeypatch):
    monkeypatch.setattr(system_check.shutil, "which", lambda name: "/usr/bin/docker")

    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=["docker", "info"], timeout=10)

    monkeypatch.setattr(system_check.subprocess, "run", boom)
    result = system_check.check_docker()
    assert result.status == "FAIL"
    assert "timed out" in result.message


def test_check_docker_ok_without_ctk(monkeypatch):
    # docker info succeeds; nvidia-ctk not on PATH -> WARN with hint
    which_map = {"docker": "/usr/bin/docker", "nvidia-ctk": None}
    monkeypatch.setattr(system_check.shutil, "which", lambda name: which_map.get(name, None))
    monkeypatch.setattr(system_check.subprocess, "run", lambda *a, **kw: _proc(returncode=0))
    monkeypatch.setattr(
        system_check, "run_info_command", lambda cmd: "Docker version 24.0.7, build afdd53b"
    )
    result = system_check.check_docker()
    assert result.status == "WARN"
    assert "24.0.7" in result.message
    assert result.fix_suggestion is not None


def test_check_docker_ok_with_ctk(monkeypatch):
    which_map = {"docker": "/usr/bin/docker", "nvidia-ctk": "/usr/bin/nvidia-ctk"}
    monkeypatch.setattr(system_check.shutil, "which", lambda name: which_map.get(name, None))
    monkeypatch.setattr(system_check.subprocess, "run", lambda *a, **kw: _proc(returncode=0))

    def fake_run_info(cmd):
        if cmd[0] == "/usr/bin/docker" or cmd[0] == "docker":
            return "Docker version 24.0.7, build afdd53b"
        return "NVIDIA Container Toolkit CLI version 1.16.0"

    monkeypatch.setattr(system_check, "run_info_command", fake_run_info)
    result = system_check.check_docker()
    assert result.status == "OK"
    assert "24.0.7" in result.message
    assert "1.16.0" in result.message


# ---- check_holoscan ---------------------------------------------------------


def test_check_holoscan_found_at_default_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HOLOSCAN_CLI_DEFAULT_HSDK_DIR", str(tmp_path))
    monkeypatch.setattr(system_check, "is_valid_sdk_installation", lambda _p: True)
    monkeypatch.setattr(system_check, "get_sdk_version", lambda _p: "3.4.0")
    result = system_check.check_holoscan()
    assert result.status == "OK"
    assert "3.4.0" in result.message


def test_check_holoscan_falls_back_to_sdk_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HOLOSCAN_CLI_DEFAULT_HSDK_DIR", str(tmp_path / "missing"))
    real_root = tmp_path / "sdk-root"
    real_root.mkdir()
    monkeypatch.setenv("HOLOSCAN_SDK_ROOT", str(real_root))

    def fake_valid(p):
        return str(p) == str(real_root)

    monkeypatch.setattr(system_check, "is_valid_sdk_installation", fake_valid)
    monkeypatch.setattr(system_check, "get_sdk_version", lambda _p: "3.4.0")
    result = system_check.check_holoscan()
    assert result.status == "OK"
    assert "3.4.0" in result.message


def test_check_holoscan_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("HOLOSCAN_CLI_DEFAULT_HSDK_DIR", str(tmp_path / "nope"))
    monkeypatch.delenv("HOLOSCAN_SDK_ROOT", raising=False)
    monkeypatch.setattr(system_check, "is_valid_sdk_installation", lambda _p: False)
    result = system_check.check_holoscan()
    assert result.status == "WARN"
    assert "not found" in result.message


# ---- check_holoscan_python --------------------------------------------------


def test_check_holoscan_python_ok(monkeypatch):
    monkeypatch.setattr(
        system_check.subprocess,
        "run",
        lambda *a, **kw: _proc(stdout="3.4.0\n/x/y/holoscan/__init__.py\n"),
    )
    result = system_check.check_holoscan_python()
    assert result.status == "OK"
    assert "3.4.0" in result.message


def test_check_holoscan_python_import_failure(monkeypatch):
    monkeypatch.setattr(
        system_check.subprocess,
        "run",
        lambda *a, **kw: _proc(returncode=1, stderr="ModuleNotFoundError: No module named 'holoscan'"),
    )
    result = system_check.check_holoscan_python()
    assert result.status == "WARN"
    assert "failed" in result.message.lower()


def test_check_holoscan_python_timeout(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=[], timeout=15)

    monkeypatch.setattr(system_check.subprocess, "run", boom)
    result = system_check.check_holoscan_python()
    assert result.status == "WARN"
    assert "timed out" in result.message


# ---- check_disk -------------------------------------------------------------


def test_check_disk_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(system_check, "get_holohub_root", lambda: tmp_path)
    monkeypatch.delenv("HOLOSCAN_CLI_BUILD_PARENT_DIR", raising=False)

    class _StatVfs:
        f_bavail = 200 * 1024 * 1024
        f_frsize = 1024

    monkeypatch.setattr(system_check.os, "statvfs", lambda _p: _StatVfs())
    result = system_check.check_disk()
    assert result.status == "OK"


def test_check_disk_warn_below_20gb(monkeypatch, tmp_path):
    monkeypatch.setattr(system_check, "get_holohub_root", lambda: tmp_path)

    class _StatVfs:
        f_bavail = 10 * 1024 * 1024
        f_frsize = 1024

    monkeypatch.setattr(system_check.os, "statvfs", lambda _p: _StatVfs())
    result = system_check.check_disk()
    assert result.status == "WARN"


def test_check_disk_fail_below_5gb(monkeypatch, tmp_path):
    monkeypatch.setattr(system_check, "get_holohub_root", lambda: tmp_path)

    class _StatVfs:
        f_bavail = 1 * 1024 * 1024
        f_frsize = 1024

    monkeypatch.setattr(system_check.os, "statvfs", lambda _p: _StatVfs())
    result = system_check.check_disk()
    assert result.status == "FAIL"


def test_check_disk_handles_oserror(monkeypatch, tmp_path):
    monkeypatch.setattr(system_check, "get_holohub_root", lambda: tmp_path)

    def boom(_p):
        raise OSError("statvfs failed")

    monkeypatch.setattr(system_check.os, "statvfs", boom)
    result = system_check.check_disk()
    assert result.status == "WARN"
    assert "Could not check" in result.message


# ---- check_cli --------------------------------------------------------------


def test_check_cli_prefers_cli_commit_hash_file(monkeypatch, tmp_path):
    monkeypatch.setattr(system_check, "get_holohub_root", lambda: tmp_path)
    (tmp_path / ".cli_commit_hash").write_text("deadbee\n")
    result = system_check.check_cli()
    assert result.status == "OK"
    assert "deadbee" in result.message


def test_check_cli_falls_back_to_git_sha(monkeypatch, tmp_path):
    monkeypatch.setattr(system_check, "get_holohub_root", lambda: tmp_path)
    monkeypatch.setattr(system_check, "get_git_short_sha", lambda length=7: "abc1234")
    result = system_check.check_cli()
    assert result.status == "OK"
    assert "abc1234" in result.message


# ---- check_container --------------------------------------------------------


def test_check_container_inside(monkeypatch):
    monkeypatch.setattr(system_check, "is_running_in_docker", lambda: True)
    result = system_check.check_container()
    assert result.status == "OK"
    assert "inside Docker" in result.message


def test_check_container_outside(monkeypatch):
    monkeypatch.setattr(system_check, "is_running_in_docker", lambda: False)
    result = system_check.check_container()
    assert result.status == "OK"
    assert "on host" in result.message


# ---- check_display ----------------------------------------------------------


def test_check_display_ok(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(system_check.os.path, "exists", lambda p: True)
    result = system_check.check_display()
    assert result.status == "OK"
    assert ":0" in result.message


def test_check_display_set_but_no_socket(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(system_check.os.path, "exists", lambda p: False)
    result = system_check.check_display()
    assert result.status == "WARN"


def test_check_display_unset_skips_in_container(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(system_check, "is_running_in_docker", lambda: True)
    result = system_check.check_display()
    assert result.status == "SKIP"


def test_check_display_unset_on_host_warns(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(system_check, "is_running_in_docker", lambda: False)
    result = system_check.check_display()
    assert result.status == "WARN"


# ---- check_devices ----------------------------------------------------------


def test_check_devices_none_detected(monkeypatch):
    monkeypatch.setattr(system_check.glob, "glob", lambda _p: [])
    monkeypatch.setattr(system_check.os.path, "isdir", lambda _p: False)
    monkeypatch.setattr(system_check.os.path, "exists", lambda _p: False)
    result = system_check.check_devices()
    assert result.status == "SKIP"


def test_check_devices_v4l2_detected(monkeypatch):
    def fake_glob(pattern):
        if "video" in pattern:
            return ["/dev/video0", "/dev/video1"]
        return []

    monkeypatch.setattr(system_check.glob, "glob", fake_glob)
    monkeypatch.setattr(system_check.os.path, "isdir", lambda _p: False)
    monkeypatch.setattr(system_check.os.path, "exists", lambda _p: False)
    result = system_check.check_devices()
    assert result.status == "OK"
    assert "V4L2" in result.message
    assert "/dev/video0" in result.message


# ---- run_all_checks + formatters --------------------------------------------


def test_run_all_checks_recovers_from_check_exception(monkeypatch):
    def boom():
        raise RuntimeError("intentional")

    monkeypatch.setattr(system_check, "check_gpu", boom)
    monkeypatch.setattr(system_check, "check_cuda", lambda: system_check.CheckResult("OK", "CUDA", "ok"))
    monkeypatch.setattr(system_check, "check_docker", lambda: system_check.CheckResult("OK", "Docker", "ok"))
    monkeypatch.setattr(system_check, "check_holoscan", lambda: system_check.CheckResult("OK", "Holoscan", "ok"))
    monkeypatch.setattr(
        system_check, "check_holoscan_python", lambda: system_check.CheckResult("OK", "py", "ok")
    )
    monkeypatch.setattr(system_check, "check_disk", lambda: system_check.CheckResult("OK", "Disk", "ok"))
    monkeypatch.setattr(system_check, "check_cli", lambda: system_check.CheckResult("OK", "CLI", "ok"))
    monkeypatch.setattr(
        system_check, "check_container", lambda: system_check.CheckResult("OK", "Container", "ok")
    )
    monkeypatch.setattr(
        system_check, "check_display", lambda: system_check.CheckResult("OK", "Display", "ok")
    )
    monkeypatch.setattr(
        system_check, "check_devices", lambda: system_check.CheckResult("OK", "Devices", "ok")
    )

    results = system_check.run_all_checks()
    gpu_result = next(r for r in results if r.name == "GPU")
    assert gpu_result.status == "FAIL"
    assert "intentional" in gpu_result.message


def test_format_results_renders_all_statuses():
    results = [
        system_check.CheckResult("OK", "GPU", "ok-msg"),
        system_check.CheckResult("WARN", "Docker", "warn-msg", fix_suggestion="hint x"),
        system_check.CheckResult("FAIL", "Disk", "fail-msg", fix_suggestion="run y", details="d1\nd2"),
        system_check.CheckResult("SKIP", "Display", "skip-msg"),
    ]
    out = system_check.format_results(results, elapsed=1.23)
    assert "ok-msg" in out
    assert "warn-msg" in out and "hint x" in out
    assert "fail-msg" in out and "run y" in out
    assert "d1" in out and "d2" in out
    assert "skip-msg" in out
    assert "1 check(s) failed" in out


def test_format_results_all_pass_message():
    results = [system_check.CheckResult("OK", "GPU", "ok")]
    out = system_check.format_results(results, elapsed=0.1)
    assert "All checks passed." in out


def test_format_results_warn_only_message():
    results = [
        system_check.CheckResult("OK", "GPU", "ok"),
        system_check.CheckResult("WARN", "Docker", "warn"),
    ]
    out = system_check.format_results(results, elapsed=0.1)
    assert "1 warning" in out


def test_format_results_json_summary():
    results = [
        system_check.CheckResult("OK", "GPU", "ok"),
        system_check.CheckResult("WARN", "Docker", "warn"),
        system_check.CheckResult("FAIL", "Disk", "fail"),
        system_check.CheckResult("SKIP", "Display", "skip"),
    ]
    out = system_check.format_results_json(results, elapsed=1.234)
    parsed = json.loads(out)
    assert parsed["elapsed_seconds"] == 1.23
    assert parsed["summary"] == {"ok": 1, "warn": 1, "fail": 1, "skip": 1}
    assert len(parsed["checks"]) == 4


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
