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
import json
import os
import sys
from argparse import Namespace
from pathlib import Path
import pytest

from holoscan_cli.common.exceptions import ManifestReadError, UnmatchedDeviceError
from holoscan_cli.runner.runner import (
    _fetch_map_manifest,
    _run_app,
    _lookup_devices,
    _dependency_verification,
    _pkg_specific_dependency_verification,
    execute_run_command,
)


class TestFetchMapManifest:
    def ensure_tmp_path(self, tmp_path):
        if not tmp_path.exists():
            tmp_path.mkdir(parents=True, exist_ok=True)

    def test_fetch_map_manifest_success(self, monkeypatch, tmp_path):
        self.ensure_tmp_path(tmp_path)

        # Mock successful docker commands
        def mock_run_cmd_output(*args, **kwargs):
            return "container123"

        def mock_run_cmd(*args, **kwargs):
            # Simulate copying files by creating them
            if f"{tmp_path}/app.json" in args[0]:
                json.dump({"app": "test"}, open(f"{tmp_path}/app.json", "w"))
                assert os.path.exists(f"{tmp_path}/app.json")
            elif f"{tmp_path}/pkg.json" in args[0]:
                json.dump({"pkg": "test"}, open(f"{tmp_path}/pkg.json", "w"))
                assert os.path.exists(f"{tmp_path}/pkg.json")
            return 0

        monkeypatch.setattr(
            "holoscan_cli.runner.runner.run_cmd_output", mock_run_cmd_output
        )
        monkeypatch.setattr("holoscan_cli.runner.runner.run_cmd", mock_run_cmd)
        monkeypatch.setattr(
            "tempfile.TemporaryDirectory.__enter__", lambda x: str(tmp_path)
        )

        app_info, pkg_info = _fetch_map_manifest("test-map:latest")
        assert app_info == {"app": "test"}
        assert pkg_info == {"pkg": "test"}

    def test_fetch_map_manifest_docker_error(self, monkeypatch):
        def mock_run_cmd(*args, **kwargs):
            return 1

        monkeypatch.setattr("holoscan_cli.runner.runner.run_cmd", mock_run_cmd)

        with pytest.raises(ManifestReadError):
            _fetch_map_manifest("test-map:latest")


class TestRunApp:
    def test_run_app_driver_mode(self, monkeypatch):
        calls = []

        def mock_docker_run(*args, **kwargs):
            calls.append(args)

        monkeypatch.setattr("holoscan_cli.runner.runner.docker_run", mock_docker_run)
        monkeypatch.setattr(
            "holoscan_cli.runner.runner.create_or_use_network",
            lambda x, y: "test-network",
        )

        args = Namespace(
            map="test-map:latest",
            input=Path("/input"),
            output=Path("/output"),
            quiet=False,
            driver=True,
            worker=False,
            health_check=False,
            fragments="fragment1,fragment2",
            network="test-network",
            nic=None,
            use_all_nics=False,
            gpus=None,
            config=None,
            address=":8888",
            worker_address=":9999",
            render=False,
            uid=1000,
            gid=1000,
            terminal=False,
            device=None,
            shm_size=None,
        )

        app_info = {"app": "test"}
        pkg_info = {"pkg": "test"}

        _run_app(args, app_info, pkg_info)

        assert len(calls) == 1
        assert calls[0][0] == "driver"
        assert "--driver" in calls[0][7]
        assert args.fragments in calls[0][7]
        assert args.address in calls[0][7]
        assert args.worker_address in calls[0][7]

    def test_run_app_worker_mode(self, monkeypatch):
        calls = []

        def mock_docker_run(*args, **kwargs):
            calls.append(args)

        monkeypatch.setattr("holoscan_cli.runner.runner.docker_run", mock_docker_run)
        monkeypatch.setattr(
            "holoscan_cli.runner.runner.create_or_use_network",
            lambda x, y: "test-network",
        )

        args = Namespace(
            map="test-map:latest",
            input=Path("/input"),
            output=Path("/output"),
            quiet=False,
            driver=False,
            worker=True,
            health_check=False,
            fragments="fragment",
            network="test-network",
            nic=None,
            use_all_nics=False,
            gpus=None,
            config=None,
            address=None,
            worker_address=None,
            render=False,
            uid=1000,
            gid=1000,
            terminal=False,
            device=None,
            shm_size=None,
        )

        app_info = {"app": "test"}
        pkg_info = {"pkg": "test"}

        _run_app(args, app_info, pkg_info)

        assert len(calls) == 1
        assert calls[0][0] is None
        assert "--worker" in calls[0][7]
        assert args.fragments in calls[0][7]


class TestLookupDevices:
    def test_lookup_devices_found(self, monkeypatch):
        def mock_glob(pattern):
            if pattern == "/dev/video0":
                return ["/dev/video0"]
            return []

        monkeypatch.setattr("holoscan_cli.runner.runner.glob", mock_glob)

        devices = _lookup_devices(["video0"])
        assert devices == ["/dev/video0"]

    def test_lookup_devices_not_found(self, monkeypatch):
        def mock_glob(pattern):
            return []

        monkeypatch.setattr("holoscan_cli.runner.runner.glob", mock_glob)

        with pytest.raises(UnmatchedDeviceError):
            _lookup_devices(["nonexistent"])

    def test_lookup_devices_with_wildcards(self, monkeypatch):
        def mock_glob(pattern):
            if pattern == "/dev/video*":
                return ["/dev/video0", "/dev/video1"]
            return []

        monkeypatch.setattr("holoscan_cli.runner.runner.glob", mock_glob)

        devices = _lookup_devices(["video*"])
        assert devices == ["/dev/video0", "/dev/video1"]


