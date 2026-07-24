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

"""Tests for ``holoscan_cli.utils.external_resolver``.

Covers:
  - ``parse_module_dependencies`` reading metadata.json:dependencies.modules
    from application/benchmark shapes and the flat ``module.dependencies``
    array; honoring ``HOLOSCAN_CLI_LOCAL_<NAME>``; skipping malformed entries.
  - String helpers ``_override_env_name`` and ``_ref_is_immutable``.
"""

from __future__ import annotations

import json

import pytest

from holoscan_cli.utils.external_resolver import (
    ModuleDep,
    _override_env_name,
    _ref_is_immutable,
    merge_deps,
    parse_module_dependencies,
    parse_module_sites,
)

FULL_SHA = "0" * 40


def _write_metadata(tmp_path, payload: dict):
    p = tmp_path / "metadata.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---- string helpers ----------------------------------------------------------


def test_override_env_name_uppercases_and_underscores():
    assert (
        _override_env_name("holoscan-example-utils") == "HOLOSCAN_CLI_LOCAL_HOLOSCAN_EXAMPLE_UTILS"
    )


def test_override_env_name_collapses_non_alnum():
    assert _override_env_name("foo.bar/baz") == "HOLOSCAN_CLI_LOCAL_FOO_BAR_BAZ"


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("abcdef0123456789abcdef0123456789abcdef01", True),
        ("abcdef0", False),  # short hex
        ("v1.0.0", False),  # tag
        ("main", False),  # branch
        ("", False),
        ("X" * 40, False),  # right length, wrong charset
    ],
)
def test_ref_is_immutable(ref, expected):
    assert _ref_is_immutable(ref) is expected


# ---- shape detection ---------------------------------------------------------


def test_parses_application_dependencies_modules_shape(tmp_path):
    meta = _write_metadata(
        tmp_path,
        {
            "application": {
                "dependencies": {
                    "operators": ["mymod8_op"],
                    "modules": [
                        {
                            "name": "mymod8",
                            "source": {"git_url": "/tmp/x", "ref": FULL_SHA},
                            "provides_operators": ["mymod8_op"],
                        }
                    ],
                }
            }
        },
    )
    deps = parse_module_dependencies(meta)
    assert deps == [
        ModuleDep(
            name="mymod8",
            git_url="/tmp/x",
            ref=FULL_SHA,
            provides_operators=["mymod8_op"],
        )
    ]


def test_parses_module_metadata_flat_dependencies_array(tmp_path):
    meta = _write_metadata(
        tmp_path,
        {
            "module": {
                "name": "holoscan-mymod",
                "authors": [{"name": "X", "affiliation": "Y"}],
                "version": "1.0.0",
                "language": ["C++"],
                "platforms": ["x86_64"],
                "tags": [],
                "holoscan_sdk": {
                    "minimum_required_version": "4.0",
                    "tested_versions": ["4.0"],
                },
                "dependencies": [
                    {"name": "transitive-dep", "source": {"git_url": "/tmp/x", "ref": FULL_SHA}}
                ],
            }
        },
    )
    deps = parse_module_dependencies(meta)
    assert [d.name for d in deps] == ["transitive-dep"]


@pytest.mark.parametrize("outer", ["application", "benchmark"])
def test_parses_application_and_benchmark_shapes(tmp_path, outer):
    meta = _write_metadata(
        tmp_path,
        {
            outer: {
                "dependencies": {
                    "modules": [
                        {"name": f"{outer}_mod", "source": {"git_url": "/tmp/x", "ref": FULL_SHA}}
                    ]
                }
            }
        },
    )
    deps = parse_module_dependencies(meta)
    assert [d.name for d in deps] == [f"{outer}_mod"]


# ---- empty / missing handling -----------------------------------------------


def test_missing_metadata_file_returns_empty(tmp_path):
    assert parse_module_dependencies(tmp_path / "does_not_exist.json") == []


def test_no_dependencies_field_returns_empty(tmp_path):
    meta = _write_metadata(tmp_path, {"application": {}})
    assert parse_module_dependencies(meta) == []


