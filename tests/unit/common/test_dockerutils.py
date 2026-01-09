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

import os
import subprocess
from pathlib import Path

import pytest
from holoscan_cli.common.dockerutils import (
    create_or_use_network,
    image_exists,
    create_and_get_builder,
    docker_export_tarball,
    build_docker_image,
    _host_is_native_igpu,
    _additional_devices_to_mount,
    parse_docker_image_name_and_tag,
    docker_run,
)
from holoscan_cli.common.exceptions import RunContainerError, GpuResourceError
from holoscan_cli.common.constants import EnvironmentVariables
from holoscan_cli.common.enum_types import PlatformConfiguration, SdkType


@pytest.fixture
def mock_docker(monkeypatch):
    class MockDocker:
        def __init__(self):
            self.network = self.MockNetwork()
            self.image = self.MockImage()
            self.buildx = self.MockBuildx()

        class MockNetwork:
            def __init__(self):
                self.networks = []
                self.should_raise_list = False
                self.should_raise_create = False

            def list(self, filters=None):
                if self.should_raise_list:
                    raise Exception("Network error")
                return self.networks

            def create(self, name, driver=None):
                if self.should_raise_create:
                    raise Exception("Creation error")
                network = type("Network", (), {"name": name})()
                self.networks.append(network)
                return network

        class MockImage:
            def __init__(self):
                self.images = {}
                self.should_raise = False

            def exists(self, name):
                if self.should_raise:
                    raise Exception("Docker error")
                return name in self.images

            def pull(self, name):
                self.images[name] = True

            def save(self, tag, file):
                pass

        class MockBuildx:
            def __init__(self):
                self.builders = []

            def list(self):
                return self.builders

            def create(self, name, driver=None, driver_options=None):
                builder = type("Builder", (), {"name": name})()
                self.builders.append(builder)
                return builder

    mock = MockDocker()
    monkeypatch.setattr("holoscan_cli.common.dockerutils.docker", mock)
    return mock


class TestParseDockerImageNameAndTag:
    @pytest.mark.parametrize(
        "image_name,expected_name,expected_tag",
        [
            ("holoscan", "holoscan", None),
            ("holoscan:1.0", "holoscan", "1.0"),
            ("holoscan:latest", "holoscan", "latest"),
            ("_/holoscan", "_/holoscan", None),
            ("_/holoscan:latest", "_/holoscan", "latest"),
            ("my/holoscan:2.5", "my/holoscan", "2.5"),
            ("my/holoscan:latest", "my/holoscan", "latest"),
            (
                "localhost:5000/holoscan/holoscan-sdk/dev",
                "localhost:5000/holoscan/holoscan-sdk/dev",
                None,
            ),
            (
                "localhost:5000/holoscan/holoscan-sdk/dev:089167e159571cb3cef625a8b6b1011094c1b292",
                "localhost:5000/holoscan/holoscan-sdk/dev",
                "089167e159571cb3cef625a8b6b1011094c1b292",
            ),
            ("holoscan-sdk/dev", "holoscan-sdk/dev", None),
            ("holoscan-sdk/dev:100", "holoscan-sdk/dev", "100"),
            (
                "holoscan/holoscan-sdk/dev:089167e159571cb3cef625a8b6b1011094c1b292",
                "holoscan/holoscan-sdk/dev",
                "089167e159571cb3cef625a8b6b1011094c1b292",
            ),
            (":", None, None),
            (":latest", None, None),
            (":1.0", None, None),
            ("my-image:1.0:beta", None, None),
        ],
    )
    def test_parsing_docker_name_tags(self, image_name, expected_name, expected_tag):
        name, tag = parse_docker_image_name_and_tag(image_name)
        assert name == expected_name
        assert tag == expected_tag


class TestCreateOrUseNetwork:
    def test_create_network_when_not_exists(self, mock_docker):
        network = create_or_use_network("test-network", None)
        assert network == "test-network"
        assert len(mock_docker.network.networks) == 1
        assert mock_docker.network.networks[0].name == "test-network"

    def test_use_existing_network(self, mock_docker):
        # Pre-create a network
        mock_docker.network.create("test-network", "bridge")
        network = create_or_use_network("test-network", None)
        assert network == "test-network"
        assert len(mock_docker.network.networks) == 1

    def test_generate_network_name_from_image(self, mock_docker):
        network = create_or_use_network(None, "myapp:latest")
        assert network == "myapp-network"
        assert len(mock_docker.network.networks) == 1
        assert mock_docker.network.networks[0].name == "myapp-network"

    def test_network_list_error(self, mock_docker):
        mock_docker.network.should_raise_list = True
        with pytest.raises(RunContainerError) as exc_info:
            create_or_use_network("test-network", None)
        assert "error retrieving network information" in str(exc_info.value)

    def test_network_create_error(self, mock_docker):
        # First allow list to succeed, then fail on create
        mock_docker.network.should_raise_list = False
        mock_docker.network.networks = []  # No existing networks
        mock_docker.network.should_raise_create = True
        with pytest.raises(RunContainerError) as exc_info:
            create_or_use_network("test-network", None)
        assert "error creating Docker network" in str(exc_info.value)


