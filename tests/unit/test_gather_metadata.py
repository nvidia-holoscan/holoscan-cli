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

import json

from holoscan_cli.metadata.gather_metadata import extract_project_name, gather_metadata


def test_extract_project_name_from_language_subdirectory():
    assert extract_project_name("applications/smoke_app/python/metadata.json") == "smoke_app"


def test_module_uses_declared_name_instead_of_mount_directory(tmp_path):
    mounted_root = tmp_path / "normalized_workspace"
    mounted_root.mkdir()
    cases = (
        ("holoscan-example-module", "holoscan-example-module"),
        ("  holoscan-example-module  ", "holoscan-example-module"),
        ("   ", mounted_root.name),
        (None, mounted_root.name),
    )

    for declared_name, expected_name in cases:
        (mounted_root / "metadata.json").write_text(
            json.dumps({"module": {"name": declared_name}}), encoding="utf-8"
        )

        projects = gather_metadata([str(mounted_root)])

        assert projects[0]["project_name"] == expected_name

        # A configured search path may name the descriptor file itself, not
        # only the directory containing it.
        projects = gather_metadata([str(mounted_root / "metadata.json")])

        assert projects[0]["project_name"] == expected_name