def test_dependencies_without_modules_subfield(tmp_path):
    meta = _write_metadata(tmp_path, {"application": {"dependencies": {"operators": ["foo"]}}})
    assert parse_module_dependencies(meta) == []


def test_malformed_json_raises_value_error(tmp_path):
    p = tmp_path / "metadata.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed JSON"):
        parse_module_dependencies(p)


def test_entry_without_name_is_skipped(tmp_path):
    meta = _write_metadata(
        tmp_path,
        {
            "application": {
                "dependencies": {
                    "modules": [
                        {"source": {"git_url": "/tmp/x", "ref": FULL_SHA}},  # no name
                        {"name": "ok", "source": {"git_url": "/tmp/y", "ref": FULL_SHA}},
                    ]
                }
            }
        },
    )
    deps = parse_module_dependencies(meta)
    assert [d.name for d in deps] == ["ok"]


# ---- source / ref validation -------------------------------------------------


def test_missing_source_raises_when_no_override(tmp_path):
    meta = _write_metadata(
        tmp_path,
        {"application": {"dependencies": {"modules": [{"name": "mod_no_source"}]}}},
    )
    with pytest.raises(ValueError, match="missing source.git_url or source.ref"):
        parse_module_dependencies(meta)


def test_branch_ref_warns_but_succeeds(tmp_path, capsys):
    meta = _write_metadata(
        tmp_path,
        {
            "application": {
                "dependencies": {
                    "modules": [
                        {"name": "mod_branch", "source": {"git_url": "/tmp/x", "ref": "main"}}
                    ]
                }
            }
        },
    )
    deps = parse_module_dependencies(meta)
    assert len(deps) == 1
    assert "not a 40-char commit SHA" in capsys.readouterr().err


def test_full_sha_does_not_warn(tmp_path, capsys):
    meta = _write_metadata(
        tmp_path,
        {
            "application": {
                "dependencies": {
                    "modules": [
                        {"name": "mod_sha", "source": {"git_url": "/tmp/x", "ref": FULL_SHA}}
                    ]
                }
            }
        },
    )
    parse_module_dependencies(meta)
    assert "not a 40-char commit SHA" not in capsys.readouterr().err


# ---- HOLOSCAN_CLI_LOCAL_<NAME> override ------------------------------------------


@pytest.fixture
def _clean_local_override_env(monkeypatch):
    """Strip any pre-existing ``HOLOSCAN_CLI_LOCAL_*`` env vars from the test
    environment so they don't mask the cases below. The fixture restores
    automatically via monkeypatch's teardown."""
    for key in [k for k in list(__import__("os").environ) if k.startswith("HOLOSCAN_CLI_LOCAL_")]:
        monkeypatch.delenv(key, raising=False)


def test_local_override_populates_override_path(tmp_path, monkeypatch, _clean_local_override_env):
    override_dir = tmp_path / "local_mod"
    override_dir.mkdir()
    (override_dir / "metadata.json").write_text("{}", encoding="utf-8")

    meta = _write_metadata(
        tmp_path,
        {
            "application": {
                "dependencies": {
                    "modules": [
                        {
                            "name": "mymod",
                            "source": {"git_url": "/should/not/be/used", "ref": FULL_SHA},
                        }
                    ]
                }
            }
        },
    )
    monkeypatch.setenv("HOLOSCAN_CLI_LOCAL_MYMOD", str(override_dir))
    deps = parse_module_dependencies(meta)
    assert deps[0].override_path == override_dir.resolve()


def test_local_override_without_metadata_raises(tmp_path, monkeypatch, _clean_local_override_env):
    bad_dir = tmp_path / "no_metadata"
    bad_dir.mkdir()
    meta = _write_metadata(
        tmp_path,
        {
            "application": {
                "dependencies": {
                    "modules": [{"name": "mymod", "source": {"git_url": "/x", "ref": FULL_SHA}}]
                }
            }
        },
    )
    monkeypatch.setenv("HOLOSCAN_CLI_LOCAL_MYMOD", str(bad_dir))
    with pytest.raises(FileNotFoundError, match="metadata.json"):
        parse_module_dependencies(meta)


