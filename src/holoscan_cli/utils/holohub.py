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

"""HoloHub-specific source-project utilities.

Root discovery, search paths, the ``HOLOHUB_PATH_PREFIX`` placeholder
namespace, project-type prefixes, build-type translation, sccache
location, environment-variable interpolation, and git-state helpers for
tagging container images.

These are the helpers that know about the source-project repository
layout the CLI operates on; they are deliberately separated from the
more generic :mod:`holoscan_cli.utils.io` and
:mod:`holoscan_cli.utils.text` modules.
"""

import functools
import grp
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from holoscan_cli.utils.io import format_cmd, info, run_info_command, warn
from holoscan_cli.utils.text import _slugify, get_env_bool

DEFAULT_GIT_REF = "latest"

PROJECT_PREFIXES = {
    "application": "APP",
    "benchmark": "APP",
    "gxf_extension": "EXT",
    "operator": "OP",
    "package": "PKG",
    "tutorial": "APP",
    "workflow": "APP",
    "default": "APP",  # specified type but not recognized
}

BUILD_TYPES = {
    "debug": "Debug",
    "release": "Release",
    "rel-debug": "RelWithDebInfo",
    "relwithdebinfo": "RelWithDebInfo",
    "default": "Release",
}


def check_skip_builds(args) -> Tuple[bool, bool]:
    """Checking skip build flags and printing info messages"""
    holohub_always_build, always_build = get_env_bool("HOLOHUB_ALWAYS_BUILD", default=True)
    skip_builds = not always_build
    skip_docker_build = skip_builds or getattr(args, "no_docker_build", False)
    skip_local_build = skip_builds or getattr(args, "no_local_build", False)
    if skip_builds:
        info(f"Skipping build due to HOLOHUB_ALWAYS_BUILD={holohub_always_build}")
    else:
        if getattr(args, "no_local_build", False):
            info("Skipping local build due to --no-local-build")
        if getattr(args, "no_docker_build", False):
            info("Skipping container build due to --no-docker-build")
    return skip_docker_build, skip_local_build


def _get_holohub_root() -> Path:
    """Get the source-project repository root path.

    The historical HoloHub CLI lived inside the source tree and could use its
    file location as the repository root. Once the code is installed in
    site-packages, root discovery must come from the wrapper environment or
    from the current working directory.
    """
    env_root = os.environ.get("HOLOHUB_ROOT")
    if env_root:
        env_path = Path(env_root).expanduser()
        if env_path.exists() and env_path.is_dir():
            return env_path
        warn(
            f"Environment variable HOLOHUB_ROOT='{env_root}' is invalid. "
            f"Falling back to default path: {Path(__file__).parent.parent.parent}"
        )
    cwd = Path.cwd().resolve()
    sentinel_files = ("holohub", "isaac_os", "i4h", "CMakeLists.txt", "Dockerfile")
    metadata_dirs = (
        "applications",
        "benchmarks",
        "gxf_extensions",
        "operators",
        "pkg",
        "subgraphs",
        "tutorials",
        "workflows",
    )
    for candidate in (cwd, *cwd.parents):
        if (candidate / "src" / "holoscan_cli").is_dir() and (
            candidate / "pyproject.toml"
        ).exists():
            return candidate
        if any((candidate / name).exists() for name in sentinel_files):
            if any((candidate / name).is_dir() for name in metadata_dirs):
                return candidate
        if any((candidate / name / "metadata.json").exists() for name in metadata_dirs):
            return candidate
    return cwd


HOLOHUB_ROOT = _get_holohub_root()


def get_holohub_root() -> Path:
    """Return the cached source-project repo root."""
    return HOLOHUB_ROOT


def get_component_search_paths(base_dir: Optional[Path] = None) -> tuple[Path, ...]:
    """Return metadata search paths honoring HOLOHUB_SEARCH_PATH overrides."""
    base_path = base_dir or HOLOHUB_ROOT
    tokens = os.environ.get("HOLOHUB_SEARCH_PATH", "").split(",")
    default_paths = (
        "applications",
        "benchmarks",
        "gxf_extensions",
        "operators",
        "pkg",
        "tutorials",
        "workflows",
    )
    paths = [token.strip() for token in tokens if token.strip()] or default_paths
    return tuple(
        (Path(token) if Path(token).is_absolute() else base_path / token) for token in paths
    )


