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
from unittest.mock import MagicMock, patch

import pytest

from holoscan_cli.__main__ import main, parse_args, set_up_logging


class TestParseArgs:
    def test_parse_args_help_when_no_command(self):
        with pytest.raises(SystemExit):
            parse_args(["holoscan"])

    def test_parse_args_version_command(self):
        argv = ["holoscan", "version"]
        args = parse_args(argv)
        assert args.command == "version"
        assert args.argv == argv

    def test_parse_args_project_command_for_top_level_help_surface(self):
        argv = ["holoscan", "list"]
        args = parse_args(argv)
        assert args.command == "list"
        assert args.argv == argv

    @pytest.mark.parametrize(
        "argv",
        [
            ["holoscan", "nics"],
        ],
    )
    def test_parse_args_rejects_removed_commands(self, argv):
        with pytest.raises(SystemExit):
            parse_args(argv)

    def test_parse_args_with_log_level(self):
        argv = ["holoscan", "version", "--log-level", "DEBUG"]
        args = parse_args(argv)
        assert args.log_level == "DEBUG"
        assert args.command == "version"

    def test_parse_args_with_short_log_level(self):
        argv = ["holoscan", "version", "-l", "ERROR"]
        args = parse_args(argv)
        assert args.log_level == "ERROR"
        assert args.command == "version"

    def test_parse_args_invalid_log_level(self):
        argv = ["holoscan", "version", "--log-level", "INVALID"]
        with pytest.raises(SystemExit):
            parse_args(argv)

    def test_parse_args_case_insensitive_log_level(self):
        argv = ["holoscan", "version", "--log-level", "debug"]
        args = parse_args(argv)
        assert args.log_level == "DEBUG"

    def test_parse_args_with_main_py_command_name(self):
        argv = ["__main__.py", "version"]
        args = parse_args(argv)
        assert args.command == "version"
        assert args.argv == argv

    def test_parse_args_no_argv_provided(self):
        with patch("sys.argv", ["holoscan", "version"]):
            args = parse_args(None)
            assert args.command == "version"
            assert args.argv == ["holoscan", "version"]

    def test_parse_args_log_level_none_by_default(self):
        argv = ["holoscan", "version"]
        args = parse_args(argv)
        assert args.log_level is None


