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

"""Lightweight source-project discovery and standalone Module contracts.

This module deliberately uses only the Python standard library.  It is safe to
import from :mod:`holoscan_cli.__main__` before the project CLI and container
classes are imported; those classes still read several defaults at class-body
execution time.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

PACKAGE_NAME = "holoscan-cli"
REQUIREMENTS_FILENAME = "requirements-cli.txt"
MODULE_METADATA_FILENAME = "metadata.json"

SENTINEL_FILES = ("holohub", "isaac_os", "i4h", "CMakeLists.txt", "Dockerfile")
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
# Default HOLOSCAN_CLI_SEARCH_PATH entries. Subgraphs are recognized as a
# project root marker but are not scanned for runnable components.
SEARCH_DIRS = tuple(name for name in METADATA_DIRS if name != "subgraphs")

_VERSION_RE = re.compile(r"[0-9A-Za-z](?:[0-9A-Za-z._+!-]{0,126}[0-9A-Za-z])?")
_PYTHON_SEGMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ProjectContextError(ValueError):
    """A project root, Module metadata, or requirement contract is invalid."""


class ProjectVersionError(ProjectContextError):
    """The running CLI cannot satisfy a standalone Module requirement."""


@dataclass(frozen=True)
class ProjectContext:
    """Discovered project information available before the full CLI import."""

    root: Path
    kind: str
    discovery: str
    module_metadata_path: Optional[Path] = None
    module_metadata: Optional[dict] = None
    requirements_path: Optional[Path] = None
    required_version: Optional[str] = None
    requirement_error: Optional[str] = None
    running_version: Optional[str] = None
    legacy_launcher: bool = False
    repo_prefix: Optional[str] = None
    base_sdk_version: Optional[str] = None
    metadata_search_paths: tuple[Path, ...] = ()
    dockerfile: Optional[Path] = None
    warnings: tuple[str, ...] = ()

    @property
    def container_prefix(self) -> Optional[str]:
        """Image/hostname form of the project identity; ``-`` is DNS-safe."""
        return None if self.repo_prefix is None else self.repo_prefix.replace("_", "-")

    @property
    def is_module(self) -> bool:
        return self.kind == "module"

    @property
    def is_standalone_module(self) -> bool:
        return self.is_module and not self.legacy_launcher

    @property
    def version_match(self) -> Optional[bool]:
        if self.required_version is None or self.running_version is None:
            return None
        return self.required_version == self.running_version

    def profile_environment(self) -> dict[str, str]:
        """Return Module-derived defaults consumed by existing CLI classes."""
        if not self.is_module:
            return {"HOLOSCAN_CLI_ROOT": str(self.root)}

        values = {
            "HOLOSCAN_CLI_ROOT": str(self.root),
            "HOLOSCAN_CLI_BUILD_PARENT_DIR": str(self.root / "build"),
            "HOLOSCAN_CLI_DATA_DIR": str(self.root / "data"),
            "HOLOSCAN_CLI_SEARCH_PATH": ",".join(
                str(path.relative_to(self.root)) for path in self.metadata_search_paths
            ),
        }
        # HoloscanContainer already derives its workspace name and hostname
        # prefix from these two, so only these two need to be published.
        optional_values = {
            "HOLOSCAN_CLI_REPO_PREFIX": self.repo_prefix,
            "HOLOSCAN_CLI_CONTAINER_PREFIX": self.container_prefix,
            "HOLOSCAN_CLI_BASE_SDK_VERSION": self.base_sdk_version,
        }
        values.update({key: value for key, value in optional_values.items() if value})
        return values

    def diagnostics(self) -> dict:
        """Return serializable project-profile and version-contract details."""
        data = {
            "kind": self.kind,
            "root": str(self.root),
            "discovery": self.discovery,
        }
        if not self.is_module:
            return data
        data.update(
            {
                "metadata": str(self.module_metadata_path),
                "requirements": str(self.requirements_path),
                "required_version": self.required_version,
                "running_version": self.running_version,
                "version_match": self.version_match,
                "requirement_error": self.requirement_error,
                "legacy_launcher": self.legacy_launcher,
                "repo_prefix": self.repo_prefix,
                "container_prefix": self.container_prefix,
                "base_sdk_version": self.base_sdk_version,
                "metadata_search_paths": [str(path) for path in self.metadata_search_paths],
                "dockerfile": str(self.dockerfile) if self.dockerfile else None,
            }
        )
        return data


_ACTIVE_PROJECT_CONTEXT: Optional[ProjectContext] = None


def get_active_project_context() -> Optional[ProjectContext]:
    """Return the context activated by the top-level dispatcher, if any."""
    return _ACTIVE_PROJECT_CONTEXT


def set_active_project_context(context: Optional[ProjectContext]) -> None:
    """Set the process-local context used by version and env-info diagnostics."""
    global _ACTIVE_PROJECT_CONTEXT
    _ACTIVE_PROJECT_CONTEXT = context


def get_running_cli_version() -> str:
    """Return the installed distribution version without importing the full CLI."""
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0+local"


def parse_cli_requirement(path: Path) -> str:
    """Parse the deliberately narrow standalone Module requirements contract."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ProjectContextError(f"Could not read {path} as UTF-8: {exc}") from exc

    active = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if len(active) != 1:
        raise ProjectContextError(
            f"{path} must contain exactly one active requirement: {PACKAGE_NAME}==<exact-version>."
        )
    prefix = f"{PACKAGE_NAME}=="
    line = active[0]
    if not line.startswith(prefix):
        raise ProjectContextError(
            f"{path} must contain exactly {PACKAGE_NAME}==<exact-version>; extras, ranges, "
            "URLs, paths, markers, and pip options are not supported."
        )
    version = line[len(prefix) :]
    if not _VERSION_RE.fullmatch(version):
        raise ProjectContextError(f"{path} contains an invalid exact version: {version!r}.")
    return version


