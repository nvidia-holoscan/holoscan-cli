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

"""Holoscan SDK selection and host GPU/CUDA detection helpers."""

import functools
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Optional, Union

from holoscan_cli.utils.io import fatal, resolve, run_info_command, warn
from holoscan_cli.utils.text import parse_semantic_version

_SDK_LAYOUT_RE = re.compile(
    r"^(?P<kind>install|build)"
    r"(?:(?:-cu(?P<cuda>[0-9]+))|"
    r"(?:-(?P<build_type>debug|release|relwithdebinfo|minsizerel)))?"
    r"-(?P<arch>x86_64|aarch64)(?:-(?P<gpu>igpu|dgpu))?$"
)
_SDK_CONFIG_NAMES = ("holoscan-config.cmake", "HoloscanConfig.cmake")
_SDK_VERSION_CONFIG_NAMES = (
    "holoscan-config-version.cmake",
    "HoloscanConfigVersion.cmake",
)


def normalize_arch(value: str) -> str:
    """Normalize common architecture aliases used by SDK layouts."""
    machine = value.strip().lower()
    base, separator, gpu = machine.partition("-")
    if base in {"x86_64", "amd64"}:
        base = "x86_64"
    elif base in {"aarch64", "arm64"}:
        base = "aarch64"
    return f"{base}-{gpu}" if separator else base


def resolve_target_arch(
    environ: Mapping[str, str], host_arch: Optional[str] = None
) -> tuple[str, str]:
    """Resolve the target architecture and its source."""
    configured = environ.get("HOLOSCAN_CLI_TARGET_ARCH")
    if configured:
        arch = normalize_arch(configured)
        if arch not in {"x86_64", "aarch64"}:
            raise ValueError(
                "HOLOSCAN_CLI_TARGET_ARCH must be x86_64/amd64 or aarch64/arm64; "
                f"got {configured!r}."
            )
        return arch, "HOLOSCAN_CLI_TARGET_ARCH"
    return normalize_arch(host_arch or platform.machine()), "host"


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
    return normalize_arch(platform.machine())


def get_arch_gpu_str() -> str:
    """Get architecture+GPU string like bash get_arch+gpu_str()"""
    arch = get_host_arch()
    if arch == "aarch64":
        gpu = get_host_gpu()
        return f"{arch}-{gpu}"
    return arch


def get_sdk_version(sdk_path: Path) -> str:
    """Extract the Holoscan SDK version from an installation or build tree."""
    try:
        version_file = sdk_path / "VERSION"
        if version_file.is_file():
            return version_file.read_text().strip()

        for directory in (sdk_path, sdk_path / "lib" / "cmake" / "holoscan"):
            for name in _SDK_VERSION_CONFIG_NAMES:
                cmake_config = directory / name
                if cmake_config.is_file():
                    match = re.search(r'PACKAGE_VERSION\s+"([^"]+)"', cmake_config.read_text())
                    if match:
                        return match.group(1)
    except (OSError, UnicodeDecodeError):
        pass
    return "unknown"


def is_valid_sdk_installation(path: Union[str, Path]) -> bool:
    """Return whether a directory contains an installed Holoscan SDK."""
    path = Path(path)
    return path.is_dir() and _has_sdk_config(path / "lib" / "cmake" / "holoscan")


def is_valid_sdk_build(path: Union[str, Path]) -> bool:
    """Return whether a directory contains a configured Holoscan SDK build tree."""
    path = Path(path)
    return path.is_dir() and (path / "lib").is_dir() and _has_sdk_config(path)


def _has_sdk_config(path: Path) -> bool:
    """Return whether a directory contains a recognized SDK CMake config."""
    return any((path / name).is_file() for name in _SDK_CONFIG_NAMES)


def is_valid_sdk_directory(path: Union[str, Path]) -> bool:
    """Return whether a path is a usable Holoscan SDK installation or build tree."""
    return is_valid_sdk_installation(path) or is_valid_sdk_build(path)


def get_sdk_cmake_prefix_path(path: Union[str, Path]) -> str:
    """Return CMake prefixes that work for SDK install and source-build layouts."""
    sdk_path = Path(path)
    return ";".join((str(sdk_path), str(sdk_path / "lib")))


def _cuda_major(value: Optional[str | int]) -> Optional[str]:
    """Extract a CUDA major used in SDK source-tree directory names."""
    if value is None:
        return None
    match = re.search(r"[0-9]+", str(value))
    return match.group(0) if match else None


def _target_arch_gpu(target_arch: str) -> str:
    """Return the SDK layout architecture, including the host aarch64 GPU type."""
    normalized = normalize_arch(target_arch)
    if normalized == "aarch64":
        return f"aarch64-{get_host_gpu()}"
    return normalized