def get_holohub_setup_scripts_dir() -> Path:
    """Return the directory containing named setup scripts (`./holohub setup --scripts`)."""
    return Path(
        os.environ.get("HOLOHUB_SETUP_SCRIPTS_DIR", HOLOHUB_ROOT / "utilities" / "setup")
    ).expanduser()


def get_group_id(group: str) -> Optional[int]:
    """Get group ID for a given group name"""
    try:
        return grp.getgrnam(group).gr_gid
    except KeyError:
        return None


def determine_project_prefix(project_type: str) -> str:
    """Map a project_type metadata value to its CMake target prefix."""
    type_str = project_type.lower().strip()
    if type_str in PROJECT_PREFIXES:
        return PROJECT_PREFIXES[type_str]
    return PROJECT_PREFIXES["default"]


def get_buildtype_str(build_type: Optional[str]) -> str:
    """Get CMake build type string"""
    if not build_type:
        return os.environ.get("CMAKE_BUILD_TYPE", BUILD_TYPES["default"])
    build_type_str = build_type.lower().strip()
    return BUILD_TYPES.get(build_type_str, BUILD_TYPES["default"])


@functools.lru_cache(maxsize=32)
def resolve_path_prefix(prefix: Optional[str] = None) -> str:
    """Resolve the path prefix for HoloHub placeholders"""
    if prefix is None:
        prefix = os.environ.get("HOLOHUB_PATH_PREFIX", "holohub_")
    if not prefix.endswith("_"):
        prefix = prefix + "_"
    return prefix


def build_holohub_path_mapping(
    holohub_root: Path,
    project_data: Optional[dict] = None,
    build_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    prefix: Optional[str] = None,
    verbose: bool = False,
) -> dict[str, str]:
    """Build a mapping of HoloHub placeholders to their resolved paths

    Args:
        holohub_root: Root directory of HoloHub
        project_data: Optional project metadata dictionary
        build_dir: Optional build directory path
        data_dir: Optional data directory path
        prefix: Prefix for placeholder keys. If None, reads from HOLOHUB_PATH_PREFIX
                environment variable (default: "holohub_")
        verbose: Whether to print verbose output

    Returns:
        Dictionary mapping placeholder names to their resolved paths
    """
    prefix = resolve_path_prefix(prefix)

    if data_dir is None:
        data_dir = holohub_root / "data"

    path_mapping = {
        f"{prefix}root": str(holohub_root),
        f"{prefix}data_dir": str(data_dir),
    }
    if not project_data:
        return path_mapping
    # Add project-specific mappings if project_data is provided
    app_source_path = project_data.get("source_folder", "")
    if app_source_path:
        path_mapping[f"{prefix}app_source"] = str(app_source_path)
    if build_dir:
        path_mapping[f"{prefix}bin"] = str(build_dir)
        if app_source_path:
            try:
                app_build_dir = build_dir / Path(app_source_path).relative_to(holohub_root)
                path_mapping[f"{prefix}app_bin"] = str(app_build_dir)
            except ValueError:
                # Handle case where app_source_path is not relative to holohub_root
                path_mapping[f"{prefix}app_bin"] = str(build_dir)
    elif project_data.get("project_name"):
        # If no build_dir provided but we have project name, try to infer it
        project_name = project_data["project_name"]
        inferred_build_dir = holohub_root / "build" / project_name
        path_mapping[f"{prefix}bin"] = str(inferred_build_dir)
        if app_source_path:
            try:
                app_build_dir = inferred_build_dir / Path(app_source_path).relative_to(holohub_root)
                path_mapping[f"{prefix}app_bin"] = str(app_build_dir)
            except ValueError:
                path_mapping[f"{prefix}app_bin"] = str(inferred_build_dir)

    if verbose:
        mapping_info = ";\n".join(f"<{key}>: {value}" for key, value in path_mapping.items())
        print(format_cmd(f"Path mappings: \n{mapping_info}", is_dryrun=False))

    return path_mapping


