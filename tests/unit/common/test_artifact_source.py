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
        self._artifact_source = ArtifactSources(
            13
        )  # Default CUDA 13 for existing tests
        current_file_path = Path(__file__).parent.parent.resolve()
        source_file_sample = current_file_path / "./artifacts.json"
        self._artifact_source.load(str(source_file_sample))

    def test_loads_invalid_file(self, monkeypatch):
        monkeypatch.setattr(Path, "read_text", lambda x: "{}")

        source_file_sample = Path("some-bogus-file.json")
        artifact_sources = ArtifactSources(13)

        with pytest.raises(FileNotFoundError):
            artifact_sources.load(str(source_file_sample))

    def test_loads_from_https_with_error(self, monkeypatch):
        def mock_get(*args, **kwargs):
            response = requests.Response()
            response.status_code = 500
            response.reason = "error"
            return response

        monkeypatch.setattr(requests, "get", mock_get)
        artifact_source = ArtifactSources(13)
        with pytest.raises(ManifestDownloadError):
            artifact_source.load("https://holoscan")

    def test_loads_from_http_with_error(self, monkeypatch):
        def mock_get(*args, **kwargs):
            response = requests.Response()
            response.status_code = 500
            response.reason = "error"
            return response

        monkeypatch.setattr(requests, "get", mock_get)
        artifact_source = ArtifactSources(13)
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
        artifact_source = ArtifactSources(13)
        artifact_source.download_manifest()
        assert artifact_source.base_image("1.0.0") == "test-base"

    def test_download_manifest_failure(self, monkeypatch):
        def mock_get(*args, **kwargs):
            response = requests.Response()
            response.status_code = 404
            response.reason = "Not Found"
            return response

        monkeypatch.setattr(requests, "get", mock_get)
        artifact_source = ArtifactSources(13)
        with pytest.raises(ManifestDownloadError) as exc_info:
            artifact_source.download_manifest()
        assert "Error downloading manifest file" in str(exc_info.value)

    def test_cuda_12_url_selection(self, monkeypatch):
        """Test that CUDA 12 selects the cu12 artifacts URL"""
        # Mock the version detection to return a known version
        monkeypatch.setattr(
            "holoscan_cli.common.artifact_sources.Version",
            lambda x: type("Version", (), {"release": (3, 7, 0)}),
        )

        artifact_source = ArtifactSources(12)
        expected_url = "https://raw.githubusercontent.com/nvidia-holoscan/holoscan-cli/refs/heads/main/releases/3.7.0/artifacts-cu12.json"
        assert artifact_source.ManifestFileUrl == expected_url

    def test_cuda_13_url_selection(self, monkeypatch):
        """Test that CUDA 13 selects the standard artifacts URL"""
        # Mock the version detection to return a known version
        monkeypatch.setattr(
            "holoscan_cli.common.artifact_sources.Version",
            lambda x: type("Version", (), {"release": (3, 7, 0)}),
        )

        artifact_source = ArtifactSources(13)
        expected_url = "https://raw.githubusercontent.com/nvidia-holoscan/holoscan-cli/refs/heads/main/releases/3.7.0/artifacts.json"
        assert artifact_source.ManifestFileUrl == expected_url

    def test_cuda_12_directory_selection(self, tmp_path, monkeypatch):
        """Test that CUDA 12 selects artifacts-cu12.json from directory"""
        import json

        # Create test directory structure
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        # Create both artifact files with valid structure
        artifacts_cu12 = artifacts_dir / "artifacts-cu12.json"
        artifacts_standard = artifacts_dir / "artifacts.json"

        test_data_cu12 = {
            "1.0.0": {
                "holoscan": {
                    "wheel-version": "1.0.0-cu12",
                    "debian-version": "1.0.0-cu12",
                    "base-images": {
                        "dgpu": "test-base-cu12",
                        "igpu": "test-base-igpu-cu12",
                    },
                    "build-images": {
                        "igpu": {"jetson-agx-orin-devkit": "test-build-igpu-cu12"},
                        "dgpu": {"x64-workstation": "test-build-dgpu-cu12"},
                        "cpu": {"x64-workstation": "test-build-cpu-cu12"},
                    },
                }
            }
        }
        test_data_standard = {
            "1.0.0": {
                "holoscan": {
                    "wheel-version": "1.0.0",
                    "debian-version": "1.0.0",
                    "base-images": {"dgpu": "test-base", "igpu": "test-base-igpu"},
                    "build-images": {
                        "igpu": {"jetson-agx-orin-devkit": "test-build-igpu"},
                        "dgpu": {"x64-workstation": "test-build-dgpu"},
                        "cpu": {"x64-workstation": "test-build-cpu"},
                    },
                }
            }
        }

        artifacts_cu12.write_text(json.dumps(test_data_cu12))
        artifacts_standard.write_text(json.dumps(test_data_standard))

        artifact_source = ArtifactSources(12)
        artifact_source.load(str(artifacts_dir))

        # Should have loaded the cu12 data
        assert artifact_source.debian_package_version("1.0.0") == "1.0.0-cu12"

    def test_cuda_13_directory_selection(self, tmp_path, monkeypatch):
        """Test that CUDA 13 selects artifacts.json from directory"""
        import json

        # Create test directory structure
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        # Create both artifact files with valid structure
        artifacts_cu12 = artifacts_dir / "artifacts-cu12.json"
        artifacts_standard = artifacts_dir / "artifacts.json"

        test_data_cu12 = {
            "1.0.0": {
                "holoscan": {
                    "wheel-version": "1.0.0-cu12",
                    "debian-version": "1.0.0-cu12",
                    "base-images": {
                        "dgpu": "test-base-cu12",
                        "igpu": "test-base-igpu-cu12",
                    },
                    "build-images": {
                        "igpu": {"jetson-agx-orin-devkit": "test-build-igpu-cu12"},
                        "dgpu": {"x64-workstation": "test-build-dgpu-cu12"},
                        "cpu": {"x64-workstation": "test-build-cpu-cu12"},
                    },
                }
            }
        }
        test_data_standard = {
            "1.0.0": {
                "holoscan": {
                    "wheel-version": "1.0.0",
                    "debian-version": "1.0.0",
                    "base-images": {"dgpu": "test-base", "igpu": "test-base-igpu"},
                    "build-images": {
                        "igpu": {"jetson-agx-orin-devkit": "test-build-igpu"},
                        "dgpu": {"x64-workstation": "test-build-dgpu"},
                        "cpu": {"x64-workstation": "test-build-cpu"},
                    },
                }
            }
        }

        artifacts_cu12.write_text(json.dumps(test_data_cu12))
        artifacts_standard.write_text(json.dumps(test_data_standard))

        artifact_source = ArtifactSources(13)
        artifact_source.load(str(artifacts_dir))

        # Should have loaded the standard data
        assert artifact_source.debian_package_version("1.0.0") == "1.0.0"
