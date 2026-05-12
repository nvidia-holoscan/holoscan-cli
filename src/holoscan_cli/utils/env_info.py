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

"""``collect_*`` printers used by ``holoscan env-info``.

Each ``collect_*`` function inspects one slice of the host (system,
Python, Docker, CUDA/GPU, sccache, environment variables) and prints a
formatted block to stdout. They are pure I/O helpers; the env-info
command composes them into a single report.
"""

import os
import platform
import shutil
import sys
from pathlib import Path

from holoscan_cli.utils.holohub import get_sccache_dir
from holoscan_cli.utils.io import Color, run_info_command
from holoscan_cli.utils.text import get_env_bool


def collect_system_info() -> None:
    """Collect and display system information"""
    print(f"\n{Color.blue('System Information:')}")
    print(f"  OS: {platform.system()} {platform.release()} {platform.machine()}")
    print(f"  Platform: {platform.platform()}")


def collect_python_info() -> None:
    """Collect and display Python information"""
    print(f"\n{Color.blue('Python Information:')}")
    print(f"  Version: {sys.version}")
    print(f"  Executable: {sys.executable} Path: {sys.path[0] if sys.path else 'N/A'}")


def collect_holohub_info(
    holohub_root: Path, build_dir: Path, data_dir: Path, sdk_dir: Path
) -> None:
    """Collect and display HoloHub information"""
    print(f"\n{Color.blue('HoloHub Information:')}")
    print(f"  HOLOHUB_ROOT: {holohub_root}")
    print(f"  HOLOHUB_BUILD_PARENT_DIR: {build_dir}")
    print(f"  HOLOHUB_DATA_DIR: {data_dir}")
    print(f"  HOLOHUB_SDK_DIR: {sdk_dir}")


def collect_git_info(holohub_root: Path) -> None:
    """Collect and display Git repository information"""
    print(f"\n{Color.blue('Git Repository Information:')}")
    if not holohub_root.exists() or not holohub_root.is_dir():
        print(f"  HoloHub root directory does not exist or is not a directory: {holohub_root}")
        return
    original_cwd = os.getcwd()
    try:
        os.chdir(holohub_root)
    except Exception as e:
        print(f"  Cannot access HoloHub directory: {e}")
        return
    try:
        git_branch = run_info_command(["git", "branch", "--show-current"])
        git_commit_full = run_info_command(["git", "rev-parse", "HEAD"])
        git_status = run_info_command(["git", "status", "--porcelain"])
        if git_branch is None or git_commit_full is None or git_status is None:
            print("  Git information not available")
            return
        git_commit = git_commit_full[:8]
        print(f"  Branch: {git_branch} Commit: {git_commit}")
        print(f"  Modified: {git_status.splitlines()}")
    finally:
        try:
            os.chdir(original_cwd)  # try to restore the original working directory
        except Exception:
            pass


def collect_docker_info() -> None:
    """Collect and display Docker information"""
    print(f"\n{Color.blue('Docker Information:')}")
    docker_exe = os.environ.get("HOLOHUB_DOCKER_EXE", "docker")
    docker_version = run_info_command([docker_exe, "--version"])
    docker_info = run_info_command([docker_exe, "info", "--format", "{{.ServerVersion}}"])
    if docker_version is None or docker_info is None:
        print("  Docker not available")
        return
    print(f"  Version: {docker_version} Server Version: {docker_info}")
    nvidia_ctk_version = run_info_command(["nvidia-ctk", "--version"])
    if nvidia_ctk_version is not None:
        print(f"  NVIDIA Container Toolkit: {nvidia_ctk_version.strip()}")


