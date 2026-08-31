# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small validation and path helpers shared by project discovery."""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Optional, cast

from holoscan_cli.utils.docker import resolve_cli_docker_opts
from holoscan_cli.utils.io import fatal, resolve
from holoscan_cli.utils.validators import validate_nonempty_string

if TYPE_CHECKING:
    from holoscan_cli.container.core import HoloscanContainer
    from holoscan_cli.project_context import ProjectContext

ReportedValue = str | Path

CMAKE_BUILD_TYPES = {
    "debug": "Debug",
    "release": "Release",
    "rel-debug": "RelWithDebInfo",
    "relwithdebinfo": "RelWithDebInfo",
    "default": "Release",
}


class ProjectContextError(ValueError):
    """A project root, Module descriptor, or project configuration is invalid."""


def resolve_build_type(
    build_type: Optional[str], environ: Optional[Mapping[str, str]] = None
) -> str:
    """Resolve and validate a supported CMake build type."""
    source = os.environ if environ is None else environ
    value = build_type if build_type is not None else source.get("CMAKE_BUILD_TYPE")
    if value is None or not value.strip():
        return CMAKE_BUILD_TYPES["default"]
    normalized = value.strip().lower()
    if normalized not in CMAKE_BUILD_TYPES:
        fatal(
            f"Unsupported build type {value!r}; expected debug, release, rel-debug, "
            "or RelWithDebInfo."
        )
    return CMAKE_BUILD_TYPES[normalized]


def validate_object_keys(value: object, *, path: str, allowed: set[str], source_path: Path) -> dict:
    """Validate a strict TOML table and return it as a dictionary."""
    if not isinstance(value, dict):
        raise ProjectContextError(f"{source_path}: {path} must be a table.")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProjectContextError(
            f"{source_path}: {path} contains unknown field(s): {', '.join(unknown)}."
        )
    return value


def relative_project_path(value: object, *, path: str, source_path: Path) -> str:
    """Return a validated relative path that cannot traverse above a project."""
    try:
        value = validate_nonempty_string(value).strip()
    except ValueError:
        raise ProjectContextError(f"{source_path}: {path} must be a non-empty string.")
    candidate = Path(value)
    if candidate.is_absolute() or value.startswith("~") or ".." in candidate.parts:
        raise ProjectContextError(
            f"{source_path}: {path} must stay within the project and be relative."
        )
    return candidate.as_posix()


def resolve_project_root(value: str | os.PathLike[str], cwd: Path) -> Path:
    """Resolve an absolute or cwd-relative project-root selection."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return resolve(path)


def append_configure_args(command: list[str], args: argparse.Namespace) -> None:
    """Propagate additive CMake options across container recursion."""
    for value in getattr(args, "configure_args", None) or []:
        command.append(f"--configure-args={value}")


def _explicit_environment_value(name: str) -> Optional[str]:
    """Read an explicit environment layer without creating an import cycle."""
    from holoscan_cli.project_context import explicit_environment_value

    return explicit_environment_value(name)


def resolve_effective_build_type(
    explicit_build_type: Optional[str],
    mode_environment: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve CLI/process/mode build type before container recursion."""
    build_type = explicit_build_type
    if build_type is None:
        build_type = _explicit_environment_value("CMAKE_BUILD_TYPE")
    if build_type is None and mode_environment:
        build_type = mode_environment.get("CMAKE_BUILD_TYPE")
    return resolve_build_type(build_type, environ={})


def _source_label(source: Optional[str]) -> str:
    if not source:
        return "built-in default"
    if source.startswith("--"):
        return f"command line ({source})"
    if source.startswith("container:"):
        return source
    if source.startswith("automatic:"):
        return "automatic discovery"
    if source.startswith("HOLOSCAN_") or source == "CMAKE_BUILD_TYPE":
        return f"environment ({source})"
    return source


def _reported_options(
    label: str,
    mode_value: object,
    cli_value: object,
    *,
    project_value: object = None,
    environment_name: Optional[str] = None,
) -> str:
    environment_value = _explicit_environment_value(environment_name) if environment_name else None
    layers = (
        ("project", project_value),
        ("mode", mode_value),
        ("environment", environment_value),
        ("command line", cli_value),
    )
    sources = [source for source, value in layers if value]
    if not sources:
        return f"{label}: none"
    return f"{label}: configured by {', '.join(sources)} (values hidden)"


