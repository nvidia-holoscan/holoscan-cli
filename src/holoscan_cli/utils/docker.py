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

"""Docker + VS Code Dev Container tooling helpers.

This module groups the container/dev-container integration helpers:

* Docker host inspection — ``get_container_entrypoint``,
  ``get_image_pythonpath``, ``is_running_in_docker``,
  ``get_entrypoint_command_args``, ``docker_args_to_devcontainer_format``.
  Used by the project lifecycle commands (``build``, ``run``, ``install``,
  ``test``) and by ``HoloscanContainer`` to figure out how to invoke
  ``docker run`` correctly for a given image.
* VS Code Dev Container launchers — ``launch_vscode``, ``open_url``,
  ``launch_vscode_devcontainer``, ``get_devcontainer_config``.
  Used by ``holoscan vscode`` to build the dev container image and open
  the matching ``vscode://vscode-remote/dev-container+...`` URL.
"""

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from holoscan_cli.utils.io import Color, run_command
from holoscan_cli.utils.text import get_cli_arg_value


def docker_args_to_devcontainer_format(docker_args: List[str]) -> List[str]:
    """Convert Docker argument format to devcontainer format (--flag value -> --flag=value)"""
    standalone = {"--rm", "--init", "--no-cache"}
    result, i = [], 0
    while i < len(docker_args):
        curr = docker_args[i]
        if (
            i + 1 < len(docker_args)
            and curr.startswith("--")
            and "=" not in curr
            and curr not in standalone
            and not docker_args[i + 1].startswith("-")
        ):
            result.append(f"{curr}={docker_args[i + 1]}")
            i += 2
        else:
            result.append(curr)
            i += 1
    return result


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


# ---- VS Code Dev Container launchers ----------------------------------------


def launch_vscode(workspace_path: str, dry_run: bool = False) -> None:
    """Install VS Code Remote Development extension and launch VS Code with new window"""
    print("Installing VS Code Remote Development extension...")
    run_command(
        [
            "code",
            "--force",
            "--install-extension",
            "ms-vscode-remote.vscode-remote-extensionpack",
        ],
        dry_run=dry_run,
    )
    run_command(["code", "--new-window", workspace_path], dry_run=dry_run)


def open_url(url: str, dry_run: bool = False) -> bool:
    """Open a URL using the system's default URL opener"""
    if shutil.which("open"):
        run_command(["open", url], check=False, dry_run=dry_run)
        return True
    elif shutil.which("xdg-open"):
        run_command(["xdg-open", url], check=False, dry_run=dry_run)
        return True
    if not dry_run:
        print("Could not automatically open URL.")
        print(f"Please manually open: {url}")
    return False


def launch_vscode_devcontainer(
    workspace_path: str, workspace_name: str = "holohub", dry_run: bool = False
) -> None:
    """Launch VS Code with dev container and open the dev container URL"""
    hash_hex = str(workspace_path).encode().hex()
    url = f"vscode://vscode-remote/dev-container+{hash_hex}/workspace/{workspace_name}"

    if dry_run:
        print(f"Dryrun URL: {url}")
    else:
        print(f"Launching VSCode Dev Container from: {workspace_path}")
        print(f"Connecting to {url}...")
    launch_vscode(workspace_path, dry_run=dry_run)
    open_url(url, dry_run=dry_run)


def get_devcontainer_config(
    holohub_root: Path, project_name: Optional[str] = None, dry_run: bool = False
) -> str:
    """Get devcontainer configuration content"""

    default_config_path = holohub_root / ".devcontainer"
    if (
        project_name
        and (holohub_root / ".devcontainer" / project_name / "devcontainer.json").exists()
    ):
        dev_container_path = holohub_root / ".devcontainer" / project_name
        print(f"Using application-specific DevContainer configuration: {dev_container_path}")
    else:
        dev_container_path = default_config_path
        print(f"Using top-level DevContainer configuration: {dev_container_path}")

    devcontainer_json_src = dev_container_path / "devcontainer.json"

    if dry_run:
        print(f"Would read and modify {devcontainer_json_src}")
        print("Would substitute environment variables and launch VS Code")
        return ""
    else:
        with open(devcontainer_json_src, "r") as f:
            devcontainer_content = f.read()

    return devcontainer_content
