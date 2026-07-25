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

"""Invocation-scoped structured command plans.

The first public slice records process steps for ``build-container``.  The
recorder is deliberately private and active only for ``--dryrun --json`` or
``--dryrun --shell`` so the normal execution path and human dry-run output stay
unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping, Optional, Sequence


class CommandPlanError(RuntimeError):
    """Raised when an invocation cannot produce a complete v1 plan."""


_ACTIVE_RECORDER: ContextVar[Optional["PlanRecorder"]] = ContextVar(
    "holoscan_cli_command_plan", default=None
)

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_EXACT_NAMES = {
    "API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "NGC_API_KEY",
    "NGC_CLI_API_KEY",
    "PASSWORD",
    "SECRET",
    "TOKEN",
}
_SENSITIVE_SUFFIXES = ("_API_KEY", "_PASSWORD", "_SECRET", "_TOKEN")
_DOCKER_VALUE_OPTIONS = {"-e", "--env", "--build-arg"}


def add_plan_output_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the command-plan output formats to one audited action parser."""

    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--json",
        dest="plan_format",
        action="store_const",
        const="json",
        help="With --dryrun, print a machine-readable command plan",
    )
    output.add_argument(
        "--shell",
        dest="plan_format",
        action="store_const",
        const="shell",
        help="With --dryrun, print a copyable Bash command plan",
    )
    parser.set_defaults(plan_format=None)


def get_active_recorder() -> Optional["PlanRecorder"]:
    """Return the recorder for the current invocation, if any."""

    return _ACTIVE_RECORDER.get()


def command_plan_active() -> bool:
    """Return whether structured planning is active in this context."""

    return get_active_recorder() is not None


def record_probe_fallback(message: str) -> None:
    """Attach a warning when the real resolver uses a documented fallback."""

    recorder = get_active_recorder()
    if recorder is not None:
        recorder.add_warning("probe_fallback_used", message)


def _normalize_env_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()


def _is_sensitive_env_name(name: str) -> bool:
    normalized = _normalize_env_name(name)
    return normalized in _SENSITIVE_EXACT_NAMES or normalized.endswith(_SENSITIVE_SUFFIXES)


def _redact_assignment(assignment: str) -> tuple[str, bool, Optional[str]]:
    """Return public assignment, redaction state, and named-env requirement."""

    if "=" not in assignment:
        name = assignment
        required = name if _ENV_NAME.fullmatch(name) else None
        return assignment, False, required

    name, _value = assignment.split("=", 1)
    if not _is_sensitive_env_name(name):
        return assignment, False, None
    return f"{name}=<redacted>", True, None


def _public_argv(argv: Sequence[str]) -> tuple[list[str], bool, list[str]]:
    """Redact recognized literal credentials in Docker option assignments."""

    public = [str(token) for token in argv]
    redacted = False
    required: set[str] = set()
    index = 0

    while index < len(public):
        token = public[index]
        if token in _DOCKER_VALUE_OPTIONS and index + 1 < len(public):
            replacement, changed, required_name = _redact_assignment(public[index + 1])
            public[index + 1] = replacement
            redacted = redacted or changed
            if required_name:
                required.add(required_name)
            index += 2
            continue

        for prefix in ("--env=", "-e=", "--build-arg="):
            if token.startswith(prefix):
                replacement, changed, required_name = _redact_assignment(token[len(prefix) :])
                public[index] = f"{prefix}{replacement}"
                redacted = redacted or changed
                if required_name:
                    required.add(required_name)
                break
        index += 1

    return public, redacted, sorted(required)


def _environment_delta(
    baseline: Mapping[str, str],
    effective: Mapping[str, str],
    explicit_set: Optional[Mapping[str, str]] = None,
) -> tuple[dict[str, str], list[str], bool]:
    changed: dict[str, str] = {}
    redacted = False
    explicit_names = set(explicit_set or {})
    for name in sorted(effective):
        value = str(effective[name])
        if baseline.get(name) == value and name not in explicit_names:
            continue
        if _is_sensitive_env_name(name):
            changed[name] = "<redacted>"
            redacted = True
        else:
            changed[name] = value
    unset = sorted(name for name in baseline if name not in effective)
    return changed, unset, redacted


