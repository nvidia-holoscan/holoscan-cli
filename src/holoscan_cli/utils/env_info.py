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

import holoscan_cli
from holoscan_cli.utils.holohub import get_sccache_dir
from holoscan_cli.utils.io import Color, run_info_command
from holoscan_cli.utils.text import get_env_bool


def _managed_venv_dir() -> Path:
    """The wrapper-managed venv location (mirrors the ./holohub default)."""
    default = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return Path(os.environ.get("HOLOSCAN_CLI_VENV") or default / "holoscan-cli" / "venv")


def collect_cli_info() -> None:
    """Collect and display information about the holoscan-cli package itself:
    version, install location, which Python environment it runs in, and how
    to remove it."""
    print(f"\n{Color.blue('Holoscan CLI Information:')}")
    print(f"  Version: {holoscan_cli.__version__}")
    print(f"  Package: {Path(holoscan_cli.__file__).parent}")
    prefix = Path(sys.prefix).resolve()
    if prefix == _managed_venv_dir().resolve():
        print(f"  Environment: wrapper-managed venv ({prefix})")
        print(f"  Uninstall: rm -rf {prefix}  (the wrapper re-provisions on next run)")
    elif sys.prefix != sys.base_prefix:
        print(f"  Environment: virtual environment ({prefix})")
        print(f"  Uninstall: {sys.executable} -m pip uninstall holoscan-cli")
    else:
        print(f"  Environment: system Python ({prefix})")
        print(f"  Uninstall: {sys.executable} -m pip uninstall holoscan-cli")
    source = os.environ.get("HOLOSCAN_CLI_SOURCE")
    if source:
        print(f"  Source override (HOLOSCAN_CLI_SOURCE): {source}")


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
    """Collect and display source-project information"""
    print(f"\n{Color.blue('Source Project Information:')}")
    print(f"  HOLOSCAN_CLI_ROOT: {holohub_root}")
    print(f"  HOLOSCAN_CLI_BUILD_PARENT_DIR: {build_dir}")
    print(f"  HOLOSCAN_CLI_DATA_DIR: {data_dir}")
    print(f"  HOLOSCAN_CLI_SDK_DIR: {sdk_dir}")


def collect_git_info(holohub_root: Path) -> None:
    """Collect and display Git repository information"""
    print(f"\n{Color.blue('Git Repository Information:')}")
    if not holohub_root.exists() or not holohub_root.is_dir():
        print(
            "  Source-project root directory does not exist or is not a directory: "
            f"{holohub_root}"
        )
        return
    original_cwd = os.getcwd()
    try:
        os.chdir(holohub_root)
    except Exception as e:
        print(f"  Cannot access source-project directory: {e}")
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
    docker_exe = os.environ.get("HOLOSCAN_CLI_DOCKER_EXE", "docker")
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
    print(f"\n{Color.blue('Holoscan CLI Environment Variables:')}")
    holoscan_cli_env_vars = [
        "HOLOSCAN_CLI_SOURCE",
        "HOLOSCAN_CLI_VENV",
        "HOLOSCAN_CLI_PYTHON_BIN",
        "HOLOSCAN_CLI_INSTALL_ARGS",
        "HOLOSCAN_CLI_CMD_NAME",
        "HOLOSCAN_CLI_BUILD_LOCAL",
        "HOLOSCAN_CLI_ALWAYS_BUILD",
        "HOLOSCAN_CLI_ENABLE_SCCACHE",
        "HOLOSCAN_CLI_BUILD_PARENT_DIR",
        "HOLOSCAN_CLI_DATA_DIR",
        "HOLOSCAN_CLI_DEFAULT_HSDK_DIR",
        "HOLOSCAN_CLI_CTEST_SCRIPT",
        "HOLOSCAN_CLI_REPO_PREFIX",
        "HOLOSCAN_CLI_CONTAINER_PREFIX",
        "HOLOSCAN_CLI_WORKSPACE_NAME",
        "HOLOSCAN_CLI_HOSTNAME_PREFIX",
        "HOLOSCAN_CLI_BASE_IMAGE",
        "HOLOSCAN_CLI_DOCKER_EXE",
        "HOLOSCAN_CLI_BASE_SDK_VERSION",
        "HOLOSCAN_CLI_BENCHMARKING_SUBDIR",
        "HOLOSCAN_CLI_DEFAULT_DOCKERFILE",
        "HOLOSCAN_CLI_BASE_IMAGE_FORMAT",
        "HOLOSCAN_CLI_DEFAULT_IMAGE_FORMAT",
        "HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS",
        "HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS",
        "HOLOSCAN_CLI_DATA_PATH",
        "HOLOSCAN_CLI_SETUP_SCRIPTS_DIR",
        "HOLOSCAN_CLI_SEARCH_PATH",
        "HOLOSCAN_CLI_APP_NAME",
        "HOLOSCAN_CLI_PATH_PREFIX",
    ]
    for var in sorted(holoscan_cli_env_vars):
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
        "PIP_BREAK_SYSTEM_PACKAGES",
        "XDG_SESSION_TYPE",
        "XDG_RUNTIME_DIR",
    ]
    for var in sorted(other_env_vars):
        print(f"  {var}: {os.environ.get(var) or '(not set)'}")


def collect_env_info() -> None:
    """Collect and display comprehensive environment information"""
    collect_cli_info()
    collect_system_info()
    collect_python_info()
    collect_docker_info()
    collect_cuda_gpu_info()
    collect_sccache_info()
    collect_environment_variables()


def collect_sccache_info() -> None:
    """Collect and display sccache-related information"""
    print(f"\n{Color.blue('sccache Information:')}")

    enable_val, enabled = get_env_bool("HOLOSCAN_CLI_ENABLE_SCCACHE", default=False)
    print(f"  HOLOSCAN_CLI_ENABLE_SCCACHE: {enable_val} ({'enabled' if enabled else 'disabled'})")

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
