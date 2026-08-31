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


def test_get_host_gpu_orin_driver_disambiguation(monkeypatch):
    monkeypatch.setattr(sdk, "get_gpu_name", lambda: "Orin (nvgpu)")

    monkeypatch.setattr(sdk, "get_default_cuda_version", lambda: "12")
    assert sdk.get_host_gpu() == "igpu"

    sdk.get_host_gpu.cache_clear()
    monkeypatch.setattr(sdk, "get_default_cuda_version", lambda: "13")
    assert sdk.get_host_gpu() == "dgpu"

    sdk.get_host_gpu.cache_clear()
    monkeypatch.setattr(sdk, "get_default_cuda_version", lambda: None)
    assert sdk.get_host_gpu() == "dgpu"


def test_get_host_gpu_non_orin(monkeypatch):
    monkeypatch.setattr(sdk, "get_gpu_name", lambda: "NVIDIA RTX 4090")

    assert sdk.get_host_gpu() == "dgpu"


def test_get_default_cuda_version_from_driver(monkeypatch):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(sdk, "run_info_command", lambda cmd: "580.126.20")

    assert sdk.get_default_cuda_version() == "13"


def test_get_default_cuda_version_falls_back_without_nvidia_smi(monkeypatch, capsys):
    monkeypatch.setattr(sdk.shutil, "which", lambda name: None)

    assert sdk.get_default_cuda_version() == "13"
    assert "nvidia-smi not found" in capsys.readouterr().err


def test_get_cuda_tag_handles_sdk_and_cuda_matrix(monkeypatch):
    # Host probes are stubbed so the matrix is deterministic: the host GPU is
    # pinned to igpu and the auto-detected CUDA version to 12. That is why a
    # ``None`` cuda_version (auto-detect) resolves to an igpu tag at CUDA 12.
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


def test_get_sdk_version_and_validation_from_install_tree(tmp_path, make_sdk_directory):
    install = make_sdk_directory(tmp_path / "install")
    config_dir = install / "lib" / "cmake" / "holoscan"
    (config_dir / "holoscan-config-version.cmake").write_text(
        'set(PACKAGE_VERSION "4.2.1")\n',
        encoding="utf-8",
    )

    assert sdk.is_valid_sdk_installation(install)
    assert not sdk.is_valid_sdk_build(install)
    assert sdk.is_valid_sdk_directory(install)
    assert sdk.get_sdk_version(install) == "4.2.1"
    (install / "VERSION").write_text("4.3.0\n", encoding="utf-8")
    assert sdk.get_sdk_version(install) == "4.3.0"


def test_get_sdk_version_and_validation_from_4x_build_tree(tmp_path, make_sdk_directory):
    build = make_sdk_directory(tmp_path / "build-cu13-x86_64", build=True)
    (build / "holoscan-config-version.cmake").write_text(
        'set(PACKAGE_VERSION "4.6.0")\n',
        encoding="utf-8",
    )

    assert not sdk.is_valid_sdk_installation(build)
    assert sdk.is_valid_sdk_build(build)
    assert sdk.is_valid_sdk_directory(build)
    assert sdk.get_sdk_version(build) == "4.6.0"
    assert sdk.get_sdk_cmake_prefix_path(build) == f"{build};{build / 'lib'}"


def test_find_hsdk_dir_prefers_cuda_install_then_other_install_then_build(
    tmp_path, make_sdk_directory
):
    root = tmp_path / "sdk-src"
    install_cuda12 = make_sdk_directory(
        root / "public/install-cu12-x86_64", config_name="HoloscanConfig.cmake"
    )
    install_cuda13 = make_sdk_directory(
        root / "public/install-cu13-x86_64", config_name="HoloscanConfig.cmake"
    )
    make_sdk_directory(root / "public/build-cu13-x86_64", build=True)

    assert (
        sdk.find_hsdk_dir(root, target_arch="x86_64", cuda_version="13")
        == "public/install-cu13-x86_64"
    )
    assert sdk.resolve_sdk_installation(root, "x86_64", "13") == install_cuda13

    (install_cuda13 / "lib/cmake/holoscan/HoloscanConfig.cmake").unlink()
    assert (
        sdk.find_hsdk_dir(root, target_arch="x86_64", cuda_version="13")
        == "public/install-cu12-x86_64"
    )

    (install_cuda12 / "lib/cmake/holoscan/HoloscanConfig.cmake").unlink()
    assert (
        sdk.find_hsdk_dir(root, target_arch="x86_64", cuda_version="13")
        == "public/build-cu13-x86_64"
    )


