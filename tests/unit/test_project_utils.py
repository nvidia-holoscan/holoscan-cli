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
