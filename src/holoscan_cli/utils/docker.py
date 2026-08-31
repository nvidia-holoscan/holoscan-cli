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

"""Docker image-reference and host-inspection helpers.

Used by the project lifecycle commands (``build``, ``run``, ``install``,
``test``) and by ``HoloscanContainer`` to figure out how to invoke
``docker run`` correctly for a given image: ``get_container_entrypoint``,
``get_image_pythonpath``, ``is_running_in_docker``,
``get_entrypoint_command_args``.
"""

import argparse
import json
import os
import shlex
import subprocess
from functools import cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, List, Optional, Sequence

from holoscan_cli.utils.io import Color, run_command
from holoscan_cli.utils.text import get_cli_arg_value, merge_args_str

if TYPE_CHECKING:
    from holoscan_cli.container.core import HoloscanContainer

RESERVED_CONTAINER_ENV_NAMES = frozenset(
    {
        "NVIDIA_DRIVER_CAPABILITIES",
        "NVIDIA_VISIBLE_DEVICES",
        "HOME",
        "CUPY_CACHE_DIR",
        "HOLOSCAN_CLI_BUILD_LOCAL",
    }
)


def apply_container_cli_overrides(
    args: argparse.Namespace,
    container: "HoloscanContainer",
) -> None:
    """Apply typed invocation choices before image names are inspected."""
    cuda = getattr(args, "cuda", None)
    if cuda is not None:
        container.cuda_version = cuda
    local_sdk_root = getattr(args, "local_sdk_root", None)
    if local_sdk_root is not None:
        args.local_sdk_root = container.resolve_local_sdk_root(local_sdk_root)


def resolve_cli_docker_opts(args: argparse.Namespace) -> str:
    """Return repeated ``--docker-opts`` fragments as one shell-safe string."""
    values = getattr(args, "docker_opts", None)
    return merge_args_str(*values) if isinstance(values, list) else merge_args_str(values)


def image_reference_has_tag_or_digest(image: str) -> bool:
    """Return whether an image reference already names an exact tag or digest."""
    return "@" in image or ":" in image.rsplit("/", 1)[-1]


def get_build_arg_names(tokens: Sequence[str]) -> set[str]:
    """Return names assigned through Docker's raw ``--build-arg`` syntax."""
    names = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        value = None
        if token == "--build-arg" and index + 1 < len(tokens):
            value = tokens[index + 1]
            index += 1
        elif token.startswith("--build-arg="):
            value = token.split("=", 1)[1]
        if value:
            names.add(value.split("=", 1)[0])
        index += 1
    return names


def _find_cpu_cgroup(proc_root: Path) -> tuple[Optional[Path], Optional[Path], bool]:
    """Return the CPU cgroup mount, current directory, and whether it is v2."""
    cgroup_v2 = None
    cgroup_v1 = None
    for line in (proc_root / "self" / "cgroup").read_text(encoding="utf-8").splitlines():
        _, controllers, cgroup_path = line.split(":", 2)
        if not controllers:
            cgroup_v2 = cgroup_path
        elif "cpu" in controllers.split(","):
            cgroup_v1 = cgroup_path

    for line in (proc_root / "self" / "mountinfo").read_text(encoding="utf-8").splitlines():
        try:
            mount, filesystem = line.split(" - ", 1)
            mount_fields = mount.split()
            filesystem_fields = filesystem.split()
            root = PurePosixPath(mount_fields[3])
            mountpoint = Path(mount_fields[4])
            fs_type = filesystem_fields[0]
            options = filesystem_fields[2].split(",")

            if cgroup_v1 is not None:
                if fs_type != "cgroup" or "cpu" not in options:
                    continue
                cgroup_path = cgroup_v1
                is_v2 = False
            else:
                if fs_type != "cgroup2" or cgroup_v2 is None:
                    continue
                cgroup_path = cgroup_v2
                is_v2 = True

            relative_path = PurePosixPath(cgroup_path).relative_to(root)
            return mountpoint, mountpoint / relative_path, is_v2
        except (ValueError, IndexError):
            continue

    return None, None, False


