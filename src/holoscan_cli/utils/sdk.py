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

"""Holoscan SDK / GPU / CUDA detection helpers.

These helpers only inspect the host (``nvidia-smi``, ``nvidia-ctk``,
filesystem layout) — none of them mutate state. They underpin the
container-tag selection in :mod:`holoscan_cli.container.core` and the
SDK-discovery branches in the project ``run`` / ``test`` commands.
"""

import functools
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union

from holoscan_cli.utils.io import fatal, run_info_command, warn
from holoscan_cli.utils.text import parse_semantic_version


def check_nvidia_ctk(min_version: str = "1.12.0", recommended_version: str = "1.14.1") -> None:
    """Check NVIDIA Container Toolkit version"""

    if not shutil.which("nvidia-ctk"):
        fatal("nvidia-ctk not found. Please install the NVIDIA Container Toolkit.")

    try:
        output = subprocess.check_output(["nvidia-ctk", "--version"], text=True)
        match = re.search(r"(\d+\.\d+\.\d+)", output)
        if match:
            version = match.group(1)
            try:
                version_check = parse_semantic_version(version) < parse_semantic_version(
                    min_version
                )
            except ValueError:
                version_check = False

            if version_check:
                fatal(
                    f"Found nvidia-ctk {version}. Version {min_version}+ is required "
                    f"({recommended_version}+ recommended)."
                )
        else:
            print(f"Failed to parse available nvidia-ctk version: {output}")
    except subprocess.CalledProcessError:
        fatal(f"Could not determine nvidia-ctk version. Version {min_version}+ required.")


@functools.cache
def get_gpu_name() -> Optional[str]:
    """
    Helper function to get GPU name from nvidia-smi.  Returns None if nvidia-smi is not available.
    """
    if not shutil.which("nvidia-smi"):
        return None
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return output.strip() if output else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


@functools.cache
def get_host_gpu() -> str:
    """Determine if running on dGPU or iGPU"""
    gpu_name = get_gpu_name()
    if gpu_name is None:
        print(
            "Could not find any GPU drivers on host. Defaulting build to target dGPU/CPU stack.",
            file=sys.stderr,
        )
        return "dgpu"

    # Orin (nvgpu) appears on both JP6.x (integrated GPU stack, driver ~540)
    # and JP7.x (SBSA-compatible dGPU stack, driver >= 580). Use CUDA/driver
    # version to distinguish: JP6.x / IGX OS 1.x ship CUDA 12 (driver < 580);
    # JP7.x / IGX OS 2.x ship CUDA 13 (driver >= 580).
    if "Orin (nvgpu)" in gpu_name:
        return "igpu" if get_default_cuda_version() == "12" else "dgpu"
    return "dgpu"


def cuda_major_from_driver(driver_version_str: str) -> Optional[str]:
    """Map a driver version string (e.g. '580.126.20') to a CUDA major version.

    Returns '13' for driver >= 580, '12' otherwise, or None on parse failure.
    """
    try:
        return "13" if int(driver_version_str.split(".")[0]) >= 580 else "12"
    except (ValueError, IndexError):
        return None


@functools.cache
def get_default_cuda_version() -> str:
    """
    Get default CUDA version based on NVIDIA driver version.

    Returns:
        - "13" if driver version >= 580 or if nvidia-smi is not available
        - "12" if driver version < 580
    """
    if not shutil.which("nvidia-smi"):
        warn("nvidia-smi not found, default CUDA version is 13")
        return "13"

    driver_version = run_info_command(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]
    )

    if not driver_version:
        warn("Unable to detect NVIDIA driver version, default CUDA version is 13")
        return "13"

    result = cuda_major_from_driver(driver_version)
    if result is None:
        warn(f"Unable to parse driver version '{driver_version}', default CUDA version is 13")
        return "13"
    return result


def get_cuda_tag(
    cuda_version: Optional[Union[str, int]] = None, sdk_version: Optional[str] = None
) -> str:
    """
    Determine the CUDA container tag based on CUDA version and GPU type.

    SDK version support:
    - SDK < 3.6.1: Old format (dgpu/igpu)
    - SDK == 3.6.1: only cuda13-dgpu available
    - SDK >= 3.7.0: Full CUDA support
      - cuda13: CUDA 13 (x86_64, Jetson AGX Orin w/ JP7.x, Jetson AGX Thor w/ JP7.x)
      - cuda12-dgpu: CUDA 12 dGPU (x86_64, IGX Orin dGPU, Clara AGX dGPU, GH200)
      - cuda12-igpu: CUDA 12 iGPU (Jetson AGX Orin w/ JP6.x, IGX Orin iGPU w/ IGX OS 1.x, Clara AGX iGPU)

    Args:
        cuda_version: CUDA major version (e.g., 12, 13). If None, uses platform default.
        sdk_version: Optional SDK version string (e.g., "3.6.0", "3.6.1", "3.7.0").
            When omitted or unparsable, the current CUDA tag scheme is used.

    Returns:
        The appropriate container tag string
    """
    sdk_ver = None
    if sdk_version:
        try:
            sdk_ver = parse_semantic_version(sdk_version)
        except (ValueError, IndexError):
            sdk_ver = None
    if sdk_ver is not None and sdk_ver < (3, 6, 1):
        return get_host_gpu()
    if sdk_ver == (3, 6, 1):
        return "cuda13-dgpu"
    if cuda_version is None:
        cuda_version = get_default_cuda_version()
    cuda_str = str(cuda_version)
    if cuda_str == "13":
        return "cuda13"
    if cuda_str == "12":
        return f"cuda12-{get_host_gpu()}"
    return f"cuda{cuda_str}-{get_host_gpu()}"


