#!/usr/bin/env python3
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

import shutil
import subprocess
import sys
from typing import List, Optional, Tuple, Union

from .formatting import format_long_command
from .logging import Color, format_cmd

_sudo_available = None  # Cache for sudo availability check


def _get_maybe_sudo() -> str:
    """Get sudo command if available, with caching to avoid repeated subprocess calls"""
    global _sudo_available

    if _sudo_available is not None:
        return _sudo_available
    _sudo_available = "sudo" if shutil.which("sudo") else ""
    return _sudo_available


def _classify_sudo_requirement(cmd: Union[str, List[str]]) -> Tuple[bool, str]:
    """Classify command sudo requirement and return (needs_sudo, reason)"""
    cmd_parts = cmd.split() if isinstance(cmd, str) else [str(x) for x in cmd]
    if not cmd_parts:
        return False, ""
    # Already has sudo
    if cmd_parts[0] == "sudo":
        return True, "Command already includes sudo"
    cmd_name = cmd_parts[0]
    # Commands that always need sudo
    always_sudo = {
        "apt": "Package management requires root privileges",
        "apt-get": "Package management requires root privileges",
        "dpkg": "Package database access requires root privileges",
        "chmod": "Changing file permissions requires root privileges",
        "chown": "Changing file ownership requires root privileges",
    }
    if cmd_name in always_sudo:
        return True, always_sudo[cmd_name]
    # Commands that need sudo for system paths
    if cmd_name in ["ln", "cp", "mv", "rm", "mkdir"]:
        if any(
            arg.startswith(("/etc/", "/usr/", "/var/", "/opt/", "/sys/", "/proc/"))
            for arg in cmd_parts[1:]
        ):
            return True, "Writing to system directories requires root privileges"
    # Shell commands with system redirections
    if isinstance(cmd, str) and ("tee /" in cmd or ">/etc/" in cmd or ">/usr/" in cmd):
        return True, "Writing to system locations requires root privileges"

    return False, ""


def _process_command_with_sudo(
    cmd: Union[str, List[str]], maybe_sudo: str
) -> Union[str, List[str]]:
    """Process command and add sudo if needed and available"""
    needs_sudo, _ = _classify_sudo_requirement(cmd)
    if not needs_sudo or not maybe_sudo:
        return cmd

    # Check if already has sudo anywhere in the command
    if isinstance(cmd, str):
        if cmd.strip().startswith("sudo ") or " sudo " in cmd:
            return cmd  # Don't add sudo if it's already present anywhere
        return f"{maybe_sudo} {cmd}"
    else:
        if cmd and (str(cmd[0]) == "sudo" or "sudo" in [str(x) for x in cmd]):
            return cmd  # Don't add sudo if it's already present anywhere
        return [maybe_sudo] + cmd


def run_command(
    cmd: Union[str, List[str]], dry_run: bool = False, check: bool = True, **kwargs
) -> subprocess.CompletedProcess:
    """Run a command and handle errors"""
    # Process the command and add sudo if needed
    processed_cmd = _process_command_with_sudo(cmd, _get_maybe_sudo())
    if isinstance(processed_cmd, str):
        cmd_str = processed_cmd
    else:
        cmd_list = [f'"{x}"' if " " in str(x) else str(x) for x in processed_cmd]
        cmd_str = format_long_command(cmd_list) if dry_run else " ".join(cmd_list)

    needs_sudo, sudo_reason = _classify_sudo_requirement(cmd)  # Add reason for sudo usage
    if needs_sudo:
        print(Color.yellow(f"[SUDO REQUIRED] {sudo_reason}"))
    if dry_run:
        print(format_cmd(cmd_str, is_dryrun=True))
        return subprocess.CompletedProcess(cmd_str, 0)

    print(format_cmd(cmd_str))
    try:
        return subprocess.run(processed_cmd, check=check, **kwargs)
    except subprocess.CalledProcessError as e:
        print(f"Non-zero exit code running command: {cmd_str}")
        print(f"Exit code: {e.returncode}")
        sys.exit(e.returncode)


def run_info_command(cmd: List[str], cwd: Optional[str] = None) -> Optional[str]:
    """Run a command for information gathering and return stripped output or None if failed"""
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, cwd=cwd).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