def _matches_existing_root(candidate: Path) -> bool:
    if (candidate / "src" / "holoscan_cli").is_dir() and (candidate / "pyproject.toml").exists():
        return True
    if any((candidate / name).exists() for name in SENTINEL_FILES) and any(
        (candidate / name).is_dir() for name in METADATA_DIRS
    ):
        return True
    return any((candidate / name / MODULE_METADATA_FILENAME).exists() for name in METADATA_DIRS)


def _read_module_metadata(root: Path, *, strict: bool) -> Optional[dict]:
    metadata_path = root / MODULE_METADATA_FILENAME
    if not metadata_path.is_file():
        return None
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        if strict:
            raise ProjectContextError(f"Invalid Module metadata at {metadata_path}: {exc}") from exc
        return None
    if not isinstance(raw, dict) or "module" not in raw:
        return None
    if not isinstance(raw["module"], dict):
        if strict:
            raise ProjectContextError(f"Module metadata at {metadata_path} must contain an object.")
        return None
    return raw["module"]


def _module_identity(module: dict, metadata_path: Path) -> tuple[str, Optional[str]]:
    module_name = module.get("name")
    if not isinstance(module_name, str) or not module_name.strip():
        raise ProjectContextError(f"Module metadata at {metadata_path} has no valid module.name.")

    namespace = module.get("namespace")
    python_namespace = None
    if namespace is not None:
        if not isinstance(namespace, dict):
            raise ProjectContextError(
                f"Module metadata at {metadata_path} has an invalid module.namespace."
            )
        python_namespace = namespace.get("python")

    if python_namespace is not None:
        if not isinstance(python_namespace, str) or not python_namespace.strip():
            raise ProjectContextError(
                f"Module metadata at {metadata_path} has an invalid module.namespace.python."
            )
        segments = python_namespace.split(".")
        if not all(_PYTHON_SEGMENT_RE.fullmatch(segment) for segment in segments):
            raise ProjectContextError(
                f"Module metadata at {metadata_path} has an invalid Python namespace: "
                f"{python_namespace!r}."
            )
        repo_prefix = segments[-1]
    else:
        normalized_name = module_name.strip().lower()
        if normalized_name.startswith("holoscan-"):
            normalized_name = normalized_name[len("holoscan-") :]
        repo_prefix = re.sub(r"[^a-z0-9]+", "_", normalized_name).strip("_")
        if not repo_prefix:
            raise ProjectContextError(
                f"Module metadata at {metadata_path} cannot derive a project identity from "
                f"module.name={module_name!r}."
            )

    sdk_version = None
    sdk = module.get("holoscan_sdk")
    if sdk is not None:
        if not isinstance(sdk, dict):
            raise ProjectContextError(
                f"Module metadata at {metadata_path} has an invalid module.holoscan_sdk."
            )
        minimum = sdk.get("minimum_required_version")
        if minimum is not None:
            if not isinstance(minimum, str) or not minimum.strip():
                raise ProjectContextError(
                    f"Module metadata at {metadata_path} has an invalid minimum SDK version."
                )
            sdk_version = minimum.strip()
    return repo_prefix, sdk_version


