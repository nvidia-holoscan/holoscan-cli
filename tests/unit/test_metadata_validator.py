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

"""Tests for ``holoscan_cli.metadata.metadata_validator``.

The validator is reached through ``holoscan create`` and was at 0%
coverage after the package consolidation. These tests pin the contracts
the CLI relies on: README-title extraction, the
metadata.name/README-title mismatch detector, and the
``Draft4Validator`` wrapper that backs ``validate_generated_metadata``
in ``commands/create.py``.
"""

import json

import pytest

from holoscan_cli.metadata import metadata_validator


# ---- extract_readme_title ----------------------------------------------------


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_extract_readme_title_plain_h1(tmp_path):
    readme = _write(tmp_path, "README.md", "# My Application\n\nSome body\n")
    assert metadata_validator.extract_readme_title(readme) == "My Application"


def test_extract_readme_title_skips_leading_html_comment(tmp_path):
    readme = _write(
        tmp_path,
        "README.md",
        "<!-- SPDX-FileCopyrightText: foo -->\n# My App\nBody\n",
    )
    assert metadata_validator.extract_readme_title(readme) == "My App"


def test_extract_readme_title_skips_multiline_html_comment(tmp_path):
    readme = _write(
        tmp_path,
        "README.md",
        "<!--\n  Copyright header.\n  Multiple lines.\n-->\n\n# Real Title\n",
    )
    assert metadata_validator.extract_readme_title(readme) == "Real Title"


def test_extract_readme_title_returns_none_when_no_h1(tmp_path):
    readme = _write(tmp_path, "README.md", "Just a paragraph.\n## Subheading\n")
    assert metadata_validator.extract_readme_title(readme) is None


def test_extract_readme_title_ignores_blank_lines(tmp_path):
    readme = _write(tmp_path, "README.md", "\n\n\n# Title After Blanks\n")
    assert metadata_validator.extract_readme_title(readme) == "Title After Blanks"


# ---- check_name_matches_readme ----------------------------------------------


def test_check_name_matches_readme_match(tmp_path):
    readme = _write(tmp_path, "README.md", "# Endoscopy Tool Tracking\n")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps({"application": {"name": "Endoscopy Tool Tracking"}}),
        encoding="utf-8",
    )

    ok, msg = metadata_validator.check_name_matches_readme(
        str(metadata),
        {"application": {"name": "Endoscopy Tool Tracking"}},
    )
    assert ok is True
    assert "matches" in msg.lower()


def test_check_name_matches_readme_rejects_forbidden_terms(tmp_path):
    _write(tmp_path, "README.md", "# HoloHub Endoscopy Tool\n")
    metadata = tmp_path / "metadata.json"

    ok, msg = metadata_validator.check_name_matches_readme(
        str(metadata),
        {"application": {"name": "HoloHub Endoscopy Tool"}},
    )
    assert ok is False
    assert "holohub" in msg.lower()


def test_check_name_matches_readme_rejects_word_application(tmp_path):
    _write(tmp_path, "README.md", "# Endoscopy Application\n")
    metadata = tmp_path / "metadata.json"

    ok, msg = metadata_validator.check_name_matches_readme(
        str(metadata),
        {"application": {"name": "Endoscopy Application"}},
    )
    assert ok is False
    assert "application" in msg


def test_check_name_matches_readme_falls_back_to_parent_readme(tmp_path):
    """When the project directory has no README.md, the validator checks the
    parent directory — applications/<proj>/python/metadata.json with the
    README at applications/<proj>/README.md."""
    project = tmp_path / "my_proj"
    project.mkdir()
    _write(project, "README.md", "# My Real App\n")
    impl = project / "python"
    impl.mkdir()
    metadata_path = impl / "metadata.json"
    metadata_path.write_text(
        json.dumps({"application": {"name": "My Real App"}}), encoding="utf-8"
    )

    ok, msg = metadata_validator.check_name_matches_readme(
        str(metadata_path),
        {"application": {"name": "My Real App"}},
    )
    assert ok is True, msg


def test_check_name_matches_readme_complains_when_no_readme(tmp_path):
    metadata = tmp_path / "metadata.json"

    ok, msg = metadata_validator.check_name_matches_readme(
        str(metadata),
        {"application": {"name": "Solo App"}},
    )
    assert ok is False
    assert "no readme" in msg.lower()


