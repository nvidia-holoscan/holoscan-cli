#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate release workflow inputs and resolve an explicit package version."""

from __future__ import annotations

import argparse
import re

BASE_VERSION_PATTERN = re.compile(r"^v(?P<base>[0-9]+\.[0-9]+\.[0-9]+)$")
POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")


def _optional_positive_integer(value: str | None, name: str) -> int | None:
    if value in (None, ""):
        return None
    if not POSITIVE_INTEGER_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return int(value)


def resolve_release_version(
    *,
    version: str,
    alpha: str | None = None,
    rc: str | None = None,
    ga: bool = False,
    ref_name: str,
) -> str | None:
    """Return the exact explicit release version, or ``None`` for a development build."""

    version_match = BASE_VERSION_PATTERN.fullmatch(version)
    if version_match is None:
        raise ValueError(f"version must look like vX.Y.Z, got {version!r}")

    alpha_number = _optional_positive_integer(alpha, "alpha")
    rc_number = _optional_positive_integer(rc, "rc")

    if alpha_number is not None and rc_number is not None:
        raise ValueError("alpha and rc are mutually exclusive")
    if ga and (alpha_number is not None or rc_number is not None):
        raise ValueError("alpha and rc must be empty for GA releases")

    is_explicit_release = ga or alpha_number is not None or rc_number is not None
    if is_explicit_release and not ref_name.startswith("release/"):
        raise ValueError("explicit alpha, RC, and GA releases must use a release/* branch")

    base_version = version_match.group("base")
    if alpha_number is not None:
        return f"{base_version}a{alpha_number}"
    if rc_number is not None:
        return f"{base_version}rc{rc_number}"
    if ga:
        return base_version
    return None


def _parse_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--alpha", default="")
    parser.add_argument("--rc", default="")
    parser.add_argument("--ga", default=False, type=_parse_bool)
    parser.add_argument("--ref-name", required=True)
    args = parser.parse_args()

    try:
        resolved_version = resolve_release_version(
            version=args.version,
            alpha=args.alpha,
            rc=args.rc,
            ga=args.ga,
            ref_name=args.ref_name,
        )
    except ValueError as error:
        parser.error(str(error))

    if resolved_version is not None:
        print(resolved_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
