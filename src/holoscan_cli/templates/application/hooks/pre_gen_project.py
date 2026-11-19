#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reject Cookiecutter values that cannot form a valid Holoscan application."""

import re
import sys
import unicodedata

PROJECT_SLUG = {{ cookiecutter.project_slug | tojson }}
LANGUAGE = {{ cookiecutter.language | tojson }}
VERSION = {{ cookiecutter.version | tojson }}
HOLOSCAN_VERSION = {{ cookiecutter.holoscan_version | tojson }}
# Free text appears in metadata.json, the README, and source comments, so it
# must stay on one line.
FREE_TEXT = {
    "project_name": {{ cookiecutter.project_name | tojson }},
    "description": {{ cookiecutter.description | tojson }},
    "full_name": {{ cookiecutter.full_name | tojson }},
    "affiliation": {{ cookiecutter.affiliation | tojson }},
    "copyright_holder": {{ cookiecutter.copyright_holder | tojson }},
}

MINIMUM_HOLOSCAN_VERSION = (5, 0, 0)

_SNAKE_CASE = re.compile(r"[a-z][a-z0-9_]*")
_VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def reject(message: str) -> None:
    print(f"Invalid application template context: {message}", file=sys.stderr)
    raise SystemExit(1)


if not _SNAKE_CASE.fullmatch(PROJECT_SLUG):
    reject(
        f"project_slug {PROJECT_SLUG!r} must be snake_case: a lowercase letter followed by "
        "lowercase letters, digits, or underscores."
    )

if LANGUAGE not in ("cpp", "python"):
    reject(f"language {LANGUAGE!r} must be 'cpp' or 'python'; an application uses one language.")

for name, value in FREE_TEXT.items():
    # Control characters (Cc) include newlines and tabs; Zl and Zp are Unicode
    # line and paragraph separators.
    if any(unicodedata.category(character) in ("Cc", "Zl", "Zp") for character in value):
        reject(f"{name} must be a single line without control characters.")

if not _VERSION.fullmatch(VERSION):
    reject(f"version {VERSION!r} must be MAJOR.MINOR.PATCH, for example 0.1.0.")

sdk_version = _VERSION.fullmatch(HOLOSCAN_VERSION)
if sdk_version is None:
    reject(f"holoscan_version {HOLOSCAN_VERSION!r} must be MAJOR.MINOR.PATCH, such as 5.0.0.")
if tuple(int(part) for part in sdk_version.groups()) < MINIMUM_HOLOSCAN_VERSION:
    reject(
        f"holoscan_version {HOLOSCAN_VERSION!r} is older than 5.0.0; the generated application "
        "uses the Holoscan SDK 5 API."
    )
