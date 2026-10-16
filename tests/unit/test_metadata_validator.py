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

"""Tests for ``holoscan_cli.metadata.metadata_validator``.

The validator is reached through ``holoscan create`` and was at 0%
coverage after the package consolidation. These tests pin the
``Draft202012Validator`` wrapper that backs ``validate_generated_metadata``
in ``commands/create.py``.
"""

import json

import pytest

from holoscan_cli.metadata import metadata_validator

# ---- validate_json ----------------------------------------------------------


def _valid_application_metadata():
    return {
        "name": "Smoke Test App",
        "authors": [{"name": "Holoscan CLI Maintainers", "affiliation": "NVIDIA"}],
        "version": "0.0.1",
        "changelog": {"0.0.1": "Initial test metadata."},
        "holoscan_sdk": {
            "minimum_required_version": "2.5.0",
            "tested_versions": ["2.5.0"],
        },
        "platforms": ["x86_64"],
        "tags": ["smoke", "test"],
        "ranking": 4,
        "requirements": {},
        "modes": {
            "smoke": {
                "description": "Run the smoke check.",
                "run": {"command": "true", "workdir": "<holohub_root>"},
            }
        },
    }


def test_validate_json_accepts_minimal_package_metadata():
    # The package schema has no required fields on the `package` object;
    # any well-formed dict passes.
    ok, msg = metadata_validator.validate_json({"package": {"dockerfile": "Dockerfile"}}, "pkg")
    assert ok is True, msg
    assert msg == "valid"


def test_validate_json_rejects_violations():
    # `operators` schema has required fields; an empty operator fails.
    ok, msg = metadata_validator.validate_json({"operator": {}}, "operators")
    assert ok is False
    # `msg` here is a `jsonschema.exceptions.ValidationError`; str-ifying
    # it gives the violation summary.
    assert "required" in str(msg).lower() or "validation" in str(msg).lower()


@pytest.mark.parametrize("ci_mode", ["smoke-test", "1_smoke"])
def test_validate_json_rejects_invalid_ci_mode_name(ci_mode):
    application = _valid_application_metadata()
    application["ci_mode"] = ci_mode

    ok, msg = metadata_validator.validate_json({"application": application}, "applications")

    assert ok is False
    assert "does not match" in str(msg)


def test_validate_json_accepts_ci_mode_with_modes():
    application = _valid_application_metadata()
    application["ci_mode"] = "smoke"

    ok, msg = metadata_validator.validate_json({"application": application}, "applications")

    assert ok is True, msg


def test_validate_json_rejects_ci_mode_without_modes():
    application = _valid_application_metadata()
    application["ci_mode"] = "smoke"
    del application["modes"]

    ok, msg = metadata_validator.validate_json({"application": application}, "applications")

    assert ok is False
    assert "modes" in str(msg)


def test_validate_json_rejects_invalid_schema_file(tmp_path, monkeypatch):
    """If the schema file itself is not parseable, validate_json must return
    (False, JSONDecodeError) rather than crashing."""
    bogus_schema = tmp_path / "broken.schema.json"
    bogus_schema.write_text("{not valid json", encoding="utf-8")

    monkeypatch.setattr(metadata_validator, "get_schema_path", lambda directory: bogus_schema)

    ok, msg = metadata_validator.validate_json({"anything": {}}, "anything")
    assert ok is False
    assert isinstance(msg, json.JSONDecodeError)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