def _prefers_cuda_qualified_layout(root: Path) -> Optional[bool]:
    """Infer whether an SDK source checkout uses the 4.x CUDA-qualified layout."""
    for version_file in (root / "VERSION", root / "public" / "VERSION"):
        try:
            match = re.match(r"\s*([0-9]+)", version_file.read_text())
        except (OSError, UnicodeDecodeError):
            continue
        if match:
            return int(match.group(1)) < 5
    return None


def _sdk_layout_rank(
    *,
    candidate_cuda: Optional[str],
    build_type: Optional[str],
    cuda_major: Optional[str],
    prefer_cuda_qualified: Optional[bool],
) -> int:
    """Rank 4.x CUDA-qualified, 5.x architecture-only, and developer builds."""
    if candidate_cuda is not None:
        if cuda_major is not None and candidate_cuda != cuda_major:
            return 3
        return 2 if prefer_cuda_qualified is False else 0
    if build_type is not None:
        return 2 if prefer_cuda_qualified is None else 1
    return {True: 2, False: 0, None: 1}[prefer_cuda_qualified]


def _sdk_layout_candidates(
    root: Path,
    *,
    kind: str,
    arch_gpu: str,
    cuda_major: Optional[str],
    allow_generic: bool,
) -> list[Path]:
    """Return valid matching SDK directories in compatibility order."""
    target_arch, _, expected_gpu = arch_gpu.partition("-")
    prefer_cuda_qualified = _prefers_cuda_qualified_layout(root)
    validator = is_valid_sdk_installation if kind == "install" else is_valid_sdk_directory
    ranked: list[tuple[tuple[int, int, int, str], Path]] = []
    for root_priority, parent in enumerate((root, root / "public")):
        if allow_generic:
            generic = parent / kind
            if validator(generic):
                ranked.append(((3, 3, root_priority, generic.name), generic))
        try:
            entries = list(parent.glob(f"{kind}-*"))
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            match = _SDK_LAYOUT_RE.fullmatch(entry.name)
            if match is None or match.group("kind") != kind:
                continue
            build_type = match.group("build_type")
            if kind == "install" and build_type is not None:
                continue
            if match.group("arch") != target_arch or not validator(entry):
                continue

            candidate_gpu = match.group("gpu") or ""
            if expected_gpu:
                gpu_rank = 0 if candidate_gpu == expected_gpu else 1 if not candidate_gpu else 2
            else:
                gpu_rank = 0 if not candidate_gpu else 1

            candidate_cuda = match.group("cuda")
            layout_rank = _sdk_layout_rank(
                candidate_cuda=candidate_cuda,
                build_type=build_type,
                cuda_major=cuda_major,
                prefer_cuda_qualified=prefer_cuda_qualified,
            )
            ranked.append(((gpu_rank, layout_rank, root_priority, entry.name), entry))

    return [entry for _, entry in sorted(ranked)]


def _resolve_sdk_path(
    path: Path,
    arch: str,
    cuda_version: Optional[str | int],
    *,
    include_build: bool,
) -> Optional[Path]:
    """Resolve a concrete SDK directory from a direct path or source checkout."""
    try:
        resolved = resolve(path)
    except OSError:
        return None
    roots = (resolved, resolved / "public")
    validator = is_valid_sdk_directory if include_build else is_valid_sdk_installation
    direct = next((root for root in roots if validator(root)), None)
    if direct is not None:
        return direct
    arch_gpu = _target_arch_gpu(arch)
    cuda_major = _cuda_major(cuda_version)
    for kind in ("install", "build") if include_build else ("install",):
        candidates = _sdk_layout_candidates(
            resolved,
            kind=kind,
            arch_gpu=arch_gpu,
            cuda_major=cuda_major,
            allow_generic=False,
        )
        if candidates:
            return candidates[0]
    return None


def resolve_sdk_installation(
    path: Path,
    arch: str,
    cuda_version: Optional[str | int] = None,
) -> Optional[Path]:
    """Resolve an SDK installation from an install tree or SDK source checkout."""
    return _resolve_sdk_path(path, arch, cuda_version, include_build=False)


def resolve_sdk_directory(
    path: Path,
    arch: str,
    cuda_version: Optional[str | int] = None,
) -> Optional[Path]:
    """Resolve an SDK installation or configured build from a path or source checkout."""
    return _resolve_sdk_path(path, arch, cuda_version, include_build=True)