@functools.cache
def get_host_arch() -> str:
    """Get host architecture"""
    machine = platform.machine().lower()
    if machine in ["x86_64", "amd64"]:
        return "x86_64"
    if machine in ["aarch64", "arm64"]:
        return "aarch64"
    return machine


def get_arch_gpu_str() -> str:
    """Get architecture+GPU string like bash get_arch+gpu_str()"""
    arch = get_host_arch()
    if arch == "aarch64":
        gpu = get_host_gpu()
        return f"{arch}-{gpu}"
    return arch


def get_sdk_version(sdk_path: Path) -> str:
    """Extract Holoscan SDK version from a valid SDK installation path."""
    try:
        version_file = sdk_path / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
        cmake_config = sdk_path / "lib" / "cmake" / "holoscan" / "holoscan-config-version.cmake"
        if cmake_config.exists():
            content = cmake_config.read_text()
            match = re.search(r'PACKAGE_VERSION\s+"([^"]+)"', content)
            if match:
                return match.group(1)
    except (OSError, UnicodeDecodeError):
        pass
    return "unknown"


def is_valid_sdk_installation(path: Union[str, Path]) -> bool:
    """
    Validate if a directory contains a valid Holoscan SDK installation.
    """
    path = Path(path) if isinstance(path, str) else path
    if not path.exists() or not path.is_dir() or not (path / "lib").exists():
        return False
    # Check for at least one of these to confirm it's a Holoscan SDK
    return (path / "lib" / "cmake" / "holoscan" / "holoscan-config.cmake").exists() or (
        path / "lib" / "cmake" / "holoscan" / "HoloscanConfig.cmake"
    ).exists()


def find_hsdk_build_rel_dir(local_sdk_root: Optional[Union[str, Path]] = None) -> str:
    """
    Find a suitable SDK installation or build directory.
    https://github.com/nvidia-holoscan/holoscan-sdk/blob/9c5b3c3d4831f2e65ebda6b79ae9b1c5517c6a7c/run#L226-L228

    Search order:
    1. Direct SDK installation directory
    2. Environment variable `HOLOSCAN_SDK_ROOT` SDK root directory
    3. Assuming the direct or env var is the src code root, searching for immediate subdirectories:
        3.1 Install directory (prefer)
        3.2 Build directory (fallback)

    Args:
        local_sdk_root: Path to SDK root directory, or direct SDK installation/build directory

    Returns:
        Relative path to the SDK directory from the root, or absolute path if passed directly
    """
    search_paths = []

    # Handle user-provided path
    if local_sdk_root:
        local_sdk_root = Path(local_sdk_root) if isinstance(local_sdk_root, str) else local_sdk_root
        if local_sdk_root.exists():
            # Check if this is a direct SDK installation directory
            if is_valid_sdk_installation(local_sdk_root):
                return str(local_sdk_root)
            else:
                # Treat as SDK root directory to search
                search_paths.append(local_sdk_root)

    # Add environment variable path
    if os.environ.get("HOLOSCAN_SDK_ROOT"):
        env_path = Path(os.environ["HOLOSCAN_SDK_ROOT"])
        if env_path.exists():
            if is_valid_sdk_installation(env_path):
                return str(env_path)
            else:
                search_paths.append(env_path)

    # Search within SDK root directories
    arch_gpu = get_arch_gpu_str()
    for sdk_path in search_paths:
        for install_dir in [f"install-{arch_gpu}", "install"]:
            if is_valid_sdk_installation(sdk_path / install_dir):
                return install_dir
        for install_dir in sorted([d.name for d in sdk_path.glob("install-*") if d.is_dir()]):
            if is_valid_sdk_installation(sdk_path / install_dir):
                return install_dir
        for build_dir in [f"build-{arch_gpu}", "build"]:
            if is_valid_sdk_installation(sdk_path / build_dir):
                return build_dir
        for build_dir in sorted([d.name for d in sdk_path.glob("build-*") if d.is_dir()]):
            if is_valid_sdk_installation(sdk_path / build_dir):
                return build_dir
    return f"build-{arch_gpu}"


def get_compute_capacity() -> str:
    """Get GPU compute capacity"""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return "0.0"
    try:
        output = subprocess.check_output(
            [nvidia_smi, "--query-gpu=compute_cap", "--format=csv,noheader"]
        )
        return output.decode().strip().split("\n")[0]
    except (subprocess.CalledProcessError, OSError):
        return "0.0"


def get_cuda_runtime_version() -> Optional[str]:
    """Get CUDA runtime version from dpkg"""
    try:
        result = subprocess.run(["dpkg", "-l"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None

        cuda_pattern = re.search(r"cuda-cudart-[0-9]+-[0-9]+.*\n", result.stdout)
        if cuda_pattern:
            version_match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+", cuda_pattern.group(0))
            return version_match.group(0) if version_match else None
    except Exception:
        pass
    return None
