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

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from holoscan_cli.__main__ import parse_args, set_up_logging, main


class TestParseArgs:
    def test_parse_args_help_when_no_command(self):
        """Test that help is printed and program exits when no command is provided"""
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["holoscan"]):
                parse_args(["holoscan"])

    def test_parse_args_package_command(self):
        """Test parsing package command"""
        # Use a temporary directory that exists and create necessary files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a dummy __main__.py to make it a valid application directory
            main_file = Path(temp_dir) / "__main__.py"
            main_file.write_text("# dummy main file")

            # Create a dummy config file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False
            ) as config_file:
                config_file.write("# dummy config")
                config_path = config_file.name

            try:
                argv = [
                    "holoscan",
                    "package",
                    temp_dir,
                    "--config",
                    config_path,
                    "--platform",
                    "x86_64",
                    "--tag",
                    "test:latest",
                ]
                args = parse_args(argv)
                assert args.command == "package"
                assert args.argv == argv
            finally:
                Path(config_path).unlink()  # Clean up config file

    def test_parse_args_run_command(self):
        """Test parsing run command"""
        argv = ["holoscan", "run", "some-image:tag"]
        args = parse_args(argv)
        assert args.command == "run"
        assert args.argv == argv

    def test_parse_args_version_command(self):
        """Test parsing version command"""
        argv = ["holoscan", "version"]
        args = parse_args(argv)
        assert args.command == "version"
        assert args.argv == argv

    def test_parse_args_nics_command(self):
        """Test parsing nics command"""
        argv = ["holoscan", "nics"]
        args = parse_args(argv)
        assert args.command == "nics"
        assert args.argv == argv

    def test_parse_args_with_log_level(self):
        """Test parsing with log level option"""
        argv = ["holoscan", "version", "--log-level", "DEBUG"]
        args = parse_args(argv)
        assert args.log_level == "DEBUG"
        assert args.command == "version"

    def test_parse_args_with_short_log_level(self):
        """Test parsing with short log level option"""
        argv = ["holoscan", "version", "-l", "ERROR"]
        args = parse_args(argv)
        assert args.log_level == "ERROR"
        assert args.command == "version"

    def test_parse_args_invalid_log_level(self):
        """Test parsing with invalid log level"""
        argv = ["holoscan", "version", "--log-level", "INVALID"]
        with pytest.raises(SystemExit):
            parse_args(argv)

    def test_parse_args_case_insensitive_log_level(self):
        """Test that log level is converted to uppercase"""
        argv = ["holoscan", "version", "--log-level", "debug"]
        args = parse_args(argv)
        assert args.log_level == "DEBUG"

    def test_parse_args_with_main_py_command_name(self):
        """Test program name handling when called as __main__.py"""
        argv = ["__main__.py", "version"]
        args = parse_args(argv)
        # The program name should be normalized to 'holoscan' but argv is preserved
        assert args.command == "version"
        assert args.argv == argv

    def test_parse_args_no_argv_provided(self):
        """Test parse_args when no argv is provided (uses sys.argv)"""
        with patch("sys.argv", ["holoscan", "version"]):
            args = parse_args(None)
            assert args.command == "version"
            assert args.argv == ["holoscan", "version"]

    def test_parse_args_log_level_none_by_default(self):
        """Test that log_level is None by default (not overriding config file)"""
        argv = ["holoscan", "version"]
        args = parse_args(argv)
        assert args.log_level is None


class TestSetUpLogging:
    def test_set_up_logging_with_default_config(self, monkeypatch):
        """Test set_up_logging with default logging config"""
        # Mock the default config file path
        mock_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "root": {"level": "INFO"},
        }

        def mock_read_bytes():
            return json.dumps(mock_config).encode()

        mock_path = MagicMock()
        mock_path.read_bytes = mock_read_bytes

        with patch("holoscan_cli.__main__.Path") as mock_path_class:
            mock_path_class.return_value.absolute.return_value.parent.__truediv__.return_value = mock_path
            mock_path_class.return_value.exists.return_value = False

            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging(None)
                mock_dict_config.assert_called_once_with(mock_config)

    def test_set_up_logging_with_level_override(self, monkeypatch):
        """Test set_up_logging with log level override"""
        mock_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "root": {"level": "INFO"},
        }

        expected_config = mock_config.copy()
        expected_config["root"]["level"] = "DEBUG"

        def mock_read_bytes():
            return json.dumps(mock_config).encode()

        mock_path = MagicMock()
        mock_path.read_bytes = mock_read_bytes

        with patch("holoscan_cli.__main__.Path") as mock_path_class:
            mock_path_class.return_value.absolute.return_value.parent.__truediv__.return_value = mock_path
            mock_path_class.return_value.exists.return_value = False

            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging("DEBUG")
                mock_dict_config.assert_called_once_with(expected_config)

    def test_set_up_logging_with_custom_config_path(self, monkeypatch):
        """Test set_up_logging with custom config file path"""
        mock_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "root": {"level": "WARN"},
        }

        def mock_read_bytes():
            return json.dumps(mock_config).encode()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(mock_config, temp_file)

        try:
            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging(None, temp_path)
                mock_dict_config.assert_called_once_with(mock_config)
        finally:
            temp_path.unlink()  # Clean up

    def test_set_up_logging_no_root_in_config(self, monkeypatch):
        """Test set_up_logging when config doesn't have root section"""
        mock_config = {"version": 1, "disable_existing_loggers": False}

        def mock_read_bytes():
            return json.dumps(mock_config).encode()

        mock_path = MagicMock()
        mock_path.read_bytes = mock_read_bytes

        with patch("holoscan_cli.__main__.Path") as mock_path_class:
            mock_path_class.return_value.absolute.return_value.parent.__truediv__.return_value = mock_path
            mock_path_class.return_value.exists.return_value = False

            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging("DEBUG")
                # Config should remain unchanged since there's no root section
                mock_dict_config.assert_called_once_with(mock_config)

    def test_set_up_logging_current_dir_config_override(self, monkeypatch):
        """Test that config file in current directory overrides default"""
        mock_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "root": {"level": "ERROR"},
        }

        def mock_read_bytes():
            return json.dumps(mock_config).encode()

        mock_current_config = MagicMock()
        mock_current_config.read_bytes = mock_read_bytes
        mock_current_config.exists.return_value = True

        with patch("holoscan_cli.__main__.Path") as mock_path_class:
            mock_path_class.return_value = mock_current_config

            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging(None, "logging.json")
                mock_dict_config.assert_called_once_with(mock_config)


