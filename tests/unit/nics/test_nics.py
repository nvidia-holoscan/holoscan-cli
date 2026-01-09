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

import logging
import sys
from argparse import Namespace

from holoscan_cli.nics.nics import execute_nics_command


class TestExecuteNicsCommand:
    def test_execute_nics_command_with_ipv4(self, monkeypatch, capsys):
        # Mock get_host_ip_addresses to return sample IPv4 data
        ipv4_data = [("eth0", "192.168.1.100"), ("wlan0", "10.0.0.50")]
        monkeypatch.setattr(
            "holoscan_cli.nics.nics.get_host_ip_addresses", lambda: (ipv4_data, [])
        )

        # Execute command
        execute_nics_command(Namespace())

        # Check output
        captured = capsys.readouterr()
        assert "eth0            : 192.168.1.100" in captured.out
        assert "wlan0           : 10.0.0.50" in captured.out

    def test_execute_nics_command_ipv4_empty_fallback_to_ipv6(
        self, monkeypatch, capsys
    ):
        # Mock get_host_ip_addresses to return only IPv6 data
        ipv6_data = [("eth0", "fe80::1234"), ("wlan0", "fe80::5678")]
        monkeypatch.setattr(
            "holoscan_cli.nics.nics.get_host_ip_addresses", lambda: ([], ipv6_data)
        )

        # Execute command
        execute_nics_command(Namespace())

        # Check output
        captured = capsys.readouterr()
        assert "eth0            : fe80::1234" in captured.out
        assert "wlan0           : fe80::5678" in captured.out

    def test_execute_nics_command_error_handling(self, monkeypatch, capsys):
        # Mock get_host_ip_addresses to raise an exception
        def mock_get_host_ip_addresses():
            raise Exception("Network error")

        monkeypatch.setattr(
            "holoscan_cli.nics.nics.get_host_ip_addresses", mock_get_host_ip_addresses
        )

        # Mock sys.exit to prevent actual exit
        mock_exit_calls = []

        def mock_exit(code):
            mock_exit_calls.append(code)

        monkeypatch.setattr(sys, "exit", mock_exit)

        # Mock logger to capture error message
        mock_error_messages = []

        def mock_error(msg):
            mock_error_messages.append(msg)

        monkeypatch.setattr(logging.getLogger("nics"), "error", mock_error)

        # Execute command
        execute_nics_command(Namespace())

        # Check error handling
        assert mock_exit_calls == [4]
        assert "Error executing nics command." in mock_error_messages

    def test_execute_nics_command_empty_addresses(self, monkeypatch, capsys):
        # Mock get_host_ip_addresses to return empty data
        monkeypatch.setattr(
            "holoscan_cli.nics.nics.get_host_ip_addresses", lambda: ([], [])
        )

        # Execute command
        execute_nics_command(Namespace())

        # Check output
        captured = capsys.readouterr()
        assert "Available network interface cards/IP addresses" in captured.out
        # Should print empty list since no addresses found
        assert captured.out.strip().endswith(":")
