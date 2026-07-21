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

"""Pure data helpers — text/version/distance, env/arg parsing, filesystem stats.

No subprocess and no terminal I/O — everything in this module is testable
without side effects beyond reading os.environ or the filesystem.
"""

import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

# ---- version parsing ---------------------------------------------------------


def parse_semantic_version(version: str) -> Tuple[int, int, int]:
    """
    Parse semantic version string MAJOR.MINOR.PATCH into tuple of integers for comparison

    Note: Implementing our own version parsing to avoid dependency on PyPI 'packaging' module.

    ref: https://semver.org/
    """
    match = re.match(r"^(\d+\.\d+\.\d+).*", version.strip())
    if not match:
        raise ValueError(f"Failed to parse semantic version string: {version}")
    return tuple(map(int, match.group(1).split(".")))


# ---- string helpers ----------------------------------------------------------


def _slugify(text: str, max_len: int = 63) -> str:
    """Make a branch slug: lowercase, non-alnum to '-', trim dashes, max length."""
    lowered = text.lower()
    replaced = re.sub(r"[^a-z0-9]+", "-", lowered)
    trimmed = replaced.strip("-")
    return trimmed[:max_len]


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings."""
    s1 = s1.lower()
    s2 = s2.lower()

    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


# ---- env / CLI arg helpers ---------------------------------------------------


_FALSE_ENV_VALUES: Tuple[str, ...] = ("false", "no", "n", "0", "f", "off")


def is_env_flag_true(value: Optional[str]) -> bool:
    """Return whether an optional environment flag is enabled."""
    normalized = (value or "").strip().lower()
    return bool(normalized) and normalized not in _FALSE_ENV_VALUES


def get_env_bool(
    env_var_name: str,
    default: bool = True,
    false_values: Tuple[str, ...] = _FALSE_ENV_VALUES,
) -> Tuple[str, bool]:
    """Check environment variable as boolean flag"""
    env_value = os.environ.get(env_var_name, str(default).lower())
    is_true = env_value.lower() not in false_values
    return env_value, is_true


def get_cli_arg_value(args: List[str], flag: str) -> Optional[str]:
    """Return the last value of ``flag`` in a CLI argument list.

    Supports both ``--flag value`` and ``--flag=value`` forms. Returns ``None``
    if the flag is not present. The last-wins rule mirrors typical CLI behavior
    where later occurrences override earlier ones.
    """
    value: Optional[str] = None
    prefix = f"{flag}="
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == flag and i + 1 < len(args):
            value = args[i + 1]
            i += 2
            continue
        if arg.startswith(prefix):
            value = arg.removeprefix(prefix)
        i += 1
    return value


def normalize_args_str(args):
    """Convert arguments to string format, handling both string and array inputs"""
    if isinstance(args, str):
        return os.path.expandvars(args)
    elif isinstance(args, list):
        expanded_args = [os.path.expandvars(arg) for arg in args]
        return " ".join(expanded_args)
    return ""


# ---- filesystem stats + reporting --------------------------------------------


def dir_size_mb(path: Path) -> float:
    """Return the total size of a directory tree in megabytes."""
    total = 0
    for root, _dirs, files in os.walk(str(path)):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
    return total / (1024 * 1024)


def relative_time(mtime: float) -> str:
    """Format an mtime as a human-readable relative time string."""
    elapsed = time.time() - mtime
    if elapsed < 60:
        return "just now"
    if elapsed < 3600:
        return f"{int(elapsed / 60)}m ago"
    if elapsed < 86400:
        return f"{int(elapsed / 3600)}h ago"
    return f"{int(elapsed / 86400)}d ago"


def format_size(mb: float) -> str:
    """Format a size in megabytes as a human-readable string."""
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"
