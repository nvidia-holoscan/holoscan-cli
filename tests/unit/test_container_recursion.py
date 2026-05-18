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
    """The HOLOHUB_CMD_NAME deprecation alias is gone — the env var is ignored."""
    monkeypatch.delenv("HOLOSCAN_CLI_IN_CONTAINER_CMD", raising=False)
    monkeypatch.setenv("HOLOHUB_CMD_NAME", "./holohub")
    assert in_container_cli_command() == "holoscan"


def test_in_container_cli_command_honors_override(monkeypatch):
    monkeypatch.setenv("HOLOSCAN_CLI_IN_CONTAINER_CMD", "python3 -m holoscan_cli")
    assert in_container_cli_command() == "python3 -m holoscan_cli"


def _make_container() -> project_container.HoloscanContainer:
    return project_container.HoloscanContainer({"metadata": {"language": "python"}})


def _delenv_wrapper_vars(monkeypatch) -> None:
    """Clear the canonical HOLOSCAN_CLI_* wrapper vars."""
    for suffix in ("PATH_PREFIX", "SEARCH_PATH", "CTEST_SCRIPT"):
        monkeypatch.delenv(f"HOLOSCAN_CLI_{suffix}", raising=False)


def test_environment_args_forward_path_prefix(monkeypatch):
    _delenv_wrapper_vars(monkeypatch)
    monkeypatch.setenv("HOLOSCAN_CLI_PATH_PREFIX", "isaac")

    args = _make_container().get_environment_args()

    assert "HOLOSCAN_CLI_PATH_PREFIX=isaac" in args
    # Legacy HOLOHUB_* spelling is no longer forwarded.
    assert "HOLOHUB_PATH_PREFIX=isaac" not in args
    assert all(
        not a.startswith("HOLOSCAN_CLI_SEARCH_PATH=") for a in args
    ), "search path must not be forwarded when unset"


def test_environment_args_forward_search_path(monkeypatch):
    _delenv_wrapper_vars(monkeypatch)
    monkeypatch.setenv(
        "HOLOSCAN_CLI_SEARCH_PATH",
        "tutorials,applications,benchmarks,subgraphs,operators",
    )

    args = _make_container().get_environment_args()

    expected_value = "tutorials,applications,benchmarks,subgraphs,operators"
    assert f"HOLOSCAN_CLI_SEARCH_PATH={expected_value}" in args
    assert f"HOLOHUB_SEARCH_PATH={expected_value}" not in args


def test_environment_args_forward_ctest_script(monkeypatch):
    _delenv_wrapper_vars(monkeypatch)
    monkeypatch.setenv("HOLOSCAN_CLI_CTEST_SCRIPT", "cmake/isaac_os.container.ctest")

    args = _make_container().get_environment_args()

    assert "HOLOSCAN_CLI_CTEST_SCRIPT=cmake/isaac_os.container.ctest" in args
    assert "HOLOHUB_CTEST_SCRIPT=cmake/isaac_os.container.ctest" not in args


def test_environment_args_omits_unset_wrapper_vars(monkeypatch):
    _delenv_wrapper_vars(monkeypatch)
    monkeypatch.delenv("HOLOSCAN_CLI_ENABLE_SCCACHE", raising=False)
    for var in list(os.environ):
        if var.startswith("SCCACHE_"):
            monkeypatch.delenv(var, raising=False)

    args = _make_container().get_environment_args()

    # The always-on HOLOSCAN_CLI_BUILD_LOCAL=1 is the only wrapper-var that
    # should appear; nothing else.
    forwarded = [a for a in args if a.startswith(("HOLOSCAN_CLI_", "HOLOHUB_"))]
    assert forwarded == [
        "HOLOSCAN_CLI_BUILD_LOCAL=1"
    ], f"Only the always-on BUILD_LOCAL var should be present; got: {forwarded}"


def test_environment_args_forward_sccache_canonical_name_only(monkeypatch):
    _delenv_wrapper_vars(monkeypatch)
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "true")
    monkeypatch.setenv("SCCACHE_BUCKET", "holoscan-cache")
    monkeypatch.delenv("SCCACHE_DIR", raising=False)

    args = _make_container().get_environment_args()

    assert "HOLOSCAN_CLI_ENABLE_SCCACHE" in args
    assert "SCCACHE_DIR=/.cache/sccache" in args
    assert "SCCACHE_BUCKET" in args
    assert all(not a.startswith("HOLOHUB_") for a in args)


def test_local_source_build_context_args_empty_when_unset(monkeypatch):
    monkeypatch.delenv("HOLOSCAN_CLI_SOURCE", raising=False)
    assert project_container.HoloscanContainer.local_source_build_context_args() == []


def test_local_source_build_context_args_emits_named_context(monkeypatch):
    monkeypatch.setenv("HOLOSCAN_CLI_SOURCE", "/tmp/cli-src")

    args = project_container.HoloscanContainer.local_source_build_context_args()

    assert args == [
        "--build-context",
        "holoscan-cli-src=/tmp/cli-src",
    ]


def _bare_cli() -> project_cli.HoloscanCLI:
    return object.__new__(project_cli.HoloscanCLI)


def test_ctest_script_arg_uses_user_override():
    cli = _bare_cli()
    args = SimpleNamespace(ctest_script="cmake/isaac_os.container.ctest")

    assert _ctest_script_arg(cli, args, in_container=True) == "-S cmake/isaac_os.container.ctest"
    assert _ctest_script_arg(cli, args, in_container=False) == "-S cmake/isaac_os.container.ctest"


def test_ctest_script_arg_local_uses_host_resolved_path(monkeypatch):
    cli = _bare_cli()
    monkeypatch.setattr(
        project_cli.HoloscanCLI, "DEFAULT_CTEST_SCRIPT", "/host/path/container.ctest"
    )
    args = SimpleNamespace(ctest_script=None)

    assert _ctest_script_arg(cli, args, in_container=False) == "-S /host/path/container.ctest"


def test_ctest_script_arg_container_defers_resolution_to_runtime():
    cli = _bare_cli()
    args = SimpleNamespace(ctest_script=None)

    rendered = _ctest_script_arg(cli, args, in_container=True)

    assert rendered.startswith('-S "$(python3 -c '), rendered
    assert "from holoscan_cli.cli import HoloscanCLI" in rendered
    assert "HoloscanCLI.DEFAULT_CTEST_SCRIPT" in rendered
    assert "/host/" not in rendered, "must not bake host paths into the in-container command"