def test_local_override_skips_source_validation(tmp_path, monkeypatch, _clean_local_override_env):
    # No source block at all is fine when the override is set — the CLI
    # doesn't need to fetch.
    override_dir = tmp_path / "ok_override"
    override_dir.mkdir()
    (override_dir / "metadata.json").write_text("{}", encoding="utf-8")

    meta = _write_metadata(
        tmp_path, {"application": {"dependencies": {"modules": [{"name": "mymod"}]}}}
    )
    monkeypatch.setenv("HOLOSCAN_CLI_LOCAL_MYMOD", str(override_dir))
    deps = parse_module_dependencies(meta)
    assert deps[0].override_path == override_dir.resolve()
    assert deps[0].git_url is None


# ---- in-tree module resolution ----------------------------------------------


def _make_in_tree_module(source_root, name: str):
    module_dir = source_root / "modules" / name
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "metadata.json").write_text(
        json.dumps({"$schema": "holoscan/module/v2", "module": {"name": name}}),
        encoding="utf-8",
    )
    return module_dir


def test_in_tree_module_recognized(tmp_path, _clean_local_override_env):
    source_root = tmp_path / "source"
    module_dir = _make_in_tree_module(source_root, "holoscan-gstreamer")
    meta = _write_metadata(
        tmp_path,
        {
            "application": {
                "dependencies": {
                    "modules": [
                        {
                            "name": "holoscan-gstreamer",
                            "provides_operators": ["gstreamer"],
                        }
                    ]
                }
            }
        },
    )

    deps = parse_module_dependencies(meta, source_root=source_root)

    assert deps == [
        ModuleDep(
            name="holoscan-gstreamer",
            provides_operators=["gstreamer"],
            override_path=module_dir,
            is_internal=True,
        )
    ]


def test_in_tree_module_no_error_for_missing_source(tmp_path, _clean_local_override_env):
    source_root = tmp_path / "source"
    _make_in_tree_module(source_root, "holoscan-gstreamer")
    meta = _write_metadata(
        tmp_path,
        {"application": {"dependencies": {"modules": [{"name": "holoscan-gstreamer"}]}}},
    )

    deps = parse_module_dependencies(meta, source_root=source_root)

    assert len(deps) == 1
    assert deps[0].is_internal is True


def test_missing_module_still_raises_with_source_root(tmp_path, _clean_local_override_env):
    source_root = tmp_path / "source"
    source_root.mkdir()
    meta = _write_metadata(
        tmp_path,
        {"application": {"dependencies": {"modules": [{"name": "unknown-module"}]}}},
    )

    with pytest.raises(ValueError, match="modules/unknown-module/metadata.json"):
        parse_module_dependencies(meta, source_root=source_root)


def test_local_override_wins_over_in_tree_module(tmp_path, monkeypatch, _clean_local_override_env):
    source_root = tmp_path / "source"
    _make_in_tree_module(source_root, "holoscan-gstreamer")
    override_dir = tmp_path / "override"
    override_dir.mkdir()
    (override_dir / "metadata.json").write_text("{}", encoding="utf-8")
    meta = _write_metadata(
        tmp_path,
        {"application": {"dependencies": {"modules": [{"name": "holoscan-gstreamer"}]}}},
    )
    monkeypatch.setenv("HOLOSCAN_CLI_LOCAL_HOLOSCAN_GSTREAMER", str(override_dir))

    deps = parse_module_dependencies(meta, source_root=source_root)

    assert deps[0].override_path == override_dir.resolve()
    assert deps[0].is_internal is False


def test_in_tree_lookup_is_opt_in(tmp_path, _clean_local_override_env):
    source_root = tmp_path / "source"
    _make_in_tree_module(source_root, "holoscan-gstreamer")
    meta = _write_metadata(
        tmp_path,
        {"application": {"dependencies": {"modules": [{"name": "holoscan-gstreamer"}]}}},
    )

    with pytest.raises(ValueError, match="missing source.git_url"):
        parse_module_dependencies(meta)


# ---- module-sites (parse_module_sites) ---------------------------------------


