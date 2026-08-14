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

This module is safe to import from :mod:`holoscan_cli.__main__` before the
project CLI and container classes.  Python 3.11+ uses :mod:`tomllib`; Python
3.10 uses the small conditional ``tomli`` runtime dependency.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

PACKAGE_NAME = "holoscan-cli"
REQUIREMENTS_FILENAME = "requirements-cli.txt"
MODULE_METADATA_FILENAME = "metadata.json"
PYPROJECT_FILENAME = "pyproject.toml"
MAX_REQUIREMENTS_BYTES = 64 * 1024
MAX_PYPROJECT_BYTES = 1024 * 1024
HOLOSCAN_CONFIG_SCHEMA_VERSION = 1

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
SEARCH_DIRS = tuple(name for name in METADATA_DIRS if name != "subgraphs")

_VERSION_RE = re.compile(r"[0-9A-Za-z](?:[0-9A-Za-z._+!-]{0,126}[0-9A-Za-z])?")
_PYTHON_SEGMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REPO_PREFIX_RE = re.compile(r"[a-z0-9](?:[a-z0-9_]{0,126}[a-z0-9])?")
_CONTAINER_PREFIX_RE = re.compile(r"[a-z0-9](?:[a-z0-9_.-]{0,126}[a-z0-9])?")
_WORKSPACE_NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9])?")
_IMAGE_REFERENCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,254}")
_SUPPORTED_ARCHITECTURES = {"x86_64", "aarch64"}
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


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
    repo_prefix: Optional[str] = None
    container_prefix: Optional[str] = None
    workspace_name: Optional[str] = None
    hostname_prefix: Optional[str] = None
    base_sdk_version: Optional[str] = None
    metadata_search_paths: tuple[Path, ...] = ()
    dockerfile: Optional[Path] = None
    project_config_path: Optional[Path] = None
    project_config_schema_version: Optional[int] = None
    target_arch: Optional[str] = None
    target_arch_source: Optional[str] = None
    base_image: Optional[str] = None
    default_cuda_version: Optional[str] = None
    sdk_root: Optional[Path] = None
    sdk_root_source: Optional[str] = None
    sdk_mount_read_only: bool = False
    ctest_script: Optional[str] = None
    build_type: Optional[str] = None
    docker_build_args: Optional[str] = None
    docker_run_args: Optional[str] = None
    forward_env: Optional[str] = None
    warnings: tuple[str, ...] = ()

    @property
    def is_module(self) -> bool:
        return self.kind == "module"

    @property
    def is_standalone_module(self) -> bool:
        return self.is_module

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
        optional_values = {
            "HOLOSCAN_CLI_REPO_PREFIX": self.repo_prefix,
            "HOLOSCAN_CLI_CONTAINER_PREFIX": self.container_prefix,
            "HOLOSCAN_CLI_WORKSPACE_NAME": self.workspace_name,
            "HOLOSCAN_CLI_HOSTNAME_PREFIX": self.hostname_prefix,
            "HOLOSCAN_CLI_BASE_SDK_VERSION": self.base_sdk_version,
            "HOLOSCAN_CLI_DEFAULT_DOCKERFILE": str(self.dockerfile) if self.dockerfile else None,
            "HOLOSCAN_CLI_BASE_IMAGE": self.base_image,
            "HOLOSCAN_CLI_BASE_IMAGE_FORMAT": "{base_image}" if self.base_image else None,
            "HOLOSCAN_CLI_DEFAULT_CUDA_VERSION": self.default_cuda_version,
            "HOLOSCAN_CLI_DEFAULT_HSDK_DIR": str(self.sdk_root) if self.sdk_root else None,
            "HOLOSCAN_SDK_ROOT": str(self.sdk_root) if self.sdk_root else None,
            "holoscan_ROOT": str(self.sdk_root) if self.sdk_root else None,
            "HOLOSCAN_CLI_CTEST_SCRIPT": self.ctest_script,
            "CMAKE_BUILD_TYPE": self.build_type,
            "HOLOSCAN_CLI_TARGET_ARCH": self.target_arch,
            "HOLOSCAN_CLI_SDK_MOUNT_READ_ONLY": "1" if self.sdk_mount_read_only else None,
            "HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS": self.docker_build_args,
            "HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS": self.docker_run_args,
            "HOLOSCAN_CLI_FORWARD_ENV": self.forward_env,
        }
        values.update({key: value for key, value in optional_values.items() if value})
        return values

    def diagnostics(self) -> dict:
        """Return serializable project-profile and version-contract details."""
        data: dict[str, object] = {
            "kind": self.kind,
            "root": str(self.root),
            "discovery": self.discovery,
            "warnings": list(self.warnings),
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
                "repo_prefix": self.repo_prefix,
                "container_prefix": self.container_prefix,
                "workspace_name": self.workspace_name,
                "hostname_prefix": self.hostname_prefix,
                "base_sdk_version": self.base_sdk_version,
                "metadata_search_paths": [str(path) for path in self.metadata_search_paths],
                "dockerfile": str(self.dockerfile) if self.dockerfile else None,
                "project_config": (
                    str(self.project_config_path) if self.project_config_path else None
                ),
                "project_config_schema_version": self.project_config_schema_version,
                "target_arch": self.target_arch,
                "target_arch_source": self.target_arch_source,
                "base_image": self.base_image,
                "default_cuda_version": self.default_cuda_version,
                "sdk_root": str(self.sdk_root) if self.sdk_root else None,
                "sdk_root_source": self.sdk_root_source,
                "sdk_mount_read_only": self.sdk_mount_read_only,
                "ctest_script": self.ctest_script,
                "build_type": self.build_type,
                "docker_build_args": self.docker_build_args,
                "docker_run_args": self.docker_run_args,
                "forward_env": self.forward_env,
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
        size = path.stat().st_size
    except OSError as exc:
        raise ProjectContextError(f"Could not read {path}: {exc}") from exc
    if size > MAX_REQUIREMENTS_BYTES:
        raise ProjectContextError(
            f"{path} is too large ({size} bytes); expected one exact {PACKAGE_NAME} requirement."
        )
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
    """Read the root Module descriptor from ecosystem ``metadata.json``."""
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


def _normalized_arch(value: str) -> str:
    machine = value.strip().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine in {"aarch64", "arm64"}:
        return "aarch64"
    return machine


def _resolve_target_arch(environ: Mapping[str, str]) -> tuple[str, str]:
    configured = environ.get("HOLOSCAN_CLI_TARGET_ARCH")
    if configured:
        arch = _normalized_arch(configured)
        if arch not in _SUPPORTED_ARCHITECTURES:
            raise ProjectContextError(
                "HOLOSCAN_CLI_TARGET_ARCH must be x86_64/amd64 or aarch64/arm64; "
                f"got {configured!r}."
            )
        return arch, "HOLOSCAN_CLI_TARGET_ARCH"
    return _normalized_arch(platform.machine()), "host"


def _validate_object_keys(
    value: object, *, path: str, allowed: set[str], source_path: Path
) -> dict:
    if not isinstance(value, dict):
        raise ProjectContextError(f"{source_path}: {path} must be a table.")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProjectContextError(
            f"{source_path}: {path} contains unknown field(s): {', '.join(unknown)}."
        )
    return value


def _relative_project_path(value: object, *, path: str, source_path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectContextError(f"{source_path}: {path} must be a non-empty string.")
    candidate = Path(value.strip())
    if candidate.is_absolute() or value.strip().startswith("~") or ".." in candidate.parts:
        raise ProjectContextError(
            f"{source_path}: {path} must stay within the project and be relative."
        )
    return candidate.as_posix()


def _read_holoscan_project_config(root: Path) -> tuple[Optional[Path], dict]:
    """Read and strictly validate the versioned ``[tool.holoscan]`` table."""
    config_path = root / PYPROJECT_FILENAME
    if not config_path.is_file():
        return None, {}
    try:
        size = config_path.stat().st_size
    except OSError as exc:
        raise ProjectContextError(f"Could not read {config_path}: {exc}") from exc
    if size > MAX_PYPROJECT_BYTES:
        raise ProjectContextError(
            f"{config_path} is too large ({size} bytes); limit is {MAX_PYPROJECT_BYTES} bytes."
        )
    try:
        document = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ProjectContextError(f"Invalid TOML at {config_path}: {exc}") from exc

    tool = document.get("tool", {})
    if not isinstance(tool, dict):
        raise ProjectContextError(f"{config_path}: tool must be a table.")
    config = tool.get("holoscan")
    if config is None:
        return None, {}
    config = _validate_object_keys(
        config,
        path="tool.holoscan",
        allowed={
            "schema-version",
            "repo-prefix",
            "container-prefix",
            "workspace-name",
            "hostname-prefix",
            "search-path",
            "build-type",
            "ctest-script",
            "cuda",
            "docker-build-args",
            "docker-run-args",
            "forward-env",
            "sdk",
        },
        source_path=config_path,
    )
    # Optional: omitting it means the current schema. Declare it only to pin a
    # version, which lets an older CLI reject a newer schema by name.
    schema_version = config.get("schema-version", HOLOSCAN_CONFIG_SCHEMA_VERSION)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ProjectContextError(
            f"{config_path}: tool.holoscan.schema-version must be the integer "
            f"{HOLOSCAN_CONFIG_SCHEMA_VERSION}."
        )
    if schema_version != HOLOSCAN_CONFIG_SCHEMA_VERSION:
        raise ProjectContextError(
            f"{config_path}: unsupported tool.holoscan schema-version {schema_version}; "
            f"this CLI supports {HOLOSCAN_CONFIG_SCHEMA_VERSION}."
        )

    sdk = _validate_object_keys(
        config.get("sdk", {}),
        path="tool.holoscan.sdk",
        allowed={
            "version",
            "search",
            "allow-parent-search",
            "mount-read-only",
            "base-images",
        },
        source_path=config_path,
    )
    if "base-images" in sdk:
        _validate_object_keys(
            sdk["base-images"],
            path="tool.holoscan.sdk.base-images",
            allowed=_SUPPORTED_ARCHITECTURES,
            source_path=config_path,
        )
    return config_path, config


def _validated_name(
    value: object,
    *,
    path: str,
    source_path: Path,
    pattern: re.Pattern[str],
) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value.strip()):
        raise ProjectContextError(f"{source_path}: {path} has an invalid value: {value!r}.")
    return value.strip()


def _resolve_metadata_search_paths(root: Path, config: dict, config_path: Path) -> tuple[Path, ...]:
    configured = config.get("search-path")
    if configured is None:
        return (root / MODULE_METADATA_FILENAME, *(root / name for name in SEARCH_DIRS))
    if not isinstance(configured, list) or not configured:
        raise ProjectContextError(
            f"{config_path}: tool.holoscan.search-path must be a non-empty array of paths."
        )
    paths: list[Path] = []
    for index, value in enumerate(configured):
        relative = _relative_project_path(
            value,
            path=f"tool.holoscan.search-path[{index}]",
            source_path=config_path,
        )
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:  # protects against a symlink escaping the project
            raise ProjectContextError(
                f"{config_path}: tool.holoscan.search-path[{index}] resolves outside the project."
            ) from exc
        paths.append(candidate)
    return tuple(paths)


def _is_sdk_installation(path: Path) -> bool:
    cmake_dir = path / "lib" / "cmake" / "holoscan"
    return path.is_dir() and (
        (cmake_dir / "holoscan-config.cmake").is_file()
        or (cmake_dir / "HoloscanConfig.cmake").is_file()
    )


def _resolve_sdk_installation(path: Path, arch: str, cuda: Optional[str] = None) -> Optional[Path]:
    """Resolve a direct install or a stable SDK root without shell expansion."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    if _is_sdk_installation(resolved):
        return resolved
    candidates = [resolved / f"install-{arch}"]
    if cuda:
        # Older SDK build layouts included the selected CUDA line. Prefer the
        # canonical current layout, but accept the matching reviewed profile
        # without asking the user to reconstruct its name with uname.
        candidates.extend(
            [
                resolved / f"install-cu{cuda}-{arch}",
                resolved / f"install-cuda{cuda}-{arch}",
            ]
        )
    return next((candidate for candidate in candidates if _is_sdk_installation(candidate)), None)


def _resolve_project_profile(
    root: Path,
    config: dict,
    config_path: Optional[Path],
    *,
    environ: Mapping[str, str],
) -> dict:
    """Resolve static project policy and machine-local SDK selection."""
    config_source = config_path or root / PYPROJECT_FILENAME
    arch, arch_source = _resolve_target_arch(environ)
    resolved: dict[str, object] = {
        "target_arch": arch,
        "target_arch_source": arch_source,
        "warnings": [],
    }
    build_type = config.get("build-type")
    if build_type is not None:
        if build_type not in {"Debug", "Release", "RelWithDebInfo"}:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.build-type must be Debug, Release, "
                "or RelWithDebInfo."
            )
        resolved["build_type"] = build_type

    cuda = config.get("cuda")
    if cuda is not None:
        if isinstance(cuda, bool) or not isinstance(cuda, int) or not 1 <= cuda <= 99:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.cuda must be an integer major version."
            )
        resolved["default_cuda_version"] = str(cuda)

    ctest_script = config.get("ctest-script")
    if ctest_script is not None:
        relative_script = _relative_project_path(
            ctest_script,
            path="tool.holoscan.ctest-script",
            source_path=config_source,
        )
        if not (root / relative_script).is_file():
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.ctest-script does not exist: {relative_script}."
            )
        resolved["ctest_script"] = relative_script

    for key, env_name in (
        ("docker-build-args", "docker_build_args"),
        ("docker-run-args", "docker_run_args"),
    ):
        values = config.get(key)
        if values is None:
            continue
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.{key} must be an array of non-empty strings."
            )
        resolved[env_name] = shlex.join(value.strip() for value in values)

    forward_env = config.get("forward-env")
    if forward_env is not None:
        if not isinstance(forward_env, list) or not all(
            isinstance(name, str) and _ENV_NAME_RE.fullmatch(name) for name in forward_env
        ):
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.forward-env must be an array of "
                "environment variable names."
            )
        resolved["forward_env"] = ",".join(forward_env)

    sdk = config.get("sdk", {})
    base_images = sdk.get("base-images")
    if base_images is not None:
        if arch not in base_images:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.sdk.base-images has no entry for {arch!r}."
            )
        base_image = base_images[arch]
        if not isinstance(base_image, str) or not _IMAGE_REFERENCE_RE.fullmatch(base_image.strip()):
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.sdk.base-images.{arch} must be a "
                "valid image reference without whitespace."
            )
        resolved["base_image"] = base_image.strip()

    sdk_version = sdk.get("version")
    if sdk_version is not None:
        if not isinstance(sdk_version, str) or not _VERSION_RE.fullmatch(sdk_version.strip()):
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.sdk.version must be an exact version."
            )
        resolved["sdk_version"] = sdk_version.strip()

    mount_read_only = sdk.get("mount-read-only", False)
    if not isinstance(mount_read_only, bool):
        raise ProjectContextError(
            f"{config_source}: tool.holoscan.sdk.mount-read-only must be a boolean."
        )
    resolved["sdk_mount_read_only"] = mount_read_only

    allow_parent_search = sdk.get("allow-parent-search", False)
    if not isinstance(allow_parent_search, bool):
        raise ProjectContextError(
            f"{config_source}: tool.holoscan.sdk.allow-parent-search must be a boolean."
        )
    candidates = sdk.get("search", [])
    if not isinstance(candidates, list) or not all(
        isinstance(candidate, str) and candidate.strip() for candidate in candidates
    ):
        raise ProjectContextError(
            f"{config_source}: tool.holoscan.sdk.search must be an array of non-empty strings."
        )

    configured_candidates: list[tuple[Path, str]] = []
    for index, raw_candidate in enumerate(candidates):
        candidate = raw_candidate.strip()
        rendered = candidate.replace("{arch}", arch)
        if "{" in rendered or "}" in rendered:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.sdk.search[{index}] uses an unsupported "
                "placeholder; only {{arch}} is allowed."
            )
        candidate_path = Path(rendered)
        if candidate_path.is_absolute() or rendered.startswith("~"):
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.sdk.search[{index}] must be relative; "
                "use HOLOSCAN_SDK_ROOT for a machine-local absolute path."
            )
        candidate_path = (root / candidate_path).resolve()
        boundary = root.parent.resolve() if allow_parent_search else root.resolve()
        try:
            candidate_path.relative_to(boundary)
        except ValueError as exc:
            capability = " with allow-parent-search = true" if not allow_parent_search else ""
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.sdk.search[{index}] resolves outside its "
                f"allowed boundary{capability}."
            ) from exc
        configured_candidates.append(
            (candidate_path, f"{config_source}:tool.holoscan.sdk.search[{index}]")
        )

    if environ.get("HOLOSCAN_CLI_BUILD_LOCAL", "").strip().lower() in _TRUE_ENV_VALUES:
        # Container recursion mounts a caller-selected SDK at this stable path.
        # Resolve it before repository hints, which describe host-side layouts.
        configured_candidates.insert(
            0,
            (Path("/workspace/holoscan-sdk"), "container:/workspace/holoscan-sdk"),
        )

    sdk_root = None
    sdk_source = None
    configured_cuda = resolved.get("default_cuda_version")
    cuda_for_sdk = configured_cuda if isinstance(configured_cuda, str) else None
    # Report an invalid HOLOSCAN_SDK_ROOT instead of raising: this runs before the
    # parser, so --local-sdk-root must still be able to override it.
    env_root = environ.get("HOLOSCAN_SDK_ROOT")
    env_error = None
    if env_root:
        env_path = Path(env_root)
        if not env_path.is_absolute():
            env_error = (
                "HOLOSCAN_SDK_ROOT must be an absolute path to an SDK installation or "
                f"its parent; got {env_root!r}."
            )
        else:
            sdk_root = _resolve_sdk_installation(env_path, arch, cuda_for_sdk)
            if sdk_root is None:
                env_error = (
                    f"HOLOSCAN_SDK_ROOT={env_root!r} is not a valid SDK installation for {arch}."
                )
            else:
                sdk_source = "HOLOSCAN_SDK_ROOT"
    if env_error:
        # An explicit override that cannot be honored must not silently resolve a
        # different tree, so do not fall back to committed hints.
        resolved["warnings"].append(
            f"{env_error} Pass --local-sdk-root to override it for a single command."
        )
    elif sdk_root is None:
        for candidate_path, candidate_source in configured_candidates:
            sdk_root = _resolve_sdk_installation(candidate_path, arch, cuda_for_sdk)
            if sdk_root is not None:
                sdk_source = candidate_source
                break
    resolved["sdk_root"] = sdk_root
    resolved["sdk_root_source"] = sdk_source
    return resolved


def _module_identity(module: dict, metadata_path: Path) -> tuple[str, str, Optional[str]]:
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
    return repo_prefix, repo_prefix.replace("_", "-"), sdk_version


def _build_context(
    root: Path,
    *,
    kind: str,
    discovery: str,
    descriptor: Optional[dict] = None,
    warnings: tuple[str, ...] = (),
    running_version: Optional[str] = None,
    load_module_contract: bool = True,
    environ: Optional[Mapping[str, str]] = None,
) -> ProjectContext:
    if kind != "module" or descriptor is None:
        return ProjectContext(root=root, kind=kind, discovery=discovery, warnings=warnings)

    module = descriptor
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
    derived_repo_prefix, derived_container_prefix, metadata_sdk_version = _module_identity(
        module, metadata_path
    )
    config_path, config = _read_holoscan_project_config(root)
    profile = _resolve_project_profile(
        root,
        config,
        config_path,
        environ=os.environ if environ is None else environ,
    )
    profile_warnings = tuple(profile.pop("warnings", []))

    repo_prefix = derived_repo_prefix
    container_prefix = derived_container_prefix
    workspace_name = repo_prefix
    hostname_prefix = container_prefix
    if config_path is not None:
        if "repo-prefix" in config:
            repo_prefix = _validated_name(
                config["repo-prefix"],
                path="tool.holoscan.repo-prefix",
                source_path=config_path,
                pattern=_REPO_PREFIX_RE,
            )
        if "container-prefix" in config:
            container_prefix = _validated_name(
                config["container-prefix"],
                path="tool.holoscan.container-prefix",
                source_path=config_path,
                pattern=_CONTAINER_PREFIX_RE,
            )
        workspace_name = config.get("workspace-name", repo_prefix)
        workspace_name = _validated_name(
            workspace_name,
            path="tool.holoscan.workspace-name",
            source_path=config_path,
            pattern=_WORKSPACE_NAME_RE,
        )
        hostname_prefix = config.get("hostname-prefix", container_prefix)
        hostname_prefix = _validated_name(
            hostname_prefix,
            path="tool.holoscan.hostname-prefix",
            source_path=config_path,
            pattern=_CONTAINER_PREFIX_RE,
        )

    requirements_path = root / REQUIREMENTS_FILENAME
    required_version = None
    requirement_error = None
    if requirements_path.is_file():
        try:
            required_version = parse_cli_requirement(requirements_path)
        except ProjectContextError as exc:
            requirement_error = str(exc)
    else:
        requirement_error = (
            f"Standalone Module {root} is missing {REQUIREMENTS_FILENAME}. "
            "Restore the generated file or recreate the Module."
        )

    search_paths = (
        _resolve_metadata_search_paths(root, config, config_path)
        if config_path is not None
        else (metadata_path, *(root / name for name in SEARCH_DIRS))
    )
    dockerfile_value = module.get("dockerfile")
    dockerfile = None
    if isinstance(dockerfile_value, str) and dockerfile_value.strip():
        relative_dockerfile = _relative_project_path(
            dockerfile_value,
            path="module.dockerfile",
            source_path=metadata_path,
        )
        dockerfile = (root / relative_dockerfile).resolve()
        try:
            dockerfile.relative_to(root.resolve())
        except ValueError as exc:
            raise ProjectContextError(
                f"{metadata_path}: module.dockerfile resolves outside the project."
            ) from exc
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
        repo_prefix=repo_prefix,
        container_prefix=container_prefix,
        workspace_name=workspace_name,
        hostname_prefix=hostname_prefix,
        base_sdk_version=profile.get("sdk_version", metadata_sdk_version),
        metadata_search_paths=tuple(search_paths),
        dockerfile=dockerfile,
        project_config_path=config_path,
        project_config_schema_version=(config.get("schema-version") if config else None),
        target_arch=profile.get("target_arch"),
        target_arch_source=profile.get("target_arch_source"),
        base_image=profile.get("base_image"),
        default_cuda_version=profile.get("default_cuda_version"),
        sdk_root=profile.get("sdk_root"),
        sdk_root_source=profile.get("sdk_root_source"),
        sdk_mount_read_only=bool(profile.get("sdk_mount_read_only", False)),
        ctest_script=profile.get("ctest_script"),
        build_type=profile.get("build_type"),
        docker_build_args=profile.get("docker_build_args"),
        docker_run_args=profile.get("docker_run_args"),
        forward_env=profile.get("forward_env"),
        warnings=(*warnings, *profile_warnings),
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
        descriptor = _read_module_metadata(root, strict=load_module_contract)
        if not existing_match and descriptor is None:
            raise ProjectContextError(
                f"--project-root {root} is not a recognized Holoscan source-project or Module root."
            )
        return _build_context(
            root,
            kind="module" if descriptor is not None else "source",
            discovery="project-root",
            descriptor=descriptor,
            running_version=running_version,
            load_module_contract=load_module_contract,
            environ=env,
        )

    env_root = env.get("HOLOSCAN_CLI_ROOT")
    if env_root:
        root = _resolve_explicit_root(env_root, original_cwd)
        # Same recognition check as --project-root, or an arbitrary directory
        # yields an empty project that skips the Module contract. This form warns
        # and falls back rather than failing, because it is ambient.
        if not root.exists() or not root.is_dir():
            warnings = (f"Ignoring invalid HOLOSCAN_CLI_ROOT={env_root!r}; discovering from cwd.",)
        else:
            descriptor = _read_module_metadata(root, strict=load_module_contract)
            if _matches_existing_root(root) or descriptor is not None:
                return _build_context(
                    root,
                    kind="module" if descriptor is not None else "source",
                    discovery="environment",
                    descriptor=descriptor,
                    running_version=running_version,
                    load_module_contract=load_module_contract,
                    environ=env,
                )
            warnings = (
                f"Ignoring HOLOSCAN_CLI_ROOT={env_root!r}: not a recognized Holoscan "
                "source-project or Module root; discovering from cwd.",
            )

    module_fallback: Optional[tuple[Path, dict]] = None
    for candidate in (original_cwd, *original_cwd.parents):
        existing_match = _matches_existing_root(candidate)
        descriptor = _read_module_metadata(
            candidate, strict=existing_match and load_module_contract
        )
        if existing_match:
            return _build_context(
                candidate,
                kind="module" if descriptor is not None else "source",
                discovery="ancestor",
                descriptor=descriptor,
                warnings=warnings,
                running_version=running_version,
                load_module_contract=load_module_contract,
                environ=env,
            )
        if descriptor is not None and module_fallback is None:
            module_fallback = (candidate, descriptor)

    if module_fallback is not None:
        root, descriptor = module_fallback
        return _build_context(
            root,
            kind="module",
            discovery="module-fallback",
            descriptor=descriptor,
            warnings=warnings,
            running_version=running_version,
            load_module_contract=load_module_contract,
            environ=env,
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
