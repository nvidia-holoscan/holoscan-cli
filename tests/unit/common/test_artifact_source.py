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

from pathlib import Path

import pytest
import requests

from holoscan_cli.common.artifact_sources import ArtifactSources
from holoscan_cli.common.exceptions import ManifestDownloadError


class TestArtifactSource:
    def _init(self) -> None:
        self._artifact_source = ArtifactSources()
        current_file_path = Path(__file__).parent.parent.resolve()
        source_file_sample = current_file_path / "./artifacts.json"
        self._artifact_source.load(str(source_file_sample))

    def test_loads_invalid_file(self, monkeypatch):
        monkeypatch.setattr(Path, "read_text", lambda x: "{}")

        source_file_sample = Path("some-bogus-file.json")
        artifact_sources = ArtifactSources()

        with pytest.raises(FileNotFoundError):
            artifact_sources.load(str(source_file_sample))

    def test_loads_from_https_with_error(self, monkeypatch):
        def mock_get(*args, **kwargs):
            response = requests.Response()
            response.status_code = 500
            response.reason = "error"
            return response

        monkeypatch.setattr(requests, "get", mock_get)
        artifact_source = ArtifactSources()
        with pytest.raises(ManifestDownloadError):
            artifact_source.load("https://holoscan")

    def test_loads_from_http_with_error(self, monkeypatch):
        def mock_get(*args, **kwargs):
            response = requests.Response()
            response.status_code = 500
            response.reason = "error"
            return response

        monkeypatch.setattr(requests, "get", mock_get)
        artifact_source = ArtifactSources()
        with pytest.raises(ManifestDownloadError):
            artifact_source.load("http://holoscan")

    def test_debian_package_version(self):
        self._init()
        assert self._artifact_source.debian_package_version("1.0.0") is not None

    def test_debian_package_version_missing(self):
        self._init()
        assert self._artifact_source.debian_package_version("2.4.1") is None

    def test_base_images(self):
        self._init()
        assert self._artifact_source.base_image("1.0.0") is not None

    def test_build_images(self):
        self._init()
        assert self._artifact_source.build_images("1.0.0") is not None

    def test_health_probe(self):
        self._init()
        assert self._artifact_source.health_probe("1.0.0") is not None

    def test_download_manifest_success(self, monkeypatch):
        def mock_get(*args, **kwargs):
            response = requests.Response()
            response.status_code = 200
            response._content = b"""{
                "1.0.0": {
                    "holoscan": {
                        "wheel-version": "1.0.0",
                        "debian-version": "1.0.0",
                        "base-images": "test-base",
                        "build-images": {
                            "igpu": "test-build-igpu",
                            "dgpu": "test-build-dgpu",
                            "cpu": "test-build-cpu"
                        }
                    }
                }
            }"""
            return response

        monkeypatch.setattr(requests, "get", mock_get)
        artifact_source = ArtifactSources()
        artifact_source.download_manifest()
        assert artifact_source.base_image("1.0.0") == "test-base"

    def test_download_manifest_failure(self, monkeypatch):
        def mock_get(*args, **kwargs):
            response = requests.Response()
            response.status_code = 404
            response.reason = "Not Found"
            return response

        monkeypatch.setattr(requests, "get", mock_get)
        artifact_source = ArtifactSources()
        with pytest.raises(ManifestDownloadError) as exc_info:
            artifact_source.download_manifest()
        assert "Error downloading manifest file" in str(exc_info.value)