def _shell_argv_groups(argv: Sequence[str]) -> list[list[str]]:
    """Group argv tokens into readable lines without changing shell semantics."""

    tokens = [str(token) for token in argv]
    if not tokens:
        return []

    head_length = 2 if len(tokens) > 1 and not tokens[1].startswith("-") else 1
    return [tokens[:head_length], *[[token] for token in tokens[head_length:]]]


def _shell_group_lines(
    groups: Sequence[Sequence[str]], *, first_indent: str, continuation_indent: str
) -> list[str]:
    """Quote grouped argv and add Bash line continuations."""

    lines = []
    for index, group in enumerate(groups):
        indent = first_indent if index == 0 else continuation_indent
        suffix = " \\" if index + 1 < len(groups) else ""
        lines.append(f"{indent}{shlex.join([str(token) for token in group])}{suffix}")
    return lines


def _process_shell(
    argv: Sequence[str],
    cwd: str,
    environment_set: Mapping[str, str],
    environment_unset: Sequence[str],
) -> str:
    command_groups = _shell_argv_groups(argv)
    lines = ["(", f"  {shlex.join(['cd', '--', cwd])} && \\"]
    if environment_set or environment_unset:
        lines.append("    env \\")
        env_groups = [["-u", name] for name in environment_unset]
        env_groups.extend([[f"{name}={value}"] for name, value in environment_set.items()])
        for group in env_groups:
            lines.append(f"      {shlex.join(group)} \\")
        lines.extend(
            _shell_group_lines(
                command_groups,
                first_indent="      ",
                continuation_indent="        ",
            )
        )
    else:
        lines.extend(
            _shell_group_lines(
                command_groups,
                first_indent="    ",
                continuation_indent="      ",
            )
        )
    lines.append(")")
    return "\n".join(lines)


@dataclass
class ProcessStep:
    """A process invocation plus its private parity data."""

    id: str
    role: str
    argv: list[str]
    private_argv: list[str] = field(repr=False)
    shell: str
    cwd: str
    environment: dict
    check: bool
    privilege: str
    redacted: bool
    destructive: bool = False

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": "process",
            "role": self.role,
            "argv": self.argv,
            "shell": self.shell,
            "cwd": self.cwd,
            "environment": self.environment,
            "check": self.check,
            "privilege": self.privilege,
            "redacted": self.redacted,
            "destructive": self.destructive,
        }