class TestMain:
    def test_main_package_command(self, monkeypatch):
        """Test main function with package command"""
        mock_args = MagicMock()
        mock_args.command = "package"
        mock_args.log_level = None

        mock_execute = MagicMock()

        with patch("holoscan_cli.__main__.parse_args", return_value=mock_args):
            with patch("holoscan_cli.__main__.set_up_logging"):
                with patch(
                    "holoscan_cli.packager.packager.execute_package_command",
                    mock_execute,
                ):
                    main(["holoscan", "package", "/some/path"])
                    mock_execute.assert_called_once_with(mock_args)

    def test_main_run_command(self, monkeypatch):
        """Test main function with run command"""
        mock_args = MagicMock()
        mock_args.command = "run"
        mock_args.log_level = None

        mock_execute = MagicMock()

        with patch("holoscan_cli.__main__.parse_args", return_value=mock_args):
            with patch("holoscan_cli.__main__.set_up_logging"):
                with patch(
                    "holoscan_cli.runner.runner.execute_run_command", mock_execute
                ):
                    main(["holoscan", "run", "some-image:tag"])
                    mock_execute.assert_called_once_with(mock_args)

    def test_main_version_command(self, monkeypatch):
        """Test main function with version command"""
        mock_args = MagicMock()
        mock_args.command = "version"
        mock_args.log_level = None

        mock_execute = MagicMock()

        with patch("holoscan_cli.__main__.parse_args", return_value=mock_args):
            with patch("holoscan_cli.__main__.set_up_logging"):
                with patch(
                    "holoscan_cli.version.version.execute_version_command", mock_execute
                ):
                    main(["holoscan", "version"])
                    mock_execute.assert_called_once_with(mock_args)

    def test_main_nics_command(self, monkeypatch):
        """Test main function with nics command"""
        mock_args = MagicMock()
        mock_args.command = "nics"
        mock_args.log_level = None

        mock_execute = MagicMock()

        with patch("holoscan_cli.__main__.parse_args", return_value=mock_args):
            with patch("holoscan_cli.__main__.set_up_logging"):
                with patch("holoscan_cli.nics.nics.execute_nics_command", mock_execute):
                    main(["holoscan", "nics"])
                    mock_execute.assert_called_once_with(mock_args)

    def test_main_with_log_level(self, monkeypatch):
        """Test main function properly sets up logging with specified level"""
        mock_args = MagicMock()
        mock_args.command = "version"
        mock_args.log_level = "DEBUG"

        mock_execute = MagicMock()

        with patch("holoscan_cli.__main__.parse_args", return_value=mock_args):
            with patch("holoscan_cli.__main__.set_up_logging") as mock_logging:
                with patch(
                    "holoscan_cli.version.version.execute_version_command", mock_execute
                ):
                    main(["holoscan", "--log-level", "DEBUG", "version"])
                    mock_logging.assert_called_once_with("DEBUG")
                    mock_execute.assert_called_once_with(mock_args)

    def test_main_no_argv_provided(self, monkeypatch):
        """Test main function when no argv is provided"""
        mock_args = MagicMock()
        mock_args.command = "version"
        mock_args.log_level = None

        mock_execute = MagicMock()

        with patch(
            "holoscan_cli.__main__.parse_args", return_value=mock_args
        ) as mock_parse:
            with patch("holoscan_cli.__main__.set_up_logging"):
                with patch(
                    "holoscan_cli.version.version.execute_version_command", mock_execute
                ):
                    main(None)
                    mock_parse.assert_called_once_with(None)
                    mock_execute.assert_called_once_with(mock_args)

    def test_main_calls_parse_args_and_logging_setup(self, monkeypatch):
        """Test that main function calls parse_args and set_up_logging in correct order"""
        mock_args = MagicMock()
        mock_args.command = "version"
        mock_args.log_level = "INFO"

        call_order = []

        def mock_parse_args(argv):
            call_order.append("parse_args")
            return mock_args

        def mock_set_up_logging(level):
            call_order.append("set_up_logging")
            assert level == "INFO"

        def mock_execute(args):
            call_order.append("execute_command")

        with patch("holoscan_cli.__main__.parse_args", side_effect=mock_parse_args):
            with patch(
                "holoscan_cli.__main__.set_up_logging", side_effect=mock_set_up_logging
            ):
                with patch(
                    "holoscan_cli.version.version.execute_version_command", mock_execute
                ):
                    main(["holoscan", "version"])

        assert call_order == ["parse_args", "set_up_logging", "execute_command"]
