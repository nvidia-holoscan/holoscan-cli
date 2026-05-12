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

"""Terminal output (Color + info/warn/fatal) and subprocess execution."""

import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Union


# ---- terminal color formatting -----------------------------------------------


class Color:
    """Utility class for terminal color formatting.

    ANSI codes are emitted based on the destination stream and environment:
      - NO_COLOR=<non-empty>    always strip colors (no-color.org)
      - FORCE_COLOR=<non-empty> always emit colors
      - otherwise: emit only when the destination stream is a TTY

    Callers that write to stderr should pass stream=sys.stderr so the TTY
    check targets the correct destination.
    """

    # ANSI color codes
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Text attributes
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @staticmethod
    def _should_color(stream=None) -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        stream = stream or sys.stdout
        return hasattr(stream, "isatty") and stream.isatty()

    @staticmethod
    def format(text: str, color: str, bold: bool = False, stream=None) -> str:
        """Format text with color and optional bold attribute.

        Returns plain text (no ANSI codes) when the destination stream is not
        a TTY, or when NO_COLOR is set. Set FORCE_COLOR to override.
        """
        if not Color._should_color(stream):
            return text
        result = color
        if bold:
            result += Color.BOLD
        result += text + Color.RESET
        return result

    def _create_color_method(color_code: str):
        """Create a color method for the given color code"""

        def color_method(text: str, bold: bool = False, stream=None) -> str:
            return Color.format(text, color_code, bold, stream=stream)

        return color_method

    # Create color methods dynamically
    red = _create_color_method(RED)
    green = _create_color_method(GREEN)
    yellow = _create_color_method(YELLOW)
    blue = _create_color_method(BLUE)
    cyan = _create_color_method(CYAN)
    white = _create_color_method(WHITE)


# ---- logging primitives ------------------------------------------------------


def get_timestamp() -> str:
    """Get current timestamp in the format used by the bash script"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def format_cmd(command: str, is_dryrun: bool = False) -> str:
    """Format command output with consistent timestamp and color formatting"""
    timestamp = Color.blue(get_timestamp())
    if is_dryrun:
        dryrun_tag = Color.cyan("[dryrun]")
        return f"{timestamp} {dryrun_tag} {Color.white('$')} {Color.green(command)}"
    return f"{timestamp} {Color.white('$')} {Color.green(command)}"


def info(message: str) -> None:
    """Print informational message with consistent formatting"""
    print(f"{Color.yellow('INFO:')} {message}")


def fatal(message: str) -> None:
    """Print fatal error and exit with backtrace"""
    err = sys.stderr
    print(
        f"{Color.red(get_timestamp(), stream=err)} "
        f"{Color.red('[FATAL]', bold=True, stream=err)} {message}",
        file=err,
    )
    print("\nBacktrace: ...", file=err)
    traceback.print_list(traceback.extract_stack()[-3:], file=err)
    sys.exit(1)


def warn(message: str) -> None:
    print(f"{Color.yellow('WARNING:', stream=sys.stderr)} {message}", file=sys.stderr)


def format_long_command(cmd: List[str], max_line_length: int = 80) -> str:
    """Format a long command into multiple lines for better readability

    Args:
        cmd: Command to format as a list of strings
        max_line_length: Maximum line length before wrapping

    Returns:
        Formatted command string with line continuations
    """
    if not cmd:
        return ""

    # Check if total command length exceeds max length
    total_length = sum(len(arg) + 1 for arg in cmd) - 1
    if total_length <= max_line_length:
        return " ".join(cmd)

    # Start with the first command
    formatted = cmd[0]
    current_line = cmd[0]

    # Common patterns that suggest good break points
    break_patterns = {
        "--",  # Long options
        "-",  # Short options
        "&&",  # Command chaining
        "||",  # Command chaining
        "|",  # Pipes
        ";",  # Command separator
        ">",  # Output redirection
        "<",  # Input redirection
        ">>",  # Append redirection
        "2>",  # Error redirection
    }

    for i, arg in enumerate(cmd[1:]):
        # Check if this is a good place to break
        should_break = (
            # Break if we exceed max length
            len(current_line) + len(arg) + 1 > max_line_length
            or
            # Break before common command separators
            any(arg.startswith(pattern) for pattern in break_patterns)
            or
            # Break after common command separators
            any(cmd[i].endswith(pattern) for pattern in break_patterns)
        )

        if should_break:
            formatted += " \\\n    " + arg
            current_line = arg
        else:
            formatted += " " + arg
            current_line += " " + arg

    return formatted


# ---- subprocess execution + sudo handling ------------------------------------

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
