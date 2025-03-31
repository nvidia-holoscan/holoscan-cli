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
from pathlib import Path
from typing import Any, Dict

import pytest

from holoscan_cli.runner.run_command import create_run_parser


class TestRunCommand:
    @pytest.fixture
    def parser(self) -> argparse.ArgumentParser:
        """
        Create and return an ArgumentParser instance for testing.

        Returns:
            argparse.ArgumentParser: The configured argument parser
        """
        main_parser = argparse.ArgumentParser(description="Test parser")
        subparsers = main_parser.add_subparsers(dest="command")
        return create_run_parser(subparsers, "run", [])

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
        Create a dictionary of valid arguments for the run command.

        Args:
            temp_dir: Temporary directory path

        Returns:
            Dict[str, Any]: Dictionary of valid arguments
        """
        # Create necessary files and directories
        input_dir = temp_dir / "input"
        input_dir.mkdir()
        (input_dir / "data.bin").touch()

        output_dir = temp_dir / "output"
        output_dir.mkdir()

        config_file = temp_dir / "config.yaml"
        config_file.touch()

        return {
            "map": "myapp:1.0",
            "address": "localhost:8765",
            "driver": True,
            "input": str(input_dir),
            "output": str(output_dir),
            "fragments": "fragment1,fragment2",
            "worker": True,
            "worker_address": "localhost:10000",
            "rm": True,
            "config": str(config_file),
            "name": "test-container",
            "health_check": True,
            "network": "custom-network",
            "nic": "eth0",
            "use_all_nics": True,
            "render": True,
            "quiet": True,
            "shm_size": "2g",
            "terminal": True,
            "device": ["ajantv0", "video1"],
            "gpus": "all",
            "uid": "1001",
            "gid": "1001",
        }

    def test_parser_creation(self) -> None:
        """Test that the parser is created correctly."""
        main_parser = argparse.ArgumentParser(description="Test parser")
        subparsers = main_parser.add_subparsers(dest="command")
        parser = create_run_parser(subparsers, "run", [])

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
        # The only required argument is the map (image name)
        with pytest.raises(SystemExit):
            parser.parse_args([])

        # This should work
        args = parser.parse_args(["myapp:1.0"])
        assert args.map == "myapp:1.0"

    def test_valid_arguments(
        self, parser: argparse.ArgumentParser, valid_args: Dict[str, Any]
    ) -> None:
        """
        Test parsing with valid arguments.

        Args:
            parser: The argument parser to test
            valid_args: Dictionary of valid arguments
        """
        # Convert the dictionary to command line arguments
        cmd_args = []
        for key, value in valid_args.items():
            if key == "map":
                cmd_args.insert(0, str(value))  # Positional argument should be first
                continue

            if isinstance(value, list):
                for item in value:
                    cmd_args.extend([f"--{key.replace('_', '-')}", str(item)])
            elif value is True:
                cmd_args.append(f"--{key.replace('_', '-')}")
            elif value is not False and value is not None:
                cmd_args.extend([f"--{key.replace('_', '-')}", str(value)])

        args = parser.parse_args(cmd_args)

        # Check that all arguments were parsed correctly
        for key, expected in valid_args.items():
            if isinstance(expected, list):
                assert getattr(args, key) == expected
            elif expected is True or expected is False:
                assert getattr(args, key) == expected
            elif expected is not None:
                assert str(getattr(args, key)) == str(expected)

    def test_default_values(self, parser: argparse.ArgumentParser) -> None:
        """
        Test default values.

        Args:
            parser: The argument parser to test
        """
        args = parser.parse_args(["myapp:1.0"])

        # Check default values
        assert args.driver is False
        assert args.worker is False
        assert args.rm is False
        assert args.network == "host"
        assert args.use_all_nics is False
        assert args.render is False
        assert args.quiet is False
        assert args.terminal is False
        assert args.health_check == "False"  # Note: This is a string in the code
        assert args.uid == os.getuid()
        assert args.gid == os.getgid()

    def test_device_argument(self, parser: argparse.ArgumentParser) -> None:
        """
        Test the device argument which can accept multiple values.

        Args:
            parser: The argument parser to test
        """
        # Test with single device
        args = parser.parse_args(["myapp:1.0", "--device", "ajantv0"])
        assert args.device == ["ajantv0"]

        # Test with multiple devices
        args = parser.parse_args(["myapp:1.0", "--device", "ajantv0", "video1"])
        assert args.device == ["ajantv0", "video1"]

    def test_fragments_parsing(self, parser: argparse.ArgumentParser) -> None:
        """
        Test fragments argument parsing.

        Args:
            parser: The argument parser to test
        """
        # Test with comma-separated fragments
        args = parser.parse_args(
            ["myapp:1.0", "--fragments", "fragment1,fragment2,fragment3"]
        )
        assert args.fragments == "fragment1,fragment2,fragment3"

        # Test with 'all' value
        args = parser.parse_args(["myapp:1.0", "--fragments", "all"])
        assert args.fragments == "all"

    def test_path_arguments(
        self, parser: argparse.ArgumentParser, temp_dir: Path
    ) -> None:
        """
        Test path-related arguments.

        Args:
            parser: The argument parser to test
            temp_dir: Temporary directory path
        """
        input_dir = temp_dir / "input"
        input_dir.mkdir()

        output_dir = temp_dir / "output"
        output_dir.mkdir()

        config_file = temp_dir / "config.yaml"
        config_file.touch()

        args = parser.parse_args(
            [
                "myapp:1.0",
                "--input",
                str(input_dir),
                "--output",
                str(output_dir),
                "--config",
                str(config_file),
            ]
        )

        assert str(args.input) == str(input_dir)
        assert str(args.output) == str(output_dir)
        assert str(args.config) == str(config_file)

    def test_network_options(self, parser: argparse.ArgumentParser) -> None:
        """
        Test network-related options.

        Args:
            parser: The argument parser to test
        """
        args = parser.parse_args(
            [
                "myapp:1.0",
                "--address",
                "192.168.1.100:8765",
                "--worker-address",
                "192.168.1.101:10000",
                "--network",
                "custom-network",
                "--nic",
                "eth0",
                "--use-all-nics",
            ]
        )

        assert args.address == "192.168.1.100:8765"
        assert args.worker_address == "192.168.1.101:10000"
        assert args.network == "custom-network"
        assert args.nic == "eth0"
        assert args.use_all_nics is True

    def test_container_options(self, parser: argparse.ArgumentParser) -> None:
        """
        Test container-related options.

        Args:
            parser: The argument parser to test
        """
        args = parser.parse_args(
            [
                "myapp:1.0",
                "--name",
                "test-container",
                "--rm",
                "--shm-size",
                "2g",
                "--gpus",
                "all",
            ]
        )

        assert args.name == "test-container"
        assert args.rm is True
        assert args.shm_size == "2g"
        assert args.gpus == "all"
