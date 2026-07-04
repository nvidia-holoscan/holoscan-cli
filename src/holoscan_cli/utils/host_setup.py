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

"""Host environment setup helpers used by ``holoscan setup``.

This module bundles two concerns:

* Low-level ``apt`` package-management primitives (``install_packages_if_missing``,
  ``install_cuda_dependencies_package``, ``PackageInstallationError`` ...) used
  to install host packages with version constraints.
* High-level ``setup_*`` orchestrators (``setup_cmake``, ``setup_python_dev``,
  ``setup_ngc_cli``, ``setup_sccache``, ``setup_cuda_*``) that wrap apt / wget /
  vendor shell scripts into idempotent helpers callable individually or together
  via ``handle_setup`` in ``commands/setup_cmd.py``.
"""

import os
import platform
import re
import shutil
import subprocess
import sys
from typing import List, Optional

from holoscan_cli.utils.io import fatal, info, run_command, warn, write_system_file
from holoscan_cli.utils.sdk import get_cuda_runtime_version
from holoscan_cli.utils.text import parse_semantic_version

# ---- apt package management primitives --------------------------------------

_apt_updated = False  # track whether apt update has been called


class PackageInstallationError(Exception):
    """Raised when a package cannot be installed via apt"""

    def __init__(self, package_name: str, version_pattern: str, message: str = None):
        self.package_name = package_name
        self.version_pattern = version_pattern
        super().__init__(
            message or f"Failed to install package {package_name} matching {version_pattern}"
        )


