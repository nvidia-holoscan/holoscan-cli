# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from argparse import Namespace
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import install as install_cmd


def _dev_args(**overrides):
    defaults = {
        "dev": True,
        "uninstall": False,
        "project": None,
        "build_dir": None,
        "site_dir": None,
        "dryrun": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def test_install_dev_copies_staged_hook_pair(tmp_path):
    build_dir = tmp_path / "build" / "smoke"
    site_dir = tmp_path / "site"
    build_dir.mkdir(parents=True)
    (build_dir / "holoscan_smoke_dev.py").write_text("# helper\n", encoding="utf-8")
    (build_dir / "holoscan-smoke-dev.pth").write_text(
        "import holoscan_smoke_dev\n", encoding="utf-8"
    )
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")

    install_cmd.handle_install(cli, _dev_args(project="holoscan-smoke", site_dir=site_dir))

    assert (site_dir / "holoscan_smoke_dev.py").read_text(encoding="utf-8") == "# helper\n"
    assert (site_dir / "holoscan-smoke-dev.pth").exists()


def test_install_dev_uses_most_recent_hook_per_slug(tmp_path):
    old_dir = tmp_path / "build" / "old"
    new_dir = tmp_path / "build" / "new"
    site_dir = tmp_path / "site"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "holoscan_smoke_dev.py").write_text("# old\n", encoding="utf-8")
    (old_dir / "holoscan-smoke-dev.pth").write_text("import holoscan_smoke_dev\n", encoding="utf-8")
    (new_dir / "holoscan_smoke_dev.py").write_text("# new\n", encoding="utf-8")
    (new_dir / "holoscan-smoke-dev.pth").write_text("import holoscan_smoke_dev\n", encoding="utf-8")
    os.utime(old_dir / "holoscan_smoke_dev.py", (1, 1))
    os.utime(new_dir / "holoscan_smoke_dev.py", (2, 2))
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")

    install_cmd.handle_install(cli, _dev_args(project="smoke", site_dir=site_dir))

    assert (site_dir / "holoscan_smoke_dev.py").read_text(encoding="utf-8") == "# new\n"


def test_install_dev_uninstall_removes_hook_pair(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "holoscan-smoke-dev.pth").write_text("import holoscan_smoke_dev\n", encoding="utf-8")
    (site_dir / "holoscan_smoke_dev.py").write_text("# helper\n", encoding="utf-8")
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")

    install_cmd.handle_install(
        cli, _dev_args(project="holoscan-smoke", site_dir=site_dir, uninstall=True)
    )

    assert not (site_dir / "holoscan-smoke-dev.pth").exists()
    assert not (site_dir / "holoscan_smoke_dev.py").exists()


def test_install_requires_project_without_dev(tmp_path):
    cli = SimpleNamespace(DEFAULT_BUILD_PARENT_DIR=tmp_path / "build", script_name="holoscan")
    with pytest.raises(SystemExit):
        install_cmd.handle_install(cli, Namespace(dev=False, project=None))