def _build_context(
    root: Path,
    *,
    kind: str,
    discovery: str,
    module: Optional[dict] = None,
    warnings: tuple[str, ...] = (),
    running_version: Optional[str] = None,
    load_module_contract: bool = True,
) -> ProjectContext:
    if kind != "module" or module is None:
        return ProjectContext(root=root, kind=kind, discovery=discovery, warnings=warnings)

    metadata_path = root / MODULE_METADATA_FILENAME
    if not load_module_contract:
        return ProjectContext(
            root=root,
            kind=kind,
            discovery=discovery,
            module_metadata_path=metadata_path,
            module_metadata=module,
            warnings=warnings,
        )
    repo_prefix, sdk_version = _module_identity(module, metadata_path)
    requirements_path = root / REQUIREMENTS_FILENAME
    required_version = None
    requirement_error = None
    legacy_launcher = any((root / name).is_file() for name in ("holohub", "holoscan"))
    if requirements_path.is_file():
        try:
            required_version = parse_cli_requirement(requirements_path)
        except ProjectContextError as exc:
            requirement_error = str(exc)
    elif not legacy_launcher:
        requirement_error = (
            f"Standalone Module {root} is missing {REQUIREMENTS_FILENAME}. "
            "Restore the generated file or recreate the Module."
        )

    search_paths = (metadata_path, *(root / name for name in SEARCH_DIRS))
    dockerfile_value = module.get("dockerfile")
    dockerfile = None
    if isinstance(dockerfile_value, str) and dockerfile_value.strip():
        candidate = Path(dockerfile_value).expanduser()
        dockerfile = candidate if candidate.is_absolute() else root / candidate
    elif (root / "Dockerfile").is_file():
        dockerfile = root / "Dockerfile"

    return ProjectContext(
        root=root,
        kind=kind,
        discovery=discovery,
        module_metadata_path=metadata_path,
        module_metadata=module,
        requirements_path=requirements_path,
        required_version=required_version,
        requirement_error=requirement_error,
        running_version=running_version or get_running_cli_version(),
        legacy_launcher=legacy_launcher,
        repo_prefix=repo_prefix,
        base_sdk_version=sdk_version,
        metadata_search_paths=tuple(search_paths),
        dockerfile=dockerfile,
        warnings=warnings,
    )


