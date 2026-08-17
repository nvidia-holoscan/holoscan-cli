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


def _cuda_major(value: str) -> str:
    normalized = value.strip()
    if not normalized.isdigit() or not 1 <= int(normalized) <= 99:
        raise argparse.ArgumentTypeError("CUDA must be an integer major version from 1 to 99")
    return normalized


def _image_reference(value: str) -> str:
    if not value or any(character.isspace() for character in value):
        raise argparse.ArgumentTypeError(
            "image references must be non-empty and contain no whitespace"
        )
    return value


def _nonempty_path(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("path must not be empty")
    return value


class _DeprecatedDisplayFlagAction(argparse.Action):
    def __call__(self, _parser, namespace, _values, option_string=None):
        warn(
            f"{option_string} is deprecated and ignored; X11 and Wayland "
            "forwarding now happens automatically when DISPLAY or "
            "WAYLAND_DISPLAY is set."
        )
        setattr(namespace, self.dest, True)


def _add_config_vector_layer_args(parser: argparse.ArgumentParser) -> None:
    """Add invocation-wide controls for inherited additive option vectors."""
    parser.add_argument(
        "--no-project-config",
        action="store_true",
        help=(
            "Ignore additive Docker/forward-env vectors from [tool.holoscan]; "
            "scalar project settings remain active"
        ),
    )
    parser.add_argument(
        "--no-mode-config",
        action="store_true",
        help=(
            "Ignore additive Docker/CMake vectors from the selected mode; the mode command, "
            "environment, and other settings remain active"
        ),
    )
    parser.add_argument(
        "--no-inherited-config",
        action="store_true",
        help=(
            "Ignore additive option vectors from project, mode, and environment layers, "
            "including wrapper-provided defaults; CLI-generated invariants remain active"
        ),
    )


def get_build_argparse() -> argparse.ArgumentParser:
    """Get argument parser for container build options."""
    parser = argparse.ArgumentParser(add_help=False)
    _add_config_vector_layer_args(parser)
    parser.add_argument(
        "--base-img",
        type=_image_reference,
        help=(
            "(Build container) Base image used exactly as written (tag or digest recommended; "
            "an untagged repository uses Docker's default tag)"
        ),
    )
    parser.add_argument("--docker-file", help="(Build container) Path to Dockerfile to use")
    parser.add_argument(
        "--img",
        type=_image_reference,
        help="(Build container) Specify fully qualified container name",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="(Build container) Do not use cache when building the image",
    )
    parser.add_argument(
        "--cuda",
        type=_cuda_major,
        help=(
            "(Build container) CUDA major version (normally 12 or 13). Defaults to "
            "HOLOSCAN_CLI_DEFAULT_CUDA_VERSION, project configuration, then host detection; "
            "compatibility outside the project's reviewed profile is not inferred"
        ),
    )
    parser.add_argument(
        "--build-args",
        help="(Build container) Extra arguments to docker build command, "
        "example: `--build-args '--network=host --build-arg \"CUSTOM=value with spaces\"'`",
    )
    parser.add_argument(
        "--replace-build-args",
        action="store_true",
        help=(
            "Ignore Docker build arguments from the environment, project configuration, "
            "and selected mode; use only --build-args"
        ),
    )
    parser.add_argument(
        "--extra-scripts",
        action="append",
        help=(
            "(Build container) Named dependency scripts to run as Docker layers. Search order: "
            "HOLOSCAN_CLI_SETUP_SCRIPTS_DIR, project utilities/setup, bundled scripts. "
            "Use `holoscan setup --list-scripts` to list them."
        ),
    )
    return parser


def get_run_argparse() -> argparse.ArgumentParser:
    """Get argument parser for container run options."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--docker-opts",
        action="append",
        help=(
            "Additional options appended to the Docker run command. Repeat for multiple "
            "fragments; example: `--docker-opts='--entrypoint=bash'` or "
            "`--docker-opts='-e DISPLAY=:1'`"
        ),
    )
    parser.add_argument(
        "--replace-docker-opts",
        nargs="?",
        const="",
        default=None,
        metavar="OPTS",
        help=(
            "Replace inherited project, mode, and environment Docker run options with OPTS; "
            "use the equals form for dash-prefixed values, or omit OPTS to clear them. "
            "Any --docker-opts fragments are appended afterward"
        ),
    )
    parser.add_argument(
        "--forward-env",
        action="append",
        metavar="NAME",
        help=(
            "Forward a host environment variable by name. Repeat for multiple variables; "
            "values are inherited by Docker and are not placed in the command line"
        ),
    )
    parser.add_argument(
        "--replace-forward-env",
        action="store_true",
        help=(
            "Ignore forward-env from the environment and project configuration; use only "
            "--forward-env"
        ),
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
        type=_nonempty_path,
        help=(
            "SDK installation or parent directory for local builds and container mounts; "
            "overrides HOLOSCAN_SDK_ROOT for this command"
        ),
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
        help="Run the container as root. For `run`, build as the user and run only the application phase as root",
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
