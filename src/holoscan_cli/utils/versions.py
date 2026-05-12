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

import re
from typing import Tuple


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
