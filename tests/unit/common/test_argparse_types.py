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
import argparse
import os
import pathlib
from pathlib import PosixPath

import pytest
from holoscan_cli.common.argparse_types import (
    valid_dir_path,
    valid_existing_dir_path,
    valid_existing_path,
    valid_platform_config,
    valid_platforms,
    valid_sdk_type,
    valid_host_ip,
)
from holoscan_cli.common.enum_types import Platform, PlatformConfiguration, SdkType


class TestValidDirPath:
    def test_dir_exists_and_isdir(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: True)
        result = valid_dir_path("/this/is/some/path")

        assert type(result) is PosixPath
        assert str(result).startswith("/this")

    def test_dir_exists_and_not_isdir(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: False)

        with pytest.raises(argparse.ArgumentTypeError):
            valid_dir_path("this/is/some/path")

    def test_not_dir_exists(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: False)
        monkeypatch.setattr(pathlib.Path, "mkdir", lambda x, parents: False)

        result = valid_dir_path("this/is/some/path")

        assert type(result) is PosixPath

    def test_dir_exists_and_isdir_and_expands_user_dir(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: True)
        result = valid_dir_path("~/this/is/some/path")

        assert type(result) is PosixPath

        assert str(result).startswith(os.path.expanduser("~"))

    def test_dir_path_with_create_if_not_exists_false(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: False)

        with pytest.raises(argparse.ArgumentTypeError):
            valid_dir_path("this/is/some/path", create_if_not_exists=False)

    def test_dir_path_mkdir_fails(self, monkeypatch):
        def mkdir_raise(*args, **kwargs):
            raise PermissionError()

        monkeypatch.setattr(pathlib.Path, "exists", lambda x: False)
        monkeypatch.setattr(pathlib.Path, "mkdir", mkdir_raise)

        with pytest.raises(PermissionError):
            valid_dir_path("this/is/some/path")


class TestValidExistingDirPath:
    def test_dir_path_exists_and_isdir(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: True)
        result = valid_existing_dir_path("this/is/some/path")

        assert type(result) is PosixPath

    @pytest.mark.parametrize(
        "exists,isdir", [(False, False), (True, False), (False, True)]
    )
    def test_dir_path_exists_and_isdir_combo(self, monkeypatch, exists, isdir):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: exists)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: isdir)
        with pytest.raises(argparse.ArgumentTypeError):
            valid_existing_dir_path("this/is/some/path")


class TestValidExistingPath:
    def test_existing_path_exists(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        result = valid_existing_path("this/is/some/path")

        assert type(result) is PosixPath

    def test_existing_path_not_exists(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: False)
        with pytest.raises(argparse.ArgumentTypeError):
            valid_existing_path("this/is/some/path")

    def test_empty_directory(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: True)
        monkeypatch.setattr(os, "scandir", lambda x: [])
        with pytest.raises(argparse.ArgumentTypeError):
            valid_existing_path("this/is/some/path")

    def test_non_empty_directory(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: True)
        monkeypatch.setattr(os, "scandir", lambda x: ["file"])
        result = valid_existing_path("this/is/some/path")
        assert type(result) is PosixPath

    def test_existing_path_with_file(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: False)
        result = valid_existing_path("this/is/some/file.txt")
        assert type(result) is PosixPath

    def test_existing_path_expands_user_dir(self, monkeypatch):
        monkeypatch.setattr(pathlib.Path, "exists", lambda x: True)
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda x: False)
        result = valid_existing_path("~/this/is/some/file.txt")
        assert str(result).startswith(os.path.expanduser("~"))


