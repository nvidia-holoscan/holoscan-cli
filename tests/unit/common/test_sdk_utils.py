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

import pytest
from holoscan_cli.common.artifact_sources import ArtifactSources
from holoscan_cli.common.enum_types import SdkType
from holoscan_cli.common.exceptions import (
    FailedToDetectSDKVersionError,
    InvalidSdkError,
)
from holoscan_cli.common.sdk_utils import (
    detect_holoscan_version,
    detect_holoscan_cli_version,
    detect_monaideploy_version,
    detect_sdk,
    detect_sdk_version,
    validate_holoscan_sdk_version,
)
from packaging.version import Version


class TestDetectSdk:
    def test_sdk_is_not_none(self):
        assert detect_sdk(SdkType.Holoscan) == SdkType.Holoscan
        assert detect_sdk(SdkType.MonaiDeploy) == SdkType.MonaiDeploy

    def test_sdk_as_holoscan(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["/path/to/holoscan", "package"])
        assert detect_sdk() == SdkType.Holoscan

    def test_sdk_as_monai_deploy(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["/path/to/monai-deploy", "package"])
        assert detect_sdk() == SdkType.MonaiDeploy

    def test_sdk_as_unknown(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["/path/to/bla", "package"])
        with pytest.raises(InvalidSdkError):
            detect_sdk()


class TestDetectSdkVersion:
    def test_sdk_version_(self, monkeypatch):
        monkeypatch.setattr(
            "holoscan_cli.common.sdk_utils.detect_holoscan_version",
            lambda x: SdkType.Holoscan.name,
        )
        monkeypatch.setattr(
            "holoscan_cli.common.sdk_utils.detect_monaideploy_version",
            lambda x: SdkType.MonaiDeploy.name,
        )
        assert detect_sdk_version(SdkType.Holoscan) == [
            SdkType.Holoscan.name,
            None,
        ]
        assert detect_sdk_version(SdkType.MonaiDeploy) == [
            SdkType.Holoscan.name,
            SdkType.MonaiDeploy.name,
        ]


class TestDetectHoloscanVersion:
    def test_sdk_version_from_valid_user_input(self, monkeypatch):
        assert detect_holoscan_version(Version("1.0.0")) == "1.0.0"

    @pytest.mark.parametrize(
        "package_name",
        [
            ("holoscan-cu12"),
            ("holoscan-cu13"),
            ("holoscan"),
        ],
    )
    def test_detect_sdk_version_with_supported_package_names(
        self, monkeypatch, package_name
    ):
        version = "1.0.0"

        # Mock distribution object
        class MockDistribution:
            def __init__(self, name):
                self.metadata = {"Name": name}

        mock_distributions = [MockDistribution(package_name)]
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_holoscan_version()
        assert result == version

    def test_detect_sdk_version_with_patch(self, monkeypatch):
        version = "1.0.0-beta-1"

        # Mock distribution object
        class MockDistribution:
            def __init__(self, name):
                self.metadata = {"Name": name}

        mock_distributions = [MockDistribution("holoscan-cu12")]
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_holoscan_version()
        assert result == "1.0.0"

    @pytest.mark.parametrize(
        "version,expected",
        [
            ("1.0a2+4.gcaa3b3fe", "1.0.0"),
            ("1", "1.0.0"),
            ("1.0", "1.0.0"),
            ("1.0.0.1", "1.0.0"),
        ],
    )
    def test_detect_sdk_version_with_non_semver_string(
        self, monkeypatch, version, expected
    ):
        # Mock distribution object
        class MockDistribution:
            def __init__(self, name):
                self.metadata = {"Name": name}

        mock_distributions = [MockDistribution("holoscan-cu13")]
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_holoscan_version()
        assert result == expected

    def test_detect_sdk_version_both_packages_prefers_first(self, monkeypatch):
        """Test when both holoscan-cu12 and holoscan-cu13 are found - should use the first one."""
        version = "2.0.0"

        # Mock distribution objects
        class MockDistribution:
            def __init__(self, name):
                self.metadata = {"Name": name}

        mock_distributions = [
            MockDistribution("holoscan-cu12"),
            MockDistribution("holoscan-cu13"),
            MockDistribution("other-package"),
        ]
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_holoscan_version()
        assert result == version

    def test_detect_sdk_version_no_valid_packages(self, monkeypatch):
        """Test when no valid holoscan packages are installed."""
        # Mock empty distributions
        mock_distributions = []
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )

        with pytest.raises(
            FailedToDetectSDKVersionError,
            match="No installed Holoscan PyPI package found",
        ):
            detect_holoscan_version()

    def test_detect_sdk_version_only_invalid_packages(self, monkeypatch):
        """Test when only invalid holoscan packages are installed."""

        # Mock distribution object with packages not in PYPI_PACKAGE_NAMES
        class MockDistribution:
            def __init__(self, name):
                self.metadata = {"Name": name}

        mock_distributions = [
            MockDistribution("holoscan-cli"),
            MockDistribution("holoscan-extras"),
            MockDistribution("other-package"),
        ]
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )

        with pytest.raises(
            FailedToDetectSDKVersionError,
            match="No installed Holoscan PyPI package found",
        ):
            detect_holoscan_version()

    def test_detect_sdk_version_mixed_valid_invalid_packages(self, monkeypatch):
        """Test when both valid and invalid packages exist - should use valid one."""
        version = "1.5.0"

        # Mock distribution objects with mix of valid and invalid
        class MockDistribution:
            def __init__(self, name):
                self.metadata = {"Name": name}

        mock_distributions = [
            MockDistribution("holoscan"),
            MockDistribution("holoscan-cli"),
            MockDistribution("holoscan-cu12"),  # This should be found
            MockDistribution("other-package"),
        ]
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_holoscan_version()
        assert result == version

    def test_detect_sdk_version_case_insensitive(self, monkeypatch):
        """Test that package name matching is case insensitive."""
        version = "1.5.0"

        # Mock distribution object with mixed case
        class MockDistribution:
            def __init__(self, name):
                self.metadata = {"Name": name}

        mock_distributions = [MockDistribution("HoloScan-CU12")]
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_holoscan_version()
        assert result == version

    def test_detect_sdk_version_with_version_error(self, monkeypatch):
        """Test when importlib.metadata.version raises an exception."""

        # Mock distribution object
        class MockDistribution:
            def __init__(self, name):
                self.metadata = {"Name": name}

        mock_distributions = [MockDistribution("holoscan-cu12")]
        monkeypatch.setattr(
            "importlib.metadata.distributions", lambda: mock_distributions
        )

        def raise_error(x):
            raise Exception("version error")

        monkeypatch.setattr("importlib.metadata.version", raise_error)

        with pytest.raises(Exception, match="version error"):
            detect_holoscan_version()