class TestDependencyVerification:
    def test_dependency_verification_success(self, monkeypatch):
        def mock_which(prog):
            return True

        def mock_image_exists(name):
            return True

        monkeypatch.setattr("holoscan_cli.runner.runner.shutil.which", mock_which)
        monkeypatch.setattr(
            "holoscan_cli.runner.runner.image_exists", mock_image_exists
        )

        assert _dependency_verification("test-map:latest") is True

    def test_dependency_verification_missing_docker(self, monkeypatch):
        def mock_which(prog):
            return False if prog == "docker" else True

        monkeypatch.setattr("holoscan_cli.runner.runner.shutil.which", mock_which)

        assert _dependency_verification("test-map:latest") is False

    def test_dependency_verification_missing_buildx(self, monkeypatch):
        def mock_which(prog):
            return False if "docker-buildx" in prog else True

        monkeypatch.setattr("holoscan_cli.runner.runner.shutil.which", mock_which)
        monkeypatch.setattr("holoscan_cli.runner.runner.os.path.join", lambda x, y: y)

        assert _dependency_verification("test-map:latest") is False


class TestPkgSpecificDependencyVerification:
    def test_pkg_specific_verification_no_gpu(self, monkeypatch):
        pkg_info = {"resources": {"gpu": 0}}
        assert _pkg_specific_dependency_verification(pkg_info) is True

    def test_pkg_specific_verification_with_gpu_success(self, monkeypatch):
        def mock_which(prog):
            return True

        def mock_run_cmd_output(*args, **kwargs):
            return "version 1.14.1"

        monkeypatch.setattr("holoscan_cli.runner.runner.shutil.which", mock_which)
        monkeypatch.setattr(
            "holoscan_cli.runner.runner.run_cmd_output", mock_run_cmd_output
        )

        pkg_info = {"resources": {"gpu": 1}}
        assert _pkg_specific_dependency_verification(pkg_info) is True

    def test_pkg_specific_verification_with_gpu_old_version(self, monkeypatch):
        def mock_which(prog):
            return True

        def mock_run_cmd_output(*args, **kwargs):
            return "version 1.11.0"

        monkeypatch.setattr("holoscan_cli.runner.runner.shutil.which", mock_which)
        monkeypatch.setattr(
            "holoscan_cli.runner.runner.run_cmd_output", mock_run_cmd_output
        )

        pkg_info = {"resources": {"gpu": 1}}
        assert _pkg_specific_dependency_verification(pkg_info) is False


class TestExecuteRunCommand:
    def test_execute_run_command_success(self, monkeypatch):
        def mock_dependency_verification(*args):
            return True

        def mock_fetch_map_manifest(*args):
            return {"app": "test"}, {"pkg": "test"}

        def mock_pkg_specific_dependency_verification(*args):
            return True

        def mock_run_app(*args):
            pass

        monkeypatch.setattr(
            "holoscan_cli.runner.runner._dependency_verification",
            mock_dependency_verification,
        )
        monkeypatch.setattr(
            "holoscan_cli.runner.runner._fetch_map_manifest", mock_fetch_map_manifest
        )
        monkeypatch.setattr(
            "holoscan_cli.runner.runner._pkg_specific_dependency_verification",
            mock_pkg_specific_dependency_verification,
        )
        monkeypatch.setattr("holoscan_cli.runner.runner._run_app", mock_run_app)

        args = Namespace(map="test-map:latest")
        execute_run_command(args)

    def test_execute_run_command_dependency_failure(self, monkeypatch):
        def mock_dependency_verification(*args):
            return False

        monkeypatch.setattr(
            "holoscan_cli.runner.runner._dependency_verification",
            mock_dependency_verification,
        )

        # Mock sys.exit to prevent actual exit
        exit_calls = []

        def mock_exit(code):
            exit_calls.append(code)
            raise SystemExit(code)

        monkeypatch.setattr(sys, "exit", mock_exit)

        args = Namespace(map="test-map:latest")
        with pytest.raises(SystemExit) as _:
            execute_run_command(args)

        assert exit_calls == [2]

    def test_execute_run_command_manifest_error(self, monkeypatch):
        def mock_dependency_verification(*args):
            return True

        def mock_fetch_map_manifest(*args):
            raise Exception("Manifest error")

        monkeypatch.setattr(
            "holoscan_cli.runner.runner._dependency_verification",
            mock_dependency_verification,
        )
        monkeypatch.setattr(
            "holoscan_cli.runner.runner._fetch_map_manifest", mock_fetch_map_manifest
        )

        # Mock sys.exit to prevent actual exit
        exit_calls = []

        def mock_exit(code):
            exit_calls.append(code)
            raise SystemExit(code)

        monkeypatch.setattr(sys, "exit", mock_exit)

        args = Namespace(map="test-map:latest")
        with pytest.raises(SystemExit) as _:
            execute_run_command(args)

        assert exit_calls == [2]
