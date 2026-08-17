# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Safe, user-facing provenance for the small configuration ladder."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from holoscan_cli.project_context import (
    activated_environment_source,
    get_active_project_context,
)
from holoscan_cli.utils.text import merge_args_str


@dataclass(frozen=True)
class ConfigVectorLayers:
    """Additive configuration layers enabled for one invocation.

    These switches intentionally govern only extension vectors such as raw
    Docker options, CMake configure options, and forwarded environment names.
    Scalar project settings, mode commands/environments, and CLI-generated
    container invariants remain active.
    """

    project: bool = True
    mode: bool = True
    environment: bool = True


def get_config_vector_layers(args: Any) -> ConfigVectorLayers:
    """Resolve invocation-wide additive-layer suppression switches."""
    no_inherited = bool(getattr(args, "no_inherited_config", False))
    return ConfigVectorLayers(
        project=not (no_inherited or getattr(args, "no_project_config", False)),
        mode=not (no_inherited or getattr(args, "no_mode_config", False)),
        environment=not no_inherited,
    )


def merge_cli_option_fragments(values: object) -> str:
    """Merge one or more repeated shell-style CLI option fragments safely."""
    if values is None:
        return ""
    if isinstance(values, list):
        return merge_args_str(*values)
    return merge_args_str(values)


def resolve_cli_docker_opts(args: Any) -> tuple[str, bool]:
    """Return the effective CLI Docker fragment and whether it resets inheritance.

    ``--docker-opts`` remains additive and is repeatable.  The optional-value
    ``--replace-docker-opts`` is atomic: an attached value supplies the new
    baseline, while the flag without a value clears it.  Additive occurrences
    follow that baseline, which also preserves the previously documented
    two-flag spelling.
    """
    additions = merge_cli_option_fragments(getattr(args, "docker_opts", None))
    replacement = getattr(args, "replace_docker_opts", None)
    # Accept ``False`` from older programmatic Namespace fixtures as omission;
    # the parser now uses None / string, and a bare flag produces "".
    if replacement is None or replacement is False:
        return additions, False
    replacement_value = "" if replacement is True else replacement
    return merge_args_str(replacement_value, additions), True


def append_config_vector_flags(command: list[str], args: Any) -> None:
    """Propagate explicit additive-layer controls across container recursion."""
    for option, attribute in (
        ("--no-project-config", "no_project_config"),
        ("--no-mode-config", "no_mode_config"),
        ("--no-inherited-config", "no_inherited_config"),
    ):
        if getattr(args, attribute, False):
            command.append(option)


def apply_container_cli_overrides(args: Any, container: Any) -> None:
    """Apply typed invocation overrides before image names are inspected.

    Image naming depends on CUDA. Set an explicit ``--cuda`` as soon as the
    container object exists so provenance, entrypoint inspection, build tags,
    CTest labels, and launch all observe the same value. This helper is called
    regardless of whether verbose reporting is enabled.
    """
    cuda = getattr(args, "cuda", None)
    if cuda is not None:
        container.cuda_version = cuda
    container.config_layers = get_config_vector_layers(args)


def _token_count(value: object) -> int:
    if not value:
        return 0
    if isinstance(value, list):
        return len(value)
    try:
        return len(shlex.split(str(value)))
    except ValueError:
        return 0


def _real_environment_value(name: str) -> Optional[str]:
    if activated_environment_source(name) == "environment":
        return os.environ.get(name)
    return None


def _source_label(source: Optional[str]) -> str:
    if not source:
        return "built-in default"
    if source.startswith("--"):
        return f"command line ({source})"
    if source.startswith("container:"):
        return source
    if source.startswith("HOLOSCAN_") or source in {"CMAKE_BUILD_TYPE", "holoscan_ROOT"}:
        return f"environment ({source})"
    if "tool.holoscan" in source:
        return f"project ({source.rsplit(':', 1)[-1]})"
    return source


def _format_opaque_layers(
    project_value: object,
    mode_value: object,
    environment_value: object,
    cli_value: object,
    *,
    replace: bool,
    replace_option: str,
    unit: str = "token",
) -> str:
    values = (
        [("CLI", cli_value)]
        if replace
        else [
            ("project", project_value),
            ("mode", mode_value),
            ("environment", environment_value),
            ("CLI", cli_value),
        ]
    )
    counts = [(source, _token_count(value)) for source, value in values]
    counts = [(source, count) for source, count in counts if count]
    total = sum(count for _, count in counts)
    detail = " + ".join(f"{source} {count}" for source, count in counts) or "none"
    reset = f"; lower layers cleared by {replace_option}" if replace else ""
    unit_label = unit if total == 1 else {"entry": "entries"}.get(unit, f"{unit}s")
    return f"{total} {unit_label} ({detail}){reset}"


