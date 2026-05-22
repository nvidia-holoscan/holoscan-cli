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

"""Behavior tests for ``holoscan create`` against module templates.

Exercises the module-template branch added in ``commands/create.py``
without invoking cookiecutter or shell subprocesses:

* ``--template`` paths whose first component is ``modules`` are detected
  as module templates.
* Module templates require an explicit output ``--directory`` (prompted
  if omitted) and use a kebab ``holoscan-<slug>`` output folder.
* The dryrun branch reports the correct intended directory and skips
  the CMakeLists update.
* The next-steps message diverges between application and module
  templates.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from holoscan_cli.commands import create


def _make_args(**overrides) -> argparse.Namespace:
    """Build a ``--dryrun``-shaped Namespace with sensible defaults."""
    defaults = dict(
        project="My Mod",
        template="modules/template",
        language="python",
        dryrun=True,
        directory=None,
        context=None,
        interactive=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture()
def fake_cli(tmp_path):
    """Stand-in for the real ``HoloscanCLI`` — handle_create only reads
    ``HOLOHUB_ROOT`` and ``script_name``."""
    return SimpleNamespace(HOLOHUB_ROOT=tmp_path, script_name="holoscan")


# ---- dryrun smoke ------------------------------------------------------------


def test_dryrun_module_template_uses_kebab_output_folder(fake_cli, tmp_path, capsys):
    out_dir = tmp_path / "ext"
    out_dir.mkdir()
    args = _make_args(directory=out_dir)
    create.handle_create(fake_cli, args)

    captured = capsys.readouterr().out
    # holoscan-my_mod -> the slug is "my_mod"; kebab swap gives holoscan-my-mod
    assert str(out_dir / "holoscan-my-mod") in captured
    # Module templates must NOT trigger the applications/CMakeLists.txt path.
    assert "applications/CMakeLists.txt" not in captured


def test_dryrun_application_template_uses_slug_output_folder(fake_cli, tmp_path, capsys):
    # Make the default output directory exist so the existence check passes.
    (tmp_path / "applications").mkdir()
    args = _make_args(template="applications/template", dryrun=True)
    create.handle_create(fake_cli, args)

    captured = capsys.readouterr().out
    assert str(tmp_path / "applications" / "my_mod") in captured
    # Applications scaffolded under HOLOHUB_ROOT/applications/ trigger the
    # CMakeLists hint.
    assert "applications/CMakeLists.txt" in captured


def test_module_template_prompts_for_directory_when_omitted(
    fake_cli, tmp_path, capsys, monkeypatch
):
    """When ``--directory`` is omitted for a module template, ``handle_create``
    prompts via ``input()``. The path the user provides is honored."""
    out_dir = tmp_path / "user-typed"
    out_dir.mkdir()
    monkeypatch.setattr("builtins.input", lambda _prompt="": str(out_dir))

    args = _make_args(directory=None)
    create.handle_create(fake_cli, args)

    captured = capsys.readouterr().out
    assert str(out_dir / "holoscan-my-mod") in captured


def test_module_template_empty_prompt_input_is_fatal(fake_cli, monkeypatch):
    """An empty response to the directory prompt aborts."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    args = _make_args(directory=None)
    with pytest.raises(SystemExit):
        create.handle_create(fake_cli, args)


# ---- detection edge cases ----------------------------------------------------


@pytest.mark.parametrize(
    "template,is_module",
    [
        ("modules/template", True),
        ("modules/foo/bar", True),
        ("applications/template", False),
        # Substring "modules" inside another segment must NOT match — the
        # detection keys on full path parts.
        ("my_modules_collection/template", False),
        ("workflows/some-modules-thing", False),
    ],
)
def test_module_template_detection_keys_on_path_parts(
    fake_cli, tmp_path, template, is_module, capsys
):
    """The module-template detection must key on whole path segments,
    not substrings. Otherwise paths like ``my_modules_collection/`` would
    wrongly hit the module branch."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    args = _make_args(template=template, directory=out_dir)
    create.handle_create(fake_cli, args)
    captured = capsys.readouterr().out

    if is_module:
        assert str(out_dir / "holoscan-my-mod") in captured
    else:
        assert str(out_dir / "my_mod") in captured


# ---- parser surface ----------------------------------------------------------


def test_directory_argument_defaults_to_none():
    """Module templates need ``--directory`` to default to ``None`` so the
    handler can decide whether to prompt or fall back to ``applications/``.
    Pinning this prevents an accidental revert to the old behaviour where
    ``--directory`` defaulted eagerly to ``applications/`` (which made the
    module-template prompt unreachable)."""
    parser = argparse.ArgumentParser()
    cli_stub = SimpleNamespace(HOLOHUB_ROOT=Path("/dev/null"), script_name="holoscan")
    sub = parser.add_subparsers()
    create.register_create_parser(cli_stub, sub)
    ns = parser.parse_args(["create", "MyProj"])
    assert ns.directory is None
