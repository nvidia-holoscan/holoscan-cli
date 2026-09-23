# SPDX-FileCopyrightText: Copyright (c) 2022-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import logging
import os
from pathlib import Path

from holoscan_cli.metadata.utils import iter_metadata_paths, read_metadata, resolve_module_name

logger = logging.getLogger(__name__)


def extract_project_name(metadata_filepath: str) -> str:
    """Extract the project name from the metadata.json file path.

    HoloHub convention is such that a `metadata.json` file
    must be located at either:
    - the named project folder; or
    - a language subfolder one level below the project folder.

    The following are valid examples:
    - applications/my_application/metadata.json -> my_application
    - applications/nested/paths/my_application/cpp/metadata.json -> my_application

    """
    parts = metadata_filepath.split(os.sep)
    if parts[-2] in ["cpp", "python", "py"]:
        return parts[-3]
    return parts[-2]


def gather_metadata(repo_paths: list[str], exclude_paths: list[str] | None = None) -> list[dict]:
    """
    Collect project metadata from JSON files into a single dictionary

    This function will return a list of dictionaries, each containing metadata for a project.

    :input:
        repo_path: str
            The path to the repository to collect metadata from.
        exclude_paths: list
            A list of files to exclude from metadata collection.
    :return:
        A list of dictionaries, each containing metadata for a project.
    """
    SCHEMA_TYPES = [
        "application",
        "benchmark",
        "gxf_extension",
        "module",
        "package",
        "operator",
        "tutorial",
    ]

    metadata = []

    # Iterate over the found metadata files
    for file_path in iter_metadata_paths(repo_paths, exclude_patterns=exclude_paths):
        try:
            entries = read_metadata(file_path)
        except (OSError, ValueError, RecursionError) as exc:
            logger.error('Invalid metadata file "%s": %s', file_path, exc)
            continue
        entries = entries if isinstance(entries, list) else [entries]
        for data in entries:
            schema_type = (
                next((key for key in data if key in SCHEMA_TYPES), None)
                if isinstance(data, dict)
                else None
            )
            if schema_type is None or not isinstance(data[schema_type], dict):
                logger.error('No valid project object in metadata file "%s"', file_path)
                continue

            data["project_type"] = schema_type
            data["metadata"] = data.pop(schema_type)

            project_name = extract_project_name(file_path)
            if schema_type == "module":
                # Module identity must survive renamed checkouts and container mounts.
                project_name = resolve_module_name(data["metadata"], project_name)
            data["project_name"] = project_name
            data["source_folder"] = str(Path(file_path).parent)
            metadata.append(data)

    return metadata
