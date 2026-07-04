#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import argparse

from ..utils.io import warn


class _DeprecatedDisplayFlagAction(argparse.Action):
    def __call__(self, _parser, namespace, _values, option_string=None):
        warn(
            f"{option_string} is deprecated and ignored; X11 and Wayland "
            "forwarding now happens automatically when DISPLAY or "
            "WAYLAND_DISPLAY is set."
        )
        setattr(namespace, self.dest, True)


def get_build_argparse() -> argparse.ArgumentParser:
    """Get argument parser for container build options."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--base-img", help="(Build container) Fully qualified base image name")
    parser.add_argument("--docker-file", help="(Build container) Path to Dockerfile to use")
    parser.add_argument("--img", help="(Build container) Specify fully qualified container name")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="(Build container) Do not use cache when building the image",
    )
    parser.add_argument(
        "--cuda",
        type=str,
        help="(Build container) CUDA version (e.g., 12, 13). Default: 12",
    )
    parser.add_argument(
        "--build-args",
        help="(Build container) Extra arguments to docker build command, "
        "example: `--build-args '--network=host --build-arg \"CUSTOM=value with spaces\"'`",
    )
    parser.add_argument(
        "--extra-scripts",
        action="append",
        help="(Build container) Named dependency installation scripts to run as Docker layers."
        + "Searches in the directory path specified by the HOLOSCAN_CLI_SETUP_SCRIPTS_DIR environment variable."
        + "Use `holoscan setup --list-scripts` to list all available scripts.",
    )
    return parser


def get_run_argparse() -> argparse.ArgumentParser:
    """Get argument parser for container run options."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--docker-opts",
        default="",
        help="Additional options to the Docker run command, "
        "example: `--docker-opts='--entrypoint=bash'` or `--docker-opts '-e DISPLAY=:1'`",
    )
    parser.add_argument(
        "--ssh-x11",
        action=_DeprecatedDisplayFlagAction,
        nargs=0,
        default=False,
        help="[DEPRECATED] X11 over SSH is now auto-detected from DISPLAY",
    )
    parser.add_argument(
        "--nsys-profile",
        action="store_true",
        help="Support Nsight Systems profiling in container",
    )
    parser.add_argument(
        "--local-sdk-root",
        help="Path to Holoscan SDK used for building local Holoscan SDK container",
    )
    parser.add_argument("--init", action="store_true", help="Support tini entry point")
    parser.add_argument(
        "--persistent", action="store_true", help="Does not delete container after it is run"
    )
    parser.add_argument(
        "--add-volume",
        action="append",
        help="Mount additional volume to `/workspace/volumes`, example: `--add-volume /tmp`",
    )
    parser.add_argument(
        "--as-root",
        action="store_true",
        help="Run as root; for `run`, build as the user and run the application phase as root",
    )
    parser.add_argument(
        "--nsys-location",
        help="Specify location of the Nsight Systems installation on the host "
        "(e.g., /opt/nvidia/nsight-systems/2024.1.1/)",
    )
    parser.add_argument(
        "--mps",
        action="store_true",
        help="If CUDA MPS is enabled on the host, mount MPS host directories into the container",
    )
    parser.add_argument(
        "--enable-x11",
        action=_DeprecatedDisplayFlagAction,
        nargs=0,
        default=True,
        help="[DEPRECATED] X11/Wayland forwarding is now auto-detected",
    )
    return parser
