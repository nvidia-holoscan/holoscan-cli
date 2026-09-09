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
project CLI and container classes.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from holoscan_cli.utils.docker import RESERVED_CONTAINER_ENV_NAMES
from holoscan_cli.utils.project import (
    ProjectContextError,
    relative_project_path,
    resolve_project_root,
    validate_object_keys,
)
from holoscan_cli.utils.sdk import normalize_arch, resolve_sdk_directory, resolve_target_arch
from holoscan_cli.utils.validators import (
    normalize_cuda_major,
    validate_environment_name,
    validate_image_reference,
)

MODULE_METADATA_FILENAME = "metadata.json"
PYPROJECT_FILENAME = "pyproject.toml"

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
_IMAGE_REFERENCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,254}")
_SUPPORTED_ARCHITECTURES = {"x86_64", "aarch64"}
_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


class ModuleMetadataError(ProjectContextError):
    """Invalid root Module metadata."""


@dataclass(frozen=True)
class ProjectContext:
    """Discovered project information available before the full CLI import."""

    root: Path
    kind: str
    discovery: str
    repo_prefix: Optional[str] = None
    base_sdk_version: Optional[str] = None
    dockerfile: Optional[Path] = None
    target_arch: Optional[str] = None
    cuda: Optional[str] = None
    ctest_script: Optional[str] = None
    base_image: Optional[str] = None
    sdk_root: Optional[Path] = None
    sdk_root_source: Optional[str] = None
    docker_build_args: Optional[str] = None
    docker_run_args: Optional[str] = None
    forward_env: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_module(self) -> bool:
        """Whether the project declares Holoscan Module project conventions in metadata.json"""
        return self.kind == "module"

    def profile_environment(self) -> dict[str, str]:
        """Return Module-derived defaults consumed by existing CLI classes."""
        if not self.is_module:
            return {"HOLOSCAN_CLI_ROOT": str(self.root)}

        values = {
            "HOLOSCAN_CLI_ROOT": str(self.root),
            "HOLOSCAN_CLI_BUILD_PARENT_DIR": str(self.root / "build"),
            "HOLOSCAN_CLI_DATA_DIR": str(self.root / "data"),
            "HOLOSCAN_CLI_SEARCH_PATH": ",".join((MODULE_METADATA_FILENAME, *SEARCH_DIRS)),
        }
        optional_values = {
            "HOLOSCAN_CLI_REPO_PREFIX": self.repo_prefix,
            "HOLOSCAN_CLI_CONTAINER_PREFIX": (
                self.repo_prefix.replace("_", "-") if self.repo_prefix else None
            ),
            "HOLOSCAN_CLI_BASE_SDK_VERSION": self.base_sdk_version,
            "HOLOSCAN_CLI_DEFAULT_DOCKERFILE": str(self.dockerfile) if self.dockerfile else None,
            "HOLOSCAN_CLI_DEFAULT_CUDA_VERSION": self.cuda,
            "HOLOSCAN_CLI_CTEST_SCRIPT": self.ctest_script,
            "HOLOSCAN_CLI_BASE_IMAGE": self.base_image,
            "HOLOSCAN_SDK_ROOT": str(self.sdk_root) if self.sdk_root else None,
            "HOLOSCAN_CLI_TARGET_ARCH": self.target_arch,
        }
        values.update({key: value for key, value in optional_values.items() if value})
        return values


_ACTIVE_PROJECT_CONTEXT: Optional[ProjectContext] = None
_PROJECT_DERIVED_ENVIRONMENT: dict[str, str] = {}


def get_active_project_context() -> Optional[ProjectContext]:
    """Return the context activated by the top-level dispatcher, if any."""
    return _ACTIVE_PROJECT_CONTEXT


def set_active_project_context(context: Optional[ProjectContext]) -> None:
    """Set the process-local context used for configuration resolution."""
    global _ACTIVE_PROJECT_CONTEXT, _PROJECT_DERIVED_ENVIRONMENT
    # Remove values injected by the previous context, but never erase a value
    # that application code changed afterwards; that change is now an explicit
    # process-environment override.
    for name, injected_value in _PROJECT_DERIVED_ENVIRONMENT.items():
        if os.environ.get(name) == injected_value:
            os.environ.pop(name, None)
    _PROJECT_DERIVED_ENVIRONMENT.clear()
    _ACTIVE_PROJECT_CONTEXT = context


def activated_environment_source(name: str) -> str:
    """Classify a bridged environment value as project, environment, or default."""
    if (
        name in _PROJECT_DERIVED_ENVIRONMENT
        and os.environ.get(name) == _PROJECT_DERIVED_ENVIRONMENT[name]
    ):
        return "project"
    if name in os.environ:
        return "environment"
    return "default"


