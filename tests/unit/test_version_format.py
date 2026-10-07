# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Versions of builds that do not choose a release version."""

import tomllib
from pathlib import Path

import pytest

dunamai = pytest.importorskip("dunamai")
jinja2 = pytest.importorskip("jinja2")

PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"
TEMPLATE = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"][
    "poetry-dynamic-versioning"
]["format-jinja"]


@pytest.mark.parametrize(
    ("branch", "tag", "commits", "env", "expected"),
    [
        ("main", "5.0.0a1", 16, {}, "5.0.0a0.dev16"),
        ("release/5.0.0", "5.0.0a2", 1, {}, "5.0.0rc0.dev1"),
        ("other", "5.0.0a2", 3, {}, "5.0.0a0.dev3"),
        # Unchanged: explicit RC and GA builds, and GitHub Actions builds of other branches.
        ("release/5.0.0", "5.0.0a2", 1, {"rc": "1"}, "5.0.0rc1"),
        ("release/5.0.0", "5.0.0a2", 1, {"ga": "true"}, "5.0.0"),
        ("other", "5.0.0a2", 3, {"GITHUB_RUN_ID": "42"}, "5.0.0a42"),
    ],
)
def test_version_without_a_release_choice(branch, tag, commits, env, expected):
    version = dunamai.Version.parse(tag)
    rendered = jinja2.Template(TEMPLATE).render(
        base=version.base,
        stage=version.stage,
        revision=version.revision,
        distance=commits,
        branch=branch,
        env=env,
        serialize_pep440=dunamai.serialize_pep440,
    )
    assert rendered == expected
