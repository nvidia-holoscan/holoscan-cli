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

"""``holoscan vscode`` — build a dev container and launch it via VS Code Dev Containers."""

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from holoscan_cli.commands.registry import help_for
from holoscan_cli.utils.docker import get_devcontainer_config, launch_vscode_devcontainer
from holoscan_cli.utils.holohub import check_skip_builds
from holoscan_cli.utils.io import fatal


def register_vscode_parser(cli, subparsers, *, container_build) -> argparse.ArgumentParser:
    """Register the ``vscode`` subcommand.

    Inherits container build flags so users can override the dev image
    (``--img``, ``--base-img``, ``--cuda`` etc.) the same way as
    ``build-container`` and ``run-container`` do.
    """
    parser = subparsers.add_parser("vscode", help=help_for("vscode"), parents=[container_build])
    parser.add_argument("project", nargs="?", help="Project to launch VS Code for")
    parser.add_argument(
        "--language", choices=["cpp", "python"], help="Specify language implementation"
    )
    parser.add_argument("--docker-opts", help="Additional options to pass to the Docker launch")
    parser.add_argument(
        "--verbose", action="store_true", help="Print variables passed to docker run command"
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="Print commands without executing them"
    )
    parser.add_argument(
        "--no-docker-build", action="store_true", help="Skip building the container"
    )
    parser.set_defaults(func=lambda args: handle_vscode(cli, args))
    return parser


def handle_vscode(cli, args: argparse.Namespace) -> None:
    """Builds a dev container and launches VS Code with proper devcontainer configuration."""
    if not shutil.which("code") and not args.dryrun:
        fatal(
            "Please install VS Code to use VS Code Dev Container. "
            "Follow the instructions at https://code.visualstudio.com/Download"
        )

    skip_docker_build, _ = check_skip_builds(args)
    container = cli.make_project_container(
        project_name=args.project, language=getattr(args, "language", None)
    )
    container.dryrun = args.dryrun
    container.verbose = args.verbose
    dev_container_tag = "holohub-dev-container"
    if args.project:
        dev_container_tag += f"-{args.project}"
    dev_container_tag += ":dev"

    if not skip_docker_build:
        print(f"Building base Dev Container {dev_container_tag}...")
        container.build(
            docker_file=args.docker_file,
            base_img=args.base_img,
            img=dev_container_tag,
            no_cache=args.no_cache,
            build_args=args.build_args,
            cuda_version=getattr(args, "cuda", None),
            extra_scripts=getattr(args, "extra_scripts", []),
        )
    else:
        if hasattr(args, "cuda") and args.cuda is not None:
            container.cuda_version = args.cuda
        print(f"Skipping build, using existing Dev Container {dev_container_tag}...")
    devcontainer_env_options = container.get_devcontainer_args(
        docker_opts=getattr(args, "docker_opts", None) or ""
    )

    devcontainer_content = get_devcontainer_config(
        holohub_root=cli.HOLOHUB_ROOT, project_name=args.project, dry_run=args.dryrun
    )
    devcontainer_content = devcontainer_content.replace(
        "${localWorkspaceFolder}", str(cli.HOLOHUB_ROOT)
    )
    devcontainer_content = devcontainer_content.replace('//"<env>"', devcontainer_env_options)
    os.environ["HOLOSCAN_CLI_BASE_IMAGE"] = dev_container_tag
    if args.project:
        os.environ["HOLOSCAN_CLI_APP_NAME"] = args.project

    if not args.dryrun:
        tmpdir = tempfile.mkdtemp()
        workspace_name = cli.HOLOHUB_ROOT.name
        tmp_workspace = Path(tmpdir) / workspace_name
        tmp_workspace.mkdir()
        tmp_devcontainer = tmp_workspace / ".devcontainer"
        tmp_devcontainer.mkdir()
        devcontainer_json_dst = tmp_devcontainer / "devcontainer.json"
        with open(devcontainer_json_dst, "w") as f:
            f.write(devcontainer_content)
        print(f"Created temporary workspace: {tmp_devcontainer}")
    else:
        tmp_workspace = "<tmp_workspace>"
    launch_vscode_devcontainer(str(tmp_workspace), dry_run=args.dryrun)