class TestImageExists:
    def test_image_exists_true(self, mock_docker):
        mock_docker.image.images["test-image:latest"] = True
        assert image_exists("test-image:latest") is True

    def test_image_exists_false_but_pulls_successfully(self, mock_docker):
        assert image_exists("test-image:latest") is True
        assert "test-image:latest" in mock_docker.image.images

    def test_image_exists_none(self, mock_docker):
        assert image_exists(None) is False

    def test_image_exists_error(self, mock_docker):
        mock_docker.image.should_raise = True
        assert image_exists("test-image:latest") is False


class TestCreateAndGetBuilder:
    def test_use_existing_builder(self, mock_docker):
        # Pre-create a builder
        mock_docker.buildx.create("test-builder", "docker-container")
        builder = create_and_get_builder("test-builder")
        assert builder == "test-builder"
        assert len(mock_docker.buildx.builders) == 1

    def test_create_new_builder(self, mock_docker):
        builder = create_and_get_builder("test-builder")
        assert builder == "test-builder"
        assert len(mock_docker.buildx.builders) == 1
        assert mock_docker.buildx.builders[0].name == "test-builder"


class TestDockerExportTarball:
    def test_export_tarball(self, mock_docker):
        docker_export_tarball("test.tar", "test-image:latest")
        # Since we can't easily verify the file was saved, we just ensure no exception is raised


class TestBuildDockerImage:
    def test_build_docker_image(self, mock_docker):
        # Mock buildx.build method
        mock_docker.buildx.build = lambda **kwargs: None

        # Test that build_docker_image calls docker.buildx.build
        build_docker_image(path=".", tags=["test-image:latest"])
        # Since we can't easily verify the build was called with correct args,
        # we just ensure no exception is raised


class TestHostIsNativeIGPU:
    def test_host_is_native_igpu_true(self, monkeypatch):
        def mock_run(*args, **kwargs):
            return type("Process", (), {"stdout": b"nvgpu"})()

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert _host_is_native_igpu() is True

    def test_host_is_native_igpu_false(self, monkeypatch):
        def mock_run(*args, **kwargs):
            return type("Process", (), {"stdout": b"NVIDIA A100"})()

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert _host_is_native_igpu() is False


class TestAdditionalDevicesToMount:
    def test_igpu_devices_non_root(self, monkeypatch):
        def mock_exists(path):
            return True

        def mock_run_cmd(*args, **kwargs):
            return "video:x:44" if "video" in args[1] else "render:x:109"

        monkeypatch.setattr(os.path, "exists", mock_exists)
        monkeypatch.setattr(
            "holoscan_cli.common.dockerutils.run_cmd_output", mock_run_cmd
        )

        devices, group_adds = _additional_devices_to_mount(is_root=False)
        assert devices == []
        assert group_adds == ["44", "109"]

    def test_igpu_devices_root(self, monkeypatch):
        def mock_exists(path):
            return True

        monkeypatch.setattr(os.path, "exists", mock_exists)

        devices, group_adds = _additional_devices_to_mount(is_root=True)
        assert devices == []
        assert group_adds == []

    def test_no_igpu_devices(self, monkeypatch):
        def mock_exists(path):
            return False

        monkeypatch.setattr(os.path, "exists", mock_exists)

        devices, group_adds = _additional_devices_to_mount(is_root=False)
        assert devices == []
        assert group_adds == []


