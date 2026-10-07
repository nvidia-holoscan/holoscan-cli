# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from argparse import Namespace

import pytest

from holoscan_cli import project_context
from holoscan_cli.project_context import ProjectContext
from holoscan_cli.utils.project import language_cmake_args, report_effective_configuration


@pytest.mark.parametrize(
    "kind,module_name,language,expected",
    [
        ("source", None, "python", ["-DHOLOHUB_BUILD_PYTHON=ON", "-DHOLOHUB_BUILD_CPP=OFF"]),
        (
            "module",
            "holoscan-my-sensor",
            "cpp",
            [
                "-DHOLOHUB_BUILD_PYTHON=OFF",
                "-DHOLOHUB_BUILD_CPP=ON",
                "-DHOLOSCAN_MY_SENSOR_BUILD_PYTHON=OFF",
                "-DHOLOSCAN_MY_SENSOR_BUILD_CPP=ON",
            ],
        ),
        (
            "module",
            "acme.widgets--2",
            "python",
            [
                "-DHOLOHUB_BUILD_PYTHON=ON",
                "-DHOLOHUB_BUILD_CPP=OFF",
                "-DACME_WIDGETS__2_BUILD_PYTHON=ON",
                "-DACME_WIDGETS__2_BUILD_CPP=OFF",
            ],
        ),
        ("module", "holoscan-my-sensor", "", []),
    ],
)
def test_language_cmake_args(tmp_path, monkeypatch, kind, module_name, language, expected):
    context = ProjectContext(root=tmp_path, kind=kind, discovery="cwd", module_name=module_name)
    monkeypatch.setattr(project_context, "get_active_project_context", lambda: context)

    assert language_cmake_args(language) == expected


def test_language_cmake_args_uses_selected_module(tmp_path, monkeypatch):
    context = ProjectContext(root=tmp_path, kind="source", discovery="cwd")
    monkeypatch.setattr(project_context, "get_active_project_context", lambda: context)

    assert language_cmake_args("python", "holoscan-my-sensor") == [
        "-DHOLOHUB_BUILD_PYTHON=ON",
        "-DHOLOHUB_BUILD_CPP=OFF",
        "-DHOLOSCAN_MY_SENSOR_BUILD_PYTHON=ON",
        "-DHOLOSCAN_MY_SENSOR_BUILD_CPP=OFF",
    ]


def test_report_effective_configuration(capsys):
    args = Namespace(
        dryrun=False,
        cuda="13",
        local_sdk_root=None,
        base_img="example:latest",
        build_args="--build-arg SECRET=value",
    )

    report_effective_configuration(args, include_build=True)
    assert capsys.readouterr().out == ""

    args.dryrun = True
    report_effective_configuration(args, include_build=True)
    assert capsys.readouterr().out == (
        "Effective configuration (opaque option values hidden):\n"
        "  CUDA: 13 (command line (--cuda))\n"
        "  local SDK: none (container image)\n"
        "  base image: example:latest (command line (--base-img))\n"
        "  Docker build options: configured by command line (values hidden)\n"
    )


def test_report_effective_configuration_uses_sdk5_cuda(capsys, monkeypatch):
    from holoscan_cli.container.core import HoloscanContainer
    from holoscan_cli.utils import sdk

    monkeypatch.delenv("HOLOSCAN_CLI_DEFAULT_CUDA_VERSION", raising=False)
    monkeypatch.setattr(HoloscanContainer, "BASE_SDK_VERSION", "5.0.0", raising=False)
    monkeypatch.setattr(sdk, "get_default_cuda_version", lambda: "12")
    args = Namespace(dryrun=True, cuda=None, local_sdk_root=None)

    report_effective_configuration(args)
    assert "  CUDA: 13 (Holoscan SDK 5.0.0 supports only CUDA 13)\n" in capsys.readouterr().out
