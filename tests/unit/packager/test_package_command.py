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

import argparse
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict

import pytest
from packaging.version import Version

from holoscan_cli.packager.package_command import create_package_parser
from holoscan_cli.common.constants import SDK


class TestPackageCommand:
    @pytest.fixture
    def parser(self) -> argparse.ArgumentParser:
        """
        Create and return an ArgumentParser instance for testing.

        Returns:
            argparse.ArgumentParser: The configured argument parser
        """
        main_parser = argparse.ArgumentParser(description="Test parser")
        subparsers = main_parser.add_subparsers(dest="command")
        return create_package_parser(subparsers, "package", [])

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """
        Create a temporary directory for testing file paths.

        Args:
            tmp_path: Pytest fixture providing a temporary directory path

        Returns:
            Path: Path to the temporary directory
        """
        return tmp_path

    @pytest.fixture
    def valid_args(self, temp_dir: Path) -> Dict[str, Any]:
        """
        Create a dictionary of valid arguments for the package command.

        Args:
            temp_dir: Temporary directory path

        Returns:
            Dict[str, Any]: Dictionary of valid arguments
        """
        # Create necessary files and directories
        app_dir = temp_dir / "app"
        app_dir.mkdir()
        (app_dir / "__main__.py").touch()

        config_file = temp_dir / "config.yaml"
        config_file.touch()

        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "README.md").touch()

        models_dir = temp_dir / "models"
        models_dir.mkdir()
        (models_dir / "model.onnx").touch()

        additional_lib = temp_dir / "lib"
        additional_lib.mkdir()
        (additional_lib / "library.so").touch()

        return {
            "application": str(app_dir),
            "config": str(config_file),
            "docs": str(docs_dir),
            "models": str(models_dir),
            "platform": "x86_64",
            "add": [str(additional_lib)],
            "timeout": 300,
            "version": Version("1.0.0"),
            "add_host": ["example.com:192.168.1.1"],
            "base_image": "base:latest",
            "build_image": "build:latest",
            "includes": ["debug", "holoviz"],
            "build_cache": str(temp_dir / "cache"),
            "cmake_args": '"-DCMAKE_BUILD_TYPE=DEBUG"',
            "no_cache": True,
            "sdk": "holoscan",
            "source": "source.json",
            "sdk_version": Version("0.5.0"),
            "output": str(temp_dir),
            "tag": "myapp:1.0",
            "username": "testuser",
            "uid": "1001",
            "gid": "1001",
        }

    def test_parser_creation(self) -> None:
        """Test that the parser is created correctly."""
        main_parser = argparse.ArgumentParser(description="Test parser")
        subparsers = main_parser.add_subparsers(dest="command")
        parser = create_package_parser(subparsers, "package", [])

        assert parser is not None
        assert isinstance(parser, argparse.ArgumentParser)

    def test_required_arguments(
        self, parser: argparse.ArgumentParser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Test that required arguments are enforced.

        Args:
            parser: The argument parser to test
            monkeypatch: Pytest fixture for patching functions
        """
        with pytest.raises(SystemExit):
            parser.parse_args(["--tag", "myapp:1.0"])

        with pytest.raises(SystemExit):
            parser.parse_args(["app", "--platform", "x86_64"])

        with pytest.raises(SystemExit):
            parser.parse_args(["app", "--config", "config.yaml"])

    def test_valid_arguments(
        self,
        parser: argparse.ArgumentParser,
        valid_args: Dict[str, Any],
        temp_dir: Path,
    ) -> None:
        """
        Test parsing with valid arguments.

        Args:
            parser: The argument parser to test
            valid_args: Dictionary of valid arguments
            temp_dir: Temporary directory path
        """
        # Convert the dictionary to command line arguments
        cmd_args = []
        for key, value in valid_args.items():
            if key == "application":
                cmd_args.insert(0, str(value))  # Positional argument should be first
                continue

            if isinstance(value, list):
                for item in value:
                    if key == "includes":
                        cmd_args.extend(["--includes", item])
                    else:
                        cmd_args.extend([f"--{key.replace('_', '-')}", str(item)])
            elif value is True:
                cmd_args.append(f"--{key.replace('_', '-')}")
            elif value is not False and value is not None:
                cmd_args.extend([f"--{key.replace('_', '-')}", str(value)])

        args = parser.parse_args(cmd_args)

        # Check that all arguments were parsed correctly
        for key, expected in valid_args.items():
            if key == "includes":
                for item in getattr(args, key):
                    assert str(item) in expected
            elif isinstance(expected, list):
                if key == "add":
                    for item in getattr(args, "additional_libs"):
                        assert str(item) in expected
                elif key == "add_host":
                    for item in getattr(args, "add_hosts"):
                        assert str(item) in expected
                else:
                    assert getattr(args, key) == expected
            elif expected is True or expected is False:
                assert getattr(args, key) == expected
            elif isinstance(getattr(args, key), list):
                if isinstance(getattr(args, key)[0], Enum):
                    for item in getattr(args, key):
                        assert item.value in expected
                else:
                    assert getattr(args, key) == expected
            elif isinstance(getattr(args, key), Enum):
                assert getattr(args, key).value == expected
            elif expected is not None:
                print("================================================")
                print(f"key: {key}, expected: {expected}")
                print(f"type: {type(expected)}")
                print(f"arg: {getattr(args, key)}")
                print(f"type: {type(getattr(args, key))}")
                print("================================================")
                assert str(getattr(args, key)) == str(expected)

    def test_platform_validation(
        self,
        parser: argparse.ArgumentParser,
        valid_args: Dict[str, Any],
        temp_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Test platform validation.

        Args:
            parser: The argument parser to test
            valid_args: Dictionary of valid arguments
            temp_dir: Temporary directory path
            monkeypatch: Pytest fixture for patching functions
        """
        cmd_args = [
            valid_args["application"],
            "--config",
            valid_args["config"],
            "--platform",
            "invalid_platform",
            "--tag",
            valid_args["tag"],
        ]

        with pytest.raises(SystemExit):
            parser.parse_args(cmd_args)

        # Test valid platforms
        for platform in SDK.PLATFORMS:
            cmd_args = [
                valid_args["application"],
                "--config",
                valid_args["config"],
                "--platform",
                platform,
                "--tag",
                valid_args["tag"],
            ]
            args = parser.parse_args(cmd_args)
            assert str(args.platform[0].value) == platform

    def test_sdk_validation(
        self,
        parser: argparse.ArgumentParser,
        valid_args: Dict[str, Any],
        temp_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Test SDK validation.

        Args:
            parser: The argument parser to test
            valid_args: Dictionary of valid arguments
            temp_dir: Temporary directory path
            monkeypatch: Pytest fixture for patching functions
        """
        cmd_args = [
            valid_args["application"],
            "--config",
            valid_args["config"],
            "--platform",
            valid_args["platform"],
            "--tag",
            valid_args["tag"],
            "--sdk",
            "invalid_sdk",
        ]

        with pytest.raises(SystemExit):
            parser.parse_args(cmd_args)

        # Test valid SDKs
        for sdk in SDK.SDKS:
            cmd_args = [
                valid_args["application"],
                "--config",
                valid_args["config"],
                "--platform",
                valid_args["platform"],
                "--tag",
                valid_args["tag"],
                "--sdk",
                sdk,
            ]
            args = parser.parse_args(cmd_args)
            assert str(args.sdk.value) == sdk

    def test_includes_validation(
        self,
        parser: argparse.ArgumentParser,
        valid_args: Dict[str, Any],
        temp_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Test includes validation.

        Args:
            parser: The argument parser to test
            valid_args: Dictionary of valid arguments
            temp_dir: Temporary directory path
            monkeypatch: Pytest fixture for patching functions
        """
        cmd_args = [
            valid_args["application"],
            "--config",
            valid_args["config"],
            "--platform",
            valid_args["platform"],
            "--tag",
            valid_args["tag"],
            "--includes",
            "invalid_include",
        ]

        with pytest.raises(SystemExit):
            parser.parse_args(cmd_args)

        # Test valid includes
        valid_includes = ["debug", "holoviz", "torch", "onnx"]
        for include in valid_includes:
            cmd_args = [
                valid_args["application"],
                "--config",
                valid_args["config"],
                "--platform",
                valid_args["platform"],
                "--tag",
                valid_args["tag"],
                "--includes",
                include,
            ]
            args = parser.parse_args(cmd_args)
            assert include in args.includes

    def test_version_parsing(
        self,
        parser: argparse.ArgumentParser,
        valid_args: Dict[str, Any],
        temp_dir: Path,
    ) -> None:
        """
        Test version parsing.

        Args:
            parser: The argument parser to test
            valid_args: Dictionary of valid arguments
            temp_dir: Temporary directory path
        """
        cmd_args = [
            valid_args["application"],
            "--config",
            valid_args["config"],
            "--platform",
            valid_args["platform"],
            "--tag",
            valid_args["tag"],
            "--version",
            "1.2.3",
        ]

        args = parser.parse_args(cmd_args)
        assert isinstance(args.version, Version)
        assert str(args.version) == "1.2.3"

        cmd_args = [
            valid_args["application"],
            "--config",
            valid_args["config"],
            "--platform",
            valid_args["platform"],
            "--tag",
            valid_args["tag"],
            "--sdk-version",
            "0.5.1",
        ]

        args = parser.parse_args(cmd_args)
        assert isinstance(args.sdk_version, Version)
        assert str(args.sdk_version) == "0.5.1"

    def test_default_values(
        self,
        parser: argparse.ArgumentParser,
        valid_args: Dict[str, Any],
        temp_dir: Path,
    ) -> None:
        """
        Test default values.

        Args:
            parser: The argument parser to test
            valid_args: Dictionary of valid arguments
            temp_dir: Temporary directory path
        """
        cmd_args = [
            valid_args["application"],
            "--config",
            valid_args["config"],
            "--platform",
            valid_args["platform"],
            "--tag",
            valid_args["tag"],
        ]

        args = parser.parse_args(cmd_args)

        # Check default values
        assert args.username == "holoscan"
        assert args.uid == 1000
        assert args.gid == 1000
        assert args.no_cache is False
        assert args.includes == []
        assert str(args.build_cache) == os.path.expanduser("~/.holoscan_build_cache")

    def test_input_data_parameter(
        self,
        parser: argparse.ArgumentParser,
        valid_args: Dict[str, Any],
        temp_dir: Path,
    ) -> None:
        """
        Test the --input-data parameter.

        Args:
            parser: The argument parser to test
            valid_args: Dictionary of valid arguments
            temp_dir: Temporary directory path
        """
        # Create input data directory
        input_data_dir = temp_dir / "input_data"
        input_data_dir.mkdir()
        (input_data_dir / "sample.dat").touch()

        cmd_args = [
            valid_args["application"],
            "--config",
            valid_args["config"],
            "--platform",
            valid_args["platform"],
            "--tag",
            valid_args["tag"],
            "--input-data",
            str(input_data_dir),
        ]

        args = parser.parse_args(cmd_args)
        assert str(args.input_data) == str(input_data_dir)

        # Test with non-existent directory (should still pass as valid_dir_path doesn't check existence)
        non_existent_dir = temp_dir / "non_existent"
        cmd_args = [
            valid_args["application"],
            "--config",
            valid_args["config"],
            "--platform",
            valid_args["platform"],
            "--tag",
            valid_args["tag"],
            "--input-data",
            str(non_existent_dir),
        ]

        args = parser.parse_args(cmd_args)
        assert str(args.input_data) == str(non_existent_dir)