def _mode_environment(mode_config: Mapping[str, object]) -> dict[str, str]:
    environment = mode_config.get("env")
    result = dict(cast(Mapping[str, str], environment)) if isinstance(environment, Mapping) else {}
    build = mode_config.get("build")
    if isinstance(build, Mapping):
        build_environment = build.get("env")
        if isinstance(build_environment, Mapping):
            result.update(cast(Mapping[str, str], build_environment))
    return result


def _reported_cuda(
    args: argparse.Namespace, context: Optional["ProjectContext"]
) -> tuple[ReportedValue, str]:
    cli_value = cast(Optional[str], getattr(args, "cuda", None))
    if cli_value is not None:
        return cli_value, "command line (--cuda)"

    environment_value = _explicit_environment_value("HOLOSCAN_CLI_DEFAULT_CUDA_VERSION")
    if environment_value is not None:
        return environment_value, "environment (HOLOSCAN_CLI_DEFAULT_CUDA_VERSION)"

    if context is not None and context.cuda is not None:
        return context.cuda, "project (tool.holoscan.cuda)"

    from holoscan_cli.utils.sdk import get_default_cuda_version

    return get_default_cuda_version(), "host detection"


def _reported_sdk(
    args: argparse.Namespace,
    context: Optional["ProjectContext"],
    default_sdk_root: Optional[str | Path],
    is_local_mode: Optional[bool],
) -> tuple[ReportedValue, str]:
    cli_sdk = cast(Optional[str | Path], getattr(args, "local_sdk_root", None))
    if cli_sdk is not None:
        return cli_sdk, "command line (--local-sdk-root)"

    if context is not None and context.sdk_root is not None:
        return context.sdk_root, _source_label(context.sdk_root_source)

    environment_sdk = _explicit_environment_value("HOLOSCAN_SDK_ROOT")
    if environment_sdk is not None:
        return environment_sdk, "environment (HOLOSCAN_SDK_ROOT)"

    if default_sdk_root is not None and is_local_mode:
        return default_sdk_root, "built-in default"
    return "none", "container image"


def _reported_base_image(
    args: argparse.Namespace,
    context: Optional["ProjectContext"],
    container: Optional["HoloscanContainer"],
) -> tuple[ReportedValue, str]:
    cli_image = cast(Optional[str], getattr(args, "base_img", None))
    if cli_image is not None:
        return cli_image, "command line (--base-img)"

    environment_image = _explicit_environment_value("HOLOSCAN_CLI_BASE_IMAGE")
    project_image = context.base_image if context is not None else None
    if container is not None:
        value = container.default_base_image(container.cuda_version)
    elif environment_image is not None:
        value = environment_image
    elif project_image is not None:
        value = project_image
    else:
        value = "automatic"

    if _explicit_environment_value("HOLOSCAN_CLI_BASE_IMAGE_FORMAT") is not None:
        source = "environment (HOLOSCAN_CLI_BASE_IMAGE_FORMAT)"
    elif environment_image is not None:
        source = "environment (HOLOSCAN_CLI_BASE_IMAGE)"
    elif project_image is not None:
        source = "project (tool.holoscan.base-images)"
    else:
        source = "derived default"
    return value, source


def _reported_forward_env(args: argparse.Namespace, context: Optional["ProjectContext"]) -> str:
    environment_value = _explicit_environment_value("HOLOSCAN_CLI_FORWARD_ENV")
    layers = (
        ("project", list(context.forward_env) if context is not None else []),
        ("environment", environment_value.split(",") if environment_value else []),
        ("command line", cast(Optional[list[str]], getattr(args, "forward_env", None)) or []),
    )
    names = list(
        dict.fromkeys(name.strip() for _, values in layers for name in values if name.strip())
    )
    if not names:
        return "forward-env: none"
    sources = [source for source, values in layers if values]
    return f"forward-env: {', '.join(names)} ({', '.join(sources)})"


