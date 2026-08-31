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

import argparse
import re

_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def normalize_cuda_major(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("CUDA must be an integer major version from 1 to 99")
    normalized = str(value).strip()
    if not normalized.isdigit() or not 1 <= int(normalized) <= 99:
        raise ValueError("CUDA must be an integer major version from 1 to 99")
    return normalized


def validate_environment_name(value: object) -> str:
    if not isinstance(value, str) or not _ENV_NAME_RE.fullmatch(value):
        raise ValueError("invalid environment variable name")
    return value


def validate_image_reference(value: object) -> str:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError("image references must be non-empty and contain no whitespace")
    return value


def validate_nonempty_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("value must not be empty")
    return value


def cuda_major(value: str) -> str:
    try:
        return normalize_cuda_major(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def image_reference(value: str) -> str:
    try:
        return validate_image_reference(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def nonempty_path(value: str) -> str:
    try:
        return validate_nonempty_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("path must not be empty") from exc
