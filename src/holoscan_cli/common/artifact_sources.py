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
import logging
from typing import Any, Optional

import requests

from holoscan_cli import __version__
from packaging.version import InvalidVersion, Version

from .enum_types import PlatformConfiguration, SdkType
from .exceptions import InvalidSourceFileError, ManifestDownloadError


class ArtifactSources:
    """Provides default artifact source URLs with the ability to override."""

    SectionWheelVersion = "wheel-version"
    SectionDebianVersion = "debian-version"
    SectionBaseImages = "base-images"
    SectionBuildImages = "build-images"
    SectionHealthProbe = "health-probes"
    HoloscanVersion = None
    ManifestFileUrl = None

    def __init__(self) -> None:
        self._logger = logging.getLogger("common")
        try:
            ArtifactSources.HoloscanVersion = ".".join(
                str(i) for i in Version(__version__).release[0:3]
            )
        except InvalidVersion as ex:
            raise RuntimeError(
                "Unable to detect Holoscan version. Use --sdk-version to specify "
                "a Holoscan SDK version to use."
            ) from ex

        ArtifactSources.ManifestFileUrl = f"https://raw.githubusercontent.com/nvidia-holoscan/holoscan-cli/refs/heads/main/releases/{ArtifactSources.HoloscanVersion}/artifacts.json"  # noqa: E501

    @property
    def holoscan_versions(self) -> list[str]:
        # logic to dynamically fetch the supported versions
        return self._data.keys()

    def base_image(self, version) -> str:
        return self._data[version][SdkType.Holoscan.value][
            ArtifactSources.SectionBaseImages
        ]

    def build_images(self, version) -> dict[Any, str]:
        return self._data[version][SdkType.Holoscan.value][
            ArtifactSources.SectionBuildImages
        ]

    def health_probe(self, version) -> dict[Any, str]:
        return self._data[version][ArtifactSources.SectionHealthProbe]

    def load(self, uri: str):
        """Overrides the default values from a given JSON file.
           Validates top-level attributes to ensure the file is valid

        Args:
            file (Path): Path to JSON file
        """
        if uri.startswith("https"):
            self._download_manifest_internal(uri)
        elif uri.startswith("http"):
            raise ManifestDownloadError(
                "Downloading manifest files from non-HTTPS servers is not supported."
            )
        else:
            self._logger.info(f"Using CLI manifest file from {uri}...")
            with open(uri) as file:
                temp = json.load(file)

            try:
                self.validate(temp)
                self._data = temp
            except Exception as ex:
                raise InvalidSourceFileError(
                    f"{uri} is missing required data: {ex}"
                ) from ex

    def validate(self, data: Any):
        self._logger.debug("Validating CLI manifest file...")

        for key in data:
            item = data[key]
            assert SdkType.Holoscan.value in item
            holoscan = item[SdkType.Holoscan.value]

            assert ArtifactSources.SectionWheelVersion in holoscan
            assert ArtifactSources.SectionDebianVersion in holoscan
            assert ArtifactSources.SectionBaseImages in holoscan
            assert ArtifactSources.SectionBuildImages in holoscan

            for config in PlatformConfiguration:
                assert config.value in holoscan[ArtifactSources.SectionBuildImages]

    def download_manifest(self):
        self._download_manifest_internal(
            ArtifactSources.ManifestFileUrl,
        )

    def _download_manifest_internal(self, url, headers=None):
        self._logger.info("Downloading CLI manifest file...")
        manifest = requests.get(url, headers=headers)

        try:
            manifest.raise_for_status()
        except Exception as ex:
            raise ManifestDownloadError(
                f"Error downloading manifest file from {url}: {manifest.reason}"
            ) from ex
        else:
            self._data = manifest.json()
            self.validate(self._data)

    def debian_package_version(self, version: str) -> Optional[str]:
        """Gets the version of the Debian package based on the version of Holoscan.

        Args:
            version (str): version of Holoscan

        Returns:
            Optional[str]: Debian package version
        """
        return (
            self._data[version][SdkType.Holoscan.value][
                ArtifactSources.SectionDebianVersion
            ]
            if version in self._data
            else None
        )

    def wheel_package_version(self, version: str) -> Optional[str]:
        """Gets the version of the PyPI package based on the version of Holoscan.

        Args:
            version (str): version of Holoscan

        Returns:
            Optional[str]: PyPI package version
        """
        return self._data[version][SdkType.Holoscan.value][
            ArtifactSources.SectionWheelVersion
        ]
