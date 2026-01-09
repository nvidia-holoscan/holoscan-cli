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

import platform as platform_lib
import tempfile
from argparse import Namespace
from pathlib import Path

import pytest
from holoscan_cli.common.artifact_sources import ArtifactSources
from holoscan_cli.common.constants import SDK
from holoscan_cli.common.enum_types import ApplicationType
from holoscan_cli.common.enum_types import Platform as PlatformTypes
from holoscan_cli.common.enum_types import PlatformConfiguration, SdkType
from holoscan_cli.common.exceptions import IncompatiblePlatformConfigurationError
from holoscan_cli.packager.platforms import Platform
from packaging.version import Version


class TestPlatforms:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch) -> None:
        self._artifact_source = ArtifactSources(
            13
        )  # Default CUDA 13 for existing tests
        source_file_sample = Path(__file__).parent.parent.resolve() / "./artifacts.json"
        self._artifact_source.load(str(source_file_sample))

    def test_invalid_platform_options(self, monkeypatch):
        test_version = "1.0.0"
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk", lambda sdk: SdkType.Holoscan
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk_version",
            lambda sdk, sdk_version: (test_version, None),
        )

        application_verison = "1.0.0"
        input_args = Namespace()
        input_args.sdk = SdkType.Holoscan
        input_args.sdk_version = Version(test_version)
        input_args.platform = [PlatformTypes.IGXOrinDevIt, PlatformTypes.X64Workstation]
        input_args.holoscan_sdk_file = Path("some-random-file")
        input_args.cuda = 13

        platform = Platform(self._artifact_source)
        with (
            tempfile.TemporaryDirectory(
                prefix="holoscan_test", dir=tempfile.gettempdir()
            ) as temp_dir,
            pytest.raises(IncompatiblePlatformConfigurationError),
        ):
            platform.configure_platforms(
                input_args, temp_dir, application_verison, ApplicationType.CppCMake
            )

    def test_invalid_platform_options_holoscan_sdk_type_with_monai_deploy_sdk_file(
        self, monkeypatch
    ):
        test_version = "1.0.0"
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk", lambda sdk: SdkType.Holoscan
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk_version",
            lambda sdk, sdk_version: (test_version, None),
        )

        application_verison = "1.0.0"
        input_args = Namespace()
        input_args.sdk = SdkType.Holoscan
        input_args.sdk_version = Version(test_version)
        input_args.platform = [PlatformTypes.IGXOrinDevIt, PlatformTypes.X64Workstation]
        input_args.holoscan_sdk_file = None
        input_args.monai_deploy_sdk_file = Path("some-random-file")
        input_args.cuda = 13

        platform = Platform(self._artifact_source)
        with (
            tempfile.TemporaryDirectory(
                prefix="holoscan_test", dir=tempfile.gettempdir()
            ) as temp_dir,
            pytest.raises(IncompatiblePlatformConfigurationError),
        ):
            platform.configure_platforms(
                input_args, temp_dir, application_verison, ApplicationType.CppCMake
            )

    def test_single_platform_with_monai_deploy(self, monkeypatch):
        holoscan_version = "1.0.0"
        monai_deploy_version = "2.4.1"
        sdk_type = SdkType.MonaiDeploy
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk", lambda sdk: sdk_type
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk_version",
            lambda sdk, sdk_version: (
                holoscan_version,
                monai_deploy_version,
            ),
        )

        application_verison = "1.0.0"
        input_args = Namespace()
        input_args.sdk = SdkType.Holoscan
        input_args.platform = [PlatformTypes.IGX_dGPU]
        input_args.tag = "my-app"
        input_args.sdk_version = None
        input_args.holoscan_sdk_file = None
        input_args.monai_deploy_sdk_file = None
        input_args.base_image = None
        input_args.build_image = None
        input_args.cuda = 13

        platform = Platform(self._artifact_source)
        with tempfile.TemporaryDirectory(
            prefix="holoscan_test", dir=tempfile.gettempdir()
        ) as temp_dir:
            (sdk, hsdk_version, md_version, platforms) = platform.configure_platforms(
                input_args, temp_dir, application_verison, ApplicationType.PythonModule
            )

            assert sdk == sdk_type
            assert hsdk_version == holoscan_version
            assert md_version == monai_deploy_version
            assert len(platforms) == 1

            platform_parameters = platforms[0]
            assert (
                platform_parameters.platform
                == SDK.INTERNAL_PLATFORM_MAPPINGS[input_args.platform[0]][0]
            )
            assert (
                platform_parameters.base_image
                == self._artifact_source.base_image(holoscan_version)[
                    PlatformConfiguration.dGPU.value
                ]
            )
            assert platform_parameters.build_image is None
            assert (
                platform_parameters.tag
                == "my-app-igx-orin-devkit-dgpu-linux-arm64:1.0.0"
            )
            assert platform_parameters.tag_prefix == "my-app"
            assert platform_parameters.custom_base_image is False
            assert platform_parameters.custom_holoscan_sdk is False
            assert (
                platform_parameters.holoscan_sdk_file
                == self._artifact_source.wheel_package_version(holoscan_version)
            )
            assert platform_parameters.custom_monai_deploy_sdk is False
            assert platform_parameters.monai_deploy_sdk_file is None
            assert platform_parameters.version == application_verison
            assert platform_parameters.health_probe is None
            assert (
                platform_parameters.platform_arch
                == SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]]
            )
            assert (
                platform_parameters.docker_arch
                == SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]].value
            )
            assert platform_parameters.same_arch_as_system == (
                platform_lib.machine() == "aarch64"
            )
            assert platform_parameters.cuda_deb_arch == "sbsa"
            assert platform_parameters.holoscan_deb_arch == "arm64"
            assert platform_parameters.target_arch == "aarch64"

    def test_single_platform_with_monai_deploy_using_custom_sdk(self, monkeypatch):
        holoscan_version = "1.0.0"
        monai_deploy_version = "2.4.1"
        sdk_type = SdkType.MonaiDeploy
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk", lambda sdk: sdk_type
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk_version",
            lambda sdk, sdk_version: (
                holoscan_version,
                monai_deploy_version,
            ),
        )

        application_verison = "1.0.0"
        input_args = Namespace()
        input_args.sdk = SdkType.Holoscan
        input_args.platform = [PlatformTypes.IGX_iGPU]
        input_args.tag = "my-app"
        input_args.sdk_version = None
        input_args.holoscan_sdk_file = None
        input_args.monai_deploy_sdk_file = Path("my-monai-deploy-sdk.whl")
        input_args.base_image = None
        input_args.build_image = None
        input_args.cuda = 13

        platform = Platform(self._artifact_source)
        with tempfile.TemporaryDirectory(
            prefix="holoscan_test", dir=tempfile.gettempdir()
        ) as temp_dir:
            (sdk, hsdk_version, md_version, platforms) = platform.configure_platforms(
                input_args, temp_dir, application_verison, ApplicationType.PythonModule
            )

            assert sdk == sdk_type
            assert hsdk_version == holoscan_version
            assert md_version == monai_deploy_version
            assert len(platforms) == 1

            platform_parameters = platforms[0]

            assert (
                platform_parameters.platform
                == SDK.INTERNAL_PLATFORM_MAPPINGS[input_args.platform[0]][0]
            )
            assert (
                platform_parameters.base_image
                == self._artifact_source.base_image(holoscan_version)[
                    PlatformConfiguration.iGPU.value
                ]
            )
            assert platform_parameters.build_image is None
            assert (
                platform_parameters.tag
                == "my-app-igx-orin-devkit-igpu-linux-arm64:1.0.0"
            )
            assert platform_parameters.tag_prefix == "my-app"
            assert platform_parameters.custom_base_image is False
            assert platform_parameters.custom_holoscan_sdk is False
            assert (
                platform_parameters.holoscan_sdk_file
                == self._artifact_source.wheel_package_version(holoscan_version)
            )
            assert platform_parameters.custom_monai_deploy_sdk is True
            assert (
                platform_parameters.monai_deploy_sdk_file
                == input_args.monai_deploy_sdk_file
            )
            assert platform_parameters.version == application_verison
            assert platform_parameters.health_probe is None
            assert (
                platform_parameters.platform_arch
                == SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]]
            )
            assert (
                platform_parameters.docker_arch
                == SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]].value
            )
            assert platform_parameters.same_arch_as_system == (
                platform_lib.machine() == "aarch64"
            )
            assert platform_parameters.cuda_deb_arch == "sbsa"
            assert platform_parameters.holoscan_deb_arch == "arm64"
            assert platform_parameters.target_arch == "aarch64"

    def test_multiple_platforms(self, monkeypatch):
        holoscan_version = "1.0.0"
        monai_deploy_version = None
        sdk_type = SdkType.Holoscan
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk", lambda sdk: sdk_type
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk_version",
            lambda sdk, sdk_version: (
                holoscan_version,
                monai_deploy_version,
            ),
        )

        application_verison = "1.0.0"
        input_args = Namespace()
        input_args.sdk = SdkType.Holoscan
        input_args.platform = [
            PlatformTypes.Jetson,
            PlatformTypes.IGX_iGPU,
            PlatformTypes.SBSA,
        ]
        input_args.tag = "my-app"
        input_args.sdk_version = None
        input_args.holoscan_sdk_file = None
        input_args.monai_deploy_sdk_file = None
        input_args.base_image = None
        input_args.build_image = None
        input_args.cuda = 13

        platform = Platform(self._artifact_source)
        with tempfile.TemporaryDirectory(
            prefix="holoscan_test", dir=tempfile.gettempdir()
        ) as temp_dir:
            (sdk, hsdk_version, md_version, platforms) = platform.configure_platforms(
                input_args, temp_dir, application_verison, ApplicationType.CppCMake
            )

            assert len(platforms) == len(input_args.platform)
            for index, platform_parameters in enumerate(platforms):
                assert sdk == sdk_type
                assert hsdk_version == holoscan_version
                assert md_version == monai_deploy_version

                input_platform = input_args.platform[index]
                expected_platform = SDK.INTERNAL_PLATFORM_MAPPINGS[input_platform][0]
                expected_platform_config = SDK.INTERNAL_PLATFORM_MAPPINGS[
                    input_platform
                ][1]

                assert platform_parameters.platform == expected_platform
                assert (
                    platform_parameters.base_image
                    == self._artifact_source.base_image(holoscan_version)[
                        expected_platform_config.value
                    ]
                )
                assert (
                    platform_parameters.build_image
                    == f"nvcr.io/nvidia/clara-holoscan/holoscan:v1.0.0-{expected_platform_config.value}"
                )
                assert (
                    platform_parameters.tag
                    == f"my-app-{expected_platform.value}-{expected_platform_config.value}-linux-arm64:1.0.0"
                )
                assert platform_parameters.tag_prefix == "my-app"
                assert platform_parameters.custom_base_image is False
                assert platform_parameters.custom_holoscan_sdk is False
                assert (
                    platform_parameters.holoscan_sdk_file
                    == self._artifact_source.debian_package_version(holoscan_version)
                )
                assert platform_parameters.custom_monai_deploy_sdk is None
                assert platform_parameters.monai_deploy_sdk_file is None
                assert platform_parameters.version == application_verison
                assert (
                    platform_parameters.health_probe
                    == self._artifact_source.health_probe(holoscan_version)[
                        SDK.PLATFORM_ARCH_MAPPINGS[input_platform].value
                    ]
                )
                assert (
                    platform_parameters.platform_arch
                    == SDK.PLATFORM_ARCH_MAPPINGS[input_platform]
                )
                assert (
                    platform_parameters.docker_arch
                    == SDK.PLATFORM_ARCH_MAPPINGS[input_platform].value
                )
                assert platform_parameters.same_arch_as_system == (
                    platform_lib.machine() == "aarch64"
                )
                assert platform_parameters.cuda_deb_arch == "sbsa"
                assert platform_parameters.holoscan_deb_arch == "arm64"
                assert platform_parameters.target_arch == "aarch64"

    def test_platform_with_custom_base_image_and_build_image(self, monkeypatch):
        holoscan_version = "1.0.0"
        monai_deploy_version = None
        sdk_type = SdkType.Holoscan
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk", lambda sdk: sdk_type
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk_version",
            lambda sdk, sdk_version: (
                holoscan_version,
                monai_deploy_version,
            ),
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.image_exists",
            lambda img: True,
        )

        application_verison = "1.0.0"
        input_args = Namespace()
        input_args.sdk = SdkType.Holoscan
        input_args.platform = [PlatformTypes.IGX_dGPU]
        input_args.tag = "my-app"
        input_args.sdk_version = None
        input_args.holoscan_sdk_file = None
        input_args.monai_deploy_sdk_file = None
        input_args.base_image = "my-base-image"
        input_args.build_image = "my-build-image"
        input_args.cuda = 13

        platform = Platform(self._artifact_source)
        with tempfile.TemporaryDirectory(
            prefix="holoscan_test", dir=tempfile.gettempdir()
        ) as temp_dir:
            (sdk, hsdk_version, md_version, platforms) = platform.configure_platforms(
                input_args, temp_dir, application_verison, ApplicationType.CppCMake
            )

            assert sdk == sdk_type
            assert hsdk_version == holoscan_version
            assert md_version == monai_deploy_version
            assert len(platforms) == 1

            platform_parameters = platforms[0]

            assert (
                platform_parameters.platform
                == SDK.INTERNAL_PLATFORM_MAPPINGS[input_args.platform[0]][0]
            )
            assert platform_parameters.base_image == input_args.base_image
            assert platform_parameters.build_image == input_args.build_image
            assert (
                platform_parameters.tag
                == "my-app-igx-orin-devkit-dgpu-linux-arm64:1.0.0"
            )
            assert platform_parameters.tag_prefix == "my-app"
            assert platform_parameters.custom_base_image is True
            assert platform_parameters.custom_holoscan_sdk is False
            assert (
                platform_parameters.holoscan_sdk_file
                == self._artifact_source.debian_package_version(holoscan_version)
            )
            assert platform_parameters.custom_monai_deploy_sdk is None
            assert platform_parameters.monai_deploy_sdk_file is None
            assert platform_parameters.version == application_verison
            assert (
                platform_parameters.health_probe
                == self._artifact_source.health_probe(holoscan_version)[
                    SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]].value
                ]
            )
            assert (
                platform_parameters.platform_arch
                == SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]]
            )
            assert (
                platform_parameters.docker_arch
                == SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]].value
            )
            assert platform_parameters.same_arch_as_system == (
                platform_lib.machine() == "aarch64"
            )
            assert platform_parameters.cuda_deb_arch == "sbsa"
            assert platform_parameters.holoscan_deb_arch == "arm64"
            assert platform_parameters.target_arch == "aarch64"

    def test_platform_with_custom_sdk_file(self, monkeypatch):
        holoscan_version = "1.0.0"
        monai_deploy_version = None
        sdk_type = SdkType.Holoscan
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk", lambda sdk: sdk_type
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.detect_sdk_version",
            lambda sdk, sdk_version: (
                holoscan_version,
                monai_deploy_version,
            ),
        )
        monkeypatch.setattr(
            "holoscan_cli.packager.platforms.image_exists",
            lambda img: True,
        )

        application_verison = "1.0.0"
        input_args = Namespace()
        input_args.sdk = SdkType.Holoscan
        input_args.platform = [PlatformTypes.IGX_iGPU]
        input_args.tag = "my-app"
        input_args.sdk_version = None
        input_args.holoscan_sdk_file = Path("my-sdk-file.deb")
        input_args.monai_deploy_sdk_file = None
        input_args.base_image = "my-base-image"
        input_args.build_image = "my-build-image"
        input_args.cuda = 13

        platform = Platform(self._artifact_source)
        with tempfile.TemporaryDirectory(
            prefix="holoscan_test", dir=tempfile.gettempdir()
        ) as temp_dir:
            (sdk, hsdk_version, md_version, platforms) = platform.configure_platforms(
                input_args, temp_dir, application_verison, ApplicationType.CppCMake
            )

            assert sdk == sdk_type
            assert hsdk_version == holoscan_version
            assert md_version == monai_deploy_version
            assert len(platforms) == 1

            platform_parameters = platforms[0]

            assert (
                platform_parameters.platform
                == SDK.INTERNAL_PLATFORM_MAPPINGS[input_args.platform[0]][0]
            )
            assert platform_parameters.base_image == input_args.base_image
            assert platform_parameters.build_image == input_args.build_image
            assert (
                platform_parameters.tag
                == "my-app-igx-orin-devkit-igpu-linux-arm64:1.0.0"
            )
            assert platform_parameters.tag_prefix == "my-app"
            assert platform_parameters.custom_base_image is True
            assert platform_parameters.custom_holoscan_sdk is True
            assert platform_parameters.holoscan_sdk_file == input_args.holoscan_sdk_file
            assert platform_parameters.custom_monai_deploy_sdk is None
            assert platform_parameters.monai_deploy_sdk_file is None
            assert platform_parameters.version == application_verison
            assert (
                platform_parameters.health_probe
                == self._artifact_source.health_probe(holoscan_version)[
                    SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]].value
                ]
            )
            assert (
                platform_parameters.platform_arch
                == SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]]
            )
            assert (
                platform_parameters.docker_arch
                == SDK.PLATFORM_ARCH_MAPPINGS[input_args.platform[0]].value
            )
            assert platform_parameters.same_arch_as_system == (
                platform_lib.machine() == "aarch64"
            )
            assert platform_parameters.cuda_deb_arch == "sbsa"
            assert platform_parameters.holoscan_deb_arch == "arm64"
            assert platform_parameters.target_arch == "aarch64"
