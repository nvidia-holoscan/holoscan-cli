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

"""Smoke tests for installed package data and metadata.

These prevent regressions where ``pyproject.toml`` accidentally drops the
files an installed ``holoscan-cli`` wheel must ship: the ``py.typed``
marker, the project metadata JSON schemas under ``holoscan_cli.metadata``,
and the CTest scripts under ``holoscan_cli.testing``. The tests also pin
the public ``holoscan`` console script entry point so the installed
package keeps a single, stable command name on disk.

Entry-point checks read ``pyproject.toml`` directly (the ground truth for
what a fresh ``pip install`` will register) instead of the runtime
``importlib.metadata`` view, which can include stale console scripts left
over by older installs in a developer's virtualenv.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import sys
import tomllib
from pathlib import Path

import pytest

REQUIRED_SCHEMAS = {
    "application.schema.json",
    "benchmark.schema.json",
    "gxf_extension.schema.json",
    "operator.schema.json",
    "package.schema.json",
    "project.schema.json",
    "tutorial.schema.json",
    "workflow.schema.json",
}

REQUIRED_TESTING_FILES = {
    "CTestCustom.cmake",
    "cdash_submit_configure_log.py",
    "holohub.container.ctest",
    "holohub_test_all_applications.ctest",
}


PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _pyproject() -> dict:
    if not PYPROJECT.exists():
        pytest.skip(f"pyproject.toml not found at {PYPROJECT}")
    return tomllib.loads(PYPROJECT.read_text())


# ---- bundled package data ---------------------------------------------------


def test_py_typed_marker_is_shipped():
    """Typed packages must ship a ``py.typed`` marker file."""
    typed = importlib.resources.files("holoscan_cli").joinpath("py.typed")
    assert typed.is_file()


def test_all_metadata_schemas_are_packaged():
    schemas = {
        path.name
        for path in importlib.resources.files("holoscan_cli.metadata").iterdir()
        if path.name.endswith(".schema.json")
    }
    missing = REQUIRED_SCHEMAS - schemas
    assert not missing, f"missing metadata schemas: {missing}"


def test_testing_assets_are_packaged():
    files = {path.name for path in importlib.resources.files("holoscan_cli.testing").iterdir()}
    missing = REQUIRED_TESTING_FILES - files
    assert not missing, f"missing testing assets: {missing}"


# ---- pyproject.toml entry-point declarations --------------------------------


def test_pyproject_declares_only_holoscan_console_script():
    """The shipped wheel must register exactly one console script."""
    declared = _pyproject().get("project", {}).get("scripts", {})
    assert declared == {"holoscan": "holoscan_cli.__main__:main"}, declared


def test_pyproject_does_not_declare_legacy_console_scripts():
    """``holohub`` and ``monai-deploy`` must stay removed from the package."""
    declared = _pyproject().get("project", {}).get("scripts", {})
    for legacy in ("holohub", "monai-deploy"):
        assert legacy not in declared, f"legacy console script reintroduced: {legacy}"


# ---- runtime entry points (smoke check, tolerant of stale dev installs) -----


def test_holoscan_console_script_is_registered_at_runtime():
    """``holoscan`` must resolve via ``importlib.metadata`` after install.

    Stale legacy entries in a developer venv are tolerated by
    :func:`test_pyproject_does_not_declare_legacy_console_scripts`; we only
    require that the canonical ``holoscan`` entry point is reachable.
    """
    try:
        scripts = importlib.metadata.entry_points(group="console_scripts")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev only
        pytest.skip("holoscan-cli is not installed in this environment")
    holoscan = [ep for ep in scripts if ep.name == "holoscan"]
    assert holoscan, "holoscan console script not registered"
    assert holoscan[0].value == "holoscan_cli.__main__:main"


# ---- package metadata sanity ------------------------------------------------


def test_pyproject_targets_supported_python_versions():
    """``requires-python`` must stay in sync with the runtime version check."""
    requires_python = _pyproject()["project"]["requires-python"]
    assert ">=3.10" in requires_python
    assert sys.version_info >= (3, 10)


def _dep_names(specs: list[str]) -> set[str]:
    """Strip PEP 508 version markers from a dependency list, leaving names."""
    return {
        spec.split(" ")[0].split("[")[0].split(">")[0].split("<")[0].split("=")[0]
        for spec in specs
    }


def test_pyproject_has_no_runtime_dependencies():
    """``pip install holoscan-cli`` must install with zero runtime deps.

    Schema validation moved to the ``create`` extra; see
    ``test_pyproject_create_extra_bundles_validator_deps``.
    """
    assert _pyproject()["project"]["dependencies"] == []


def test_pyproject_create_extra_bundles_validator_deps():
    """``pip install 'holoscan-cli[create]'`` must pull in the schema validator.

    The fatal in ``commands/create.py::validate_generated_metadata`` instructs
    users to install this extra when ``jsonschema`` / ``referencing`` are
    missing, so the contract here is part of the user-facing install story.
    """
    extras = _pyproject()["project"].get("optional-dependencies", {})
    assert "create" in extras, sorted(extras)

    create_specs = extras["create"]
    assert _dep_names(create_specs) == {"jsonschema", "referencing"}, create_specs

    jsonschema_spec = next(spec for spec in create_specs if spec.startswith("jsonschema"))
    assert ">=4.18" in jsonschema_spec, (
        "metadata_validator uses Draft4Validator(registry=...), which requires "
        f"jsonschema>=4.18; got {jsonschema_spec!r}"
    )