class TestSetUpLogging:
    def test_set_up_logging_with_default_config(self):
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
            mock_path_class.return_value.absolute.return_value.parent.__truediv__.return_value = (
                mock_path
            )
            mock_path_class.return_value.exists.return_value = False

            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging(None)
                mock_dict_config.assert_called_once_with(mock_config)

    def test_set_up_logging_with_level_override(self):
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
            mock_path_class.return_value.absolute.return_value.parent.__truediv__.return_value = (
                mock_path
            )
            mock_path_class.return_value.exists.return_value = False

            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging("DEBUG")
                mock_dict_config.assert_called_once_with(expected_config)

    def test_set_up_logging_with_custom_config_path(self):
        mock_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "root": {"level": "WARN"},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(mock_config, temp_file)

        try:
            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging(None, temp_path)
                mock_dict_config.assert_called_once_with(mock_config)
        finally:
            temp_path.unlink()

    def test_set_up_logging_no_root_in_config(self):
        mock_config = {"version": 1, "disable_existing_loggers": False}

        def mock_read_bytes():
            return json.dumps(mock_config).encode()

        mock_path = MagicMock()
        mock_path.read_bytes = mock_read_bytes

        with patch("holoscan_cli.__main__.Path") as mock_path_class:
            mock_path_class.return_value.absolute.return_value.parent.__truediv__.return_value = (
                mock_path
            )
            mock_path_class.return_value.exists.return_value = False

            with patch("logging.config.dictConfig") as mock_dict_config:
                set_up_logging("DEBUG")
                mock_dict_config.assert_called_once_with(mock_config)

    def test_set_up_logging_current_dir_config_override(self):
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
    def test_main_source_run_dispatches_to_project_cli(self):
        mock_project_main = MagicMock()
        with patch("holoscan_cli.__main__.set_up_logging") as mock_logging:
            with patch("holoscan_cli.cli.main", mock_project_main):
                main(["holoscan", "run", "endoscopy_tool_tracking", "--dryrun"])
        mock_logging.assert_called_once_with(None)
        mock_project_main.assert_called_once_with(
            ["holoscan", "run", "endoscopy_tool_tracking", "--dryrun"]
        )

    def test_main_image_like_run_stays_source_project_dispatch(self):
        mock_project_main = MagicMock()
        with patch("holoscan_cli.__main__.set_up_logging") as mock_logging:
            with patch("holoscan_cli.cli.main", mock_project_main):
                main(["holoscan", "run", "some-image:tag", "--driver"])
        mock_logging.assert_called_once_with(None)
        mock_project_main.assert_called_once_with(["holoscan", "run", "some-image:tag", "--driver"])

    def test_main_project_dispatch_strips_top_level_log_level(self):
        mock_project_main = MagicMock()
        with patch("holoscan_cli.__main__.set_up_logging") as mock_logging:
            with patch("holoscan_cli.cli.main", mock_project_main):
                main(["holoscan", "--log-level", "debug", "list"])
        mock_logging.assert_called_once_with("DEBUG")
        mock_project_main.assert_called_once_with(["holoscan", "list"])

    def test_main_wrapper_source_command_dispatches_to_project_cli(self, monkeypatch):
        mock_project_main = MagicMock()
        monkeypatch.setenv("HOLOSCAN_CLI_CMD_NAME", "./holohub")
        with patch("holoscan_cli.__main__.set_up_logging") as mock_logging:
            with patch("holoscan_cli.cli.main", mock_project_main):
                main(["holoscan", "list"])
        mock_logging.assert_called_once_with(None)
        mock_project_main.assert_called_once_with(["holoscan", "list"])

    def test_main_version_command(self):
        mock_args = MagicMock()
        mock_args.command = "version"
        mock_args.log_level = None
        mock_execute = MagicMock()

        with patch("holoscan_cli.__main__.parse_args", return_value=mock_args):
            with patch("holoscan_cli.__main__.set_up_logging"):
                with patch("holoscan_cli.__main__._execute_version_command", mock_execute):
                    main(["holoscan", "version"])
                    mock_execute.assert_called_once_with(mock_args)

    @pytest.mark.parametrize(
        "argv,command",
        [
            (["holoscan", "nics"], "nics"),
        ],
    )
    def test_main_rejects_removed_commands(self, argv, command, capsys):
        with patch("holoscan_cli.cli.main") as mock_project_main:
            with pytest.raises(SystemExit) as excinfo:
                main(argv)
        mock_project_main.assert_not_called()
        # Exit 2 matches argparse's convention for unknown subcommands.
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert f"'holoscan {command}' was removed" in err
        assert "Removed HAP/MAP commands are out of scope" in err

    def test_main_with_log_level(self):
        mock_args = MagicMock()
        mock_args.command = "version"
        mock_args.log_level = "DEBUG"
        mock_execute = MagicMock()

        with patch("holoscan_cli.__main__.parse_args", return_value=mock_args):
            with patch("holoscan_cli.__main__.set_up_logging") as mock_logging:
                with patch("holoscan_cli.__main__._execute_version_command", mock_execute):
                    main(["holoscan", "--log-level", "DEBUG", "version"])
                    mock_logging.assert_called_once_with("DEBUG")
                    mock_execute.assert_called_once_with(mock_args)

    def test_main_no_argv_provided(self):
        mock_args = MagicMock()
        mock_args.command = "version"
        mock_args.log_level = None
        mock_execute = MagicMock()

        with patch("holoscan_cli.__main__.parse_args", return_value=mock_args) as mock_parse:
            with patch("holoscan_cli.__main__.set_up_logging"):
                with patch("holoscan_cli.__main__._execute_version_command", mock_execute):
                    main(None)
                    assert mock_parse.call_count == 1
                    mock_execute.assert_called_once_with(mock_args)

    def test_main_calls_parse_args_and_logging_setup(self):
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
            with patch("holoscan_cli.__main__.set_up_logging", side_effect=mock_set_up_logging):
                with patch("holoscan_cli.__main__._execute_version_command", mock_execute):
                    main(["holoscan", "version"])

        assert call_order == ["parse_args", "set_up_logging", "execute_command"]
