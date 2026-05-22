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

"""Schema-regression suite for module.schema.json (v2).

Round-trips the hand-curated fixtures under
``tests/fixtures/module_metadata/{valid,invalid}/`` through the bundled
``metadata_validator.validate_json`` so the contract that
``external_resolver`` relies on (dependency_source requires git_url + ref,
module_dependency forbids extra fields, dependencies is an array, …)
stays pinned to the schema as it ships in the wheel.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holoscan_cli.metadata import metadata_validator
from holoscan_cli.metadata.utils import METADATA_DIRECTORY_CONFIG, get_schema_path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "module_metadata"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_modules_directory_is_registered():
    """``METADATA_DIRECTORY_CONFIG`` must recognize ``modules/`` so
    ``iter_metadata_paths`` walks it and ``get_schema_path`` resolves
    ``modules`` → ``module.schema.json``."""
    assert "modules" in METADATA_DIRECTORY_CONFIG
    schema_path = get_schema_path("modules")
    assert schema_path.name == "module.schema.json"
    assert schema_path.exists()


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURE_DIR / "valid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid_module_fixtures_pass(fixture):
    ok, msg = metadata_validator.validate_json(_load(fixture), "modules")
    assert ok, f"{fixture.name} should be valid but failed: {msg}"


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURE_DIR / "invalid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_module_fixtures_fail(fixture):
    ok, _ = metadata_validator.validate_json(_load(fixture), "modules")
    assert not ok, f"{fixture.name} should be invalid but passed schema"
