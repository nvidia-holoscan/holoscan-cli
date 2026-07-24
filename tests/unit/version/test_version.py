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

import importlib.metadata
import json
from argparse import Namespace
from pathlib import Path

from holoscan_cli.version.version import execute_version_command, get_package_version


def test_get_package_version_from_package_metadata(monkeypatch):
    monkeypatch.setattr(
        "holoscan_cli.version.version.importlib.metadata.version",
        lambda package: "1.2.3" if package == "holoscan-cli" else None,
    )

    assert get_package_version() == "1.2.3"


def test_get_package_version_source_tree_fallback(monkeypatch):
    def raise_not_found(package):
        raise importlib.metadata.PackageNotFoundError(package)

    monkeypatch.setattr("holoscan_cli.version.version.importlib.metadata.version", raise_not_found)
    monkeypatch.setattr("holoscan_cli.version.version.__version__", "0.0.0+test")

    assert get_package_version() == "0.0.0+test"


def test_execute_version_command_reports_package_and_paths(monkeypatch, capsys):
    monkeypatch.setattr("holoscan_cli.version.version.get_package_version", lambda: "1.2.3")

    execute_version_command(Namespace())

    output = capsys.readouterr().out
    assert "Package:     holoscan-cli" in output
    assert "Version:     1.2.3" in output
    assert f"Module:      {Path('src/holoscan_cli/version/version.py').resolve()}" in output
    assert "Holoscan SDK:" not in output
    assert "MONAI Deploy App SDK:" not in output


def test_execute_version_command_json_round_trips(monkeypatch, capsys):
    monkeypatch.setattr("holoscan_cli.version.version.get_package_version", lambda: "1.2.3")

    execute_version_command(Namespace(json=True))

    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1
    assert data["package"] == "holoscan-cli"
    assert data["version"] == "1.2.3"
    assert data["module"] == str(Path("src/holoscan_cli/version/version.py").resolve())
