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
import sys
from unittest.mock import patch, MagicMock
import pytest

from holoscan_cli.version.version import execute_version_command
from holoscan_cli.common.enum_types import SdkType


@pytest.fixture
def mock_stdout(monkeypatch):
    """Fixture to capture stdout"""
    buffer = []

    def mock_print(*args, **kwargs):
        buffer.append(" ".join(map(str, args)))

    monkeypatch.setattr("builtins.print", mock_print)
    return buffer


def test_execute_version_command_holoscan_sdk(mock_stdout):
    """Test version command with Holoscan SDK"""
    args = MagicMock()

    with (
        patch("holoscan_cli.version.version.detect_sdk") as mock_detect_sdk,
        patch(
            "holoscan_cli.version.version.detect_holoscan_version"
        ) as mock_holoscan_version,
        patch(
            "holoscan_cli.version.version.detect_holoscan_cli_version"
        ) as mock_holoscan_cli_version,
    ):
        mock_detect_sdk.return_value = SdkType.Holoscan
        mock_holoscan_version.return_value = "1.0.0"
        mock_holoscan_cli_version.return_value = "0.1.0"
        execute_version_command(args)

        assert any("Holoscan SDK:           1.0.0" in line for line in mock_stdout)
        assert any("Holoscan CLI:           0.1.0" in line for line in mock_stdout)
        assert any(
            f"You are executing Holoscan CLI from: {os.path.dirname(os.path.abspath(sys.argv[0]))}"
            in line
            for line in mock_stdout
        )


def test_execute_version_command_monai_sdk(mock_stdout):
    """Test version command with MONAI Deploy SDK"""
    args = MagicMock()

    with (
        patch("holoscan_cli.version.version.detect_sdk") as mock_detect_sdk,
        patch(
            "holoscan_cli.version.version.detect_holoscan_version"
        ) as mock_holoscan_version,
        patch(
            "holoscan_cli.version.version.detect_holoscan_cli_version"
        ) as mock_holoscan_cli_version,
        patch(
            "holoscan_cli.version.version.detect_monaideploy_version"
        ) as mock_monai_version,
    ):
        mock_detect_sdk.return_value = SdkType.MonaiDeploy
        mock_holoscan_version.return_value = "1.0.0"
        mock_holoscan_cli_version.return_value = "0.1.0"
        mock_monai_version.return_value = "0.6.0"

        execute_version_command(args)

        assert any("Holoscan SDK:           1.0.0" in line for line in mock_stdout)
        assert any("Holoscan CLI:           0.1.0" in line for line in mock_stdout)
        assert any("MONAI Deploy App SDK:   0.6.0" in line for line in mock_stdout)


def test_execute_version_command_holoscan_version_error(mock_stdout):
    """Test version command when Holoscan version detection fails"""
    args = MagicMock()

    with (
        patch("holoscan_cli.version.version.detect_sdk") as mock_detect_sdk,
        patch(
            "holoscan_cli.version.version.detect_holoscan_version"
        ) as mock_holoscan_version,
        patch(
            "holoscan_cli.version.version.detect_holoscan_cli_version"
        ) as mock_holoscan_cli_version,
    ):
        mock_detect_sdk.return_value = SdkType.Holoscan
        mock_holoscan_version.side_effect = Exception("Version detection failed")
        mock_holoscan_cli_version.return_value = "0.1.0"
        execute_version_command(args)

        assert any("Holoscan SDK:           N/A" in line for line in mock_stdout)
        assert any("Holoscan CLI:           0.1.0" in line for line in mock_stdout)


def test_execute_version_command_sdk_detection_error(mock_stdout):
    """Test version command when SDK detection fails"""
    args = MagicMock()

    with (
        patch("holoscan_cli.version.version.detect_sdk") as mock_detect_sdk,
        patch("holoscan_cli.version.version.logging.error") as mock_error,
    ):
        mock_detect_sdk.side_effect = Exception("SDK detection failed")
        with pytest.raises(SystemExit) as exc_info:
            execute_version_command(args)

        assert exc_info.value.code == 3
        mock_error.assert_called_once_with("Error executing version command.")
