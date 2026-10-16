#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reject Cookiecutter values that cannot form a valid Holoscan Module."""

import keyword
import re
import sys

PROJECT_NAME = {{ cookiecutter.project_name | tojson }}
MODULE_SLUG = {{ cookiecutter.module_slug | tojson }}
MODULE_REPO_NAME = {{ cookiecutter.module_repo_name | tojson }}
OPERATOR_SLUG = {{ cookiecutter.operator_slug | tojson }}
LANGUAGE = {{ cookiecutter.language | tojson }}
LICENSE = {{ cookiecutter._license | tojson }}
HOLOSCAN_VERSION = {{ cookiecutter.holoscan_version | tojson }}

MINIMUM_HOLOSCAN_VERSION = (5, 0, 0)

_PROJECT_NAME = re.compile(r"[A-Za-z0-9]+(?:[ _-][A-Za-z0-9]+)*")
_SNAKE_CASE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_REPOSITORY_NAME = re.compile(r"holoscan-[a-z0-9]+(?:-[a-z0-9]+)*")
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?")
# Holoscan SDK modules own these names: holoscan_<name>, holoscan::<name> and holoscan.<name>.
RESERVED_MODULE_SLUGS = ("core", "vision", "visualization", "inference")


def reject(message: str) -> None:
    print(f"Invalid Module template context: {message}", file=sys.stderr)
    raise SystemExit(1)


if LANGUAGE == "python":
    reject(
        "language 'python' is not available for Holoscan SDK 5.0 Modules: pure-Python Modules "
        "return in a later release. Use 'cpp,python' to call the C++ operators from Python."
    )
if LANGUAGE not in ("cpp", "cpp,python"):
    reject("language must be 'cpp' or 'cpp,python'.")

version_match = _SEMVER.fullmatch(HOLOSCAN_VERSION)
if version_match is None:
    reject("holoscan_version must be a MAJOR.MINOR.PATCH version such as '5.0.0'.")
if tuple(int(part) for part in version_match.groups()) < MINIMUM_HOLOSCAN_VERSION:
    reject(
        f"holoscan_version {HOLOSCAN_VERSION!r} is older than 5.0.0; this template targets the "
        "Holoscan SDK 5.x API. Use a holoscan-cli 4.x release to scaffold Modules for SDK 4.x."
    )

if not _PROJECT_NAME.fullmatch(PROJECT_NAME):
    reject("project_name must contain alphanumeric words separated by spaces, '-' or '_'.")

for name, value in (("module_slug", MODULE_SLUG), ("operator_slug", OPERATOR_SLUG)):
    if not _SNAKE_CASE.fullmatch(value) or not value.isidentifier() or keyword.iskeyword(value):
        reject(f"{name} must be a lowercase snake_case identifier beginning with a letter.")

if MODULE_SLUG in RESERVED_MODULE_SLUGS:
    reject(
        f"module_slug {MODULE_SLUG!r} is reserved for the Holoscan SDK's own {MODULE_SLUG} module "
        f"(holoscan_{MODULE_SLUG}, holoscan.{MODULE_SLUG}.). Choose a different project name."
    )

expected_repo_name = f"holoscan-{MODULE_SLUG.replace('_', '-')}"
if not _REPOSITORY_NAME.fullmatch(MODULE_REPO_NAME) or MODULE_REPO_NAME != expected_repo_name:
    reject(f"module_repo_name must be {expected_repo_name!r} for module_slug {MODULE_SLUG!r}.")

if LICENSE != "Apache-2.0":
    reject("_license must be 'Apache-2.0' because the generated LICENSE contains Apache-2.0.")