class PlanRecorder:
    """Record a complete, ordered command plan for one CLI invocation."""

    def __init__(self) -> None:
        self._environment = dict(os.environ)
        self.steps: list[ProcessStep] = []
        self.limitations: list[dict] = []
        self.warnings: list[dict] = []

    @contextmanager
    def activate(self) -> Iterator["PlanRecorder"]:
        if get_active_recorder() is not None:
            raise CommandPlanError("nested command-plan recorders are not supported")
        token = _ACTIVE_RECORDER.set(self)
        try:
            yield self
        finally:
            _ACTIVE_RECORDER.reset(token)

    def add_warning(self, code: str, message: str, step_id: Optional[str] = None) -> None:
        warning = {"code": code, "message": message}
        if step_id is not None:
            warning["step_id"] = step_id
        if warning not in self.warnings:
            self.warnings.append(warning)

    def record_process(
        self,
        argv: Sequence[str],
        *,
        role: str,
        cwd: Optional[os.PathLike[str] | str] = None,
        env: Optional[Mapping[str, str]] = None,
        explicit_env: Optional[Mapping[str, str]] = None,
        check: bool,
        privilege: str = "user",
        destructive: bool = False,
    ) -> ProcessStep:
        if role not in {"probe", "action", "cleanup"}:
            raise CommandPlanError(f"unsupported process role: {role}")

        private_argv = [str(token) for token in argv]
        if not private_argv:
            raise CommandPlanError("process argv must contain at least one token")
        public_argv, argv_redacted, required = _public_argv(private_argv)
        if env is not None:
            if not explicit_env:
                raise CommandPlanError(
                    "replacement subprocess environments are not supported in v1 plans"
                )
            expected_env = dict(self._environment)
            expected_env.update({str(name): str(value) for name, value in explicit_env.items()})
            if dict(env) != expected_env:
                raise CommandPlanError(
                    "replacement subprocess environments are not supported in v1 plans"
                )
        effective_env = os.environ if env is None else env
        missing_required = [name for name in required if name not in effective_env]
        if missing_required:
            names = ", ".join(missing_required)
            raise CommandPlanError(
                f"Docker environment reference is unset during planning: {names}"
            )
        environment_set, environment_unset, env_redacted = _environment_delta(
            self._environment, effective_env, explicit_env
        )
        external_required = [name for name in required if name not in environment_set]
        resolved_cwd = str(Path.cwd() if cwd is None else Path(cwd).resolve())
        step_id = f"step-{len(self.steps) + 1:03d}"
        redacted = argv_redacted or env_redacted
        environment = {
            "inherit": True,
            "set": environment_set,
            "unset": environment_unset,
            "required": external_required,
        }
        step = ProcessStep(
            id=step_id,
            role=role,
            argv=public_argv,
            private_argv=private_argv,
            shell=_process_shell(public_argv, resolved_cwd, environment_set, environment_unset),
            cwd=resolved_cwd,
            environment=environment,
            check=check,
            privilege=privilege,
            redacted=redacted,
            destructive=destructive,
        )
        self.steps.append(step)
        if redacted:
            self.add_warning(
                "redacted_value",
                "A credential-like literal was redacted from the public command plan.",
                step_id,
            )
        return step

    def _replay(self) -> dict:
        self._ensure_complete()
        replay_steps = [step for step in self.steps if step.role != "probe"]
        required = sorted(
            {name for step in replay_steps for name in step.environment.get("required", [])}
        )

        unavailable_reason = None
        if any(step.redacted for step in replay_steps):
            unavailable_reason = "redacted_literal"
        elif any(not step.check for step in replay_steps):
            unavailable_reason = "nonfatal_exit_handling"

        if unavailable_reason is not None:
            return {
                "format": "bash",
                "script": None,
                "required_environment": required,
                "unavailable_reason": unavailable_reason,
            }

        lines = ["#!/usr/bin/env bash", "set -e", ""]
        for name in required:
            lines.append(f': "${{{name}?Set {name} before running this script}}"')
        if required:
            lines.append("")
        for index, step in enumerate(replay_steps):
            summary = shlex.join(step.argv[:2]).replace("\r", "\\r").replace("\n", "\\n")
            lines.append(f"# {step.id} ({step.role}): {summary}")
            lines.append(step.shell)
            if index + 1 < len(replay_steps):
                lines.append("")
        return {
            "format": "bash",
            "script": "\n".join(lines) + "\n",
            "required_environment": required,
            "unavailable_reason": None,
        }

    def _ensure_complete(self) -> None:
        if not any(step.role in {"action", "cleanup"} for step in self.steps):
            raise CommandPlanError("the resolved branch contains no action steps")

    def payload(self) -> dict:
        replay = self._replay()
        warnings = list(self.warnings)
        if replay["script"] is None:
            warnings.append(
                {
                    "code": "shell_replay_unavailable",
                    "message": f"Bash replay unavailable: {replay['unavailable_reason']}",
                }
            )
        return {
            "schema_version": 1,
            "status": "dryrun",
            "scope": "current_cli_process",
            "host_resolved": True,
            "complete": True,
            "steps": [step.public_dict() for step in self.steps],
            "replay": replay,
            "limitations": list(self.limitations),
            "warnings": warnings,
        }

    def json_text(self) -> str:
        """Render the complete JSON artifact without writing stdout."""

        return json.dumps(self.payload(), indent=2)

    def shell_text(self) -> str:
        """Render Bash or fail before anything is written to stdout."""

        replay = self._replay()
        if replay["script"] is None:
            raise CommandPlanError(f"Bash replay unavailable: {replay['unavailable_reason']}")
        return str(replay["script"])
