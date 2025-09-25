# SPDX-FileCopyrightText: Copyright (c) 2023-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import os
import pathlib

import pytest
from holoscan_cli.common.constants import Constants, DefaultValues
from holoscan_cli.common.enum_types import (
    ApplicationType,
    Platform,
)
from holoscan_cli.common.exceptions import UnknownApplicationTypeError
from holoscan_cli.packager.parameters import PackageBuildParameters, PlatformParameters


class TestPlatformParameters:
    @pytest.mark.parametrize(
        "platform",
        [
            (Platform.Jetson),
            (Platform.IGX_iGPU),
            (Platform.IGX_dGPU),
            (Platform.SBSA),
        ],
    )
    def test_jetson(self, platform: Platform):
        build_parameters = PlatformParameters(
            platform,
            "my-container-app",
            "1.2.3",
        )
        assert build_parameters.holoscan_deb_arch == "arm64"
        assert build_parameters.cuda_deb_arch == "sbsa"
        assert build_parameters.target_arch == "aarch64"

    def test_with_x64(self, monkeypatch):
        build_parameters = PlatformParameters(
            Platform.x86_64,
            "my-container-app",
            "1.2.3",
        )
        assert build_parameters.holoscan_deb_arch == "amd64"
        assert build_parameters.cuda_deb_arch == "x86_64"
        assert build_parameters.target_arch == "x86_64"

    def test_cuda_version_default(self):
        """Test that default CUDA version is set correctly"""
        build_parameters = PlatformParameters(
            Platform.x86_64,
            "my-container-app",
            "1.2.3",
        )
        # Default CUDA version should be 13
        assert build_parameters.cuda_version == 13

    def test_cuda_version_specified(self):
        """Test that specified CUDA version is set correctly"""
        # Test CUDA 12
        build_parameters = PlatformParameters(
            Platform.x86_64, "my-container-app", "1.2.3", 12
        )
        assert build_parameters.cuda_version == 12

        # Test CUDA 13
        build_parameters = PlatformParameters(
            Platform.Jetson, "my-container-app", "1.2.3", 13
        )
        assert build_parameters.cuda_version == 13


class TestPackageBuildParameters:
    def test_set_application_python_dir(self, monkeypatch):
        input_dir = pathlib.Path("/path/to/my/python/app/dir")

        def mock_isdir(path):
            return path == input_dir

        def mock_exists(path):
            return path == (input_dir / Constants.PYTHON_MAIN_FILE) or path == (
                input_dir / "requirements.txt"
            )

        monkeypatch.setattr(os.path, "isdir", mock_isdir)
        monkeypatch.setattr(os.path, "exists", mock_exists)
        build_parameters = PackageBuildParameters()
        build_parameters.application = input_dir

        assert build_parameters.application == input_dir
        assert build_parameters.application_type == ApplicationType.PythonModule
        assert (
            build_parameters._data["application_type"]
            == ApplicationType.PythonModule.name
        )
        assert build_parameters.application_directory == input_dir
        assert (
            build_parameters.command
            == f'["{Constants.PYTHON_EXECUTABLE}", "{build_parameters.app_dir}"]'
        )
        assert build_parameters.command_filename == os.path.basename(input_dir)

    def test_set_application_python_file(self, monkeypatch):
        input_dir = pathlib.Path("/path/to/my/python/app.py")

        def mock_isdir(path):
            return False

        def mock_exists(path):
            return path == (input_dir / Constants.PYTHON_MAIN_FILE) or path == (
                input_dir / "requirements.txt"
            )

        def mock_isfile(path):
            return path == input_dir

        monkeypatch.setattr(os.path, "isdir", mock_isdir)
        monkeypatch.setattr(os.path, "isfile", mock_isfile)
        monkeypatch.setattr(os.path, "exists", mock_exists)
        build_parameters = PackageBuildParameters()
        build_parameters.application = input_dir

        assert build_parameters.application == input_dir
        assert build_parameters.application_type == ApplicationType.PythonFile
        assert (
            build_parameters._data["application_type"]
            == ApplicationType.PythonFile.name
        )
        assert build_parameters.application_directory == pathlib.Path(
            os.path.dirname(input_dir)
        )
        assert build_parameters.command == (
            f'["{Constants.PYTHON_EXECUTABLE}", '
            + f'"{os.path.join(DefaultValues.HOLOSCAN_APP_DIR, os.path.basename(input_dir))}"]'
        )
        assert build_parameters.command_filename == os.path.basename(input_dir)

    def test_set_application_cpp_dir(self, monkeypatch):
        input_dir = pathlib.Path("/path/to/my/cpp/source/dir")

        def mock_isdir(path):
            return path == input_dir

        def mock_exists(path):
            return path == (input_dir / Constants.CPP_CMAKELIST_FILE) or path == (
                input_dir / "requirements.txt"
            )

        monkeypatch.setattr(os.path, "isdir", mock_isdir)
        monkeypatch.setattr(os.path, "exists", mock_exists)
        build_parameters = PackageBuildParameters()
        build_parameters.application = input_dir

        assert build_parameters.application == input_dir
        assert build_parameters.application_type == ApplicationType.CppCMake
        assert (
            build_parameters._data["application_type"] == ApplicationType.CppCMake.name
        )
        assert build_parameters.application_directory == input_dir
        assert (
            f'["{Constants.PYTHON_EXECUTABLE}", '
            + f'"{os.path.join(DefaultValues.HOLOSCAN_APP_DIR, os.path.basename(input_dir))}"]'
        )
        assert build_parameters.command_filename == os.path.basename(input_dir)

    def test_set_application_binary_app(self, monkeypatch):
        input_dir = pathlib.Path("/path/to/my/cpp/app/exe")

        def mock_isdir(path):
            return False

        def mock_isfile(path):
            return path == input_dir

        monkeypatch.setattr(os.path, "isdir", mock_isdir)
        monkeypatch.setattr(os.path, "isfile", mock_isfile)
        monkeypatch.setattr(os, "access", lambda x, y: True)
        build_parameters = PackageBuildParameters()
        build_parameters.application = input_dir

        assert build_parameters.application == input_dir
        assert build_parameters.application_type == ApplicationType.Binary
        assert build_parameters._data["application_type"] == ApplicationType.Binary.name
        assert build_parameters.application_directory == pathlib.Path(
            os.path.dirname(input_dir)
        )
        assert (
            f'["{Constants.PYTHON_EXECUTABLE}", '
            + f'"{os.path.join(DefaultValues.HOLOSCAN_APP_DIR, os.path.basename(input_dir))}"]'
        )
        assert build_parameters.command_filename == os.path.basename(input_dir)

    def test_set_application_unsupported(self, monkeypatch):
        input_dir = pathlib.Path("/some/path")
        monkeypatch.setattr(os.path, "isdir", lambda x: False)
        monkeypatch.setattr(os.path, "isfile", lambda x: False)
        build_parameters = PackageBuildParameters()

        with pytest.raises(UnknownApplicationTypeError):
            build_parameters.application = input_dir

    def test_invalid_tag_value_error(self):
        """Test InvalidTagValueError for invalid Docker tag (line 53)"""
        from holoscan_cli.common.exceptions import InvalidTagValueError

        with pytest.raises(InvalidTagValueError):
            # This should trigger the tag_prefix is None case
            PlatformParameters(
                Platform.x86_64,
                "",  # Empty tag should cause tag_prefix to be None
                "1.2.3",
                13,
            )
