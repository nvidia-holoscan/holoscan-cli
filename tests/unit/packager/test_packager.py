# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
import os
import tempfile
import pathlib
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from holoscan_cli.common.enum_types import ApplicationType, Platform, SdkType
from holoscan_cli.packager.packager import (
    _build_image,
    _create_app_manifest,
    _create_package_manifest,
    _package_application,
    execute_package_command,
)
from holoscan_cli.packager.manifest_files import ApplicationManifest, PackageManifest
from holoscan_cli.packager.parameters import PlatformParameters


class TestPackager:
    """Test cases for the main packager functionality"""

    @pytest.fixture
    def mock_args(self):
        """Create mock arguments for testing"""
        args = Namespace()
        args.username = "testuser"
        args.uid = 1000
        args.gid = 1000
        args.config = pathlib.Path("/test/config.yaml")
        args.timeout = 100
        args.version = "1.0.0"
        args.docs = None
        args.application = pathlib.Path("/test/app")
        args.no_cache = False
        args.output = pathlib.Path("/test/output")
        args.models = None
        args.build_cache = pathlib.Path("~/.holoscan_build_cache")
        args.cmake_args = None
        args.source = None
        args.platform = [Platform.x86_64]
        args.includes = []
        args.input_data = None
        args.add_hosts = []
        args.additional_libs = []
        args.cuda = 13
        args.tag = "test-app:1.0"
        args.base_image = None
        args.build_image = None
        args.sdk = SdkType.Holoscan
        args.sdk_version = None
        args.holoscan_sdk_file = None
        args.monai_deploy_sdk_file = None
        return args

    @pytest.fixture
    def mock_packaging_args(self):
        """Create mock PackagingArguments"""
        mock_args = MagicMock()

        # Mock build parameters
        mock_args.build_parameters.application_type = ApplicationType.PythonFile

        # Mock platforms
        platform = PlatformParameters(Platform.x86_64, "test-app:1.0", "1.0.0", 13)
        mock_args.platforms = [platform]

        # Mock manifests
        mock_args.application_manifest = ApplicationManifest()
        mock_args.package_manifest = PackageManifest()

        return mock_args

    def test_build_image_python_file(self, mock_packaging_args):
        """Test _build_image with Python file application"""
        with patch(
            "holoscan_cli.packager.packager.PythonAppBuilder"
        ) as mock_builder_class:
            mock_builder = MagicMock()
            mock_result = MagicMock()
            mock_result.succeeded = True
            mock_builder.build.return_value = mock_result
            mock_builder_class.return_value = mock_builder

            results = _build_image(mock_packaging_args, "/tmp")

            assert len(results) == 1
            assert results[0].succeeded is True
            mock_builder_class.assert_called_once_with(
                mock_packaging_args.build_parameters, "/tmp"
            )
            mock_builder.build.assert_called_once_with(mock_packaging_args.platforms[0])

    def test_build_image_python_module(self, mock_packaging_args):
        """Test _build_image with Python module application"""
        mock_packaging_args.build_parameters.application_type = (
            ApplicationType.PythonModule
        )

        with patch(
            "holoscan_cli.packager.packager.PythonAppBuilder"
        ) as mock_builder_class:
            mock_builder = MagicMock()
            mock_result = MagicMock()
            mock_result.succeeded = True
            mock_builder.build.return_value = mock_result
            mock_builder_class.return_value = mock_builder

            results = _build_image(mock_packaging_args, "/tmp")

            assert len(results) == 1
            mock_builder_class.assert_called_once()

    def test_build_image_cpp_cmake(self, mock_packaging_args):
        """Test _build_image with C++ CMake application"""
        mock_packaging_args.build_parameters.application_type = ApplicationType.CppCMake

        with patch(
            "holoscan_cli.packager.packager.CppAppBuilder"
        ) as mock_builder_class:
            mock_builder = MagicMock()
            mock_result = MagicMock()
            mock_result.succeeded = True
            mock_builder.build.return_value = mock_result
            mock_builder_class.return_value = mock_builder

            results = _build_image(mock_packaging_args, "/tmp")

            assert len(results) == 1
            mock_builder_class.assert_called_once()

    def test_build_image_binary(self, mock_packaging_args):
        """Test _build_image with binary application"""
        mock_packaging_args.build_parameters.application_type = ApplicationType.Binary

        with patch(
            "holoscan_cli.packager.packager.CppAppBuilder"
        ) as mock_builder_class:
            mock_builder = MagicMock()
            mock_result = MagicMock()
            mock_result.succeeded = True
            mock_builder.build.return_value = mock_result
            mock_builder_class.return_value = mock_builder

            results = _build_image(mock_packaging_args, "/tmp")

            assert len(results) == 1
            mock_builder_class.assert_called_once()

    def test_create_app_manifest(self):
        """Test _create_app_manifest creates the correct file and structure"""
        manifest = MagicMock()
        manifest.data = {"test": "app_manifest_data"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "holoscan_cli.packager.packager.print_manifest_json"
            ) as mock_print:
                _create_app_manifest(manifest, temp_dir)

                # Check that map directory was created
                map_dir = os.path.join(temp_dir, "map")
                assert os.path.exists(map_dir)
                assert os.path.isdir(map_dir)

                # Check that app.json was created with correct content
                app_json_path = os.path.join(map_dir, "app.json")
                assert os.path.exists(app_json_path)

                with open(app_json_path, "r") as f:
                    content = json.load(f)
                    assert content == {"test": "app_manifest_data"}

                # Check that print_manifest_json was called
                mock_print.assert_called_once_with(
                    {"test": "app_manifest_data"}, "app.json"
                )

    def test_create_package_manifest(self):
        """Test _create_package_manifest creates the correct file and structure"""
        manifest = MagicMock()
        manifest.data = {"test": "package_manifest_data"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "holoscan_cli.packager.packager.print_manifest_json"
            ) as mock_print:
                _create_package_manifest(manifest, temp_dir)

                # Check that map directory was created
                map_dir = os.path.join(temp_dir, "map")
                assert os.path.exists(map_dir)
                assert os.path.isdir(map_dir)

                # Check that pkg.json was created with correct content
                pkg_json_path = os.path.join(map_dir, "pkg.json")
                assert os.path.exists(pkg_json_path)

                with open(pkg_json_path, "r") as f:
                    content = json.load(f)
                    assert content == {"test": "package_manifest_data"}

                # Check that print_manifest_json was called
                mock_print.assert_called_once_with(
                    {"test": "package_manifest_data"}, "pkg.json"
                )

    def test_package_application_success(self, mock_args):
        """Test successful _package_application execution"""
        with (
            patch(
                "holoscan_cli.packager.packager.PackagingArguments"
            ) as mock_packaging_args_class,
            patch(
                "holoscan_cli.packager.packager._create_app_manifest"
            ) as mock_create_app,
            patch(
                "holoscan_cli.packager.packager._create_package_manifest"
            ) as mock_create_pkg,
            patch("holoscan_cli.packager.packager._build_image") as mock_build_image,
            patch("holoscan_cli.packager.packager.logger") as mock_logger,
        ):
            # Setup mocks
            mock_packaging_args = MagicMock()
            mock_packaging_args_class.return_value = mock_packaging_args

            mock_result = MagicMock()
            mock_result.succeeded = True
            mock_result.parameters = MagicMock()
            mock_result.parameters.platform.value = "x86_64"
            mock_result.parameters.platform_config.value = "dgpu"
            mock_result.docker_tag = "test-app:1.0"
            mock_result.tarball_filename = "test-app.tar"
            mock_build_image.return_value = [mock_result]

            with patch("builtins.print") as mock_print:
                _package_application(mock_args)

                # Verify all steps were called
                mock_packaging_args_class.assert_called_once()
                mock_create_app.assert_called_once_with(
                    mock_packaging_args.application_manifest,
                    mock_packaging_args_class.call_args[0][1],
                )
                mock_create_pkg.assert_called_once_with(
                    mock_packaging_args.package_manifest,
                    mock_packaging_args_class.call_args[0][1],
                )
                mock_build_image.assert_called_once()

                # Verify success output
                mock_logger.info.assert_called_with("Build Summary:")
                mock_print.assert_called()

    def test_package_application_failure(self, mock_args):
        """Test _package_application with build failure"""
        with (
            patch("holoscan_cli.packager.packager.PackagingArguments"),
            patch("holoscan_cli.packager.packager._create_app_manifest"),
            patch("holoscan_cli.packager.packager._create_package_manifest"),
            patch("holoscan_cli.packager.packager._build_image") as mock_build_image,
            patch("sys.exit") as mock_sys_exit,
        ):
            # Setup failed build result
            mock_result = MagicMock()
            mock_result.succeeded = False
            mock_result.parameters = MagicMock()
            mock_result.parameters.platform.value = "x86_64"
            mock_result.parameters.platform_config.value = "dgpu"
            mock_result.error = "Build failed"
            mock_build_image.return_value = [mock_result]

            with patch("builtins.print") as mock_print:
                _package_application(mock_args)

                # Verify failure handling
                mock_sys_exit.assert_called_with(1)
                mock_print.assert_called()

    def test_execute_package_command_success(self, mock_args):
        """Test successful execute_package_command"""
        with patch(
            "holoscan_cli.packager.packager._package_application"
        ) as mock_package:
            execute_package_command(mock_args)
            mock_package.assert_called_once_with(mock_args)

    def test_execute_package_command_exception(self, mock_args):
        """Test execute_package_command with exception"""
        test_error = Exception("Test error")

        with (
            patch(
                "holoscan_cli.packager.packager._package_application"
            ) as mock_package,
            patch("holoscan_cli.packager.packager.logger") as mock_logger,
            patch("sys.exit") as mock_sys_exit,
        ):
            mock_package.side_effect = test_error

            execute_package_command(mock_args)

            mock_logger.debug.assert_called_with(test_error, exc_info=True)
            mock_logger.error.assert_called_with(
                "Error packaging application:\n\nTest error"
            )
            mock_sys_exit.assert_called_with(1)
