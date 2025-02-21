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
import shutil
import tempfile

import holoscan_cli.common.dockerutils
import pytest
from holoscan_cli.common.enum_types import ApplicationType, Platform, SdkType
from holoscan_cli.packager.container_builder import (
    BuilderBase,
    PythonAppBuilder,
    CppAppBuilder,
)
from holoscan_cli.packager.parameters import PackageBuildParameters
from holoscan_cli.packager.platforms import PlatformParameters


class TestContainerBuilder:
    """Test cases for container builder functionality, organized by application type."""

    class MockFile:
        def __init__(self):
            self.lines = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, content):
            self.lines.append(content)

        def writelines(self, lines):
            self.lines.extend(lines)

        def __iter__(self):
            return iter(self.lines)

    @pytest.fixture
    def mock_open_file(self, monkeypatch):
        def mock_open(path, mode="r"):
            return TestContainerBuilder.MockFile()

        monkeypatch.setattr("builtins.open", mock_open)

    @pytest.fixture
    def mock_fs_operations(self, monkeypatch):
        """Common fixture for mocking file system operations"""
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(os.path, "exists", lambda x: True)
        monkeypatch.setattr(
            shutil,
            "rmtree",
            lambda path,
            ignore_errors=False,
            onerror=None,
            *,
            onexc=None,
            dir_fd=None: None,
        )
        monkeypatch.setattr(
            shutil, "copytree", lambda src, dest, dirs_exist_ok=True: None
        )
        monkeypatch.setattr(shutil, "copyfile", lambda src, dest: None)
        monkeypatch.setattr(shutil, "copy2", lambda src, dest: None)
        monkeypatch.setattr(os, "remove", lambda src: None)
        monkeypatch.setattr(BuilderBase, "_get_template", lambda x, y: "")

    @pytest.fixture
    def mock_docker_operations(self, monkeypatch):
        """Common fixture for mocking docker operations"""

        def build_docker_image(**build_args):
            pass

        monkeypatch.setattr(
            holoscan_cli.packager.container_builder,
            "create_and_get_builder",
            lambda x: "builder",
        )
        monkeypatch.setattr(
            holoscan_cli.packager.container_builder,
            "build_docker_image",
            build_docker_image,
        )
        monkeypatch.setattr(
            holoscan_cli.packager.container_builder,
            "docker_export_tarball",
            lambda path, tag: None,
        )

    class TestPythonModuleApplication:
        """Test cases for Python module applications (directory with main.py)"""

        def _get_build_parameters(self):
            parameters = PackageBuildParameters()
            parameters.application = pathlib.Path("/app/")
            parameters.config_file = pathlib.Path("/app/config.yaml")
            parameters.sdk = SdkType.Holoscan
            parameters.models = None
            parameters.docs = None
            return parameters

        def test_basic_module(
            self, mock_fs_operations, mock_docker_operations, monkeypatch
        ):
            """Test building a basic Python module application"""

            def mock_file_exists(path):
                if str(path) == "/app/requirements.txt":
                    return False
                return True

            monkeypatch.setattr(os.path, "isfile", lambda x: True)
            monkeypatch.setattr(os.path, "isdir", lambda x: True)
            monkeypatch.setattr(os.path, "exists", mock_file_exists)

            build_parameters = self._get_build_parameters()
            platform_parameters = PlatformParameters(
                Platform.x86_64, "image:tag", "1.0"
            )
            platform_parameters.holoscan_sdk_file = pathlib.Path("/sdk/holoscan.whl")

            with tempfile.TemporaryDirectory() as temp_dir:
                builder = PythonAppBuilder(build_parameters, temp_dir)
                result = builder.build(platform_parameters)
                assert result.succeeded is True

        def test_module_with_requirements(
            self,
            mock_fs_operations,
            mock_docker_operations,
            mock_open_file,
            monkeypatch,
        ):
            """Test Python module with requirements.txt"""
            monkeypatch.setattr(os.path, "isfile", lambda x: False)
            monkeypatch.setattr(os.path, "isdir", lambda x: True)

            build_parameters = self._get_build_parameters()
            build_parameters.application = pathlib.Path("/app/mymodule")
            platform_parameters = PlatformParameters(
                Platform.x86_64, "image:tag", "1.0"
            )
            platform_parameters.holoscan_sdk_file = pathlib.Path("/sdk/holoscan.whl")

            with tempfile.TemporaryDirectory() as temp_dir:
                builder = PythonAppBuilder(build_parameters, temp_dir)
                result = builder.build(platform_parameters)
                assert result.succeeded is True

    class TestPythonFileApplication:
        """Test cases for single Python file applications"""

        def _get_build_parameters(self):
            parameters = PackageBuildParameters()
            parameters.application = pathlib.Path("/app/app.py")
            parameters.config_file = pathlib.Path("/app/config.yaml")
            parameters.sdk = SdkType.Holoscan
            parameters.models = None
            parameters.docs = None
            parameters.tarball_output = pathlib.Path("/tarball/")
            return parameters

        def test_basic_file(
            self,
            mock_fs_operations,
            mock_docker_operations,
            mock_open_file,
            monkeypatch,
        ):
            """Test building a basic Python file application"""

            def mock_file_exists(path):
                if path == "/app/requirements.txt":
                    return False
                return True

            monkeypatch.setattr(os.path, "isfile", lambda x: True)
            monkeypatch.setattr(os.path, "isdir", lambda x: False)
            monkeypatch.setattr(os.path, "exists", lambda x: mock_file_exists)

            build_parameters = self._get_build_parameters()
            build_parameters.application = pathlib.Path("/app/script.py")
            platform_parameters = PlatformParameters(
                Platform.x86_64, "image:tag", "1.0"
            )
            platform_parameters.holoscan_sdk_file = pathlib.Path("/sdk/holoscan.whl")

            with tempfile.TemporaryDirectory() as temp_dir:
                builder = PythonAppBuilder(build_parameters, temp_dir)
                result = builder.build(platform_parameters)
                assert result.succeeded is True

        def test_file_with_requirements(
            self,
            mock_fs_operations,
            mock_docker_operations,
            mock_open_file,
            monkeypatch,
        ):
            """Test Python file with requirements.txt"""
            monkeypatch.setattr(os.path, "isfile", lambda x: True)
            monkeypatch.setattr(os.path, "isdir", lambda x: False)

            build_parameters = self._get_build_parameters()
            build_parameters.application = pathlib.Path("/app/script.py")
            platform_parameters = PlatformParameters(
                Platform.x86_64, "image:tag", "1.0"
            )
            platform_parameters.holoscan_sdk_file = pathlib.Path("/sdk/holoscan.whl")

            with tempfile.TemporaryDirectory() as temp_dir:
                with open(f"{temp_dir}/pip/requirements.txt", "w") as f:
                    f.write("numpy")
                builder = PythonAppBuilder(build_parameters, temp_dir)
                result = builder.build(platform_parameters)
                assert result.succeeded is True

    class TestCppCMakeApplication:
        """Test cases for C++ CMake applications"""

        @pytest.fixture
        def _fs_mocks(self, monkeypatch):
            def file_exists(path):
                if str(path) == "/app/CMakeLists.txt":
                    return True
                elif str(path) == "/app":
                    return True
                return False

            monkeypatch.setattr(os.path, "isfile", lambda x: False)
            monkeypatch.setattr(os.path, "isdir", lambda x: True)
            monkeypatch.setattr(os.path, "exists", file_exists)

        def _get_build_parameters(self):
            parameters = PackageBuildParameters()
            parameters.application = pathlib.Path("/app/")
            parameters.config_file = pathlib.Path("/app/config.yaml")
            parameters.sdk = SdkType.Holoscan
            parameters.models = None
            parameters.docs = None
            parameters.tarball_output = pathlib.Path("/tarball/")
            return parameters

        def test_basic_cpp_project(
            self, mock_fs_operations, mock_docker_operations, _fs_mocks, monkeypatch
        ):
            """Test building a basic C++ CMake project"""

            build_parameters = self._get_build_parameters()
            platform_parameters = PlatformParameters(
                Platform.x86_64, "image:tag", "1.0"
            )
            platform_parameters.holoscan_sdk_file = pathlib.Path("/sdk/holoscan.deb")

            with tempfile.TemporaryDirectory() as temp_dir:
                builder = CppAppBuilder(build_parameters, temp_dir)
                result = builder.build(platform_parameters)
                assert result.succeeded is True

        def test_cpp_project_with_libs(
            self, mock_fs_operations, mock_docker_operations, _fs_mocks, monkeypatch
        ):
            """Test C++ project with additional libraries"""
            monkeypatch.setattr(os.path, "isfile", lambda x: False)
            monkeypatch.setattr(os.path, "isdir", lambda x: True)
            monkeypatch.setattr(
                os, "walk", lambda path: [("/lib", ["dir1", "dir2"], [])]
            )

            build_parameters = self._get_build_parameters()
            build_parameters.additional_libs = [
                pathlib.Path("/lib1"),
                pathlib.Path("/lib2"),
            ]
            platform_parameters = PlatformParameters(
                Platform.x86_64, "image:tag", "1.0"
            )
            platform_parameters.holoscan_sdk_file = pathlib.Path("/sdk/holoscan.deb")

            with tempfile.TemporaryDirectory() as temp_dir:
                builder = CppAppBuilder(build_parameters, temp_dir)
                result = builder.build(platform_parameters)
                assert result.succeeded is True
                assert (
                    builder._build_parameters.additional_lib_paths
                    == "/opt/holoscan/lib/lib/dir1:/opt/holoscan/lib/lib/dir2"
                )

    class TestBinaryApplication:
        """Test cases for binary applications"""

        def _get_build_parameters(self):
            parameters = PackageBuildParameters()
            parameters.application = pathlib.Path("/app/binary")
            parameters.config_file = pathlib.Path("/app/config.yaml")
            parameters.sdk = SdkType.Holoscan
            parameters.models = None
            parameters.docs = None
            parameters.tarball_output = pathlib.Path("/tarball/")

            assert parameters.application_type == ApplicationType.Binary
            return parameters

        def test_basic_binary(
            self, mock_fs_operations, mock_docker_operations, monkeypatch
        ):
            """Test building a basic binary application"""
            monkeypatch.setattr(os.path, "isfile", lambda x: True)
            monkeypatch.setattr(os.path, "isdir", lambda x: False)
            monkeypatch.setattr(os, "access", lambda x, y: True)

            build_parameters = self._get_build_parameters()
            platform_parameters = PlatformParameters(
                Platform.x86_64, "image:tag", "1.0"
            )
            platform_parameters.holoscan_sdk_file = pathlib.Path("/sdk/holoscan.deb")

            with tempfile.TemporaryDirectory() as temp_dir:
                builder = CppAppBuilder(build_parameters, temp_dir)
                result = builder.build(platform_parameters)
                assert result.succeeded is True

        def test_binary_with_libs(
            self, mock_fs_operations, mock_docker_operations, monkeypatch
        ):
            """Test binary application with additional libraries"""
            monkeypatch.setattr(os.path, "isfile", lambda x: True)
            monkeypatch.setattr(os.path, "isdir", lambda x: False)
            monkeypatch.setattr(os, "access", lambda x, y: True)
            monkeypatch.setattr(
                os,
                "walk",
                lambda path: [("/libs", ["/my-libs/lib1", "/my-other/libs/lib2"], [])],
            )

            build_parameters = self._get_build_parameters()
            build_parameters.additional_libs = [
                pathlib.Path("/my-libs/lib1"),
                pathlib.Path("/my-other/libs/lib2"),
            ]
            platform_parameters = PlatformParameters(
                Platform.x86_64, "image:tag", "1.0"
            )
            platform_parameters.holoscan_sdk_file = pathlib.Path("/sdk/holoscan.deb")

            with tempfile.TemporaryDirectory() as temp_dir:
                builder = CppAppBuilder(build_parameters, temp_dir)
                result = builder.build(platform_parameters)
                assert result.succeeded is True
                assert (
                    builder._build_parameters.additional_lib_paths
                    == "/opt/holoscan/lib/my-libs/lib1:/opt/holoscan/lib/my-other/libs/lib2"
                )
