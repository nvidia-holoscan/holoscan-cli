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

"""HoloHub names for :mod:`holoscan_cli.utils.source_project`.

Existing callers, such as HoloHub's benchmarking tool, import these names.
New code should use :mod:`holoscan_cli.utils.source_project`.
Monkeypatch functions in that module; patching names here does not affect
the CLI.
"""

from pathlib import Path
from typing import Optional

from holoscan_cli.utils.source_project import *  # noqa: F403
from holoscan_cli.utils.source_project import (
    build_path_mapping,
    get_project_root,
    get_setup_scripts_dir,
)

get_holohub_root = get_project_root
get_holohub_setup_scripts_dir = get_setup_scripts_dir


def build_holohub_path_mapping(
    holohub_root: Path,
    project_data: Optional[dict] = None,
    build_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    prefix: Optional[str] = None,
    verbose: bool = False,
) -> dict[str, str]:
    """Call :func:`build_path_mapping` with the original parameter name."""
    return build_path_mapping(holohub_root, project_data, build_dir, data_dir, prefix, verbose)
