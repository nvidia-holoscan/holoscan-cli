# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from argparse import Namespace

from holoscan_cli.utils.project import report_effective_configuration


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