def _resolve_explicit_root(value: str | os.PathLike[str], cwd: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def discover_project_context(
    *,
    cwd: Optional[Path] = None,
    explicit_root: Optional[str | os.PathLike[str]] = None,
    environ: Optional[Mapping[str, str]] = None,
    running_version: Optional[str] = None,
    load_module_contract: bool = True,
) -> ProjectContext:
    """Discover one project root without changing HoloHub ancestor precedence."""
    original_cwd = (cwd or Path.cwd()).resolve()
    env = os.environ if environ is None else environ
    warnings: tuple[str, ...] = ()

    if explicit_root is not None:
        root = _resolve_explicit_root(explicit_root, original_cwd)
        if not root.exists() or not root.is_dir():
            raise ProjectContextError(f"--project-root {root} does not name an existing directory.")
        existing_match = _matches_existing_root(root)
        module = _read_module_metadata(root, strict=load_module_contract)
        if not existing_match and module is None:
            raise ProjectContextError(
                f"--project-root {root} is not a recognized Holoscan source-project or Module root."
            )
        return _build_context(
            root,
            kind="module" if module is not None else "source",
            discovery="project-root",
            module=module,
            running_version=running_version,
            load_module_contract=load_module_contract,
        )

    env_root = env.get("HOLOSCAN_CLI_ROOT")
    if env_root:
        root = _resolve_explicit_root(env_root, original_cwd)
        # Apply the same recognition check as --project-root. The environment
        # form warns and falls back because it is ambient rather than an
        # explicit assertion made for this invocation.
        if not root.exists() or not root.is_dir():
            warnings = (f"Ignoring invalid HOLOSCAN_CLI_ROOT={env_root!r}; discovering from cwd.",)
        else:
            module = _read_module_metadata(root, strict=load_module_contract)
            if _matches_existing_root(root) or module is not None:
                return _build_context(
                    root,
                    kind="module" if module is not None else "source",
                    discovery="environment",
                    module=module,
                    running_version=running_version,
                    load_module_contract=load_module_contract,
                )
            warnings = (
                f"Ignoring HOLOSCAN_CLI_ROOT={env_root!r}: not a recognized Holoscan "
                "source-project or Module root; discovering from cwd.",
            )

    module_fallback: Optional[tuple[Path, dict]] = None
    for candidate in (original_cwd, *original_cwd.parents):
        existing_match = _matches_existing_root(candidate)
        module = _read_module_metadata(candidate, strict=existing_match and load_module_contract)
        if existing_match:
            return _build_context(
                candidate,
                kind="module" if module is not None else "source",
                discovery="ancestor",
                module=module,
                warnings=warnings,
                running_version=running_version,
                load_module_contract=load_module_contract,
            )
        if module is not None and module_fallback is None:
            module_fallback = (candidate, module)

    if module_fallback is not None:
        root, module = module_fallback
        return _build_context(
            root,
            kind="module",
            discovery="module-fallback",
            module=module,
            warnings=warnings,
            running_version=running_version,
            load_module_contract=load_module_contract,
        )
    return _build_context(original_cwd, kind="cwd", discovery="cwd", warnings=warnings)


def activate_project_context(context: ProjectContext) -> None:
    """Apply bounded defaults before importing CLI/container class bodies."""
    set_active_project_context(context)
    values = context.profile_environment()
    # Root selection follows CLI > environment > discovery precedence and must
    # replace an invalid environment value. Other explicit environment values
    # remain authoritative over Module-derived defaults.
    os.environ["HOLOSCAN_CLI_ROOT"] = values.pop("HOLOSCAN_CLI_ROOT")
    for key, value in values.items():
        os.environ.setdefault(key, value)


def _is_container() -> bool:
    """Return whether this is a CLI-managed project development container.

    Generic container probes such as ``/.dockerenv`` cannot distinguish a
    generated Module image from a containerized CI host that launches Docker.
    ``HoloscanContainer`` already sets this marker on every recursive project
    invocation, so use it to select container-specific recovery guidance.
    """
    return os.environ.get("HOLOSCAN_CLI_BUILD_LOCAL", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def enforce_project_requirement(
    context: ProjectContext, *, in_container: Optional[bool] = None
) -> None:
    """Fail before project work when a standalone Module pin is unsatisfied."""
    if not context.is_standalone_module:
        return
    if context.requirement_error:
        raise ProjectVersionError(context.requirement_error)
    if context.required_version == context.running_version:
        return

    lines = [
        f"This Module requires {PACKAGE_NAME}=={context.required_version}, "
        f"but {context.running_version} is running.",
        f"Requirements: {context.requirements_path}",
        f"Python: {sys.executable}",
    ]
    executable = shutil.which("holoscan")
    if executable:
        lines.append(f"Holoscan executable: {executable}")
    if _is_container() if in_container is None else in_container:
        lines.extend(
            [
                "Rebuild the development image; do not use --no-docker-build with this image.",
                "The running container will not install or modify holoscan-cli.",
            ]
        )
    else:
        lines.extend(
            [
                "Activate the intended environment, or run:",
                f"  {sys.executable} -m pip install -r {context.requirements_path}",
            ]
        )
    raise ProjectVersionError("\n".join(lines))
