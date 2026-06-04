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

"""Tests for ``utils/docker.py:get_entrypoint_command_args``.

This is the helper every project lifecycle command (``build``, ``run``,
``install``, ``test``, ``run-container``) uses to turn an in-container
shell command into the right ``docker run`` argv shape. The function has
four behavioral branches and a recursion-into-``docker inspect`` path —
all of them want test coverage so the entrypoint contract for downstream
wrappers (which override images via ``--img``) doesn't quietly regress.
"""

from __future__ import annotations

import pytest

from holoscan_cli.utils import docker as utils_docker

# ---- user-supplied --entrypoint in docker_opts ------------------------------


@pytest.mark.parametrize("shell", ["/bin/sh", "/bin/bash", "sh", "bash"])
def test_user_shell_entrypoint_uses_dash_c(shell, monkeypatch):
    """When the caller passes ``--docker-opts='--entrypoint=<shell>'`` the
    helper must run ``-c <command>`` against that shell. Docker inspect
    is NOT consulted in this path (user wins)."""
    # Should not be called.
    monkeypatch.setattr(
        utils_docker, "get_container_entrypoint", lambda *a, **kw: pytest.fail("unexpected")
    )
    extra_opts, argv = utils_docker.get_entrypoint_command_args(
        "any:image", "echo hi", f"--entrypoint={shell}"
    )
    assert extra_opts == ""
    assert argv == ["-c", "echo hi"]


def test_user_non_shell_entrypoint_passes_command_as_args(monkeypatch):
    """A non-shell user entrypoint receives the command as plain argv —
    no ``-c`` wrapping."""
    monkeypatch.setattr(
        utils_docker, "get_container_entrypoint", lambda *a, **kw: pytest.fail("unexpected")
    )
    extra_opts, argv = utils_docker.get_entrypoint_command_args(
        "any:image", "python -m holoscan_cli list", "--entrypoint=/usr/bin/python3"
    )
    assert extra_opts == ""
    assert argv == ["python", "-m", "holoscan_cli", "list"]


# ---- image has no entrypoint -----------------------------------------------


def test_no_image_entrypoint_uses_bash_dash_c(monkeypatch):
    """No user entrypoint + image has no ENTRYPOINT → wrap with bash -c."""
    monkeypatch.setattr(utils_docker, "get_container_entrypoint", lambda *a, **kw: None)
    extra_opts, argv = utils_docker.get_entrypoint_command_args("img:tag", "echo hi", "")
    assert extra_opts == ""
    assert argv == ["/bin/bash", "-c", "echo hi"]


# ---- image has a shell entrypoint ------------------------------------------


@pytest.mark.parametrize(
    "image_entry",
    [
        ["/bin/sh", "-c"],
        ["/bin/bash", "-c"],
        ["sh", "-c"],
        ["bash", "-c"],
    ],
)
def test_image_shell_dash_c_entrypoint_takes_raw_command(image_entry, monkeypatch):
    """Image entrypoint is already a shell-with-``-c`` → just pass the
    command string as the single arg."""
    monkeypatch.setattr(utils_docker, "get_container_entrypoint", lambda *a, **kw: image_entry)
    extra_opts, argv = utils_docker.get_entrypoint_command_args("img:tag", "echo hi", "")
    assert extra_opts == ""
    assert argv == ["echo hi"]


@pytest.mark.parametrize("shell", ["/bin/sh", "/bin/bash", "sh", "bash"])
def test_image_bare_shell_entrypoint_gets_dash_c(shell, monkeypatch):
    """Image entrypoint is a shell but without -c (e.g. ``["bash"]``) →
    inject ``-c command`` so the command actually runs."""
    monkeypatch.setattr(utils_docker, "get_container_entrypoint", lambda *a, **kw: [shell])
    extra_opts, argv = utils_docker.get_entrypoint_command_args("img:tag", "echo hi", "")
    assert extra_opts == ""
    assert argv == ["-c", "echo hi"]


# ---- image has a non-shell entrypoint --------------------------------------


def test_image_non_shell_entrypoint_overrides_to_bash(monkeypatch):
    """Image entrypoint is something else (e.g. a tini binary or a custom
    runner) → override with ``--entrypoint=/bin/bash`` so the build/run
    command actually runs as a shell command."""
    monkeypatch.setattr(utils_docker, "get_container_entrypoint", lambda *a, **kw: ["/sbin/tini"])
    extra_opts, argv = utils_docker.get_entrypoint_command_args("img:tag", "echo hi", "")
    assert extra_opts == "--entrypoint=/bin/bash"
    assert argv == ["-c", "echo hi"]


# ---- dry_run skip-the-docker-inspect path ----------------------------------


def test_dry_run_short_circuits_to_no_entrypoint_branch(monkeypatch, capsys):
    """In dry-run mode ``get_container_entrypoint`` returns None without
    invoking docker, so the helper falls into the no-image-entrypoint
    branch (bash -c)."""
    # The real get_container_entrypoint logs a yellow hint message in
    # dry-run mode; we don't need to stub it — just call through.
    extra_opts, argv = utils_docker.get_entrypoint_command_args(
        "img:tag", "echo hi", "", dry_run=True
    )
    assert extra_opts == ""
    assert argv == ["/bin/bash", "-c", "echo hi"]
    # The helper prints a "would inspect" hint in dry-run mode.
    out = capsys.readouterr().out
    assert "docker inspect" in out


def test_get_image_pythonpath_dryrun_emits_inspect_hint(capsys):
    """`run-container --dryrun` must surface the PYTHONPATH inspect command
    so users see how the helper would look at the image. Pre-consolidation
    `test_holohub_run_pythonpath`."""
    result = utils_docker.get_image_pythonpath("holohub:smoke", dry_run=True)

    # Dry-run short-circuits to empty string — no real docker call.
    assert result == ""
    out = capsys.readouterr().out
    assert "Inspect docker image PYTHONPATH: docker inspect" in out
    assert "holohub:smoke" in out
