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

"""Bundled host-side setup scripts for ``holoscan setup --scripts`` and
``holoscan build-container --extra-scripts``.

The scripts live next to this module so the wheel always carries a working
default. ``holoscan_cli.utils.holohub.get_holohub_setup_scripts_dir`` prefers
an explicit ``HOLOSCAN_CLI_SETUP_SCRIPTS_DIR`` override and the active
project's own ``utilities/setup/`` directory (e.g. HoloHub's) before falling
back here.
"""