def get_installed_package_version(package_name: str) -> Optional[str]:
    """Get the installed version of a package"""
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", package_name],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def get_available_package_versions(package_name: str) -> List[str]:
    """Get available versions of a package from apt"""
    try:
        result = subprocess.run(
            ["apt-cache", "madison", package_name], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            return []

        versions = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                parts = line.split("|")
                if len(parts) >= 2:
                    version = parts[1].strip()
                    if version:
                        versions.append(version)
        return versions
    except Exception:
        return []


def ensure_apt_updated(dry_run: bool = False) -> None:
    """Ensure apt package list is updated, but only once per session"""
    global _apt_updated
    if not _apt_updated:
        run_command(["apt-get", "update"], dry_run=dry_run, as_root=True)
        _apt_updated = True


def install_packages_if_missing(
    packages: List[str], dry_run: bool = False, apt_options: List[str] = None
) -> List[str]:
    """Install packages only if they're not already installed

    Args:
        packages: List of package names to install (can include version specs like "pkg=1.0*")
            Note: If package has a version spec, it always runs sudo apt install to ensure version.
        dry_run: Whether to perform a dry run
        apt_options: Additional options for apt install

    Returns:
        List of packages that were actually installed (or would be installed in dry run)
    """
    if apt_options is None:
        apt_options = ["--no-install-recommends", "-y"]

    packages_to_install = []

    for package_spec in packages:
        package_name = package_spec.split("=")[0]

        if "=" in package_spec:
            packages_to_install.append(package_spec)
            info(f"Installing {package_spec}")
        else:
            if get_installed_package_version(package_name):
                info(f"Package {package_name} is already installed")
            else:
                packages_to_install.append(package_spec)

    if packages_to_install:
        ensure_apt_updated(dry_run=dry_run)
        install_cmd = ["apt", "install"] + apt_options + packages_to_install
        run_command(install_cmd, dry_run=dry_run, as_root=True)

    return packages_to_install


def install_cuda_dependencies_package(
    package_name: str,
    version_pattern: str = r"\d+\.\d+\.\d+",
    dry_run: bool = False,
) -> str:
    """Install CUDA dependencies package with version checking

    Args:
        package_name: Name of the package to install
        version_pattern: Regular expression for package version to install
        dry_run: Whether to perform a dry run

    Returns:
        str: Installed package version

    Raises:
        PackageInstallationError: If package cannot be installed
    """
    installed_version = get_installed_package_version(package_name)
    if installed_version:
        if re.search(version_pattern, installed_version):
            info(f"Package {package_name} version {installed_version} already installed")
            return installed_version
        else:
            info(f"{package_name} version {installed_version} not match pattern {version_pattern}")

    available_versions = get_available_package_versions(package_name)
    if not available_versions:
        raise PackageInstallationError(
            package_name, version_pattern, f"No versions available for {package_name}"
        )

    matching_versions = [v for v in available_versions if re.search(version_pattern, v)]
    if not matching_versions:
        raise PackageInstallationError(
            package_name,
            version_pattern,
            f"{package_name} has no versions matching pattern {version_pattern}.\n"
            f"Available versions: {', '.join(available_versions[:5])}\n"
            f"You might need to install manually: sudo apt install {package_name}",
        )

    target_version = matching_versions[0]
    install_packages_if_missing(
        [f"{package_name}={target_version}"],
        apt_options=["--no-install-recommends", "-y", "--allow-downgrades"],
        dry_run=dry_run,
    )

    return target_version


def get_ubuntu_codename() -> str:
    """Get Ubuntu codename from os-release"""
    try:
        with open("/etc/os-release") as f:
            content = f.read()
        match = re.search(r"UBUNTU_CODENAME=(\w+)", content)
        return match.group(1) if match else "jammy"
    except (FileNotFoundError, AttributeError):
        return "jammy"


# ---- high-level setup_* orchestrators ---------------------------------------


def setup_cmake(min_version: str = "3.26.4", dry_run: bool = False) -> None:
    """Setup CMake from Kitware if needed"""
    global _apt_updated
    cmake_ver = get_installed_package_version("cmake")
    if cmake_ver and parse_semantic_version(cmake_ver) >= parse_semantic_version(min_version):
        return
    ubuntu_codename = get_ubuntu_codename()
    install_packages_if_missing(["gpg", "wget"], dry_run=dry_run)

    keyring_path = "/usr/share/keyrings/kitware-archive-keyring.gpg"
    source_line = (
        "deb [signed-by=/usr/share/keyrings/kitware-archive-keyring.gpg] "
        f"https://apt.kitware.com/ubuntu/ {ubuntu_codename} main\n"
    )
    if dry_run:
        info(f"[dryrun] Would fetch the Kitware archive key -> {keyring_path}")
        write_system_file("/etc/apt/sources.list.d/kitware.list", source_line, dry_run=True)
    else:
        # Fetch + dearmor the key as the invoking user; install the keyring as
        # root. Two separate steps (not a shell pipeline) so a download failure
        # cannot be masked by the pipeline's exit status and produce an empty
        # keyring.
        try:
            key = subprocess.run(
                ["wget", "-qO-", "https://apt.kitware.com/keys/kitware-archive-latest.asc"],
                check=True,
                capture_output=True,
            ).stdout
            dearmored = subprocess.run(
                ["gpg", "--dearmor"],
                input=key,
                check=True,
                capture_output=True,
            ).stdout
        except FileNotFoundError as e:
            fatal(f"Failed to download the Kitware apt archive key: {e}")
        except subprocess.CalledProcessError as e:
            fatal(
                "Failed to download the Kitware apt archive key "
                f"(is the network available?): {e.stderr.decode(errors='replace').strip()}"
            )
        write_system_file(keyring_path, dearmored)
        write_system_file("/etc/apt/sources.list.d/kitware.list", source_line)
    # The new source must be visible to apt even when an earlier step already
    # ran `apt-get update` (which would make install_packages_if_missing skip it).
    run_command(["apt-get", "update"], dry_run=dry_run, as_root=True)
    _apt_updated = True
    install_packages_if_missing(["cmake", "cmake-curses-gui"], dry_run=dry_run)


def setup_python_dev(min_version: str = "3.10.0", dry_run: bool = False) -> None:
    """Setup Python development packages"""
    python_version = sys.version_info
    python_dev_package = f"python3.{python_version.minor}-dev"
    pydev_ver = get_installed_package_version(python_dev_package)
    if not pydev_ver:
        pydev_ver = get_installed_package_version("python3-dev")
    if not pydev_ver or parse_semantic_version(pydev_ver) < parse_semantic_version(min_version):
        install_packages_if_missing([python_dev_package], dry_run=dry_run)


def setup_ngc_cli(dry_run: bool = False) -> None:
    """Setup NGC CLI if not present"""
    # Container build (root) = system-wide, on PATH in the built image;
    # host = per-user under ~/.local/bin (no root needed).
    if os.geteuid() == 0:
        dest_dir = "/usr/local/bin"
    else:
        dest_dir = os.path.expanduser("~/.local/bin")
    dest = os.path.join(dest_dir, "ngc")
    # Also check the destination itself: ~/.local/bin may not be on PATH, and
    # `which` alone would then re-download NGC on every setup run. A dangling
    # symlink fails the check and is repaired by the `ln -sf` below.
    if shutil.which("ngc") or (os.path.isfile(dest) and os.access(dest, os.X_OK)):
        return
    if os.path.isdir(dest):
        fatal(f"Cannot install NGC CLI: destination is a directory: {dest}")

    arch_suffix = "arm64" if platform.machine() == "aarch64" else "linux"
    ngc_url = (
        "https://api.ngc.nvidia.com/v2/resources/nvidia/ngc-apps/ngc_cli"
        f"/versions/3.64.3/files/ngccli_{arch_suffix}.zip"
    )
    ngc_filename = f"ngccli_{arch_suffix}.zip"

    try:
        run_command(
            ["wget", "--quiet", "--content-disposition", ngc_url, "-O", ngc_filename],
            dry_run=dry_run,
        )
        run_command(["unzip", "-q", ngc_filename], dry_run=dry_run)
        run_command(["chmod", "u+x", "ngc-cli/ngc"], dry_run=dry_run)

        abs_path = os.path.abspath("ngc-cli/ngc")
        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
        run_command(["ln", "-sf", abs_path, dest], dry_run=dry_run)
        if not dry_run and not shutil.which("ngc"):
            info(f"Installed ngc to {dest_dir}; add it to PATH to use 'ngc' directly.")

    except Exception as e:
        fatal(f"Failed to install NGC CLI: {e}")


def setup_sccache(min_version: str = "0.12.0-rapids.20", dry_run: bool = False) -> None:
    """
    Install RAPIDS sccache if missing or older than min_version.

    Requirements:
        - Only RAPIDS-formatted versions are supported, e.g. "0.12.0-rapids.20".

    Args:
        min_version: Minimum required RAPIDS version string ("[v]MAJOR.MINOR.PATCH-rapids.CUSTOM").
        dry_run: If True, print commands without executing them.
    """
    from holoscan_cli.utils.holohub import get_holohub_setup_scripts_dir

    script_path = get_holohub_setup_scripts_dir() / "sccache.sh"
    if not script_path.exists():
        warn(f"sccache setup script not found: {script_path}")
        return

    env = os.environ.copy()
    env["SCCACHE_MIN_VERSION"] = min_version
    run_command(["bash", str(script_path)], dry_run=dry_run, env=env)


def setup_cuda_dependencies(dry_run: bool = False) -> None:
    """Setup CUDA dependencies if CUDA runtime is available"""
    cuda_runtime_version = get_cuda_runtime_version()
    if cuda_runtime_version:
        cuda_major_version = cuda_runtime_version.split(".")[0]
        setup_cuda_packages(cuda_major_version, dry_run)
    else:
        info("CUDA Runtime package not found, skipping CUDA package installation")


def setup_cuda_packages(cuda_major_version: str, dry_run: bool = False) -> None:
    """Install CUDA packages for Holoscan SDK development"""

    # Attempt to install cudnn9
    CUDNN_9_PATTERN = r"9\.[0-9]+\.[0-9]+\.[0-9]+\-[0-9]+"
    try:
        installed_cudnn9_version = install_cuda_dependencies_package(
            package_name=f"libcudnn9-cuda-{cuda_major_version}",
            version_pattern=CUDNN_9_PATTERN,
            dry_run=dry_run,
        )
        install_cuda_dependencies_package(
            package_name=f"libcudnn9-dev-cuda-{cuda_major_version}",
            version_pattern=re.escape(installed_cudnn9_version),
            dry_run=dry_run,
        )
    except PackageInstallationError as e:
        info(f"cuDNN 9.x installation failed, falling back to cuDNN 8.x: {e}")
        try:
            # Fall back to cudnn8
            CUDNN_8_PATTERN = rf"8\.[0-9]+\.[0-9]+\.[0-9]+\-[0-9]\+cuda{cuda_major_version}\.[0-9]+"
            installed_cudnn8_version = install_cuda_dependencies_package(
                package_name="libcudnn8",
                version_pattern=CUDNN_8_PATTERN,
                dry_run=dry_run,
            )
            install_cuda_dependencies_package(
                package_name="libcudnn8-dev",
                version_pattern=re.escape(installed_cudnn8_version),
                dry_run=dry_run,
            )
        except PackageInstallationError as e:
            info(f"cuDNN 8.x installation failed: {e}.")
            info("cuDNN packages may need to be installed manually.")

    # Install TensorRT dependencies
    NVINFER_PATTERN = rf"\d+\.[0-9]+\.[0-9]+\.[0-9]+-[0-9]\+cuda{cuda_major_version}\.[0-9]+"
    try:
        installed_libnvinferversion = install_cuda_dependencies_package(
            package_name="libnvinfer10",
            version_pattern=NVINFER_PATTERN,
            dry_run=dry_run,
        )
        libnvinfer_pattern = re.escape(installed_libnvinferversion)

        install_packages_if_missing(
            [
                f"libnvinfer-bin={installed_libnvinferversion}",
                f"libnvinfer-lean10={installed_libnvinferversion}",
                f"libnvinfer-plugin10={installed_libnvinferversion}",
                f"libnvinfer-vc-plugin10={installed_libnvinferversion}",
                f"libnvinfer-dispatch10={installed_libnvinferversion}",
                f"libnvonnxparsers10={installed_libnvinferversion}",
            ],
            apt_options=["--no-install-recommends", "-y", "--allow-downgrades"],
            dry_run=dry_run,
        )

        for trt_package_name in [
            "libnvinfer-headers-dev",
            "libnvinfer-safe-headers-dev",
            "libnvinfer-dev",
            "libnvinfer-headers-plugin-dev",
            "libnvinfer-plugin-dev",
            "libnvonnxparsers-dev",
        ]:
            install_cuda_dependencies_package(
                package_name=trt_package_name,
                version_pattern=libnvinfer_pattern,
                dry_run=dry_run,
            )
    except PackageInstallationError as e:
        info(f"TensorRT installation failed: {e}")
        info("Continuing with setup - TensorRT packages may need to be installed manually")