def replace_placeholders(
    text: str,
    path_mapping: dict[str, str] | None = None,
    env_mapping: dict[str, str] | None = None,
) -> str:
    """Replace placeholders in text using the provided path mapping and environment variables

    Supports two types of placeholders:
    1. Path mapping placeholders: <holohub_*> (e.g., <holohub_root>, <holohub_app_bin>)
    2. Environment variable placeholders: All other placeholders (e.g., <PATH>, <HOME>, <USER>)

    Resolution strategy:
    - Placeholders starting with "holohub_" are resolved using path_mapping
    - All other placeholders are resolved using environment variables

    Args:
        text: The text to replace placeholders in
        path_mapping: The path mapping to use
        env_mapping: The environment variables to use

    Returns:
        The text with placeholders replaced

    """
    if not text:
        return text
    result = text
    # Resolve path mapping placeholders
    path_mapping = path_mapping or {}
    for placeholder, replacement in path_mapping.items():
        bracketed_placeholder = f"<{placeholder}>"
        result = result.replace(bracketed_placeholder, replacement)

    # Resolve environment variable placeholders
    if env_mapping:
        # Find all environment variable placeholders in the result
        env_placeholders = re.findall(r"<([^>]+)>", result)
        for env_placeholder in env_placeholders:
            # check if placeholder is in env_mapping otherwise warn and continue
            if env_placeholder not in env_mapping:
                warn(
                    f"Placeholder <{env_placeholder}> is not in environment variables, "
                    "defaulting to empty string."
                )
            bracketed_env_placeholder = f"<{env_placeholder}>"
            result = result.replace(bracketed_env_placeholder, env_mapping.get(env_placeholder, ""))

    return result


def get_sccache_dir(env: Optional[dict[str, str]] = None) -> str:
    """Return the local sccache directory, honoring SCCACHE_DIR if set."""
    source_env: dict[str, str] = env if env is not None else os.environ  # type: ignore[assignment]
    return source_env.get("SCCACHE_DIR") or str(Path.home() / ".cache" / "sccache")


def update_env(
    env: dict[str, str],
    new_env: dict[str, str],
    path_mapping: dict[str, str] | None = None,
    verbose: bool = False,
) -> None:
    """
    Update the environment variable with the new value from the new environment dictionary.

    Supports placeholder replacement for:
    - Path mapping placeholders: <holohub_*> (e.g., <holohub_root>, <holohub_app_bin>)
    - Environment variable placeholders: <VAR_NAME> (e.g., <PATH>, <HOME>, <USER>)
      The variable name itself can be used as a placeholder to reference its current value.

    Examples:
    - "value:<VAR>" - prepend value to existing variable VAR
    - "<VAR>:value" - append value to existing variable VAR
    - "value:<VAR>:value2" - prepend and append to existing variable VAR
    - "value" - replace existing variable

    """
    # Default to empty dictionaries if not provided
    path_mapping = path_mapping or {}

    # Update the environment variables
    for key, value in new_env.items():
        env[key] = replace_placeholders(value, path_mapping, env)
        if verbose:
            print(format_cmd(f"    export {key}={env[key]}", is_dryrun=False))


# ---- git helpers (tag container images with the source-project state) -------


def get_git_short_sha(length: int = 12) -> str:
    """Return the short git SHA for the source-project repo, or DEFAULT_GIT_REF on failure."""
    try:
        sha = run_info_command(
            ["git", "rev-parse", f"--short={length}", "HEAD"], cwd=str(HOLOHUB_ROOT)
        )
        return sha or DEFAULT_GIT_REF
    except Exception:
        warn(f"Failed to get current git sha, defaulting to {DEFAULT_GIT_REF}")
        return DEFAULT_GIT_REF


def get_current_branch_slug() -> str:
    """Return the current git branch as a Docker-tag-friendly slug.

    Returns ``DEFAULT_GIT_REF`` when not on a branch (detached HEAD) or when
    git isn't available.
    """
    try:
        branch = run_info_command(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(HOLOHUB_ROOT)
        )
        if not branch or branch in ["HEAD", "(no branch)"] or branch.startswith("(HEAD detached"):
            return DEFAULT_GIT_REF
        return _slugify(branch) or DEFAULT_GIT_REF
    except Exception:
        warn(f"Failed to get current branch, defaulting to {DEFAULT_GIT_REF}")
        return DEFAULT_GIT_REF
