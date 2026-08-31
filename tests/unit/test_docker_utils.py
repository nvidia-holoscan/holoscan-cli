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

import subprocess
from argparse import Namespace

import pytest

from holoscan_cli.utils import docker as utils_docker


def test_resolve_cli_docker_opts_merges_repeated_fragments():
    value = utils_docker.resolve_cli_docker_opts(
        Namespace(docker_opts=["--env 'NAME=value with spaces'", "--network=host"])
    )

    assert value == "--env 'NAME=value with spaces' --network=host"


def _write_cgroup_files(tmp_path, *, cgroup: str, mountinfo: str):
    proc_root = tmp_path / "proc"
    (proc_root / "self").mkdir(parents=True)
    (proc_root / "self" / "cgroup").write_text(cgroup, encoding="utf-8")
    (proc_root / "self" / "mountinfo").write_text(mountinfo, encoding="utf-8")
    return proc_root


def test_effective_cpu_set_uses_cgroup_v2_quota(tmp_path, monkeypatch):
    cgroup_mount = tmp_path / "cgroup"
    current = cgroup_mount / "job"
    current.mkdir(parents=True)
    (current / "cpu.max").write_text("200000 100000\n", encoding="utf-8")
    proc_root = _write_cgroup_files(
        tmp_path,
        cgroup="0::/job\n",
        mountinfo=f"1 0 0:1 / {cgroup_mount} rw - cgroup2 cgroup rw\n",
    )
    monkeypatch.setattr(utils_docker.os, "sched_getaffinity", lambda _pid: set(range(8)))
    monkeypatch.setattr(utils_docker.os, "cpu_count", lambda: 8)

    assert utils_docker.get_effective_cpu_set(proc_root=proc_root) == "0,1"


