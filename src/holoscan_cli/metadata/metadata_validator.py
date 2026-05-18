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

import jsonschema
from jsonschema import Draft4Validator
from referencing import Registry
from referencing.jsonschema import DRAFT4

from holoscan_cli.metadata.utils import BASE_SCHEMA_PATH, get_schema_path


def validate_json(json_data, directory):
    with open(BASE_SCHEMA_PATH) as file:
        base_schema = json.load(file)
    registry = Registry().with_resource(base_schema["$id"], DRAFT4.create_resource(base_schema))

    schema_path = get_schema_path(directory)
    with open(schema_path, "r") as file:
        try:
            execute_api_schema = json.load(file)
        except json.decoder.JSONDecodeError as err:
            return False, err
    validator = Draft4Validator(execute_api_schema, registry=registry)

    try:
        validator.validate(json_data)
    except jsonschema.exceptions.ValidationError as err:
        return False, err

    return True, "valid"