def _write_sites(tmp_path, modules: list):
    p = tmp_path / "module-sites.json"
    p.write_text(json.dumps({"modules": modules}), encoding="utf-8")
    return p


def test_module_sites_external_entry_becomes_fetchable(tmp_path, _clean_local_override_env):
    sites = _write_sites(
        tmp_path,
        [
            {
                "name": "holoscan-deltacast",
                "url": "https://github.com/deltacasttv/holoscan-modules",
                "ref": FULL_SHA,
                "provides_operators": ["videomaster_source"],
            }
        ],
    )

    deps = parse_module_sites(sites)

    assert len(deps) == 1
    assert deps[0].name == "holoscan-deltacast"
    assert deps[0].git_url == "https://github.com/deltacasttv/holoscan-modules"
    assert deps[0].ref == FULL_SHA
    assert deps[0].provides_operators == ["videomaster_source"]
    assert deps[0].is_internal is False


def test_module_sites_missing_file_returns_empty(tmp_path):
    assert parse_module_sites(tmp_path / "nope.json") == []


def test_module_sites_partial_source_spec_raises(tmp_path, _clean_local_override_env):
    sites = _write_sites(tmp_path, [{"name": "broken", "url": "https://x/y"}])
    with pytest.raises(ValueError, match="both 'url' and 'ref'"):
        parse_module_sites(sites)


def test_module_sites_in_tree_entry_when_present(tmp_path, _clean_local_override_env):
    source_root = tmp_path / "source"
    _make_in_tree_module(source_root, "holoscan-gstreamer")
    sites = _write_sites(tmp_path, [{"name": "holoscan-gstreamer"}])

    deps = parse_module_sites(sites, source_root=source_root)

    assert len(deps) == 1
    assert deps[0].is_internal is True
    assert deps[0].git_url is None


def test_module_sites_local_only_entry_skipped_without_in_tree(tmp_path, _clean_local_override_env):
    # No url/ref and no matching modules/<name>/ -> silently skipped.
    sites = _write_sites(tmp_path, [{"name": "ghost"}])
    assert parse_module_sites(sites, source_root=tmp_path / "source") == []


def test_module_sites_local_override_wins(tmp_path, monkeypatch, _clean_local_override_env):
    override_dir = tmp_path / "local_dc"
    override_dir.mkdir()
    (override_dir / "metadata.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOLOSCAN_CLI_LOCAL_HOLOSCAN_DELTACAST", str(override_dir))
    sites = _write_sites(tmp_path, [{"name": "holoscan-deltacast"}])

    deps = parse_module_sites(sites, source_root=tmp_path / "source")

    assert len(deps) == 1
    assert deps[0].override_path == override_dir.resolve()


# ---- merge_deps --------------------------------------------------------------


def test_merge_deps_site_owns_coords_project_supplies_override():
    site = ModuleDep(name="m", git_url="https://x/y", ref=FULL_SHA)
    proj = ModuleDep(
        name="m", provides_operators=["op_a"], override_path="/local/m"  # type: ignore[arg-type]
    )

    merged = merge_deps([site], [proj])

    assert len(merged) == 1
    assert merged[0].git_url == "https://x/y"
    assert merged[0].ref == FULL_SHA
    # Site has no provides_operators -> falls back to the project dep's.
    assert merged[0].provides_operators == ["op_a"]
    assert merged[0].override_path == "/local/m"


def test_merge_deps_site_provides_operators_authoritative():
    site = ModuleDep(name="m", git_url="https://x/y", ref=FULL_SHA, provides_operators=["site_op"])
    proj = ModuleDep(name="m", provides_operators=["proj_op"])

    merged = merge_deps([site], [proj])

    assert merged[0].provides_operators == ["site_op"]


def test_merge_deps_project_only_modules_appended_after_sites():
    site = ModuleDep(name="s", git_url="https://x/y", ref=FULL_SHA)
    proj_only = ModuleDep(name="p", git_url="https://a/b", ref=FULL_SHA)

    merged = merge_deps([site], [proj_only])

    assert [d.name for d in merged] == ["s", "p"]