class TestDockerRun:
    @pytest.fixture
    def mock_container(self):
        class MockContainer:
            def __init__(self):
                self.name = "test-container"
                self.id = "123456789abc"
                self.config = type(
                    "Config",
                    (),
                    {
                        "hostname": "test-host",
                        "user": "test-user",
                    },
                )()
                self.host_config = type(
                    "HostConfig",
                    (),
                    {
                        "ulimits": [
                            type(
                                "Ulimit",
                                (),
                                {"name": "memlock", "soft": -1, "hard": -1},
                            )(),
                            type(
                                "Ulimit",
                                (),
                                {"name": "stack", "soft": 67108864, "hard": 67108864},
                            )(),
                        ],
                        "cap_add": ["CAP_SYS_PTRACE"],
                        "ipc_mode": "host",
                        "shm_size": "1GB",
                    },
                )()
                self.state = type("State", (), {"exit_code": 0})()

            def start(self, attach=False, stream=False):
                if stream:
                    return [
                        ("stdout", b"Starting container...\n"),
                        ("stderr", b"Some warning...\n"),
                        ("stdout", b"Container started\n"),
                    ]
                return None

        return MockContainer

    @pytest.fixture
    def basic_app_info(self):
        return {
            "input": {"path": "/input"},
            "output": {"path": "/output"},
            "workingDirectory": "/app",
            "environment": {
                EnvironmentVariables.HOLOSCAN_INPUT_PATH: "/input",
                EnvironmentVariables.HOLOSCAN_OUTPUT_PATH: "/output",
            },
        }

    @pytest.fixture
    def basic_pkg_info(self):
        return {"resources": {"gpu": 1}}

    @pytest.fixture
    def mock_dockerutils(self, monkeypatch):
        monkeypatch.setattr(
            "holoscan_cli.common.dockerutils.run_cmd_output",
            lambda *args, **kwargs: "video:x:44",
        )
        monkeypatch.setattr(
            "holoscan_cli.common.dockerutils._host_is_native_igpu", lambda: False
        )
        monkeypatch.setattr("holoscan_cli.common.dockerutils.get_gpu_count", lambda: 1)

    def test_basic_container_run(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_default_paths(
        self,
        mock_docker,
        mock_container,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        # App info without input/output path specified (should trigger lines 275, 285)
        app_info_no_paths = {
            "input": {},  # No "path" key
            "output": {},  # No "path" key
            "workingDirectory": "/app",
            "environment": {
                EnvironmentVariables.HOLOSCAN_INPUT_PATH: "/input",
                EnvironmentVariables.HOLOSCAN_OUTPUT_PATH: "/output",
            },
        }

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=app_info_no_paths,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_stderr_decode_error(
        self,
        mock_docker,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container with stderr decoding error (lines 445-446)
        class MockContainerWithBadStderr:
            def __init__(self):
                self.name = "test-container"
                self.id = "123456789abc"
                self.config = type(
                    "Config",
                    (),
                    {
                        "hostname": "test-host",
                        "user": "test-user",
                    },
                )()
                self.host_config = type(
                    "HostConfig",
                    (),
                    {
                        "ulimits": [
                            type(
                                "Ulimit",
                                (),
                                {"name": "memlock", "soft": -1, "hard": -1},
                            )(),
                        ],
                        "cap_add": ["CAP_SYS_PTRACE"],
                        "ipc_mode": "host",
                        "shm_size": "1GB",
                    },
                )()
                self.state = type("State", (), {"exit_code": 0})()

            def start(self, attach=False, stream=False):
                # Return bad stderr that can't be decoded as UTF-8
                return [("stderr", b"\xff\xfe")]  # Invalid UTF-8

            def remove(self):
                pass

        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: MockContainerWithBadStderr(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_remove_true(
        self,
        mock_docker,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container that tests remove=True (line 454)
        class MockContainerWithRemove:
            def __init__(self):
                self.name = "test-container"
                self.id = "123456789abc"
                self.config = type(
                    "Config",
                    (),
                    {
                        "hostname": "test-host",
                        "user": "test-user",
                    },
                )()
                self.host_config = type(
                    "HostConfig",
                    (),
                    {
                        "ulimits": [],
                        "cap_add": ["CAP_SYS_PTRACE"],
                        "ipc_mode": "host",
                        "shm_size": "1GB",
                    },
                )()
                self.state = type("State", (), {"exit_code": 0})()

            def start(self, attach=False, stream=False):
                return []

            def remove(self):
                pass

        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: MockContainerWithRemove(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=True,  # This should trigger line 454
        )

    def test_container_run_with_non_zero_exit_code(
        self,
        mock_docker,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container with non-zero exit code (line 457)
        class MockContainerWithError:
            def __init__(self):
                self.name = "test-container"
                self.id = "123456789abc"
                self.config = type(
                    "Config",
                    (),
                    {
                        "hostname": "test-host",
                        "user": "test-user",
                    },
                )()
                self.host_config = type(
                    "HostConfig",
                    (),
                    {
                        "ulimits": [],
                        "cap_add": ["CAP_SYS_PTRACE"],
                        "ipc_mode": "host",
                        "shm_size": "1GB",
                    },
                )()
                self.state = type("State", (), {"exit_code": 1})()  # Non-zero exit code

            def start(self, attach=False, stream=False):
                return []

            def remove(self):
                pass

        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: MockContainerWithError(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        with pytest.raises(RuntimeError) as exc_info:
            docker_run(
                name="test-container",
                image_name="test-image:latest",
                input_path=Path("/host/input"),
                output_path=Path("/host/output"),
                app_info=basic_app_info,
                pkg_info=basic_pkg_info,
                quiet=False,
                commands=[],
                health_check=False,
                network="test-network",
                network_interface=None,
                use_all_nics=False,
                gpu_enum=None,
                config=None,
                render=False,
                user="1000:1000",
                terminal=False,
                devices=[],
                platform_config=PlatformConfiguration.dGPU.value,
                shared_memory_size="1GB",
                is_root=False,
                remove=False,
            )
        assert "exited with code 1" in str(exc_info.value)

    def test_container_run_with_igpu(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.iGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_render(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        # Mock environment variables
        mock_env = {
            "DISPLAY": ":0",
            "XDG_SESSION_TYPE": "x11",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "WAYLAND_DISPLAY": "wayland-0",
        }
        monkeypatch.setattr(os, "environ", mock_env)

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=True,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_terminal(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=True,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_gpu_resource_error(
        self, mock_docker, mock_container, basic_app_info, mock_dockerutils, monkeypatch
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        pkg_info = {"resources": {"gpu": 2}}  # Requesting more GPUs than available

        with pytest.raises(GpuResourceError) as exc_info:
            docker_run(
                name="test-container",
                image_name="test-image:latest",
                input_path=Path("/host/input"),
                output_path=Path("/host/output"),
                app_info=basic_app_info,
                pkg_info=pkg_info,
                quiet=False,
                commands=[],
                health_check=False,
                network="test-network",
                network_interface=None,
                use_all_nics=False,
                gpu_enum=None,
                config=None,
                render=False,
                user="1000:1000",
                terminal=False,
                devices=[],
                platform_config=PlatformConfiguration.dGPU.value,
                shared_memory_size="1GB",
                is_root=False,
                remove=False,
            )
        assert "Available GPUs (1) are less than required (2)" in str(exc_info.value)

    def test_container_run_with_holoscan_config(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        # Add Holoscan SDK type and config path
        app_info_with_sdk = basic_app_info.copy()
        app_info_with_sdk["sdk"] = SdkType.Holoscan.value
        app_info_with_sdk["environment"][EnvironmentVariables.HOLOSCAN_CONFIG_PATH] = (
            "/app/config.yaml"
        )

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=app_info_with_sdk,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=Path("/host/config.yaml"),
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_network_interface(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface="eth0",  # This should trigger line 213
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_health_check(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=True,  # This should trigger line 216
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_debug_logging(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        # Mock logger to be at DEBUG level
        import logging

        monkeypatch.setattr(logging.getLogger("common").root, "level", logging.DEBUG)

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_gpu_enum(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        basic_pkg_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=basic_pkg_info,
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum="0,1",  # This should trigger line 240
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )

    def test_container_run_with_zero_gpus(
        self,
        mock_docker,
        mock_container,
        basic_app_info,
        mock_dockerutils,
        monkeypatch,
    ):
        # Setup container creation mock
        mock_docker.container = type(
            "Container",
            (),
            {
                "create": lambda *args, **kwargs: mock_container(),
                "run": lambda *args, **kwargs: None,
            },
        )()

        # Package info requesting 0 GPUs
        pkg_info_zero_gpus = {"resources": {"gpu": 0}}

        docker_run(
            name="test-container",
            image_name="test-image:latest",
            input_path=Path("/host/input"),
            output_path=Path("/host/output"),
            app_info=basic_app_info,
            pkg_info=pkg_info_zero_gpus,  # This should trigger line 266
            quiet=False,
            commands=[],
            health_check=False,
            network="test-network",
            network_interface=None,
            use_all_nics=False,
            gpu_enum=None,
            config=None,
            render=False,
            user="1000:1000",
            terminal=False,
            devices=[],
            platform_config=PlatformConfiguration.dGPU.value,
            shared_memory_size="1GB",
            is_root=False,
            remove=False,
        )
