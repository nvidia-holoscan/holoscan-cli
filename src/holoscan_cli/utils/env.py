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
from typing import List, Optional, Tuple


def get_env_bool(
    env_var_name: str,
    default: bool = True,
    false_values: Tuple[str, ...] = ("false", "no", "n", "0", "f"),
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
