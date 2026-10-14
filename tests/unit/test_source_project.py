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

"""Tests for the HoloHub names kept in ``holoscan_cli.utils.holohub``."""

from holoscan_cli.utils import holohub, source_project


def test_holohub_module_keeps_original_names(tmp_path):
    assert holohub.get_holohub_root is source_project.get_project_root
    assert holohub.get_holohub_setup_scripts_dir is source_project.get_setup_scripts_dir
    assert holohub.resolve_path_prefix is source_project.resolve_path_prefix
    assert holohub.update_env is source_project.update_env

    root = tmp_path / "repo"
    project = {"source_folder": str(root / "applications" / "app"), "project_name": "app"}
    build_dir = root / "build" / "app"
    # HoloHub's benchmarking tool passes holohub_root by keyword.
    mapping = holohub.build_holohub_path_mapping(
        holohub_root=root, project_data=project, build_dir=build_dir, prefix="holohub_"
    )

    assert mapping == source_project.build_path_mapping(root, project, build_dir, prefix="holohub_")
    assert mapping["holohub_app_bin"] == str(build_dir / "applications" / "app")
