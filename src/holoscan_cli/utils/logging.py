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

import os
import sys
import traceback
from datetime import datetime, timezone


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