def test_effective_cpu_set_uses_cgroup_v2_ancestor_quota(tmp_path, monkeypatch):
    cgroup_mount = tmp_path / "cgroup"
    current = cgroup_mount / "container"
    current.mkdir(parents=True)
    (current / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    (cgroup_mount / "cpu.max").write_text("300000 100000\n", encoding="utf-8")
    proc_root = _write_cgroup_files(
        tmp_path,
        cgroup="0::/pod/container\n",
        mountinfo=f"1 0 0:1 /pod {cgroup_mount} rw - cgroup2 cgroup rw\n",
    )
    monkeypatch.setattr(utils_docker.os, "sched_getaffinity", lambda _pid: set(range(8)))
    monkeypatch.setattr(utils_docker.os, "cpu_count", lambda: 8)

    assert utils_docker.get_effective_cpu_set(proc_root=proc_root) == "0,1,2"


def test_effective_cpu_set_prefers_v1_cpu_controller_on_hybrid_host(tmp_path, monkeypatch):
    cgroup_v2_mount = tmp_path / "unified"
    cgroup_v2_mount.mkdir()
    (cgroup_v2_mount / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    cpu_mount = tmp_path / "cpu"
    cpu_job = cpu_mount / "job"
    cpu_job.mkdir(parents=True)
    (cpu_job / "cpu.cfs_quota_us").write_text("200000\n", encoding="utf-8")
    (cpu_job / "cpu.cfs_period_us").write_text("100000\n", encoding="utf-8")
    proc_root = _write_cgroup_files(
        tmp_path,
        cgroup="0::/\n2:cpu,cpuacct:/job\n",
        mountinfo=(
            f"1 0 0:1 / {cgroup_v2_mount} rw - cgroup2 cgroup rw\n"
            f"2 0 0:2 / {cpu_mount} rw - cgroup cgroup rw,cpu,cpuacct\n"
        ),
    )
    monkeypatch.setattr(utils_docker.os, "sched_getaffinity", lambda _pid: set(range(8)))
    monkeypatch.setattr(utils_docker.os, "cpu_count", lambda: 8)

    assert utils_docker.get_effective_cpu_set(proc_root=proc_root) == "0,1"


@pytest.mark.parametrize(
    ("quota", "period", "expected"),
    [("150000", "100000", "0,1"), ("-1", "100000", None), ("100000", "0", None)],
)
def test_effective_cpu_set_uses_cgroup_v1_quota(tmp_path, monkeypatch, quota, period, expected):
    cpu_mount = tmp_path / "cpu"
    current = cpu_mount / "container"
    current.mkdir(parents=True)
    (current / "cpu.cfs_quota_us").write_text(f"{quota}\n", encoding="utf-8")
    (current / "cpu.cfs_period_us").write_text(f"{period}\n", encoding="utf-8")
    proc_root = _write_cgroup_files(
        tmp_path,
        cgroup="2:cpu,cpuacct:/pod/container\n",
        mountinfo=(
            f"1 0 0:1 /unrelated {tmp_path / 'unrelated'} rw - cgroup cgroup rw,cpu\n"
            f"2 0 0:2 /pod {cpu_mount} rw - cgroup cgroup rw,cpu,cpuacct\n"
        ),
    )
    monkeypatch.setattr(utils_docker.os, "sched_getaffinity", lambda _pid: set(range(8)))
    monkeypatch.setattr(utils_docker.os, "cpu_count", lambda: 8)

    assert utils_docker.get_effective_cpu_set(proc_root=proc_root) == expected


@pytest.mark.parametrize(
    ("affinity", "expected"),
    [
        ({0, 2, 4}, "0,2,4"),
        (set(range(8)), None),
    ],
)
def test_effective_cpu_set_respects_existing_affinity(tmp_path, monkeypatch, affinity, expected):
    cgroup_mount = tmp_path / "cgroup"
    cgroup_mount.mkdir()
    (cgroup_mount / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    proc_root = _write_cgroup_files(
        tmp_path,
        cgroup="0::/\n",
        mountinfo=f"1 0 0:1 / {cgroup_mount} rw - cgroup2 cgroup rw\n",
    )
    monkeypatch.setattr(utils_docker.os, "sched_getaffinity", lambda _pid: affinity)
    monkeypatch.setattr(utils_docker.os, "cpu_count", lambda: 8)

    assert utils_docker.get_effective_cpu_set(proc_root=proc_root) == expected


def test_effective_cpu_set_fails_open_without_affinity(tmp_path, monkeypatch):
    proc_root = _write_cgroup_files(tmp_path, cgroup="malformed\n", mountinfo="malformed\n")
    monkeypatch.delattr(utils_docker.os, "sched_getaffinity", raising=False)

    assert utils_docker.get_effective_cpu_set(proc_root=proc_root) is None


def test_effective_cpu_set_keeps_restricted_affinity_when_cgroup_is_unreadable(
    tmp_path, monkeypatch
):
    proc_root = _write_cgroup_files(tmp_path, cgroup="malformed\n", mountinfo="malformed\n")
    monkeypatch.setattr(utils_docker.os, "sched_getaffinity", lambda _pid: {1, 3})
    monkeypatch.setattr(utils_docker.os, "cpu_count", lambda: 8)

    assert utils_docker.get_effective_cpu_set(proc_root=proc_root) == "1,3"


def test_docker_build_resource_support_is_cached(monkeypatch):
    calls = []

    def docker_help(args, **kwargs):
        calls.append(args)
        help_text = "--resource stringArray" if args[0] == "docker-new" else "--tag string"
        return subprocess.CompletedProcess(args, 0, stdout=help_text)

    monkeypatch.setattr(utils_docker.subprocess, "run", docker_help)

    assert utils_docker.docker_build_supports_resource("docker-new") is True
    assert utils_docker.docker_build_supports_resource("docker-new") is True
    assert utils_docker.docker_build_supports_resource("docker-old") is False
    assert utils_docker.docker_build_supports_resource("docker-old") is False
    assert len(calls) == 2


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