def collect_cuda_gpu_info() -> None:
    """Collect and display CUDA/GPU information"""
    print(f"\n{Color.blue('CUDA/GPU Information:')}")
    nvidia_smi = run_info_command(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    if nvidia_smi is None:
        print("  NVIDIA GPU/CUDA not available")
        return
    for i, line in enumerate(nvidia_smi.split("\n")):
        if line.strip():
            parts = line.split(",")
            if len(parts) >= 3:
                print(f"  GPU {i}: {parts[0].strip()}")
                print(f"    Driver: {parts[1].strip()}")
                print(f"    Memory: {parts[2].strip()} MB")
    cuda_version = run_info_command(["nvcc", "--version"])
    if cuda_version is None:
        print("  nvcc not available")
        return
    version_line = [line for line in cuda_version.split("\n") if "release" in line.lower()]
    print(f"  NVCC: {version_line[0].strip()}")
    nvcc_path = run_info_command(["which", "nvcc"])
    if nvcc_path is not None:
        print(f"  NVCC Path: {nvcc_path}")


def collect_environment_variables() -> None:
    """Collect and display environment variables"""
    print(f"\n{Color.blue('HoloHub Environment Variables:')}")
    holohub_env_vars = [
        "HOLOHUB_CMD_NAME",
        "HOLOHUB_BUILD_LOCAL",
        "HOLOHUB_ALWAYS_BUILD",
        "HOLOHUB_ENABLE_SCCACHE",
        "HOLOHUB_BUILD_PARENT_DIR",
        "HOLOHUB_DATA_DIR",
        "HOLOHUB_DEFAULT_HSDK_DIR",
        "HOLOHUB_CTEST_SCRIPT",
        "HOLOHUB_REPO_PREFIX",
        "HOLOHUB_CONTAINER_PREFIX",
        "HOLOHUB_WORKSPACE_NAME",
        "HOLOHUB_HOSTNAME_PREFIX",
        "HOLOHUB_BASE_IMAGE",
        "HOLOHUB_DOCKER_EXE",
        "HOLOHUB_BASE_SDK_VERSION",
        "HOLOHUB_BENCHMARKING_SUBDIR",
        "HOLOHUB_DEFAULT_DOCKERFILE",
        "HOLOHUB_BASE_IMAGE_FORMAT",
        "HOLOHUB_DEFAULT_IMAGE_FORMAT",
        "HOLOHUB_DEFAULT_DOCKER_BUILD_ARGS",
        "HOLOHUB_DEFAULT_DOCKER_RUN_ARGS",
        "HOLOHUB_DOCS_URL",
        "HOLOHUB_CLI_DOCS_URL",
        "HOLOHUB_DATA_PATH",
        "HOLOHUB_SETUP_SCRIPTS_DIR",
        "HOLOHUB_SEARCH_PATH",
        # Legacy variables
        "HOLOHUB_APP_NAME",
        "HOLOHUB_CONTAINER_BASE_NAME",
        "HOLOHUB_PATH_PREFIX",
    ]
    for var in sorted(holohub_env_vars):
        print(f"  {var}: {os.environ.get(var) or '(not set)'}")

    print(f"\n{Color.blue('Holoscan Environment Variables:')}")
    holoscan_env_vars = ["HOLOSCAN_SDK_VERSION", "HOLOSCAN_INPUT_PATH"]
    for var in sorted(holoscan_env_vars):
        print(f"  {var}: {os.environ.get(var) or '(not set)'}")

    print(f"\n{Color.blue('Other Relevant Environment Variables:')}")
    other_env_vars = [
        "PYTHONPATH",
        "PATH",
        "LD_LIBRARY_PATH",
        "CMAKE_BUILD_TYPE",
        "DOCKER_BUILDKIT",
        "XDG_SESSION_TYPE",
        "XDG_RUNTIME_DIR",
    ]
    for var in sorted(other_env_vars):
        print(f"  {var}: {os.environ.get(var) or '(not set)'}")


def collect_env_info() -> None:
    """Collect and display comprehensive environment information"""
    collect_system_info()
    collect_python_info()
    collect_docker_info()
    collect_cuda_gpu_info()
    collect_sccache_info()
    collect_environment_variables()


def collect_sccache_info() -> None:
    """Collect and display sccache-related information"""
    print(f"\n{Color.blue('sccache Information:')}")

    enable_val, enabled = get_env_bool("HOLOHUB_ENABLE_SCCACHE", default=False)
    print(f"  HOLOHUB_ENABLE_SCCACHE: {enable_val} ({'enabled' if enabled else 'disabled'})")

    sccache_bin = shutil.which("sccache")
    version = run_info_command(["sccache", "--version"]) if sccache_bin else None
    print(f"  sccache binary: {sccache_bin or '(not found in PATH)'}")
    print(f"  sccache version: {version or '(unavailable)'}")

    effective_dir = get_sccache_dir()
    print(f"  Local SCCACHE_DIR: {effective_dir}")

    # Collect SCCACHE_* variables once, excluding SCCACHE_DIR which is already printed above.
    sccache_items = [
        (key, value or "(not set)")
        for key, value in os.environ.items()
        if key.startswith("SCCACHE_") and key != "SCCACHE_DIR"
    ]
    if sccache_items:
        print("  SCCACHE_* environment variables:")
        for key, value in sorted(sccache_items):
            print(f"    {key}: {value}")
    else:
        print("  SCCACHE_* environment variables: (none set)")
