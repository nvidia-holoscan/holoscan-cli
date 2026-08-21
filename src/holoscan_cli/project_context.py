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

"""Discover and activate a Holoscan source-project root before CLI imports."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

MODULE_METADATA_FILENAME = "metadata.json"
METADATA_DIRS = (
    "applications",
    "benchmarks",
    "gxf_extensions",
    "modules",
    "operators",
    "pkg",
    "subgraphs",
    "tutorials",
)
SEARCH_DIRS = tuple(name for name in METADATA_DIRS if name != "subgraphs")

_PYTHON_SEGMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ProjectContextError(ValueError):
    """The selected project root or its Module metadata is invalid."""


@dataclass(frozen=True)
class ProjectContext:
    """Values needed to activate one source project before importing the CLI."""

    root: Path
    repo_prefix: str | None = None
    base_sdk_version: str | None = None
    warnings: tuple[str, ...] = ()


def _is_source_root(path: Path) -> bool:
    if (path / "src" / "holoscan_cli").is_dir() and (path / "pyproject.toml").is_file():
        return True
    return any(
        (path / directory / MODULE_METADATA_FILENAME).is_file()
        or any((path / directory).glob(f"*/{MODULE_METADATA_FILENAME}"))
        for directory in METADATA_DIRS
    )


def _read_module(root: Path, *, strict: bool) -> dict | None:
    path = root / MODULE_METADATA_FILENAME
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        if strict:
            raise ProjectContextError(f"Invalid Module metadata at {path}: {exc}") from exc
        return None

    module = document.get("module") if isinstance(document, dict) else None
    if module is None:
        return None
    if not isinstance(module, dict):
        if strict:
            raise ProjectContextError(f"Module metadata at {path} must contain an object.")
        return None
    return module


def _module_defaults(module: dict, path: Path) -> tuple[str, str | None]:
    name = module.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProjectContextError(f"Module metadata at {path} has no valid module.name.")

    namespace = module.get("namespace") or {}
    if not isinstance(namespace, dict):
        raise ProjectContextError(f"Module metadata at {path} has an invalid module.namespace.")
    python_namespace = namespace.get("python")
    if python_namespace is not None:
        if not isinstance(python_namespace, str) or not all(
            _PYTHON_SEGMENT_RE.fullmatch(part) for part in python_namespace.split(".")
        ):
            raise ProjectContextError(
                f"Module metadata at {path} has an invalid Python namespace: {python_namespace!r}."
            )
        prefix = python_namespace.rsplit(".", 1)[-1]
    else:
        normalized = name.strip().lower().removeprefix("holoscan-")
        prefix = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        if not prefix:
            raise ProjectContextError(
                f"Module metadata at {path} cannot derive an identity from module.name={name!r}."
            )

    sdk = module.get("holoscan_sdk") or {}
    if not isinstance(sdk, dict):
        raise ProjectContextError(f"Module metadata at {path} has invalid module.holoscan_sdk.")
    version = sdk.get("minimum_required_version")
    if version is not None and (not isinstance(version, str) or not version.strip()):
        raise ProjectContextError(f"Module metadata at {path} has an invalid SDK version.")
    return prefix, version.strip() if version else None


def _context(root: Path, warnings: tuple[str, ...] = ()) -> ProjectContext:
    module = _read_module(root, strict=True)
    if module is None:
        return ProjectContext(root=root, warnings=warnings)
    prefix, sdk_version = _module_defaults(module, root / MODULE_METADATA_FILENAME)
    return ProjectContext(root, prefix, sdk_version, warnings)


def _resolve_root(value: str | os.PathLike[str], cwd: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def discover_project_context(
    *,
    cwd: Path | None = None,
    explicit_root: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProjectContext:
    """Select a root using CLI, environment, then ancestor precedence."""
    cwd = (cwd or Path.cwd()).resolve()
    env = os.environ if environ is None else environ
    warnings: tuple[str, ...] = ()

    if explicit_root is not None:
        root = _resolve_root(explicit_root, cwd)
        if not root.is_dir():
            raise ProjectContextError(f"--project-root {root} does not name an existing directory.")
        return _context(root)

    if env_root := env.get("HOLOSCAN_CLI_ROOT"):
        root = _resolve_root(env_root, cwd)
        if root.is_dir():
            return _context(root)
        warnings = (f"Ignoring invalid HOLOSCAN_CLI_ROOT={env_root!r}; discovering from cwd.",)

    module_fallback = None
    for candidate in (cwd, *cwd.parents):
        if _is_source_root(candidate):
            return _context(candidate, warnings)
        if module_fallback is None and _read_module(candidate, strict=False) is not None:
            module_fallback = candidate

    if module_fallback is not None:
        return _context(module_fallback, warnings)
    return ProjectContext(cwd, warnings=warnings)


def activate_project_context(context: ProjectContext) -> None:
    """Publish discovered defaults before CLI classes read their environment."""
    os.environ["HOLOSCAN_CLI_ROOT"] = str(context.root)
    prefix = context.repo_prefix
    if prefix is None:
        return

    defaults = {
        "HOLOSCAN_CLI_BUILD_PARENT_DIR": str(context.root / "build"),
        "HOLOSCAN_CLI_DATA_DIR": str(context.root / "data"),
        "HOLOSCAN_CLI_SEARCH_PATH": ",".join((MODULE_METADATA_FILENAME, *SEARCH_DIRS)),
        "HOLOSCAN_CLI_REPO_PREFIX": prefix,
        "HOLOSCAN_CLI_CONTAINER_PREFIX": prefix.replace("_", "-"),
        "HOLOSCAN_CLI_BASE_SDK_VERSION": context.base_sdk_version,
    }
    for name, value in defaults.items():
        if value:
            os.environ.setdefault(name, value)