def _read_cpu_quota(proc_root: Path) -> Optional[int]:
    """Return the smallest CPU quota in the current cgroup hierarchy."""
    try:
        mountpoint, current, is_v2 = _find_cpu_cgroup(proc_root)
    except (OSError, ValueError, IndexError):
        return None
    if mountpoint is None or current is None:
        return None

    quotas = []
    while True:
        try:
            if is_v2:
                quota, period = (current / "cpu.max").read_text(encoding="utf-8").split()
                if quota != "max":
                    quota = int(quota)
                    period = int(period)
                    if quota > 0 and period > 0:
                        quotas.append((quota + period - 1) // period)
            else:
                quota = int((current / "cpu.cfs_quota_us").read_text(encoding="utf-8"))
                period = int((current / "cpu.cfs_period_us").read_text(encoding="utf-8"))
                if quota > 0 and period > 0:
                    quotas.append((quota + period - 1) // period)
        except (OSError, ValueError):
            pass

        if current == mountpoint:
            break
        current = current.parent

    return min(quotas) if quotas else None


def get_effective_cpu_set(proc_root: Path = Path("/proc")) -> Optional[str]:
    """Return CPUs to forward when affinity or cgroup quota limits this process.

    A quota narrower than the affinity set deterministically selects its lowest CPU IDs.
    """
    try:
        affinity = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return None
    if not affinity:
        return None

    quota = _read_cpu_quota(proc_root)
    cpu_count = os.cpu_count()
    limited_by_affinity = cpu_count is not None and len(affinity) < cpu_count
    limited_by_quota = quota is not None and quota < len(affinity)
    if not limited_by_affinity and not limited_by_quota:
        return None

    usable_count = min(quota, len(affinity)) if quota is not None else len(affinity)
    return ",".join(str(cpu) for cpu in affinity[:usable_count])


@cache
def docker_build_supports_resource(docker_exe: str) -> bool:
    """Return whether this Docker installation accepts build resource limits."""
    try:
        result = subprocess.run(
            [docker_exe, "build", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "--resource" in result.stdout


def get_entrypoint_command_args(
    img: str, command: str, docker_opts: str, dry_run: bool = False
) -> tuple[str, List[str]]:
    """Determine how to execute a shell command in a Docker container."""

    # Check if user provided a custom entrypoint.
    entrypoint: Optional[str] = None
    try:
        entrypoint = get_cli_arg_value(shlex.split(docker_opts), "--entrypoint")
    except ValueError:
        pass

    if entrypoint:  # If user provided a custom entrypoint
        if entrypoint in ["/bin/sh", "/bin/bash", "sh", "bash"]:
            return "", ["-c", command]  # Shell needs -c to execute command string
        return "", shlex.split(command)  # For non-shell user entrypoints, pass command as arguments

    entrypoint = get_container_entrypoint(img, dry_run=dry_run)
    if not entrypoint:  # Image has no entrypoint, use default "/bin/bash -c"
        return "", ["/bin/bash", "-c", command]
    # Image has an ENTRYPOINT
    if entrypoint in [["/bin/sh", "-c"], ["/bin/bash", "-c"], ["sh", "-c"], ["bash", "-c"]]:
        return "", [command]  # Shell is already configured to take command string
    if entrypoint[0] in ["/bin/sh", "/bin/bash", "sh", "bash"]:
        return "", ["-c", command]  # Shell needs -c to execute command string
    return "--entrypoint=/bin/bash", ["-c", command]  # bash is used to run local build/run command


def get_container_entrypoint(img: str, dry_run: bool = False) -> Optional[List[str]]:
    """Check if container image has an entrypoint defined"""
    if dry_run:
        print(
            Color.yellow(
                "Inspect docker image entrypoint: "
                f"docker inspect --format={{{{json .Config.Entrypoint}}}} {img}"
            )
        )
        return None

    try:
        docker_exe = os.environ.get("HOLOSCAN_CLI_DOCKER_EXE", "docker")
        result = run_command(
            [docker_exe, "inspect", "--format={{json .Config.Entrypoint}}", img],
            capture_output=True,
            check=False,
            dry_run=dry_run,
        )
        if result.returncode != 0:
            return None
        entrypoint_json = result.stdout.strip()
        if entrypoint_json in ["<no value>", "[]", "null", "''"]:
            return None
        parsed = json.loads(entrypoint_json)
        if isinstance(parsed, list) and len(parsed) > 0:
            return parsed
        return None
    except Exception:
        pass
    return None


def get_image_pythonpath(img: str, dry_run: bool = False) -> str:
    """Get PYTHONPATH from the Docker image environment"""
    if dry_run:
        print(
            Color.yellow(
                "Inspect docker image PYTHONPATH: docker inspect "
                f"--format '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}' {img}"
            )
        )
        return ""
    try:
        docker_exe = os.environ.get("HOLOSCAN_CLI_DOCKER_EXE", "docker")
        result = run_command(
            [docker_exe, "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", img],
            check=False,
            capture_output=True,
            dry_run=dry_run,
        )
        if result.returncode != 0:
            return ""
        for line in result.stdout.decode().strip().split("\n"):
            if line.startswith("PYTHONPATH="):
                return line[len("PYTHONPATH=") :]
    except (subprocess.CalledProcessError, AttributeError):
        pass
    return ""


def is_running_in_docker() -> bool:
    """Check if the current process is inside a Docker container"""
    try:
        if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
            return True
        with open("/proc/1/cgroup", "r") as f:
            return any(indicator in f.read() for indicator in ["docker", "containerd", "kubepods"])

    except (OSError, IOError):
        return False