class TestDetectHoloscanCliVersion:
    def test_detect_holoscan_cli_version(self, monkeypatch):
        version = "1.0.0"
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)
        result = detect_holoscan_cli_version()
        assert result == version

    def test_detect_holoscan_cli_version_with_patch(self, monkeypatch):
        version = "1.0.0-beta-1"
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_holoscan_cli_version()
        assert result == "1.0.0"

    def test_detect_holoscan_cli_version_wiht_invalid_metadata(self, monkeypatch):
        def raise_error():
            raise Exception("error")

        monkeypatch.setattr("importlib.metadata.version", raise_error)

        with pytest.raises(FailedToDetectSDKVersionError):
            detect_holoscan_cli_version()


class TestDetectMonaiDeployVersion:
    def test_sdk_version_from_valid_user_input(self, monkeypatch):
        assert detect_monaideploy_version(Version("0.6.0")) == "0.6.0"

    def test_detect_sdk_version(self, monkeypatch):
        version = "0.6.0"

        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_monaideploy_version()
        assert result == version

    def test_detect_sdk_version_with_patch(self, monkeypatch):
        version = "0.6.0-beta-1"

        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        result = detect_monaideploy_version()
        assert result == "0.6.0"

    def test_detect_sdk_version_with_unsupported_version(self, monkeypatch):
        version = Version("0.1.2")

        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        with pytest.raises(FailedToDetectSDKVersionError):
            detect_monaideploy_version()

    def test_detect_sdk_version_with_no_match(self, monkeypatch):
        version = Version("100")

        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        with pytest.raises(FailedToDetectSDKVersionError):
            detect_monaideploy_version()

    def test_detect_sdk_version_wiht_invalid_metadata(self, monkeypatch):
        def raise_error():
            raise Exception("error")

        monkeypatch.setattr("importlib.metadata.version", raise_error)

        with pytest.raises(FailedToDetectSDKVersionError):
            detect_monaideploy_version()


class TestValidateSupportedVersion:
    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self._artifact_source = ArtifactSources(13)

    def test_supported_version(self, monkeypatch):
        version = "1.0.0"
        setattr(ArtifactSources, "holoscan_versions", property(lambda s: [version]))
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        validate_holoscan_sdk_version(self._artifact_source, version)

    def test_unsupported_version(self, monkeypatch):
        version = "0.1.2"

        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        with pytest.raises(InvalidSdkError):
            validate_holoscan_sdk_version(self._artifact_source, version)

    def test_detect_sdk_version_with_no_match(self, monkeypatch):
        version = "100"
        monkeypatch.setattr("importlib.metadata.version", lambda x: version)

        with pytest.raises(InvalidSdkError):
            validate_holoscan_sdk_version(self._artifact_source, version)