def report_effective_configuration(
    args: argparse.Namespace,
    *,
    mode_name: Optional[str] = None,
    mode_config: Optional[Mapping[str, object]] = None,
    location_mode_environment: Optional[Mapping[str, str]] = None,
    effective_build_type: Optional[str] = None,
    is_local_mode: Optional[bool] = None,
    default_sdk_root: Optional[str | Path] = None,
    container: Optional["HoloscanContainer"] = None,
    include_build: bool = False,
    include_run: bool = False,
    include_configure: bool = False,
) -> None:
    """Print resolved project configuration for a dry run."""
    if not getattr(args, "dryrun", False):
        return

    from holoscan_cli.project_context import get_active_project_context

    mode_config = mode_config or {}
    build_value = mode_config.get("build")
    build_config = (
        cast(Mapping[str, object], build_value) if isinstance(build_value, Mapping) else {}
    )
    run_value = mode_config.get("run")
    run_config = cast(Mapping[str, object], run_value) if isinstance(run_value, Mapping) else {}
    context = get_active_project_context()
    lines: list[str] = []

    def add(label: str, value: ReportedValue, source: str) -> None:
        lines.append(f"{label}: {value} ({source})")

    if context is not None:
        root_sources = {
            "project-root": "command line (--project-root)",
            "environment": "environment (HOLOSCAN_CLI_ROOT)",
            "ancestor": "directory discovery",
            "module-fallback": "directory discovery",
            "cwd": "current directory",
        }
        add("project root", context.root, root_sources.get(context.discovery, context.discovery))

    if mode_name:
        source = "command line" if getattr(args, "mode", None) is not None else "project default"
        add("mode", mode_name, source)

    mode_env = _mode_environment(mode_config)
    location_mode_env = mode_env if location_mode_environment is None else location_mode_environment
    if is_local_mode is not None:
        if getattr(args, "local", None):
            source = "command line (--local)"
        elif _explicit_environment_value("HOLOSCAN_CLI_BUILD_LOCAL") is not None:
            source = "environment (HOLOSCAN_CLI_BUILD_LOCAL)"
        elif "HOLOSCAN_CLI_BUILD_LOCAL" in location_mode_env:
            source = "selected mode"
        else:
            source = "built-in default"
        add("execution", "local" if is_local_mode else "container", source)

    if effective_build_type is not None:
        if getattr(args, "build_type", None) is not None:
            source = "command line (--build-type)"
        elif _explicit_environment_value("CMAKE_BUILD_TYPE") is not None:
            source = "environment (CMAKE_BUILD_TYPE)"
        elif "CMAKE_BUILD_TYPE" in mode_env:
            source = "selected mode"
        else:
            source = "built-in default"
        add("build type", effective_build_type, source)

    cuda_value, cuda_source = _reported_cuda(args, context)
    add("CUDA", cuda_value, cuda_source)

    sdk_value, sdk_source = _reported_sdk(args, context, default_sdk_root, is_local_mode)
    add("local SDK", sdk_value, sdk_source)

    if include_build:
        base_image, base_image_source = _reported_base_image(args, context, container)
        add("base image", base_image, base_image_source)
        lines.append(
            _reported_options(
                "Docker build options",
                build_config.get("docker_build_args"),
                getattr(args, "build_args", None),
                project_value=context.docker_build_args if context is not None else None,
                environment_name="HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS",
            )
        )

    if include_run:
        if container is not None:
            cli_image = getattr(args, "img", None)
            add(
                "run image",
                container.resolve_run_image(cli_image),
                "command line (--img)" if cli_image else "derived default",
            )
        cli_docker_opts = resolve_cli_docker_opts(args)
        lines.append(
            _reported_options(
                "Docker run options",
                run_config.get("docker_run_args"),
                cli_docker_opts,
                project_value=context.docker_run_args if context is not None else None,
                environment_name="HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS",
            )
        )
        lines.append(_reported_forward_env(args, context))

    if include_configure:
        lines.append(
            _reported_options(
                "CMake configure options",
                build_config.get("cmake_options"),
                getattr(args, "configure_args", None),
            )
        )

    print("Effective configuration (opaque option values hidden):")
    for line in lines:
        print(f"  {line}")
