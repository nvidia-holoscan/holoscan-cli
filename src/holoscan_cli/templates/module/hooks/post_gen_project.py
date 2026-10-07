#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Post-generation hook: tidy the generated tree and print next steps.

Repository initialization belongs to ``holoscan create`` after the staged tree
has been safely materialized, so this hook never mutates caller-owned Git state.
"""

import os

MODULE_SLUG = "{{ cookiecutter.module_slug }}"
OPERATOR_SLUG = "{{ cookiecutter.operator_slug }}"


def remove_empty_dirs(root: str = ".") -> None:
    """Bottom-up removal of directories left empty by conditional filenames."""
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        if not os.listdir(dirpath):
            os.rmdir(dirpath)


remove_empty_dirs()

# ── Next-steps message ────────────────────────────────────────────────────────
op_parts = OPERATOR_SLUG.split("_")
OPERATOR_CLASS = "".join(p.capitalize() for p in op_parts)

print(f"\n\033[32mHoloscan Module '{MODULE_SLUG}' created successfully!\033[0m\n")
print(f"Implement your operator ({OPERATOR_CLASS}) in:")
print(f"  operators/{OPERATOR_SLUG}/{OPERATOR_SLUG}.cpp\n")

print("Next steps:")
print("  See README.md for environment setup, build, run, and test instructions.\n")
print("Register your module at https://nvidia-holoscan.github.io/ when ready.")