def explicit_environment_value(name: str) -> Optional[str]:
    """Return an environment override, excluding project-injected defaults."""
    if activated_environment_source(name) != "environment":
        return None
    return os.environ.get(name)


def _is_source_root(path: Path) -> bool:
    if (path / "src" / "holoscan_cli").is_dir() and (path / PYPROJECT_FILENAME).is_file():
        return True
    return any(
        (path / directory / MODULE_METADATA_FILENAME).is_file()
        or any((path / directory).glob(f"*/{MODULE_METADATA_FILENAME}"))
        for directory in METADATA_DIRS
    )


def _read_module_metadata(root: Path) -> Optional[dict]:
    """Read the root Module descriptor from ecosystem ``metadata.json``."""
    metadata_path = root / MODULE_METADATA_FILENAME
    if not metadata_path.is_file():
        return None
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModuleMetadataError(f"Invalid Module metadata at {metadata_path}: {exc}") from exc
    if not isinstance(raw, dict) or "module" not in raw:
        return None
    if not isinstance(raw["module"], dict):
        raise ModuleMetadataError(f"Module metadata at {metadata_path} must contain an object.")
    return raw["module"]


def _read_holoscan_project_config(root: Path) -> tuple[Optional[Path], dict]:
    """Read and strictly validate the typed ``[tool.holoscan]`` table."""
    config_path = root / PYPROJECT_FILENAME
    if not config_path.is_file():
        return None, {}
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
    config = validate_object_keys(
        config,
        path="tool.holoscan",
        allowed={
            "base-images",
            "ctest-script",
            "cuda",
            "docker-build-args",
            "docker-run-args",
            "forward-env",
        },
        source_path=config_path,
    )

    if "base-images" in config:
        validate_object_keys(
            config["base-images"],
            path="tool.holoscan.base-images",
            allowed=_SUPPORTED_ARCHITECTURES,
            source_path=config_path,
        )
    return config_path, config


