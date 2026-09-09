# SPDX-FileCopyrightText: Copyright (c) 2023-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import pytest

from holoscan_cli.project_context import set_active_project_context


@pytest.fixture(autouse=True)
def _reset_active_project_context():
    """Keep process-local project defaults from leaking between tests."""
    set_active_project_context(None)
    yield
    set_active_project_context(None)


@pytest.fixture
def make_sdk_directory():
    """Return a factory for minimal installed or source-build SDK layouts."""

    def make(path, *, build=False, config_name="holoscan-config.cmake"):
        (path / "lib").mkdir(parents=True, exist_ok=True)
        config_dir = path if build else path / "lib/cmake/holoscan"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / config_name).write_text("# config\n", encoding="utf-8")
        return path

    return make