class TestValidPlatforms:
    @pytest.mark.parametrize(
        "platforms",
        [
            ([Platform.Jetson]),
            ([Platform.IGX_dGPU]),
            ([Platform.IGX_iGPU]),
            ([Platform.SBSA]),
            ([Platform.x86_64]),
            ([Platform.SBSA, Platform.x86_64]),
            (
                [
                    Platform.Jetson,
                    Platform.IGX_dGPU,
                    Platform.SBSA,
                ]
            ),
        ],
    )
    def test_valid_platforms(self, platforms: list[Platform]):
        platform_strs = ",".join(x.value for x in platforms)
        result = valid_platforms(platform_strs)

        assert result == platforms

    @pytest.mark.parametrize(
        "platforms",
        [
            ("bad-platform"),
            (f"{Platform.IGXOrinDevIt.value},bad-platform"),
            (f"{Platform.IGX_iGPU.value},"),
        ],
    )
    def test_invalid_platforms(self, platforms: str):
        with pytest.raises(argparse.ArgumentTypeError):
            valid_platforms(platforms)

    def test_valid_platforms_case_insensitive(self):
        # Test that platform strings are case-insensitive
        result = valid_platforms("JETSON,x86_64")
        assert result == [Platform.Jetson, Platform.x86_64]

    def test_valid_platforms_whitespace(self):
        # Test handling of whitespace
        result = valid_platforms(" jetson , x86_64 ")
        assert result == [Platform.Jetson, Platform.x86_64]

    def test_valid_platforms_empty_string(self):
        with pytest.raises(argparse.ArgumentTypeError):
            valid_platforms("")


class TestValidPlatformConfiguration:
    @pytest.mark.parametrize(
        "platforms_config",
        [
            (PlatformConfiguration.dGPU.value),
            (PlatformConfiguration.iGPU.value),
        ],
    )
    def test_valid_platform_config(self, platforms_config: PlatformConfiguration):
        result = valid_platform_config(platforms_config)

        assert result.value == platforms_config

    @pytest.mark.parametrize(
        "platforms_config",
        [
            ("bad-platform-config"),
            (""),
        ],
    )
    def test_invalid_platform_config(self, platforms_config: str):
        with pytest.raises(argparse.ArgumentTypeError):
            valid_platform_config(platforms_config)

    def test_valid_platform_config_case_insensitive(self):
        result = valid_platform_config("DGPU")
        assert result == PlatformConfiguration.dGPU

    def test_valid_platform_config_whitespace(self):
        result = valid_platform_config(" dgpu ")
        assert result == PlatformConfiguration.dGPU


class TestValidSdkType:
    @pytest.mark.parametrize(
        "sdk_type",
        [
            (SdkType.Holoscan.value),
            (SdkType.MonaiDeploy.value),
        ],
    )
    def test_valid_sdk_type(self, sdk_type: SdkType):
        result = valid_sdk_type(sdk_type)

        assert result.value == sdk_type

    @pytest.mark.parametrize(
        "sdk_type",
        [
            ("bad-value"),
            (""),
        ],
    )
    def test_invalid_sdk_type(self, sdk_type: str):
        with pytest.raises(argparse.ArgumentTypeError):
            valid_sdk_type(sdk_type)

    def test_valid_sdk_type_case_insensitive(self):
        result = valid_sdk_type("HOLOSCAN")
        assert result == SdkType.Holoscan

    def test_valid_sdk_type_whitespace(self):
        result = valid_sdk_type(" holoscan ")
        assert result == SdkType.Holoscan


class TestValidHostIp:
    """Test cases for valid_host_ip function in argparse_types.py."""

    def test_valid_host_ip(self) -> None:
        """Test valid_host_ip with valid host:ip format."""
        # Arrange
        valid_inputs = [
            "hostname:127.0.0.1",
            "example.com:192.168.1.1",
            "server-01:10.0.0.1",
        ]

        # Act & Assert
        for host_ip in valid_inputs:
            result = valid_host_ip(host_ip)
            assert result == host_ip

    def test_empty_host(self) -> None:
        """Test valid_host_ip with empty host part."""
        # Arrange
        invalid_input = ":127.0.0.1"

        # Act & Assert
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            valid_host_ip(invalid_input)

        assert "Invalid valid for --add-host" in str(exc_info.value)

    def test_empty_ip(self) -> None:
        """Test valid_host_ip with empty IP part."""
        # Arrange
        invalid_input = "hostname:"

        # Act & Assert
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            valid_host_ip(invalid_input)

        assert "Invalid valid for --add-host" in str(exc_info.value)

    def test_no_colon_separator(self) -> None:
        """Test valid_host_ip with no colon separator."""
        # Arrange
        invalid_input = "hostname127.0.0.1"

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            valid_host_ip(invalid_input)

        assert "not enough values to unpack" in str(exc_info.value)

    def test_multiple_colons(self) -> None:
        """Test valid_host_ip with multiple colons."""
        # Arrange
        invalid_input = "hostname:127.0.0.1:8080"

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            valid_host_ip(invalid_input)

        assert "too many values to unpack" in str(exc_info.value)