def _mode_environment(mode_config: Mapping[str, Any]) -> dict[str, str]:
    result = dict(mode_config.get("env", {}))
    result.update(mode_config.get("build", {}).get("env", {}))
    return result


def report_effective_configuration(
    args: Any,
    *,
    mode_name: Optional[str] = None,
    mode_config: Optional[Mapping[str, Any]] = None,
    location_mode_environment: Optional[Mapping[str, str]] = None,
    effective_build_type: Optional[str] = None,
    is_local_mode: Optional[bool] = None,
    default_sdk_root: Optional[object] = None,
    container: Optional[Any] = None,
    include_build: bool = False,
    include_run: bool = False,
    include_configure: bool = False,
) -> None:
    """Print effective values and sources without echoing opaque argument values."""
    if not getattr(args, "verbose", False):
        return

    mode_config = mode_config or {}
    context = get_active_project_context()
    config_layers = get_config_vector_layers(args)
    lines: list[str] = []

    if context is not None:
        root_sources = {
            "project-root": "command line (--project-root)",
            "environment": "environment (HOLOSCAN_CLI_ROOT)",
            "ancestor": "directory discovery",
            "module-fallback": "directory discovery",
            "cwd": "current directory",
        }
        lines.append(
            f"project root: {context.root} "
            f"({root_sources.get(context.discovery, context.discovery)})"
        )

    if config_layers != ConfigVectorLayers():
        states = ", ".join(
            f"{name}={'active' if enabled else 'ignored'}"
            for name, enabled in (
                ("project", config_layers.project),
                ("mode", config_layers.mode),
                ("environment", config_layers.environment),
            )
        )
        if getattr(args, "no_inherited_config", False):
            reason = "--no-inherited-config"
        else:
            reason = ", ".join(
                option
                for option, enabled in (
                    ("--no-project-config", getattr(args, "no_project_config", False)),
                    ("--no-mode-config", getattr(args, "no_mode_config", False)),
                )
                if enabled
            )
        lines.append(f"additive configuration layers: {states} ({reason})")

    if mode_name:
        source = "command line" if getattr(args, "mode", None) is not None else "project default"
        lines.append(f"mode: {mode_name} ({source})")

    mode_env = _mode_environment(mode_config)
    location_mode_env = mode_env if location_mode_environment is None else location_mode_environment
    if is_local_mode is not None:
        if getattr(args, "local", None) is not None:
            location_source = "command line (--local/--container)"
        elif _real_environment_value("HOLOSCAN_CLI_BUILD_LOCAL") is not None:
            location_source = "environment (HOLOSCAN_CLI_BUILD_LOCAL)"
        elif "HOLOSCAN_CLI_BUILD_LOCAL" in location_mode_env:
            location_source = "selected mode"
        else:
            location_source = "built-in default"
        location = "local" if is_local_mode else "container"
        lines.append(f"execution: {location} ({location_source})")

    if effective_build_type is not None:
        if getattr(args, "build_type", None) is not None:
            build_type_source = "command line (--build-type)"
        elif _real_environment_value("CMAKE_BUILD_TYPE") is not None:
            build_type_source = "environment (CMAKE_BUILD_TYPE)"
        elif "CMAKE_BUILD_TYPE" in mode_env:
            build_type_source = "selected mode"
        elif context is not None and context.build_type is not None:
            build_type_source = "project (tool.holoscan.build-type)"
        else:
            build_type_source = "built-in default"
        lines.append(f"build type: {effective_build_type} ({build_type_source})")

    cli_cuda = getattr(args, "cuda", None)
    if cli_cuda is not None:
        cuda_value, cuda_source = cli_cuda, "command line (--cuda)"
    elif context is not None and context.default_cuda_version is not None:
        cuda_value = context.default_cuda_version
        cuda_source = _source_label(context.default_cuda_version_source)
    elif _real_environment_value("HOLOSCAN_CLI_DEFAULT_CUDA_VERSION") is not None:
        cuda_value = os.environ["HOLOSCAN_CLI_DEFAULT_CUDA_VERSION"]
        cuda_source = "environment (HOLOSCAN_CLI_DEFAULT_CUDA_VERSION)"
    else:
        cuda_value, cuda_source = "automatic", "host detection"
    lines.append(f"CUDA: {cuda_value} ({cuda_source})")

    cli_sdk = getattr(args, "local_sdk_root", None)
    if cli_sdk is not None:
        sdk_value = context.sdk_root if context is not None and context.sdk_root else cli_sdk
        sdk_source = "command line (--local-sdk-root)"
    elif context is not None and context.sdk_root is not None:
        sdk_value = context.sdk_root
        sdk_source = _source_label(context.sdk_root_source)
    elif _real_environment_value("HOLOSCAN_SDK_ROOT") is not None:
        sdk_value = os.environ["HOLOSCAN_SDK_ROOT"]
        sdk_source = "environment (HOLOSCAN_SDK_ROOT)"
    elif default_sdk_root is not None and is_local_mode:
        sdk_value, sdk_source = default_sdk_root, "built-in default"
    else:
        sdk_value, sdk_source = "none", "container image"
    lines.append(f"local SDK: {sdk_value} ({sdk_source})")

    if include_build:
        if getattr(args, "base_img", None) is not None:
            base_value = args.base_img
            base_source = "command line (--base-img)"
        else:
            if container is not None and hasattr(container, "default_base_image"):
                base_value = container.default_base_image(cli_cuda)
            elif _real_environment_value("HOLOSCAN_CLI_BASE_IMAGE") is not None:
                base_value = os.environ["HOLOSCAN_CLI_BASE_IMAGE"]
            elif context is not None and context.base_image is not None:
                base_value = context.base_image
            else:
                base_value = "automatic"

            if _real_environment_value("HOLOSCAN_CLI_BASE_IMAGE_FORMAT") is not None:
                base_source = "environment (HOLOSCAN_CLI_BASE_IMAGE_FORMAT)"
            elif _real_environment_value("HOLOSCAN_CLI_BASE_IMAGE") is not None:
                base_source = "environment (HOLOSCAN_CLI_BASE_IMAGE)"
            elif context is not None and context.base_image is not None:
                base_source = "project (tool.holoscan.sdk.base-images)"
            else:
                base_source = "derived default"
        lines.append(f"base image: {base_value} ({base_source})")

        project_args = (
            getattr(context, "docker_build_args", None)
            if context and config_layers.project
            else None
        )
        mode_args = (
            mode_config.get("build", {}).get("docker_build_args") if config_layers.mode else None
        )
        env_args = (
            _real_environment_value("HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS")
            if config_layers.environment
            else None
        )
        lines.append(
            "Docker build options: "
            + _format_opaque_layers(
                project_args,
                mode_args,
                env_args,
                getattr(args, "build_args", None),
                replace=getattr(args, "replace_build_args", False),
                replace_option="--replace-build-args",
            )
        )

    if include_run:
        if container is not None:
            lines.append(
                f"run image: {container.resolve_run_image(getattr(args, 'img', None))} "
                f"({'command line (--img)' if getattr(args, 'img', None) else 'derived default'})"
            )
        project_args = (
            getattr(context, "docker_run_args", None) if context and config_layers.project else None
        )
        mode_args = (
            mode_config.get("run", {}).get("docker_run_args") if config_layers.mode else None
        )
        env_args = (
            _real_environment_value("HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS")
            if config_layers.environment
            else None
        )
        cli_docker_opts, replace_docker_opts = resolve_cli_docker_opts(args)
        lines.append(
            "Docker run options: "
            + _format_opaque_layers(
                project_args,
                mode_args,
                env_args,
                cli_docker_opts,
                replace=replace_docker_opts,
                replace_option="--replace-docker-opts",
            )
        )

        project_names = (
            getattr(context, "forward_env", None) if context and config_layers.project else None
        )
        env_names = (
            _real_environment_value("HOLOSCAN_CLI_FORWARD_ENV")
            if config_layers.environment
            else None
        )
        cli_names = getattr(args, "forward_env", None)
        name_layers = (
            [cli_names or []]
            if getattr(args, "replace_forward_env", False)
            else [
                project_names.split(",") if project_names else [],
                env_names.split(",") if env_names else [],
                cli_names or [],
            ]
        )
        effective_names = list(dict.fromkeys(name for layer in name_layers for name in layer))
        rendered_names = ", ".join(effective_names) if effective_names else "none"
        lines.append(
            "forward-env allowlist: "
            + _format_opaque_layers(
                project_names.split(",") if project_names else None,
                None,
                env_names.split(",") if env_names else None,
                cli_names,
                replace=getattr(args, "replace_forward_env", False),
                replace_option="--replace-forward-env",
                unit="name",
            )
            + f"; names: {rendered_names}"
        )

    if include_configure:
        mode_options = (
            mode_config.get("build", {}).get("cmake_options") if config_layers.mode else None
        )
        lines.append(
            "CMake configure options: "
            + _format_opaque_layers(
                None,
                mode_options,
                None,
                getattr(args, "configure_args", None),
                replace=getattr(args, "replace_configure_args", False),
                replace_option="--replace-configure-args",
                unit="entry",
            )
        )

    print("Effective configuration (opaque option values hidden):")
    for line in lines:
        print(f"  {line}")
