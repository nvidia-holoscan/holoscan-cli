# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from holoscan_cli.utils import host_setup


def test_install_packages_if_missing_installs_only_missing_and_pinned(monkeypatch):
    installed = {"already": "1.0.0"}
    updates = []
    commands = []
    monkeypatch.setattr(
        host_setup,
        "get_installed_package_version",
        lambda package_name: installed.get(package_name),
    )
    monkeypatch.setattr(
        host_setup,
        "ensure_apt_updated",
        lambda dry_run=False: updates.append(dry_run),
    )
    monkeypatch.setattr(
        host_setup,
        "run_command",
        lambda cmd, **kwargs: commands.append((cmd, kwargs)),
    )

    selected = host_setup.install_packages_if_missing(
        ["already", "missing", "pinned=1.2*"],
        dry_run=True,
        apt_options=["-y"],
    )

    assert selected == ["missing", "pinned=1.2*"]
    assert updates == [True]
    assert commands == [
        (["apt", "install", "-y", "missing", "pinned=1.2*"], {"dry_run": True, "as_root": True})
    ]


def test_install_cuda_dependencies_package_selects_matching_available_version(
    monkeypatch,
):
    install_calls = []
    monkeypatch.setattr(host_setup, "get_installed_package_version", lambda _: None)
    monkeypatch.setattr(
        host_setup,
        "get_available_package_versions",
        lambda _: [
            "8.9.7.29-1+cuda12.3",
            "9.5.1.17-1",
            "9.4.0.58-1",
        ],
    )
    monkeypatch.setattr(
        host_setup,
        "install_packages_if_missing",
        lambda packages, **kwargs: install_calls.append((packages, kwargs)),
    )

    version = host_setup.install_cuda_dependencies_package(
        "libcudnn9-cuda-12",
        version_pattern=r"9\.[0-9]+\.[0-9]+\.[0-9]+-[0-9]+",
        dry_run=True,
    )

    assert version == "9.5.1.17-1"
    assert install_calls == [
        (
            ["libcudnn9-cuda-12=9.5.1.17-1"],
            {
                "apt_options": [
                    "--no-install-recommends",
                    "-y",
                    "--allow-downgrades",
                ],
                "dry_run": True,
            },
        )
    ]


def test_install_cuda_dependencies_package_reuses_compatible_installed_version(
    monkeypatch,
):
    monkeypatch.setattr(
        host_setup,
        "get_installed_package_version",
        lambda _: "10.8.0.43-1+cuda13.0",
    )
    monkeypatch.setattr(
        host_setup,
        "get_available_package_versions",
        lambda _: pytest.fail("installed compatible version should short-circuit apt lookup"),
    )

    version = host_setup.install_cuda_dependencies_package(
        "libnvinfer10",
        version_pattern=r"10\.[0-9]+\.[0-9]+\.[0-9]+-[0-9]\+cuda13\.[0-9]+",
    )

    assert version == "10.8.0.43-1+cuda13.0"


def test_install_cuda_dependencies_package_reports_no_matching_version(
    monkeypatch,
):
    monkeypatch.setattr(host_setup, "get_installed_package_version", lambda _: None)
    monkeypatch.setattr(
        host_setup,
        "get_available_package_versions",
        lambda _: ["8.9.7.29-1+cuda12.3"],
    )

    with pytest.raises(host_setup.PackageInstallationError) as exc_info:
        host_setup.install_cuda_dependencies_package(
            "libcudnn9-cuda-12",
            version_pattern=r"9\.[0-9]+\.[0-9]+\.[0-9]+-[0-9]+",
        )

    assert exc_info.value.package_name == "libcudnn9-cuda-12"


def test_setup_cuda_packages_falls_back_to_cudnn8_and_continues_after_trt_failure(
    monkeypatch,
):
    calls = []

    def fake_install_cuda_package(package_name, version_pattern, dry_run=False):
        calls.append((package_name, version_pattern, dry_run))
        if package_name.startswith("libcudnn9"):
            raise host_setup.PackageInstallationError(package_name, version_pattern)
        if package_name == "libcudnn8":
            return "8.9.7.29-1+cuda12.3"
        if package_name == "libcudnn8-dev":
            assert version_pattern == r"8\.9\.7\.29\-1\+cuda12\.3"
            return "8.9.7.29-1+cuda12.3"
        if package_name == "libnvinfer10":
            raise host_setup.PackageInstallationError(package_name, version_pattern)
        raise AssertionError(f"unexpected package install: {package_name}")

    monkeypatch.setattr(
        host_setup,
        "install_cuda_dependencies_package",
        fake_install_cuda_package,
    )
    monkeypatch.setattr(
        host_setup,
        "install_packages_if_missing",
        lambda *args, **kwargs: pytest.fail("TensorRT meta packages should be skipped"),
    )

    host_setup.setup_cuda_packages("12", dry_run=True)

    assert [name for name, _pattern, _dry_run in calls] == [
        "libcudnn9-cuda-12",
        "libcudnn8",
        "libcudnn8-dev",
        "libnvinfer10",
    ]
    assert all(dry_run is True for _name, _pattern, dry_run in calls)


