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

import os
from types import SimpleNamespace

from holoscan_cli import cli as project_cli
from holoscan_cli import container as project_container
from holoscan_cli.cli import in_container_cli_command
from holoscan_cli.commands.test_cmd import _ctest_script_arg


def test_in_container_cli_command_defaults_to_holoscan(monkeypatch):
    monkeypatch.delenv("HOLOSCAN_CLI_IN_CONTAINER_CMD", raising=False)
    assert in_container_cli_command() == "holoscan"


def test_in_container_cli_command_ignores_holohub_cmd_name(monkeypatch):
    monkeypatch.delenv("HOLOSCAN_CLI_IN_CONTAINER_CMD", raising=False)
    monkeypatch.setenv("HOLOHUB_CMD_NAME", "./holohub")
    assert in_container_cli_command() == "holoscan"


def test_in_container_cli_command_honors_override(monkeypatch):
    monkeypatch.setenv("HOLOSCAN_CLI_IN_CONTAINER_CMD", "python3 -m holoscan_cli")
    assert in_container_cli_command() == "python3 -m holoscan_cli"


def _make_container() -> project_container.HoloHubContainer:
    return project_container.HoloHubContainer({"metadata": {"language": "python"}})


def test_environment_args_forward_path_prefix(monkeypatch):
    monkeypatch.delenv("HOLOHUB_PATH_PREFIX", raising=False)
    monkeypatch.delenv("HOLOHUB_SEARCH_PATH", raising=False)
    monkeypatch.delenv("HOLOHUB_CTEST_SCRIPT", raising=False)
    monkeypatch.setenv("HOLOHUB_PATH_PREFIX", "isaac")

    args = _make_container().get_environment_args()

    assert "HOLOHUB_PATH_PREFIX=isaac" in args
    assert all(
        not a.startswith("HOLOHUB_SEARCH_PATH=") for a in args
    ), "HOLOHUB_SEARCH_PATH must not be forwarded when unset"


def test_environment_args_forward_search_path(monkeypatch):
    monkeypatch.delenv("HOLOHUB_PATH_PREFIX", raising=False)
    monkeypatch.delenv("HOLOHUB_CTEST_SCRIPT", raising=False)
    monkeypatch.setenv(
        "HOLOHUB_SEARCH_PATH",
        "tutorials,applications,benchmarks,subgraphs,operators",
    )

    args = _make_container().get_environment_args()

    expected = "HOLOHUB_SEARCH_PATH=tutorials,applications,benchmarks,subgraphs,operators"
    assert expected in args


def test_environment_args_forward_ctest_script(monkeypatch):
    monkeypatch.delenv("HOLOHUB_PATH_PREFIX", raising=False)
    monkeypatch.delenv("HOLOHUB_SEARCH_PATH", raising=False)
    monkeypatch.setenv("HOLOHUB_CTEST_SCRIPT", "cmake/isaac_os.container.ctest")

    args = _make_container().get_environment_args()

    assert "HOLOHUB_CTEST_SCRIPT=cmake/isaac_os.container.ctest" in args


def test_environment_args_omits_unset_wrapper_vars(monkeypatch):
    for var in ("HOLOHUB_PATH_PREFIX", "HOLOHUB_SEARCH_PATH", "HOLOHUB_CTEST_SCRIPT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("HOLOHUB_ENABLE_SCCACHE", raising=False)
    for var in list(os.environ):
        if var.startswith("SCCACHE_"):
            monkeypatch.delenv(var, raising=False)

    args = _make_container().get_environment_args()

    forwarded = [a for a in args if a.startswith("HOLOHUB_")]
    assert forwarded == [
        "HOLOHUB_BUILD_LOCAL=1"
    ], f"Only the always-on HOLOHUB_BUILD_LOCAL should be present; got: {forwarded}"


def test_local_source_build_context_args_empty_when_unset(monkeypatch):
    monkeypatch.delenv("HOLOSCAN_CLI_SOURCE", raising=False)
    assert project_container.HoloHubContainer.local_source_build_context_args() == []


def test_local_source_build_context_args_emits_named_context(monkeypatch):
    monkeypatch.setenv("HOLOSCAN_CLI_SOURCE", "/home/wenqil/Documents/holoscan-cli")

    args = project_container.HoloHubContainer.local_source_build_context_args()

    assert args == [
        "--build-context",
        "holoscan-cli-src=/home/wenqil/Documents/holoscan-cli",
    ]


def _bare_cli() -> project_cli.HoloHubCLI:
    return object.__new__(project_cli.HoloHubCLI)


def test_ctest_script_arg_uses_user_override():
    cli = _bare_cli()
    args = SimpleNamespace(ctest_script="cmake/isaac_os.container.ctest")

    assert _ctest_script_arg(cli, args, in_container=True) == "-S cmake/isaac_os.container.ctest"
    assert _ctest_script_arg(cli, args, in_container=False) == "-S cmake/isaac_os.container.ctest"


def test_ctest_script_arg_local_uses_host_resolved_path(monkeypatch):
    cli = _bare_cli()
    monkeypatch.setattr(
        project_cli.HoloHubCLI, "DEFAULT_CTEST_SCRIPT", "/host/path/holohub.container.ctest"
    )
    args = SimpleNamespace(ctest_script=None)

    assert (
        _ctest_script_arg(cli, args, in_container=False) == "-S /host/path/holohub.container.ctest"
    )


def test_ctest_script_arg_container_defers_resolution_to_runtime():
    cli = _bare_cli()
    args = SimpleNamespace(ctest_script=None)

    rendered = _ctest_script_arg(cli, args, in_container=True)

    assert rendered.startswith('-S "$(python3 -c '), rendered
    assert "from holoscan_cli.cli import HoloHubCLI" in rendered
    assert "HoloHubCLI.DEFAULT_CTEST_SCRIPT" in rendered
    assert "/host/" not in rendered, "must not bake host paths into the in-container command"
