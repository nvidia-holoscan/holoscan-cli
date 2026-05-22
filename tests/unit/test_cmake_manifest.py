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

"""Tests for ``holoscan_cli.utils.cmake_manifest``.

Covers ``write_external_operators_manifest``: emits FetchContent
declarations through ``holohub_declare_external_module`` calls, supports
``FETCHCONTENT_SOURCE_DIR_<UPPER>`` overrides, warns on operator
collisions, and is idempotent on identical input. Also covers the
``_provider_id`` string helper.
"""

from __future__ import annotations

import re
from pathlib import Path

from holoscan_cli.utils.cmake_manifest import (
    _provider_id,
    write_external_operators_manifest,
)
from holoscan_cli.utils.external_resolver import ModuleDep

FULL_SHA = "0" * 40


# ---- _provider_id ------------------------------------------------------------


def test_provider_id_sanitises_hyphens():
    assert _provider_id("holoscan-example-utils") == "holoscan_example_utils"


def test_provider_id_keeps_alnum_and_underscore():
    assert _provider_id("mymod8_op") == "mymod8_op"


def test_provider_id_rejects_special_chars():
    assert _provider_id("Foo.Bar/Baz-Qux") == "Foo_Bar_Baz_Qux"


# ---- write_external_operators_manifest --------------------------------------


def _emit(tmp_path: Path, deps) -> str:
    out = tmp_path / "external_operators_manifest.cmake"
    write_external_operators_manifest(deps, out)
    return out.read_text()


def test_emits_declare_function_call(tmp_path):
    text = _emit(tmp_path, [ModuleDep(name="mymod", git_url="/tmp/x", ref=FULL_SHA)])
    assert "holohub_declare_external_module(mymod" in text


def test_emits_git_repository_and_tag(tmp_path):
    text = _emit(
        tmp_path,
        [ModuleDep(name="mymod", git_url="https://example.com/foo.git", ref="abc" + "0" * 37)],
    )
    assert 'GIT_REPOSITORY  "https://example.com/foo.git"' in text
    assert 'GIT_TAG         "' + "abc" + "0" * 37 + '"' in text


def test_provider_id_sanitised_in_declare(tmp_path):
    text = _emit(
        tmp_path,
        [ModuleDep(name="holoscan-example-utils", git_url="/x", ref=FULL_SHA)],
    )
    assert "holohub_declare_external_module(holoscan_example_utils" in text
    assert "holohub_declare_external_module(holoscan-example-utils" not in text


def test_emits_provides_operators_in_function_call(tmp_path):
    text = _emit(
        tmp_path,
        [
            ModuleDep(
                name="bigmod",
                git_url="/x",
                ref=FULL_SHA,
                provides_operators=["bigmod_signal_op", "bigmod_render_op"],
            )
        ],
    )
    # The function (defined in the consumer's CMake helpers) sets
    # HOLOHUB_EXT_OP_<op>_PROVIDER as normal variables at PARENT_SCOPE.
    # The manifest must NOT emit them as raw set() calls.
    assert "PROVIDES_OPERATORS bigmod_signal_op bigmod_render_op" in text
    assert not re.search(r"set\(HOLOHUB_EXT_OP_\S+_PROVIDER\b", text)


def test_no_provides_operators_when_empty(tmp_path):
    text = _emit(tmp_path, [ModuleDep(name="mymod", git_url="/x", ref=FULL_SHA)])
    assert "PROVIDES_OPERATORS" not in text
    assert not re.search(r"set\(HOLOHUB_EXT_OP_\S+_PROVIDER\b", text)


def test_local_override_emits_source_dir_var(tmp_path):
    text = _emit(
        tmp_path,
        [
            ModuleDep(
                name="mymod",
                override_path=Path("/abs/path/to/mymod"),
                provides_operators=["mymod_op"],
            )
        ],
    )
    idx_src = text.find("FETCHCONTENT_SOURCE_DIR_MYMOD")
    idx_decl = text.find("holohub_declare_external_module(mymod")
    assert idx_src > -1
    assert idx_decl > -1
    # The override line must precede the function call so the override is
    # visible at MakeAvailable time.
    assert idx_src < idx_decl
    assert '"/abs/path/to/mymod"' in text
    assert "FORCE" in text


def test_local_override_only_forwards_source_dir(tmp_path):
    text = _emit(tmp_path, [ModuleDep(name="mymod", override_path=Path("/abs/local"))])
    assert "holohub_declare_external_module(mymod" in text
    assert 'SOURCE_DIR  "/abs/local"' in text


def test_operator_collision_warns_and_keeps_latter(tmp_path, capsys):
    deps = [
        ModuleDep(name="modA", git_url="/x", ref=FULL_SHA, provides_operators=["shared_op"]),
        ModuleDep(name="modB", git_url="/y", ref=FULL_SHA, provides_operators=["shared_op"]),
    ]
    out = tmp_path / "manifest.cmake"
    write_external_operators_manifest(deps, out)
    text = out.read_text()
    err = capsys.readouterr().err
    assert "holohub_declare_external_module(modA" in text
    assert "holohub_declare_external_module(modB" in text
    assert "WARNING" in err
    assert "shared_op" in err
    assert "modA" in err and "modB" in err


def test_writing_twice_is_idempotent(tmp_path):
    deps = [
        ModuleDep(
            name="mymod",
            git_url="/x",
            ref=FULL_SHA,
            provides_operators=["mymod_op"],
        )
    ]
    assert _emit(tmp_path, deps) == _emit(tmp_path, deps)


def test_in_tree_module_emits_comment_only(tmp_path):
    text = _emit(
        tmp_path,
        [
            ModuleDep(
                name="holoscan-gstreamer",
                provides_operators=["gstreamer"],
                override_path=Path("/repo/modules/holoscan-gstreamer"),
                is_internal=True,
            )
        ],
    )
    assert "holoscan-gstreamer (in-tree: /repo/modules/holoscan-gstreamer)" in text
    assert "gstreamer" in text
    assert not re.search(r"^holohub_declare_external_module\s*\(", text, re.MULTILINE)
    assert "FETCHCONTENT_SOURCE_DIR" not in text
    assert "GIT_REPOSITORY" not in text


def test_empty_deps_writes_minimal_skeleton(tmp_path):
    text = _emit(tmp_path, [])
    assert not re.search(r"holohub_declare_external_module\s*\(", text)
    assert not re.search(r"FetchContent_Declare\s*\(", text)
    assert not re.search(r"set\(HOLOHUB_EXT_OP_\S+_PROVIDER\b", text)
    assert "CACHE" not in text