def _resolve_project_profile(
    root: Path,
    config: dict,
    config_path: Optional[Path],
    *,
    environ: Mapping[str, str],
) -> dict:
    """Resolve the small project contract and machine-local SDK selection."""
    config_source = config_path or root / PYPROJECT_FILENAME
    try:
        arch, arch_source = resolve_target_arch(environ, platform.machine())
    except ValueError as exc:
        raise ProjectContextError(str(exc)) from exc
    resolved: dict[str, object] = {
        "target_arch": arch,
        "warnings": [],
    }
    host_arch = normalize_arch(platform.machine())
    if arch_source != "host" and host_arch in _SUPPORTED_ARCHITECTURES and arch != host_arch:
        resolved["warnings"].append(
            f"HOLOSCAN_CLI_TARGET_ARCH selects {arch}, but this host is {host_arch}. "
            "Local SDK lookup and project base-image selection use the target architecture."
        )

    cuda = config.get("cuda")
    if cuda is not None:
        try:
            if isinstance(cuda, bool) or not isinstance(cuda, int):
                raise ValueError
            resolved["cuda"] = normalize_cuda_major(cuda)
        except ValueError as exc:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.cuda must be an integer major version "
                "from 1 to 99."
            ) from exc

    ctest_script = config.get("ctest-script")
    if ctest_script is not None:
        resolved["ctest_script"] = relative_project_path(
            ctest_script,
            path="tool.holoscan.ctest-script",
            source_path=config_source,
        )

    for key, field in (
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
        resolved[field] = shlex.join(value.strip() for value in values)

    forward_env = config.get("forward-env")
    if forward_env is not None:
        try:
            if not isinstance(forward_env, list):
                raise ValueError
            forward_env = tuple(validate_environment_name(name) for name in forward_env)
        except ValueError as exc:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.forward-env must be an array of "
                "environment variable names."
            ) from exc
        reserved_names = sorted(set(forward_env) & RESERVED_CONTAINER_ENV_NAMES)
        if reserved_names:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.forward-env contains CLI-owned container "
                f"environment name(s): {', '.join(reserved_names)}. Remove them; the CLI "
                "sets these values explicitly."
            )
        resolved["forward_env"] = forward_env

    base_images = config.get("base-images")
    if base_images is not None:
        if arch not in base_images:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.base-images has no entry for {arch!r}."
            )
        try:
            base_image = base_images[arch]
            if not isinstance(base_image, str):
                raise ValueError
            base_image = validate_image_reference(base_image.strip())
            if not _IMAGE_REFERENCE_RE.fullmatch(base_image):
                raise ValueError
        except ValueError as exc:
            raise ProjectContextError(
                f"{config_source}: tool.holoscan.base-images.{arch} must be a "
                "valid image reference without whitespace."
            ) from exc
        resolved["base_image"] = base_image

    sdk_cuda = environ.get("HOLOSCAN_CLI_DEFAULT_CUDA_VERSION") or (
        str(cuda) if cuda is not None else None
    )

    automatic_candidates: list[tuple[Path, str]] = []
    if environ.get("HOLOSCAN_CLI_BUILD_LOCAL", "").strip().lower() in _TRUE_ENV_VALUES:
        automatic_candidates.append(
            (Path("/workspace/holoscan-sdk"), "container:/workspace/holoscan-sdk")
        )
    for candidate in (root / "holoscan-sdk", root.parent / "holoscan-sdk"):
        if all(candidate != path for path, _source in automatic_candidates):
            automatic_candidates.append((candidate, f"automatic:{candidate}"))

    sdk_root = None
    sdk_source = None
    env_root = environ.get("HOLOSCAN_SDK_ROOT")
    env_error = None
    if env_root:
        env_path = Path(env_root)
        if not env_path.is_absolute():
            env_error = (
                "HOLOSCAN_SDK_ROOT must name an absolute path to an SDK installation, build, or "
                f"its parent; got {env_root!r}."
            )
        else:
            sdk_root = resolve_sdk_directory(env_path, arch, cuda_version=sdk_cuda)
            if sdk_root is None:
                env_error = (
                    f"HOLOSCAN_SDK_ROOT={env_root!r} is not a valid SDK directory for {arch}."
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
        for candidate_path, candidate_source in automatic_candidates:
            sdk_root = resolve_sdk_directory(candidate_path, arch, cuda_version=sdk_cuda)
            if sdk_root is not None:
                sdk_source = candidate_source
                break
    resolved["sdk_root"] = sdk_root
    resolved["sdk_root_source"] = sdk_source
    return resolved


def _module_identity(module: dict, metadata_path: Path) -> tuple[str, Optional[str]]:
    module_name = module.get("name")
    if not isinstance(module_name, str) or not module_name.strip():
        raise ModuleMetadataError(f"Module metadata at {metadata_path} has no valid module.name.")

    namespace = module.get("namespace")
    python_namespace = None
    if namespace is not None:
        if not isinstance(namespace, dict):
            raise ModuleMetadataError(
                f"Module metadata at {metadata_path} has an invalid module.namespace."
            )
        python_namespace = namespace.get("python")

    if python_namespace is not None:
        if not isinstance(python_namespace, str) or not python_namespace.strip():
            raise ModuleMetadataError(
                f"Module metadata at {metadata_path} has an invalid module.namespace.python."
            )
        segments = python_namespace.split(".")
        if not all(_PYTHON_SEGMENT_RE.fullmatch(segment) for segment in segments):
            raise ModuleMetadataError(
                f"Module metadata at {metadata_path} has an invalid Python namespace: "
                f"{python_namespace!r}."
            )
        repo_prefix = segments[-1]
    else:
        normalized_name = module_name.strip().lower().removeprefix("holoscan-")
        repo_prefix = re.sub(r"[^a-z0-9]+", "_", normalized_name).strip("_")
        if not repo_prefix:
            raise ModuleMetadataError(
                f"Module metadata at {metadata_path} cannot derive a project identity from "
                f"module.name={module_name!r}."
            )

    sdk_version = None
    sdk = module.get("holoscan_sdk")
    if sdk is not None:
        if not isinstance(sdk, dict):
            raise ModuleMetadataError(
                f"Module metadata at {metadata_path} has an invalid module.holoscan_sdk."
            )
        minimum = sdk.get("minimum_required_version")
        if minimum is not None:
            if not isinstance(minimum, str) or not minimum.strip():
                raise ModuleMetadataError(
                    f"Module metadata at {metadata_path} has an invalid minimum SDK version."
                )
            sdk_version = minimum.strip()
    return repo_prefix, sdk_version


def _build_module_context(
    root: Path,
    descriptor: dict,
    *,
    discovery: str,
    warnings: tuple[str, ...] = (),
    environ: Optional[Mapping[str, str]] = None,
) -> ProjectContext:
    metadata_path = root / MODULE_METADATA_FILENAME
    derived_repo_prefix, metadata_sdk_version = _module_identity(descriptor, metadata_path)
    config_path, config = _read_holoscan_project_config(root)
    profile = _resolve_project_profile(
        root,
        config,
        config_path,
        environ=os.environ if environ is None else environ,
    )
    profile_warnings = tuple(profile.pop("warnings", []))

    dockerfile_value = descriptor.get("dockerfile")
    dockerfile = None
    if isinstance(dockerfile_value, str) and dockerfile_value.strip():
        try:
            relative_dockerfile = relative_project_path(
                dockerfile_value,
                path="module.dockerfile",
                source_path=metadata_path,
            )
        except ProjectContextError as exc:
            raise ModuleMetadataError(str(exc)) from exc
        dockerfile = (root / relative_dockerfile).resolve()
        try:
            dockerfile.relative_to(root.resolve())
        except ValueError as exc:
            raise ModuleMetadataError(
                f"{metadata_path}: module.dockerfile resolves outside the project."
            ) from exc
    elif (root / "Dockerfile").is_file():
        dockerfile = root / "Dockerfile"

    return ProjectContext(
        root=root,
        kind="module",
        discovery=discovery,
        repo_prefix=derived_repo_prefix,
        base_sdk_version=metadata_sdk_version,
        dockerfile=dockerfile,
        target_arch=profile.get("target_arch"),
        cuda=profile.get("cuda"),
        ctest_script=profile.get("ctest_script"),
        base_image=profile.get("base_image"),
        sdk_root=profile.get("sdk_root"),
        sdk_root_source=profile.get("sdk_root_source"),
        docker_build_args=profile.get("docker_build_args"),
        docker_run_args=profile.get("docker_run_args"),
        forward_env=profile.get("forward_env", ()),
        warnings=(*warnings, *profile_warnings),
    )


def _selected_context(
    root: Path,
    *,
    discovery: str,
    warnings: tuple[str, ...] = (),
    environ: Optional[Mapping[str, str]] = None,
) -> ProjectContext:
    """Build a selected context without making metadata validity a root requirement."""
    try:
        descriptor = _read_module_metadata(root)
        if descriptor is not None:
            return _build_module_context(
                root,
                descriptor,
                discovery=discovery,
                warnings=warnings,
                environ=environ,
            )
    except ModuleMetadataError as exc:
        # Keep malformed metadata recoverable for `holoscan lint`.
        warnings = (*warnings, str(exc))
    return ProjectContext(root=root, kind="source", discovery=discovery, warnings=warnings)


def discover_project_context(
    *,
    cwd: Optional[Path] = None,
    explicit_root: Optional[str | os.PathLike[str]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> ProjectContext:
    """Select a root using CLI, environment, then ancestor precedence."""
    original_cwd = (cwd or Path.cwd()).resolve()
    env = os.environ if environ is None else environ
    warnings: tuple[str, ...] = ()

    if explicit_root is not None:
        root = resolve_project_root(explicit_root, original_cwd)
        if not root.exists() or not root.is_dir():
            raise ProjectContextError(f"--project-root {root} does not name an existing directory.")
        return _selected_context(
            root,
            discovery="project-root",
            environ=env,
        )

    env_root = env.get("HOLOSCAN_CLI_ROOT")
    if env_root:
        root = resolve_project_root(env_root, original_cwd)
        if not root.exists() or not root.is_dir():
            warnings = (f"Ignoring invalid HOLOSCAN_CLI_ROOT={env_root!r}; discovering from cwd.",)
        else:
            return _selected_context(
                root,
                discovery="environment",
                environ=env,
            )

    module_fallback: Optional[Path] = None
    for candidate in (original_cwd, *original_cwd.parents):
        if _is_source_root(candidate):
            return _selected_context(
                candidate,
                discovery="ancestor",
                warnings=warnings,
                environ=env,
            )
        if module_fallback is None and (candidate / MODULE_METADATA_FILENAME).is_file():
            module_fallback = candidate

    if module_fallback is not None:
        return _selected_context(
            module_fallback,
            discovery="module-fallback",
            warnings=warnings,
            environ=env,
        )
    return ProjectContext(root=original_cwd, kind="cwd", discovery="cwd", warnings=warnings)


def activate_project_context(context: ProjectContext) -> None:
    """Apply bounded defaults before importing CLI/container class bodies."""
    global _PROJECT_DERIVED_ENVIRONMENT
    set_active_project_context(context)
    values = context.profile_environment()
    # Root selection follows CLI > environment > discovery precedence and must
    # replace an invalid environment value. Other explicit environment values
    # remain authoritative over Module-derived defaults.
    root_was_present = "HOLOSCAN_CLI_ROOT" in os.environ
    root_value = values.pop("HOLOSCAN_CLI_ROOT")
    os.environ["HOLOSCAN_CLI_ROOT"] = root_value
    if not root_was_present:
        _PROJECT_DERIVED_ENVIRONMENT["HOLOSCAN_CLI_ROOT"] = root_value
    for key, value in values.items():
        if key not in os.environ:
            os.environ[key] = value
            _PROJECT_DERIVED_ENVIRONMENT[key] = value
