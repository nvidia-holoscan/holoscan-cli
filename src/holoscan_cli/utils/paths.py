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
import re
import time
from pathlib import Path
from typing import List, Tuple


def _slugify(text: str, max_len: int = 63) -> str:
    """Make a branch slug: lowercase, non-alnum to '-', trim dashes, max length."""
    lowered = text.lower()
    replaced = re.sub(r"[^a-z0-9]+", "-", lowered)
    trimmed = replaced.strip("-")
    return trimmed[:max_len]


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


def list_metadata_json_dir(*paths: Path) -> List[Tuple[str, str]]:
    """List all metadata.json files in given paths"""
    results = []
    for path in paths:
        for json_path in path.rglob("metadata.json"):
            json_dir = json_path.parent
            dir_name = json_dir.name

            if "{{" in dir_name and "}}" in dir_name:
                continue  # Skip templates

            if dir_name in ["cpp", "python"]:
                language = f"({dir_name})"
                name = json_dir.parent.name
            else:
                language = ""
                name = dir_name

            results.append((name, language))

    return sorted(results)
