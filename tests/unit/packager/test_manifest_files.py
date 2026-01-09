# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

from holoscan_cli.packager.manifest_files import ApplicationManifest, PackageManifest


class TestApplicationManifest:
    """Test cases for ApplicationManifest property getters and setters"""

    def test_sdk_property(self):
        """Test sdk property getter and setter (lines 93, 97)"""
        manifest = ApplicationManifest()

        # Test setter (line 97)
        manifest.sdk = "holoscan"

        # Test getter (line 93)
        assert manifest.sdk == "holoscan"

    def test_sdk_version_property(self):
        """Test sdk_version property getter and setter (lines 101, 105)"""
        manifest = ApplicationManifest()

        # Test setter (line 105)
        manifest.sdk_version = "1.0.0"

        # Test getter (line 101)
        assert manifest.sdk_version == "1.0.0"

    def test_title_property(self):
        """Test title property getter and setter (lines 130, 137)"""
        manifest = ApplicationManifest()

        # Test setter (line 137)
        manifest.title = "My Test App"

        # Test getter (line 130)
        assert manifest.title == "My Test App"

    def test_version_property(self):
        """Test version property getter and setter (lines 153, 160)"""
        manifest = ApplicationManifest()

        # Test setter (line 160)
        manifest.version = "2.1.0"

        # Test getter (line 153)
        assert manifest.version == "2.1.0"


class TestPackageManifest:
    """Test cases for PackageManifest property getters and setters"""

    def test_package_version_property(self):
        """Test package_version property getter and setter (lines 174, 181)"""
        manifest = PackageManifest()

        # Test setter (line 181)
        manifest.package_version = "3.0.0"

        # Test getter (line 174)
        assert manifest.package_version == "3.0.0"

    def test_platform_config_property(self):
        """Test platform_config property getter and setter (lines 185, 192)"""
        manifest = PackageManifest()

        # Test setter (line 192)
        manifest.platform_config = "dgpu"

        # Test getter (line 185)
        assert manifest.platform_config == "dgpu"

    def test_sdk_type_property(self):
        """Test sdk_type property getter and setter (lines 217, 224)"""
        manifest = PackageManifest()

        # Test setter (line 224)
        manifest.sdk_type = "holoscan"

        # Test getter (line 217)
        assert manifest.sdk_type == "holoscan"