def resolve_local_sdk_dir(
    default_sdk_root: str | Path,
    local_sdk_root: Optional[str | Path] = None,
    environ: Optional[Mapping[str, str]] = None,
    *,
    cuda_version: Optional[str | int] = None,
) -> Path:
    """Resolve the SDK used by a local lifecycle command."""
    # Import lazily because project_context imports SDK discovery helpers from
    # this module while constructing the active project.
    from holoscan_cli.project_context import get_active_project_context

    source_environment = os.environ if environ is None else environ
    context = get_active_project_context()
    if local_sdk_root is None:
        local_sdk_root = source_environment.get("HOLOSCAN_SDK_ROOT") or None
        if local_sdk_root is None:
            if context is not None and context.is_module and context.sdk_root is not None:
                return context.sdk_root
            return Path(default_sdk_root)
        source_label = f"HOLOSCAN_SDK_ROOT={local_sdk_root}"
    else:
        source_label = f"--local-sdk-root {local_sdk_root}"

    requested_root = resolve(local_sdk_root)
    target_arch = source_environment.get("HOLOSCAN_CLI_TARGET_ARCH")
    effective_cuda_version = cuda_version or source_environment.get(
        "HOLOSCAN_CLI_DEFAULT_CUDA_VERSION"
    )
    if context is not None:
        target_arch = target_arch or context.target_arch
        effective_cuda_version = effective_cuda_version or context.cuda
    sdk_dir = find_hsdk_dir(
        requested_root,
        target_arch=target_arch,
        cuda_version=effective_cuda_version,
    )
    installation = Path(sdk_dir) if Path(sdk_dir).is_absolute() else requested_root / sdk_dir
    if not is_valid_sdk_directory(installation):
        fatal(
            f"{source_label} does not contain a usable Holoscan SDK directory "
            "(expected an installed config under lib/cmake/holoscan or a source-build "
            "config at the build root, directly or under install-* or build-*)."
        )
    return installation


def find_hsdk_dir(
    local_sdk_root: Optional[Union[str, Path]] = None,
    target_arch: Optional[str] = None,
    cuda_version: Optional[str | int] = None,
) -> str:
    """
    Find a suitable SDK installation or build directory.
    https://github.com/nvidia-holoscan/holoscan-sdk/blob/9c5b3c3d4831f2e65ebda6b79ae9b1c5517c6a7c/run#L226-L228

    Search order:
    1. When ``local_sdk_root`` is provided, use only that direct installation
       or its install/build subdirectories, including the source tree's
       ``public`` directory.
    2. Otherwise, use ``HOLOSCAN_SDK_ROOT`` as the direct installation or
       parent to search.
    3. Within a parent directory, prefer an install directory over a build
       directory and restrict fallbacks to the selected architecture. Current
       4.x ``install/build-cu<major>-<arch>[-<gpu>]`` and developer
       ``build-<type>-<arch>`` layouts are supported alongside 5.x
       ``install/build-<arch>`` names. The source checkout's version selects
       the preferred layout, and the host GPU variant is preferred for
       ``aarch64``.

    Args:
        local_sdk_root: Path to SDK root directory, or direct SDK installation/build directory
        target_arch: Optional target architecture; host architecture is used when omitted.
        cuda_version: Optional CUDA major used to prioritize current SDK layouts.

    Returns:
        Relative path to the SDK directory from the root, or absolute path if passed directly
    """
    search_root: Optional[Path] = None

    # An explicit argument is authoritative. Do not let an ambient SDK select a
    # different installation while the caller later mounts local_sdk_root.
    if local_sdk_root is not None:
        local_sdk_root = Path(local_sdk_root) if isinstance(local_sdk_root, str) else local_sdk_root
        if local_sdk_root.exists():
            if is_valid_sdk_directory(local_sdk_root):
                return str(local_sdk_root)
            search_root = local_sdk_root
    elif os.environ.get("HOLOSCAN_SDK_ROOT"):
        env_path = Path(os.environ["HOLOSCAN_SDK_ROOT"])
        if env_path.exists():
            if is_valid_sdk_directory(env_path):
                return str(env_path)
            search_root = env_path

    configured_target = target_arch or os.environ.get("HOLOSCAN_CLI_TARGET_ARCH")
    arch_gpu = _target_arch_gpu(configured_target) if configured_target else get_arch_gpu_str()
    cuda_major = _cuda_major(cuda_version or os.environ.get("HOLOSCAN_CLI_DEFAULT_CUDA_VERSION"))
    if search_root is not None:
        resolved_root = resolve(search_root)
        for kind in ("install", "build"):
            candidates = _sdk_layout_candidates(
                resolved_root,
                kind=kind,
                arch_gpu=arch_gpu,
                cuda_major=cuda_major,
                allow_generic=configured_target is None,
            )
            if candidates:
                return candidates[0].relative_to(resolved_root).as_posix()

    prefer_cuda_qualified = (
        _prefers_cuda_qualified_layout(resolve(search_root)) if search_root is not None else None
    )
    use_cuda_qualified = cuda_major is not None and prefer_cuda_qualified is not False
    suffix = f"cu{cuda_major}-{arch_gpu}" if use_cuda_qualified else arch_gpu
    return f"build-{suffix}"


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
