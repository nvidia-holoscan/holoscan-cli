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
import warnings

import pytest

from holoscan_cli.metadata import metadata_validator

# ---- validate_json ----------------------------------------------------------


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


def test_validate_json_reports_unsupported_project_type():
    # Metadata without a known top-level key in a folder without a schema has
    # nothing to validate against.
    ok, msg = metadata_validator.validate_json({"unknown_type": {"name": "x"}}, "unknown_types")
    assert ok is False
    assert msg.startswith("No supported project type; expected one of: application,")


def test_validate_json_rejects_invalid_schema_file(tmp_path, monkeypatch):
    """If the schema file itself is not parseable, validate_json must return
    (False, JSONDecodeError) rather than crashing."""
    bogus_schema = tmp_path / "broken.schema.json"
    bogus_schema.write_text("{not valid json", encoding="utf-8")

    monkeypatch.setattr(metadata_validator, "get_schema_path", lambda directory: bogus_schema)

    ok, msg = metadata_validator.validate_json({"anything": {}}, "anything")
    assert ok is False
    assert isinstance(msg, json.JSONDecodeError)


# ---- $schema labels ---------------------------------------------------------


def test_validate_json_accepts_canonical_schema_label():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ok, msg = metadata_validator.validate_json(
            {"$schema": "urn:holoscan:package:v1", "package": {}}, "pkg"
        )
    assert ok is True, msg


def test_validate_json_warns_on_legacy_schema_label():
    with pytest.warns(FutureWarning, match="2027"):
        ok, msg = metadata_validator.validate_json(
            {"$schema": "urn:holohub:package:v1", "package": {}}, "pkg"
        )
    assert ok is True, msg


@pytest.mark.parametrize(
    "label",
    [
        "urn:holoscan:module:v2",
        "urn:holoscan:package:v2",
        "holoscan/package/v1",
        "urn:example:package:v1",
        1,
    ],
)
def test_validate_json_rejects_mismatched_schema_label(label):
    ok, msg = metadata_validator.validate_json({"$schema": label, "package": {}}, "pkg")
    assert ok is False
    assert '"$schema"' in msg


def test_validate_json_resolves_legacy_ref_alias(tmp_path, monkeypatch):
    schema = tmp_path / "legacy.schema.json"
    schema.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "urn:holoscan:legacy:v1",
                "type": "object",
                "properties": {"tags": {"$ref": "urn:holohub:project:v1#/$defs/tags"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(metadata_validator, "get_schema_path", lambda directory: schema)

    with pytest.warns(FutureWarning, match="2027"):
        ok, msg = metadata_validator.validate_json({"tags": ["a"]}, "legacy")
    assert ok is True, msg
    with pytest.warns(FutureWarning, match="2027"):
        ok, _ = metadata_validator.validate_json({"tags": [1]}, "legacy")
    assert ok is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
