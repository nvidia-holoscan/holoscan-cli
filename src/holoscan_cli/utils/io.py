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
import shlex
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Union

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


# ---- subprocess execution + explicit privilege elevation ---------------------


def run_command(
    cmd: Union[str, List[str]],
    dry_run: bool = False,
    check: bool = True,
    as_root: bool = False,
    preserve_env: Optional[Iterable[str]] = None,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run a command, optionally elevated with ``sudo``.

    Elevation is explicit and per-operation; ``sudo`` is prepended only when
    ``as_root`` is set and the process is not already root. ``preserve_env``
    names variables re-applied via ``/usr/bin/env`` after sudo, so policies
    like ``secure_path`` cannot replace them; root keeps its own HOME (-H).
    Missing sudo fails clearly rather than running unprivileged.
    """
    if preserve_env is not None and not as_root:
        raise ValueError("preserve_env requires as_root=True")

    elevate = as_root and os.geteuid() != 0
    sudo_prefix: List[str] = []
    sudo_display_prefix: List[str] = []
    if elevate:
        sudo = shutil.which("sudo") or ""
        if not sudo:
            if dry_run:
                sudo = "sudo"  # display only; a dry run executes nothing
            else:
                display = cmd if isinstance(cmd, str) else " ".join(str(x) for x in cmd)
                fatal(
                    "This step needs root privileges but 'sudo' is not available:\n"
                    f"  {display}\n"
                    "Re-run it as an administrator, or install sudo."
                )
        sudo_prefix = [sudo]
        sudo_display_prefix = [sudo]
        if preserve_env is not None:
            sudo_prefix.extend(["-H", "-E", "/usr/bin/env"])
            sudo_display_prefix.extend(["-H", "-E", "/usr/bin/env"])
            env = kwargs.get("env") or {}
            for name in sorted(set(preserve_env)):
                if name in env:
                    sudo_prefix.append(f"{name}={env[name]}")
                    sudo_display_prefix.append(f"{name}=<preserved>")

    if isinstance(cmd, str):
        prefix = shlex.join(sudo_prefix)
        exec_cmd: Union[str, List[str]] = f"{prefix} {cmd}" if elevate else cmd
        display_prefix = shlex.join(sudo_display_prefix)
        display_cmd = f"{display_prefix} {cmd}" if elevate else cmd
    else:
        argv = [str(x) for x in cmd]
        exec_cmd = [*sudo_prefix, *argv] if elevate else argv
        display_argv = [*sudo_display_prefix, *argv] if elevate else argv
        quoted = [f'"{x}"' if " " in x else x for x in display_argv]
        display_cmd = format_long_command(quoted) if dry_run else " ".join(quoted)

    if elevate:
        print(Color.yellow("[system] elevating with sudo"))
    if dry_run:
        print(format_cmd(display_cmd, is_dryrun=True))
        # Return the same args shape as a real run (the exec argv/command,
        # not the display string), so callers can inspect .args uniformly.
        return subprocess.CompletedProcess(exec_cmd, 0)

    print(format_cmd(display_cmd))
    try:
        return subprocess.run(exec_cmd, check=check, **kwargs)
    except subprocess.CalledProcessError as e:
        print(f"Non-zero exit code running command: {display_cmd}")
        print(f"Exit code: {e.returncode}")
        sys.exit(e.returncode)


def write_system_file(
    path: Union[str, "os.PathLike[str]"],
    content: Union[str, bytes],
    dry_run: bool = False,
) -> None:
    """Write ``content`` to a root-owned ``path`` via ``sudo tee``.

    Do not build ``sudo sh -c 'echo ... > /etc/...'``: that redirection runs in
    the *unprivileged* shell. ``tee`` runs as the elevated process, so the write
    itself is privileged. When already root, ``tee`` runs directly.
    """
    is_bytes = isinstance(content, bytes)
    run_command(
        ["tee", str(path)],
        as_root=True,
        dry_run=dry_run,
        input=content,
        text=not is_bytes,
        stdout=subprocess.DEVNULL,
    )


def run_info_command(cmd: List[str], cwd: Optional[str] = None) -> Optional[str]:
    """Run a command for information gathering and return stripped output or None if failed"""
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, cwd=cwd).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
