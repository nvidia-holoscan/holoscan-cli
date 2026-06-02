# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from holoscan_cli.utils import sdk


@pytest.fixture(autouse=True)
def _clear_sdk_caches():
    for fn in (
        sdk.get_gpu_name,
        sdk.get_host_gpu,
        sdk.get_default_cuda_version,
        sdk.get_host_arch,
    ):
        fn.cache_clear()
    yield
    for fn in (
        sdk.get_gpu_name,
        sdk.get_host_gpu,
        sdk.get_default_cuda_version,
        sdk.get_host_arch,
    ):
        fn.cache_clear()


@pytest.mark.parametrize(
    "driver,expected",
    [
        ("580.126.20", "13"),
        ("575.57.08", "12"),
        ("not-a-version", None),
        ("", None),
    ],
)
def test_cuda_major_from_driver(driver, expected):
    assert sdk.cuda_major_from_driver(driver) == expected


def test_get_gpu_name_returns_first_nvidia_smi_result(monkeypatch):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        sdk.subprocess,
        "check_output",
        lambda cmd, **kwargs: "NVIDIA H100\n",
    )

    assert sdk.get_gpu_name() == "NVIDIA H100"


def test_get_host_gpu_defaults_to_dgpu_without_driver(monkeypatch, capsys):
    monkeypatch.setattr(sdk, "get_gpu_name", lambda: None)

    assert sdk.get_host_gpu() == "dgpu"
    assert "Defaulting build to target dGPU/CPU stack" in capsys.readouterr().err


def test_get_host_gpu_detects_orin_igpu(monkeypatch):
    monkeypatch.setattr(sdk, "get_gpu_name", lambda: "Orin (nvgpu)")

    assert sdk.get_host_gpu() == "igpu"


def test_get_default_cuda_version_from_driver(monkeypatch):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(sdk, "run_info_command", lambda cmd: "580.126.20")

    assert sdk.get_default_cuda_version() == "13"


def test_get_default_cuda_version_falls_back_without_nvidia_smi(monkeypatch, capsys):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: None)

    assert sdk.get_default_cuda_version() == "13"
    assert "nvidia-smi not found" in capsys.readouterr().err


def test_get_cuda_tag_handles_sdk_and_cuda_matrix(monkeypatch):
    monkeypatch.setattr(sdk, "get_host_gpu", lambda: "igpu")
    monkeypatch.setattr(sdk, "get_default_cuda_version", lambda: "12")

    assert sdk.get_cuda_tag(sdk_version="3.6.0") == "igpu"
    assert sdk.get_cuda_tag(sdk_version="3.6.1") == "cuda13-dgpu"
    assert sdk.get_cuda_tag(None) == "cuda12-igpu"
    assert sdk.get_cuda_tag(None, sdk_version="4.2.0") == "cuda12-igpu"
    assert sdk.get_cuda_tag("13", sdk_version="4.2.0") == "cuda13"
    assert sdk.get_cuda_tag("14", sdk_version="4.2.0") == "cuda14-igpu"


@pytest.mark.parametrize(
    "machine,expected",
    [
        ("x86_64", "x86_64"),
        ("AMD64", "x86_64"),
        ("aarch64", "aarch64"),
        ("arm64", "aarch64"),
        ("riscv64", "riscv64"),
    ],
)
def test_get_host_arch_normalizes_common_architectures(monkeypatch, machine, expected):
    monkeypatch.setattr(sdk.platform, "machine", lambda: machine)

    assert sdk.get_host_arch() == expected


def test_get_sdk_version_and_validation_from_install_tree(tmp_path):
    install = tmp_path / "install"
    config_dir = install / "lib" / "cmake" / "holoscan"
    config_dir.mkdir(parents=True)
    (config_dir / "holoscan-config.cmake").write_text("# ok\n", encoding="utf-8")
    (config_dir / "holoscan-config-version.cmake").write_text(
        'set(PACKAGE_VERSION "4.2.1")\n',
        encoding="utf-8",
    )

    assert sdk.is_valid_sdk_installation(install)
    assert sdk.get_sdk_version(install) == "4.2.1"
    (install / "VERSION").write_text("4.3.0\n", encoding="utf-8")
    assert sdk.get_sdk_version(install) == "4.3.0"


def test_find_hsdk_build_rel_dir_prefers_install_then_build(tmp_path, monkeypatch):
    root = tmp_path / "sdk-src"
    install = root / "install-x86_64"
    build = root / "build-x86_64"
    for candidate in (install, build):
        config_dir = candidate / "lib" / "cmake" / "holoscan"
        config_dir.mkdir(parents=True)
        (config_dir / "HoloscanConfig.cmake").write_text("# ok\n", encoding="utf-8")
    monkeypatch.delenv("HOLOSCAN_SDK_ROOT", raising=False)
    monkeypatch.setattr(sdk, "get_arch_gpu_str", lambda: "x86_64")

    assert sdk.find_hsdk_build_rel_dir(root) == "install-x86_64"
    assert sdk.find_hsdk_build_rel_dir(root / "missing") == "build-x86_64"


def test_get_compute_capacity_from_nvidia_smi(monkeypatch):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        sdk.subprocess,
        "check_output",
        lambda cmd: b"9.0\n8.9\n",
    )

    assert sdk.get_compute_capacity() == "9.0"


def test_get_cuda_runtime_version_from_dpkg(monkeypatch):
    monkeypatch.setattr(
        sdk.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="ii  cuda-cudart-13-0  13.0.48-1  amd64  CUDA Runtime\n",
        ),
    )

    assert sdk.get_cuda_runtime_version() == "13.0.48"


def test_check_nvidia_ctk_rejects_missing_or_old_tool(monkeypatch):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit):
        sdk.check_nvidia_ctk()

    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/usr/bin/nvidia-ctk")
    monkeypatch.setattr(
        sdk.subprocess,
        "check_output",
        lambda cmd, **kwargs: "NVIDIA Container Toolkit CLI version 1.10.0\n",
    )
    with pytest.raises(SystemExit):
        sdk.check_nvidia_ctk()


def test_check_nvidia_ctk_accepts_new_tool(monkeypatch):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/usr/bin/nvidia-ctk")
    monkeypatch.setattr(
        sdk.subprocess,
        "check_output",
        lambda cmd, **kwargs: "NVIDIA Container Toolkit CLI version 1.16.2\n",
    )

    sdk.check_nvidia_ctk()


def test_get_gpu_name_and_compute_capacity_handle_subprocess_failures(monkeypatch):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(sdk.subprocess, "check_output", fail)

    assert sdk.get_gpu_name() is None
    assert sdk.get_compute_capacity() == "0.0"
