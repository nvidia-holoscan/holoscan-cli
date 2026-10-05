# SPDX-FileCopyrightText: Copyright (c) 2023-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
import json
import re
import warnings

import jsonschema
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from holoscan_cli.metadata.utils import BASE_SCHEMA_PATH, SCHEMA_DIR, get_schema_path

# Top-level keys that uniquely identify which schema applies to a metadata.json,
# adapted from holohub/utilities/metadata/metadata_validator.py.
KNOWN_ENVELOPES = (
    "application",
    "operator",
    "tutorial",
    "benchmark",
    "module",
    "package",
)


SCHEMA_URN_PREFIX = "urn:holoscan:"
# Accepted with a FutureWarning until its planned removal in 2027.
LEGACY_SCHEMA_URN_PREFIX = "urn:holohub:"
SCHEMA_LABEL_PATTERN = re.compile(
    r"urn:(?P<namespace>holoscan|holohub):(?P<type>[a-z_-]+):v(?P<version>[1-9][0-9]*)"
)


def legacy_schema_id(schema_id):
    """Return the deprecated ``urn:holohub:`` alias of a ``urn:holoscan:`` schema ID."""
    return LEGACY_SCHEMA_URN_PREFIX + schema_id.removeprefix(SCHEMA_URN_PREFIX)


def check_schema_label(json_data, schema_id):
    """Check an optional top-level ``$schema`` label against the selected schema's ``$id``."""
    if not isinstance(json_data, dict) or "$schema" not in json_data:
        return True, "no $schema label"
    label = json_data["$schema"]
    match = SCHEMA_LABEL_PATTERN.fullmatch(label) if isinstance(label, str) else None
    if match is None:
        return (
            False,
            f'"$schema" must have the form "{SCHEMA_URN_PREFIX}<type>:v<N>", got {label!r}',
        )
    canonical = f"{SCHEMA_URN_PREFIX}{match['type']}:v{match['version']}"
    if canonical != schema_id:
        return False, f'"$schema" {label!r} does not match the selected schema {schema_id!r}'
    if match["namespace"] == "holohub":
        warnings.warn(
            f'"$schema" {label!r} uses the deprecated "{LEGACY_SCHEMA_URN_PREFIX}" prefix and '
            f"will be rejected after its planned removal in 2027; use {schema_id!r}",
            FutureWarning,
            stacklevel=3,
        )
    return True, "valid $schema label"


def legacy_schema_refs(schema):
    """Return the ``$ref`` values in ``schema`` that use the deprecated ``urn:holohub:`` prefix."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        refs = [ref] if isinstance(ref, str) and ref.startswith(LEGACY_SCHEMA_URN_PREFIX) else []
        return refs + [r for value in schema.values() for r in legacy_schema_refs(value)]
    if isinstance(schema, list):
        return [r for item in schema for r in legacy_schema_refs(item)]
    return []


def validate_json(json_data, directory):
    with open(BASE_SCHEMA_PATH) as file:
        base_schema = json.load(file)
    base_resource = DRAFT202012.create_resource(base_schema)
    registry = Registry().with_resources(
        [
            (base_schema["$id"], base_resource),
            (legacy_schema_id(base_schema["$id"]), base_resource),
        ]
    )

    # Pick the schema by envelope key when present (e.g. an operator metadata.json
    # nested under applications/ uses operator.schema.json, not the schema of its
    # containing directory). Fall back to directory-based lookup otherwise.
    schema_path = None
    if isinstance(json_data, dict):
        envelopes = [k for k in KNOWN_ENVELOPES if k in json_data]
        if len(envelopes) == 1:
            schema_path = SCHEMA_DIR / f"{envelopes[0]}.schema.json"
    if schema_path is None:
        schema_path = get_schema_path(directory)
    if not schema_path.is_file():
        return False, f"No supported project type; expected one of: {', '.join(KNOWN_ENVELOPES)}"
    with open(schema_path, "r") as file:
        try:
            execute_api_schema = json.load(file)
        except json.decoder.JSONDecodeError as err:
            return False, err
    label_ok, label_msg = check_schema_label(json_data, execute_api_schema.get("$id"))
    if not label_ok:
        return False, label_msg
    legacy_refs = sorted(set(legacy_schema_refs(execute_api_schema)))
    if legacy_refs:
        warnings.warn(
            f"schema {execute_api_schema.get('$id')!r} uses deprecated "
            f'"{LEGACY_SCHEMA_URN_PREFIX}" $refs {legacy_refs} that will be rejected after '
            f'their planned removal in 2027; use "{SCHEMA_URN_PREFIX}"',
            FutureWarning,
            stacklevel=2,
        )
    validator = Draft202012Validator(execute_api_schema, registry=registry)

    try:
        validator.validate(json_data)
    except jsonschema.exceptions.ValidationError as err:
        return False, err

    return True, "valid"
