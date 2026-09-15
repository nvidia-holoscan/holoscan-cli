# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "resolve_release_version.py"


def run_resolver(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("maturity_arguments", "expected_version"),
    [
        (("--alpha", "1"), "5.0.0a1"),
        (("--alpha", "12"), "5.0.0a12"),
        (("--rc", "2"), "5.0.0rc2"),
        (("--ga", "true"), "5.0.0"),
    ],
)
def test_resolves_explicit_release_version(maturity_arguments, expected_version):
    result = run_resolver(
        "--version",
        "v5.0.0",
        "--ref-name",
        "release/5.0.0",
        *maturity_arguments,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected_version


def test_leaves_implicit_development_version_to_dynamic_versioning():
    result = run_resolver(
        "--version",
        "v5.0.0",
        "--ref-name",
        "feature/integration-test",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--version", "5.0.0"), "version must look like vX.Y.Z"),
        (("--alpha", "0"), "alpha must be a positive integer"),
        (("--rc", "-1"), "rc must be a positive integer"),
        (("--alpha", "1", "--rc", "1"), "alpha and rc are mutually exclusive"),
        (
            ("--alpha", "1", "--ga", "true"),
            "alpha and rc must be empty for GA releases",
        ),
    ],
)
def test_rejects_invalid_release_inputs(arguments, message):
    result = run_resolver(
        "--version",
        "v5.0.0",
        "--ref-name",
        "release/5.0.0",
        *arguments,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_rejects_explicit_release_from_non_release_branch():
    result = run_resolver(
        "--version",
        "v5.0.0",
        "--alpha",
        "1",
        "--ref-name",
        "main",
    )

    assert result.returncode != 0
    assert "must use a release/* branch" in result.stderr
