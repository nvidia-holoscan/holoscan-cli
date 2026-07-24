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
the logging configuration, and the CTest scripts under ``holoscan_cli.testing``.
The tests also pin the public ``holoscan`` console script entry point and the
``holoscan-cli`` package-name tool-runner alias.

Entry-point checks read ``pyproject.toml`` directly (the ground truth for
what a fresh ``pip install`` will register) instead of the runtime
``importlib.metadata`` view, which can include stale console scripts left
over by older installs in a developer's virtualenv.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

REQUIRED_SCHEMAS = {
    "application.schema.json",
    "benchmark.schema.json",
    "gxf_extension.schema.json",
    "module.schema.json",
    "operator.schema.json",
    "package.schema.json",
    "project.schema.json",
    "tutorial.schema.json",
}

REQUIRED_TESTING_FILES = {
    "CTestCustom.cmake",
    "container.ctest",
}

REQUIRED_SETUP_SCRIPTS = {
    "Dockerfile.util",
    "benchmarking.sh",
    "coverage.sh",
    "debug.sh",
    "sccache.sh",
    "template.sh",
    "xvfb.sh",
    "requirements.template.txt",
}


PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
README = Path(__file__).resolve().parents[2] / "README.md"


def _pyproject() -> dict:
    if not PYPROJECT.exists():
        pytest.skip(f"pyproject.toml not found at {PYPROJECT}")
    return tomllib.loads(PYPROJECT.read_text())


def _readme() -> str:
    if not README.exists():
        pytest.skip(f"README.md not found at {README}")
    return README.read_text(encoding="utf-8")


# ---- bundled package data ---------------------------------------------------


def test_py_typed_marker_is_shipped():
    """Typed packages must ship a ``py.typed`` marker file."""
    typed = importlib.resources.files("holoscan_cli").joinpath("py.typed")
    assert typed.is_file()


def test_logging_config_is_shipped():
    """Forwarded project commands load the bundled logging configuration."""
    logging_config = importlib.resources.files("holoscan_cli").joinpath("logging.json")
    assert logging_config.is_file()


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


def test_setup_scripts_are_packaged():
    """The bundled setup scripts back the ``holoscan setup --scripts <name>``
    and ``build-container --extra-scripts <name>`` paths for downstream
    consumers that don't vendor their own ``utilities/setup/`` directory.
    """
    files = {
        path.name for path in importlib.resources.files("holoscan_cli.setup_scripts").iterdir()
    }
    missing = REQUIRED_SETUP_SCRIPTS - files
    assert not missing, f"missing bundled setup scripts: {missing}"


def test_bundled_template_script_uses_bundled_requirements(tmp_path):
    """The fallback template setup script must not depend on HoloHub's
    ``utilities/requirements.template.txt`` being present."""
    setup_dir = importlib.resources.files("holoscan_cli.setup_scripts")
    script = setup_dir.joinpath("template.sh")
    requirements = setup_dir.joinpath("requirements.template.txt")
    assert script.is_file()
    assert requirements.is_file()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "python-args.txt"
    fake_python = bin_dir / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n" 'printf \'%s\\n\' "$@" > "${PYTHON_ARGS_FILE}"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["PYTHON_ARGS_FILE"] = str(args_file)
    subprocess.run(["bash", str(script)], check=True, env=env)

    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "pip",
        "install",
        "-r",
        str(requirements),
    ]


def test_bundled_sccache_script_does_not_warn_when_binary_is_on_path(tmp_path):
    setup_dir = importlib.resources.files("holoscan_cli.setup_scripts")
    script = setup_dir.joinpath("sccache.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_sccache = bin_dir / "sccache"
    fake_sccache.write_text(
        "#!/usr/bin/env bash\necho 'sccache 0.12.0-rapids.20'\n",
        encoding="utf-8",
    )
    fake_sccache.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    result = subprocess.run(
        ["bash", str(script)],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )

    assert "already installed and meets minimum version requirement" in result.stdout
    assert "add " not in result.stderr


def test_readme_links_are_valid_for_pypi_rendering():
    """PyPI renders README.md as the long description, outside the GitHub repo.

    Repo-relative links such as ``./CONTRIBUTING.md`` become broken PyPI URLs, so
    docs shipped in package metadata should use absolute URLs or page anchors.
    """
    relative_links = []
    for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", _readme()):
        target = match.group(1).strip()
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        if "://" in target:
            continue
        relative_links.append(target)

    assert not relative_links, f"README has PyPI-broken relative links: {relative_links}"


# ---- pyproject.toml entry-point declarations --------------------------------


def test_pyproject_declares_expected_console_scripts():
    """The shipped wheel must register the canonical CLI and tool-runner alias."""
    declared = _pyproject().get("project", {}).get("scripts", {})
    assert declared == {
        "holoscan": "holoscan_cli.__main__:main",
        "holoscan-cli": "holoscan_cli.__main__:main",
    }, declared


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
    # entry_points() never raises for a missing package; probe the
    # distribution explicitly so uninstalled dev environments skip.
    try:
        importlib.metadata.distribution("holoscan-cli")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev only
        pytest.skip("holoscan-cli is not installed in this environment")
    scripts = importlib.metadata.entry_points(group="console_scripts")
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
        spec.split(" ")[0].split("[")[0].split(">")[0].split("<")[0].split("=")[0] for spec in specs
    }


def test_pyproject_has_no_runtime_dependencies():
    """``pip install holoscan-cli`` must install with zero runtime deps.

    Schema validation moved to the ``create`` extra; see
    ``test_pyproject_create_extra_bundles_validator_deps``.
    """
    assert _pyproject()["project"]["dependencies"] == []


def test_pyproject_create_extra_bundles_validator_deps():
    """``pip install 'holoscan-cli[create]'`` must cover the entire ``create`` path.

    The fatal in ``commands/create.py::validate_generated_metadata`` instructs
    users to install this extra when ``jsonschema`` / ``referencing`` are
    missing, and ``commands/create.py::run_create`` does the same for
    ``cookiecutter``, so the contract here is part of the user-facing install
    story.
    """
    extras = _pyproject()["project"].get("optional-dependencies", {})
    assert "create" in extras, sorted(extras)

    create_specs = extras["create"]
    assert _dep_names(create_specs) == {
        "jsonschema",
        "referencing",
        "cookiecutter",
    }, create_specs

    jsonschema_spec = next(spec for spec in create_specs if spec.startswith("jsonschema"))
    assert ">=4.18" in jsonschema_spec, (
        "metadata_validator uses Draft202012Validator(registry=...), which requires "
        f"jsonschema>=4.18; got {jsonschema_spec!r}"
    )