@pytest.mark.parametrize(
    ("source_version", "expected"),
    [
        ("4.6.0", "public/install-cu13-x86_64"),
        ("5.0.0", "public/install-x86_64"),
    ],
)
def test_find_hsdk_dir_uses_source_version_to_select_4x_or_5x_layout(
    tmp_path, source_version, expected, make_sdk_directory
):
    root = tmp_path / "sdk-src"
    public = root / "public"
    public.mkdir(parents=True)
    (public / "VERSION").write_text(f"{source_version}\n", encoding="utf-8")
    for name in ("install-cu13-x86_64", "install-x86_64"):
        make_sdk_directory(public / name)

    assert sdk.find_hsdk_dir(root, target_arch="x86_64", cuda_version="13") == expected
    assert sdk.resolve_sdk_directory(root, "x86_64", "13") == root / expected


def test_find_hsdk_dir_supports_4x_developer_build_layout(tmp_path, make_sdk_directory):
    root = tmp_path / "sdk-src"
    build = root / "public/build-debug-x86_64"
    (root / "public").mkdir(parents=True)
    (root / "public/VERSION").write_text("4.6.0\n", encoding="utf-8")
    make_sdk_directory(build, build=True)

    assert (
        sdk.find_hsdk_dir(root, target_arch="x86_64", cuda_version="13")
        == "public/build-debug-x86_64"
    )
    assert sdk.resolve_sdk_directory(root, "x86_64", "13") == build
    assert sdk.resolve_sdk_installation(root, "x86_64", "13") is None


def test_resolve_local_sdk_dir_accepts_direct_4x_build_tree(tmp_path, make_sdk_directory):
    build = make_sdk_directory(tmp_path / "build-cu13-x86_64", build=True)

    assert (
        sdk.resolve_local_sdk_dir(
            "/opt/nvidia/holoscan",
            build,
            environ={
                "HOLOSCAN_CLI_TARGET_ARCH": "x86_64",
                "HOLOSCAN_CLI_DEFAULT_CUDA_VERSION": "13",
            },
        )
        == build.resolve()
    )


def test_find_hsdk_dir_explicit_parent_outranks_ambient_install(
    tmp_path, monkeypatch, make_sdk_directory
):
    explicit_root = tmp_path / "explicit-sdk"
    explicit_install = explicit_root / "install-cu13-x86_64"
    ambient_install = tmp_path / "ambient-sdk"
    for candidate in (explicit_install, ambient_install):
        make_sdk_directory(candidate, config_name="HoloscanConfig.cmake")
    monkeypatch.setenv("HOLOSCAN_SDK_ROOT", str(ambient_install))

    assert (
        sdk.find_hsdk_dir(explicit_root, target_arch="x86_64", cuda_version="13")
        == "install-cu13-x86_64"
    )


def test_resolve_local_sdk_dir_treats_empty_environment_as_unset(tmp_path):
    assert sdk.resolve_local_sdk_dir(tmp_path, environ={"HOLOSCAN_SDK_ROOT": ""}) == tmp_path


@pytest.mark.parametrize("gpu", ["igpu", "dgpu"])
def test_find_hsdk_dir_prefers_host_aarch64_gpu_variant(
    tmp_path, monkeypatch, gpu, make_sdk_directory
):
    root = tmp_path / "sdk-src"
    for name in ("install-cu13-aarch64-dgpu", "install-cu13-aarch64-igpu"):
        make_sdk_directory(root / name, config_name="HoloscanConfig.cmake")
    monkeypatch.setattr(sdk, "get_host_gpu", lambda: gpu)

    assert (
        sdk.find_hsdk_dir(root, target_arch="aarch64", cuda_version="13")
        == f"install-cu13-aarch64-{gpu}"
    )


def test_find_hsdk_dir_never_falls_back_to_another_target(
    tmp_path, monkeypatch, make_sdk_directory
):
    root = tmp_path / "sdk-src"
    for name in ("install-cu13-x86_64", "install"):
        make_sdk_directory(root / name, config_name="HoloscanConfig.cmake")
    monkeypatch.setattr(sdk, "get_host_gpu", lambda: "dgpu")

    assert (
        sdk.find_hsdk_dir(root, target_arch="aarch64", cuda_version="13")
        == "build-cu13-aarch64-dgpu"
    )


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