def test_check_name_matches_readme_returns_true_for_non_application(tmp_path):
    """The check is only run for the ``application`` entity; everything else
    is reported as 'not an application' (caller skips)."""
    ok, msg = metadata_validator.check_name_matches_readme(
        str(tmp_path / "metadata.json"),
        {"operator": {"name": "Whatever"}},
    )
    assert ok is True
    assert "not an application" in msg.lower()


def test_check_name_matches_readme_missing_name_field(tmp_path):
    metadata = tmp_path / "metadata.json"
    ok, msg = metadata_validator.check_name_matches_readme(
        str(metadata),
        {"application": {}},
    )
    assert ok is False
    assert "no name field" in msg.lower()


# ---- validate_json ----------------------------------------------------------


def _schema_dir(schema_kind):
    """Return a directory name that ``get_schema_path`` maps to ``schema_kind``.

    The validator reads the schema for a given directory via
    ``get_schema_path``, which keys on ``METADATA_DIRECTORY_CONFIG`` —
    so e.g. ``"pkg"`` maps to ``package.schema.json``.
    """
    return {"package": "pkg"}.get(schema_kind, schema_kind + "s")


def test_validate_json_accepts_minimal_package_metadata(tmp_path):
    # The package schema has no required fields on the `package` object;
    # any well-formed dict passes.
    ok, msg = metadata_validator.validate_json(
        {"package": {"dockerfile": "Dockerfile"}}, "pkg"
    )
    assert ok is True, msg
    assert msg == "valid"


def test_validate_json_rejects_violations(tmp_path):
    # `operators` schema has required fields; an empty operator fails.
    ok, msg = metadata_validator.validate_json({"operator": {}}, "operators")
    assert ok is False
    # `msg` here is a `jsonschema.exceptions.ValidationError`; str-ifying
    # it gives the violation summary.
    assert "required" in str(msg).lower() or "validation" in str(msg).lower()


def test_validate_json_rejects_invalid_schema_file(tmp_path, monkeypatch):
    """If the schema file itself is not parseable, validate_json must return
    (False, JSONDecodeError) rather than crashing."""
    bogus_schema = tmp_path / "broken.schema.json"
    bogus_schema.write_text("{not valid json", encoding="utf-8")

    monkeypatch.setattr(
        metadata_validator, "get_schema_path", lambda directory: bogus_schema
    )

    ok, msg = metadata_validator.validate_json({"anything": {}}, "anything")
    assert ok is False
    assert isinstance(msg, json.JSONDecodeError)


# ---- validate_json_directory ------------------------------------------------


def test_validate_json_directory_zero_when_all_valid(tmp_path, monkeypatch):
    """A directory with one valid metadata.json returns exit code 0."""
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "pkg"
    base.mkdir()
    sub = base / "my_package"
    sub.mkdir()
    (sub / "metadata.json").write_text(
        json.dumps({"package": {"dockerfile": "Dockerfile"}}), encoding="utf-8"
    )

    code = metadata_validator.validate_json_directory("pkg", metadata_is_required=False)
    assert code == 0


def test_validate_json_directory_nonzero_when_subdir_missing_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "operators"
    base.mkdir()
    sub = base / "broken_op"
    sub.mkdir()
    # No metadata.json under broken_op/, and metadata is required for `operators`.

    code = metadata_validator.validate_json_directory("operators", metadata_is_required=True)
    assert code == 1


def test_validate_json_directory_nonzero_when_metadata_json_unparseable(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "operators"
    base.mkdir()
    sub = base / "op_with_bad_json"
    sub.mkdir()
    (sub / "metadata.json").write_text("{ definitely not json", encoding="utf-8")

    code = metadata_validator.validate_json_directory("operators")
    assert code == 1


def test_validate_json_directory_ignores_patterns(tmp_path, monkeypatch):
    """``ignore_patterns`` should skip both the missing-metadata complaint
    and the parse pass for matching subdirectories."""
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "operators"
    base.mkdir()
    skipped = base / "template"
    skipped.mkdir()
    # No metadata.json under template/ — should NOT trip the metadata_is_required
    # check because "template" is in ignore_patterns.

    code = metadata_validator.validate_json_directory(
        "operators", ignore_patterns=["template"], metadata_is_required=True
    )
    assert code == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
