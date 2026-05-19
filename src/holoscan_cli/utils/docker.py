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

"""Docker host inspection helpers.

Used by the project lifecycle commands (``build``, ``run``, ``install``,
``test``) and by ``HoloscanContainer`` to figure out how to invoke
``docker run`` correctly for a given image: ``get_container_entrypoint``,
``get_image_pythonpath``, ``is_running_in_docker``,
``get_entrypoint_command_args``.
"""

import json
import os
import shlex
import subprocess
from typing import List, Optional

from holoscan_cli.utils.io import Color, run_command
from holoscan_cli.utils.text import get_cli_arg_value


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