def test_setup_cuda_packages_pins_tensorrt_components_to_core_version(monkeypatch):
    calls = []
    meta_install_calls = []
    trt_version = "10.8.0.43-1+cuda13.0"

    def fake_install_cuda_package(package_name, version_pattern, dry_run=False):
        calls.append((package_name, version_pattern, dry_run))
        if package_name.startswith("libcudnn9"):
            return "9.5.1.17-1"
        if package_name == "libnvinfer10":
            return trt_version
        if package_name.startswith("libnvinfer") or package_name.startswith("libnvonnx"):
            assert version_pattern == r"10\.8\.0\.43\-1\+cuda13\.0"
            return trt_version
        raise AssertionError(f"unexpected package install: {package_name}")

    monkeypatch.setattr(
        host_setup,
        "install_cuda_dependencies_package",
        fake_install_cuda_package,
    )
    monkeypatch.setattr(
        host_setup,
        "install_packages_if_missing",
        lambda packages, **kwargs: meta_install_calls.append((packages, kwargs)),
    )

    host_setup.setup_cuda_packages("13", dry_run=True)

    assert meta_install_calls == [
        (
            [
                f"libnvinfer-bin={trt_version}",
                f"libnvinfer-lean10={trt_version}",
                f"libnvinfer-plugin10={trt_version}",
                f"libnvinfer-vc-plugin10={trt_version}",
                f"libnvinfer-dispatch10={trt_version}",
                f"libnvonnxparsers10={trt_version}",
            ],
            {
                "apt_options": [
                    "--no-install-recommends",
                    "-y",
                    "--allow-downgrades",
                ],
                "dry_run": True,
            },
        )
    ]
    assert "libnvinfer-dev" in [name for name, _pattern, _dry_run in calls]


def test_setup_cuda_dependencies_uses_runtime_major_version(monkeypatch):
    captured = []
    monkeypatch.setattr(host_setup, "get_cuda_runtime_version", lambda: "12.6.3")
    monkeypatch.setattr(
        host_setup,
        "setup_cuda_packages",
        lambda cuda_major_version, dry_run=False: captured.append((cuda_major_version, dry_run)),
    )

    host_setup.setup_cuda_dependencies(dry_run=True)

    assert captured == [("12", True)]


def _run_ngc_setup(monkeypatch):
    commands = []
    monkeypatch.setattr(
        host_setup,
        "run_command",
        lambda cmd, **kwargs: commands.append((cmd, kwargs)),
    )
    host_setup.setup_ngc_cli(dry_run=False)
    return commands


def test_setup_ngc_cli_links_into_local_bin_for_non_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(host_setup.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(host_setup.shutil, "which", lambda _: None)

    commands = _run_ngc_setup(monkeypatch)

    dest = str(tmp_path / ".local" / "bin" / "ngc")
    assert commands[-1][0][:2] == ["ln", "-sf"]
    assert commands[-1][0][-1] == dest
    assert (tmp_path / ".local" / "bin").is_dir()


def test_setup_ngc_cli_links_system_wide_for_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(host_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(host_setup.shutil, "which", lambda _: None)
    # Keep the test hermetic: ignore any real /usr/local/bin/ngc on the test
    # machine, and don't create directories outside tmp_path.
    monkeypatch.setattr(host_setup.os.path, "exists", lambda _: False)
    monkeypatch.setattr(host_setup.os, "makedirs", lambda *a, **k: None)

    commands = _run_ngc_setup(monkeypatch)

    assert commands[-1][0][:2] == ["ln", "-sf"]
    assert commands[-1][0][-1] == "/usr/local/bin/ngc"


def test_setup_ngc_cli_skips_when_destination_exists(monkeypatch, tmp_path):
    # ~/.local/bin may not be on PATH; the destination check must still
    # short-circuit so setup does not re-download NGC on every run.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(host_setup.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(host_setup.shutil, "which", lambda _: None)
    dest = tmp_path / ".local" / "bin" / "ngc"
    dest.parent.mkdir(parents=True)
    dest.write_text("")

    commands = _run_ngc_setup(monkeypatch)

    assert commands == []
