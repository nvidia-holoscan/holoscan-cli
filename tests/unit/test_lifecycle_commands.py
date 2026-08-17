# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import shlex
from argparse import Namespace

import pytest

from holoscan_cli.commands import build as build_cmd
from holoscan_cli.commands import containers as containers_cmd
from holoscan_cli.commands import install as install_cmd
from holoscan_cli.commands import run as run_cmd
from holoscan_cli.commands import test_cmd
from holoscan_cli.project_context import ProjectContext, set_active_project_context


class RecordingContainer:
    def __init__(self, project_metadata: dict | None = None):
        self.project_metadata = project_metadata or {
            "project_name": "smoke_app",
            "project_type": "application",
            "metadata": {"language": "python"},
        }
        self.image_name = "holohub-smoke:latest"
        self.image_names = [self.image_name]
        self.dryrun = False
        self.verbose = False
        self.cuda_version = None
        self.build_calls = []
        self.run_calls = []

    def build(self, **kwargs):
        self.build_calls.append(kwargs)

    def run(self, **kwargs):
        self.run_calls.append(kwargs)

    def compose_run_args(
        self,
        *,
        mode_docker_opts=None,
        docker_opts=None,
        include_default_run_args=True,
    ):
        if not include_default_run_args:
            return docker_opts or ""
        return " ".join(value for value in (mode_docker_opts, docker_opts) if value)

    def default_base_image(self, _cuda_version=None):
        return "nvcr.io/nvidia/holoscan:v4.2.0-cuda13"

    def resolve_run_image(self, img=None):
        return img or self.image_names[0]


class RecordingCLI:
    def __init__(self, tmp_path, project_data: dict | None = None):
        source = tmp_path / "repo" / "applications" / "smoke_app"
        source.mkdir(parents=True, exist_ok=True)
        self.project_data = project_data or {
            "project_name": "smoke_app",
            "project_type": "application",
            "source_folder": source,
            "metadata": {
                "language": "python",
                "run": {"command": "python app.py", "workdir": ""},
            },
        }
        self.DEFAULT_BUILD_PARENT_DIR = tmp_path / "build"
        self.DEFAULT_DATA_DIR = tmp_path / "data"
        self.DEFAULT_SDK_DIR = "/opt/nvidia/holoscan"
        self.DEFAULT_CTEST_SCRIPT = "/opt/holoscan-cli/container.ctest"
        self.HOLOHUB_ROOT = tmp_path / "repo"
        self.prefix = "holohub_"
        self.script_name = "holoscan"
        self.container = RecordingContainer(self.project_data)
        self.find_project_calls = []
        self.validated_modes = []

    def find_project(self, project_name, language=None):
        self.find_project_calls.append((project_name, language))
        return self.project_data

    def resolve_mode(self, project_data, mode_name):
        modes = project_data.get("metadata", {}).get("modes", {})
        if mode_name:
            return mode_name, modes.get(mode_name, {})
        return None, None

    def validate_mode(self, mode_name, mode_config):
        self.validated_modes.append((mode_name, mode_config))

    def get_effective_build_config(self, args, mode_config):
        build = mode_config.get("build", {})
        run = mode_config.get("run", {})
        return {
            "with_operators": build.get("with_operators", getattr(args, "with_operators", None)),
            "configure_args": build.get("configure_args", getattr(args, "configure_args", None)),
            "build_args": getattr(args, "build_args", None),
            "mode_build_args": (
                build.get("build_args") if not getattr(args, "replace_build_args", False) else None
            ),
            "docker_opts": getattr(args, "docker_opts", ""),
            "mode_docker_opts": (
                run.get("docker_opts") if not getattr(args, "replace_docker_opts", False) else None
            ),
            "include_default_build_args": not getattr(args, "replace_build_args", False),
            "include_default_run_args": not getattr(args, "replace_docker_opts", False),
        }

    def get_effective_run_config(self, args, mode_config):
        run = mode_config.get("run", {})
        return {
            "run_args": getattr(args, "run_args", None) or run.get("run_args"),
            "docker_opts": getattr(args, "docker_opts", ""),
            "mode_docker_opts": (
                run.get("docker_opts") if not getattr(args, "replace_docker_opts", False) else None
            ),
            "include_default_run_args": not getattr(args, "replace_docker_opts", False),
        }

    def make_project_container(self, project_name=None, language=None):
        self.container.project_name_arg = project_name
        self.container.language_arg = language
        return self.container


def _container_args(**overrides):
    defaults = {
        "project": "smoke_app",
        "mode": None,
        "docker_file": "Dockerfile",
        "base_img": "base:image",
        "img": None,
        "no_cache": False,
        "build_args": "--build-arg USER=dev",
        "cuda": "13",
        "extra_scripts": [],
        "local_sdk_root": None,
        "enable_x11": True,
        "ssh_x11": False,
        "init": False,
        "persistent": False,
        "nsys_profile": False,
        "nsys_location": "",
        "as_root": False,
        "docker_opts": "",
        "add_volume": None,
        "mps": False,
        "verbose": False,
        "dryrun": True,
        "language": None,
        "local": False,
        "no_docker_build": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def _project_args(**overrides):
    defaults = vars(_container_args()).copy()
    defaults.update(
        {
            "local": False,
            "build_type": None,
            "with_operators": None,
            "pkg_generator": "DEB",
            "parallel": None,
            "benchmark": False,
            "configure_args": None,
            "run_args": None,
            "no_local_build": False,
            "dev": False,
            "uninstall": False,
            "build_dir": None,
            "site_dir": None,
        }
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def test_handle_build_container_applies_mode_build_args(tmp_path, capsys):
    project = {
        "project_name": "smoke_app",
        "project_type": "application",
        "metadata": {
            "language": "python",
            "modes": {"dev": {"build": {"build_args": "--build-arg MODE=dev"}}},
        },
    }
    cli = RecordingCLI(tmp_path, project)

    containers_cmd.handle_build_container(cli, _container_args(mode="dev"))

    assert cli.container.build_calls == [
        {
            "docker_file": "Dockerfile",
            "base_img": "base:image",
            "img": None,
            "no_cache": False,
            "build_args": "--build-arg USER=dev",
            "mode_build_args": "--build-arg MODE=dev",
            "cuda_version": "13",
            "extra_scripts": [],
            "include_default_build_args": True,
        }
    ]
    assert "Building container for smoke_app in 'dev' mode" in capsys.readouterr().out


def test_handle_run_container_skips_build_and_wraps_trailing_command(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    monkeypatch.setattr(
        containers_cmd,
        "get_entrypoint_command_args",
        lambda img, cmd, opts, dry_run=False: ("--entrypoint=/bin/bash", ["-c", cmd]),
    )

    containers_cmd.handle_run_container(
        cli,
        _container_args(
            no_docker_build=True,
            as_root=True,
            docker_opts="--ipc=host",
            _trailing_args=["echo", "hello world"],
        ),
    )

    assert cli.container.build_calls == []
    assert cli.container.cuda_version == "13"
    run_call = cli.container.run_calls[0]
    assert run_call["as_root"] is True
    assert run_call["docker_opts"] == "--ipc=host --entrypoint=/bin/bash"
    assert run_call["extra_args"] == ["-c", "echo 'hello world'"]


def test_build_project_locally_emits_application_cmake_and_build_commands(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    calls = []
    monkeypatch.setattr(build_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(build_cmd.shutil, "which", lambda name: None)
    monkeypatch.setattr(build_cmd.os, "cpu_count", lambda: 8)

    build_dir, project_data = build_cmd.build_project_locally(
        cli,
        "smoke_app",
        language="python",
        build_type="debug",
        with_operators="op_a;op_b",
        dryrun=True,
        parallel="3",
        configure_args=["-DFEATURE=ON"],
    )

    cmake_args = " ".join(str(part) for part in calls[0])
    assert build_dir == tmp_path / "build" / "smoke_app"
    assert not build_dir.exists()
    assert project_data is cli.project_data
    assert "-DAPP_smoke_app=ON" in cmake_args
    assert "-DCMAKE_BUILD_TYPE=Debug" in cmake_args
    assert '-DHOLOHUB_BUILD_OPERATORS="op_a;op_b"' in cmake_args
    assert "-DHOLOHUB_BUILD_PYTHON=ON" in cmake_args
    assert "-DHOLOHUB_BUILD_CPP=OFF" in cmake_args
    assert "-DFEATURE=ON" in cmake_args
    assert calls[1] == ["cmake", "--build", str(build_dir), "--config", "Debug", "-j", "3"]


def test_local_sdk_environment_is_fail_closed(tmp_path, monkeypatch, capsys):
    cli = RecordingCLI(tmp_path)
    monkeypatch.setenv("HOLOSCAN_SDK_ROOT", str(tmp_path / "missing-sdk"))

    with pytest.raises(SystemExit):
        build_cmd.resolve_local_sdk_dir(cli)

    assert "HOLOSCAN_SDK_ROOT=" in capsys.readouterr().err


def test_local_build_reuses_standalone_project_sdk_resolution(tmp_path):
    cli = RecordingCLI(tmp_path)
    installation = tmp_path / "sdk" / "install-x86_64"
    context = ProjectContext(
        root=tmp_path,
        kind="module",
        discovery="test",
        target_arch="x86_64",
        sdk_root=installation,
        sdk_root_source="tool.holoscan.sdk.search[0]",
    )
    set_active_project_context(context)
    try:
        assert build_cmd.resolve_local_sdk_dir(cli, tmp_path / "sdk") == installation
    finally:
        set_active_project_context(None)


def test_typed_cmake_settings_outrank_free_form_extensions(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    calls = []
    monkeypatch.setattr(build_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(build_cmd.shutil, "which", lambda name: None)

    build_cmd.build_project_locally(
        cli,
        "smoke_app",
        language="python",
        build_type="debug",
        dryrun=True,
        configure_args=[
            "-DCMAKE_BUILD_TYPE=Release",
            "-DHOLOHUB_BUILD_PYTHON=OFF",
        ],
    )

    configure_command = calls[0]
    assert configure_command.index("-DCMAKE_BUILD_TYPE=Release") < configure_command.index(
        "-DCMAKE_BUILD_TYPE=Debug"
    )
    assert configure_command.index("-DHOLOHUB_BUILD_PYTHON=OFF") < configure_command.index(
        "-DHOLOHUB_BUILD_PYTHON=ON"
    )


def test_local_build_redacts_configure_extensions_from_display(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    calls = []

    def record_command(cmd, **kwargs):
        calls.append((cmd, kwargs))

    monkeypatch.setattr(build_cmd, "run_command", record_command)
    monkeypatch.setattr(build_cmd.shutil, "which", lambda name: None)

    build_cmd.build_project_locally(
        cli,
        "smoke_app",
        language="python",
        dryrun=True,
        configure_args=["-DAPI_TOKEN=secret-value"],
    )

    configure_command, configure_kwargs = calls[0]
    assert "-DAPI_TOKEN=secret-value" in configure_command
    assert "-DAPI_TOKEN=secret-value" not in configure_kwargs["display_override"]
    assert any("configured CMake option" in token for token in configure_kwargs["display_override"])


def test_build_project_locally_module_enables_subprojects_and_sccache(
    tmp_path, monkeypatch, capsys
):
    module_dir = tmp_path / "repo" / "modules" / "holoscan-smoke"
    module_dir.mkdir(parents=True)
    project = {
        "project_name": "holoscan-smoke",
        "project_type": "module",
        "source_folder": module_dir,
        "metadata": {
            "language": ["C++", "Python"],
            "subprojects": {"operators": ["smoke_op"], "applications": ["smoke_app"]},
        },
    }
    cli = RecordingCLI(tmp_path, project)
    stats_file = cli.DEFAULT_BUILD_PARENT_DIR / "holoscan-smoke" / "sccache-stats.txt"
    stats_file.parent.mkdir(parents=True)
    stats_file.write_text("existing stats", encoding="utf-8")
    calls = []
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "true")
    monkeypatch.setenv("SCCACHE_REDIS", "redis://user:secret@example.test")
    monkeypatch.setattr(build_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(
        build_cmd.shutil, "which", lambda name: "/usr/bin/sccache" if name == "sccache" else None
    )

    build_dir, _ = build_cmd.build_project_locally(
        cli, "holoscan-smoke", language="cpp", dryrun=True
    )

    cmake_args = " ".join(str(part) for part in calls[0])
    assert "-DMODULE_holoscan_smoke=ON" in cmake_args
    assert "-DOP_smoke_op=ON" in cmake_args
    assert "-DAPP_smoke_app=ON" in cmake_args
    assert "-DCMAKE_CXX_COMPILER_LAUNCHER=/usr/bin/sccache" in cmake_args
    assert calls[-1] == ["sccache", "--show-stats"]
    assert build_dir == stats_file.parent
    assert stats_file.read_text(encoding="utf-8") == "existing stats"
    output = capsys.readouterr().out
    assert "Building module 'holoscan-smoke'" in output
    assert "SCCACHE_REDIS=<configured>" in output
    assert "redis://user:secret@example.test" not in output


def test_build_writes_external_operators_manifest_from_module_sites(tmp_path, monkeypatch):
    """build_project_locally emits external_operators_manifest.cmake from
    modules/module-sites.json before configuring CMake (holohub#1587)."""
    modules_dir = tmp_path / "repo" / "modules"
    modules_dir.mkdir(parents=True)
    (modules_dir / "module-sites.json").write_text(
        json.dumps(
            {
                "modules": [
                    {
                        "name": "holoscan-deltacast",
                        "url": "https://github.com/deltacasttv/holoscan-modules",
                        "ref": "0" * 40,
                        "provides_operators": ["videomaster_source"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    app_dir = tmp_path / "repo" / "applications" / "demo"
    app_dir.mkdir(parents=True)
    project = {
        "project_name": "demo",
        "project_type": "application",
        "source_folder": app_dir,
        "metadata": {"language": "python"},
    }
    cli = RecordingCLI(tmp_path, project)
    monkeypatch.setattr(build_cmd, "run_command", lambda cmd, **kwargs: None)
    monkeypatch.setattr(build_cmd.shutil, "which", lambda name: None)

    build_dir, _ = build_cmd.build_project_locally(cli, "demo", dryrun=False)

    manifest = build_dir / "external_operators_manifest.cmake"
    assert manifest.exists()
    content = manifest.read_text(encoding="utf-8")
    assert "deltacasttv/holoscan-modules" in content
    assert "videomaster_source" in content


def test_build_project_locally_verbose_redacts_env_mapping(tmp_path, monkeypatch, capsys):
    """`--verbose` names mode environment entries without logging their values."""
    cli = RecordingCLI(tmp_path)
    monkeypatch.setattr(build_cmd, "run_command", lambda cmd, **kwargs: None)
    monkeypatch.setattr(build_cmd.shutil, "which", lambda name: None)

    build_cmd.build_project_locally(
        cli,
        "smoke_app",
        dryrun=False,
        verbose=True,
        extra_env={"DEMO_VAR": "secret-value"},
    )

    output = capsys.readouterr().out
    assert "export DEMO_VAR=<configured>" in output
    assert "secret-value" not in output


def test_handle_build_container_branch_passes_recursive_local_command(tmp_path, monkeypatch):
    project = {
        "project_name": "smoke_app",
        "project_type": "application",
        "metadata": {
            "language": "python",
            "modes": {
                "dev": {
                    "build": {
                        "build_args": "--build-arg MODE=dev",
                        "configure_args": ["-DMODE=dev"],
                    },
                    "run": {"docker_opts": "--ipc=host"},
                }
            },
        },
    }
    cli = RecordingCLI(tmp_path, project)
    captured = {}

    def capture_entrypoint(img, cmd, opts, dry_run=False):
        captured["entrypoint"] = (img, cmd, opts, dry_run)
        return "", []

    monkeypatch.setattr(build_cmd, "get_entrypoint_command_args", capture_entrypoint)

    build_cmd.handle_build(
        cli,
        _project_args(
            mode="dev",
            build_type="rel-debug",
            with_operators="cli_op",
            language="python",
            parallel="2",
            verbose=True,
            benchmark=True,
            configure_args=["-DCLI=ON"],
        ),
    )

    assert cli.container.build_calls[0]["build_args"] == "--build-arg USER=dev"
    assert cli.container.build_calls[0]["mode_build_args"] == "--build-arg MODE=dev"
    img, command, docker_opts, dryrun = captured["entrypoint"]
    assert img == "holohub-smoke:latest"
    assert docker_opts == "--ipc=host"
    assert dryrun is True
    assert shlex.split(command) == [
        "holoscan",
        "build",
        "smoke_app",
        "dev",
        "--local",
        "--build-type",
        "RelWithDebInfo",
        "--build-with=cli_op",
        "--pkg-generator",
        "DEB",
        "--language",
        "python",
        "--parallel",
        "2",
        "--verbose",
        "--benchmark",
        "--configure-args=-DCLI=ON",
    ]
    assert cli.container.run_calls


def test_container_entrypoint_inspection_and_launch_use_same_generated_tag(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    cli.container.image_name = "holohub-smoke:legacy"
    cli.container.image_names = ["holohub-smoke:branch", "holohub-smoke:legacy"]
    inspected = []

    def capture_entrypoint(img, cmd, opts, dry_run=False):
        inspected.append(img)
        return "", []

    monkeypatch.setattr(build_cmd, "get_entrypoint_command_args", capture_entrypoint)

    build_cmd.handle_build(cli, _project_args(no_docker_build=True))

    assert inspected == ["holohub-smoke:branch"]
    assert cli.container.run_calls[0]["img"] == "holohub-smoke:branch"


def test_recursive_build_uses_mode_type_and_quotes_layered_values(tmp_path, monkeypatch):
    project = {
        "project_name": "smoke_app",
        "project_type": "application",
        "metadata": {
            "language": "python",
            "modes": {"dev": {"build": {"env": {"CMAKE_BUILD_TYPE": "Debug"}}}},
        },
    }
    cli = RecordingCLI(tmp_path, project)
    captured = {}
    monkeypatch.delenv("CMAKE_BUILD_TYPE", raising=False)

    def capture_entrypoint(img, cmd, opts, dry_run=False):
        captured["command"] = cmd
        return "", []

    monkeypatch.setattr(build_cmd, "get_entrypoint_command_args", capture_entrypoint)

    build_cmd.handle_build(
        cli,
        _project_args(
            mode="dev",
            build_type=None,
            parallel="2; echo not-a-command",
            with_operators="",
        ),
    )

    tokens = shlex.split(captured["command"])
    assert tokens[tokens.index("--build-type") + 1] == "Debug"
    assert tokens[tokens.index("--parallel") + 1] == "2; echo not-a-command"
    assert "--build-with=" in tokens


def test_handle_run_local_dryrun_builds_mapping_and_executes_command(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    build_dir = tmp_path / "build" / "smoke_app"
    calls = []
    monkeypatch.setattr(
        run_cmd,
        "build_project_locally",
        lambda *args, **kwargs: (build_dir, cli.project_data),
    )
    monkeypatch.setattr(run_cmd, "run_command", lambda cmd, **kwargs: calls.append((cmd, kwargs)))

    run_cmd.handle_run(
        cli,
        _project_args(
            local=True,
            run_args="--frames 1",
            language="python",
            verbose=True,
        ),
    )

    command, kwargs = calls[0]
    assert command == ["python", "app.py", "--frames", "1"]
    assert kwargs["dry_run"] is True


def test_handle_run_container_branch_passes_recursive_local_command(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    captured = {}

    def capture_entrypoint(img, cmd, opts, dry_run=False):
        captured["entrypoint"] = (img, cmd, opts, dry_run)
        return "--entrypoint=/bin/bash", ["-c", cmd]

    monkeypatch.setattr(run_cmd, "get_entrypoint_command_args", capture_entrypoint)

    run_cmd.handle_run(
        cli,
        _project_args(
            build_type="debug",
            language="python",
            run_args="--once",
            no_local_build=True,
            pkg_generator="WHEEL",
            docker_opts="--ipc=host",
        ),
    )

    assert cli.container.build_calls
    img, command, docker_opts, dryrun = captured["entrypoint"]
    assert img == "holohub-smoke:latest"
    assert docker_opts == "--ipc=host"
    assert dryrun is True
    assert command.startswith("holoscan run smoke_app --language python --local")
    assert "--build-type Debug" in command
    assert "--pkg-generator WHEEL" in command
    assert "--no-local-build" in command
    assert "--run-args=--once" in command
    assert cli.container.run_calls[0]["extra_args"] == ["-c", command]


def test_handle_run_container_as_root_builds_as_user_then_runs_as_root(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    monkeypatch.setattr(run_cmd.os, "getuid", lambda: 12345)
    monkeypatch.setattr(run_cmd.os, "getgid", lambda: 23456)
    cli.container.DEFAULT_DOCKER_RUN_ARGS = "--network host --name default -dit"
    entrypoints = []

    def capture_entrypoint(img, cmd, opts, dry_run=False):
        entrypoints.append((cmd, opts))
        return "--entrypoint=/bin/bash", ["-c", cmd]

    monkeypatch.setattr(run_cmd, "get_entrypoint_command_args", capture_entrypoint)

    run_cmd.handle_run(
        cli,
        _project_args(
            as_root=True,
            build_type="debug",
            run_args="--once",
            configure_args=["-DDEV=ON"],
            replace_configure_args=True,
            no_mode_config=True,
            docker_opts="--ipc=host --user root --detach",
            replace_docker_opts=True,
        ),
    )

    assert len(cli.container.run_calls) == 2
    build_command, build_opts = entrypoints[0]
    assert build_command.startswith("holoscan build smoke_app --local")
    assert "--build-type Debug" in build_command
    assert "--configure-args=-DDEV=ON" in build_command
    assert "--replace-configure-args" in build_command
    assert "--no-mode-config" in build_command
    assert "--run-args" not in build_command
    # blocking, user-mapped builder: name/detach/user overrides stripped
    assert "--user 12345:23456" in build_opts
    assert "-it" not in build_opts
    assert "--ipc=host" in build_opts
    assert "--network host" not in build_opts
    for stripped in ("--name", "--detach", "--user root"):
        assert stripped not in build_opts

    build_run, app_run = cli.container.run_calls
    assert build_run["as_root"] is False
    assert build_run["include_default_run_args"] is False
    run_command, _ = entrypoints[1]
    assert "--no-local-build" in run_command
    assert "--run-args=--once" in run_command
    assert "--replace-configure-args" in run_command
    assert "--no-mode-config" in run_command
    assert app_run["as_root"] is True
    assert app_run["extra_args"] == ["-c", run_command]


def test_handle_install_local_installs_built_project(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    build_dir = tmp_path / "build" / "smoke_app"
    calls = []
    monkeypatch.setattr(
        install_cmd,
        "build_project_locally",
        lambda *args, **kwargs: (build_dir, cli.project_data),
    )
    monkeypatch.setattr(install_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))

    install_cmd.handle_install(cli, _project_args(local=True))

    assert calls == [["cmake", "--install", str(build_dir)]]


def test_handle_install_container_branch_passes_recursive_local_command(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    captured = {}

    def capture_entrypoint(img, cmd, opts, dry_run=False):
        captured["entrypoint"] = (img, cmd, opts, dry_run)
        return "", ["-c", cmd]

    monkeypatch.setattr(install_cmd, "get_entrypoint_command_args", capture_entrypoint)

    install_cmd.handle_install(
        cli,
        _project_args(
            build_type="debug",
            language="python",
            with_operators="op_a",
            parallel="4",
            configure_args=["-DDEV=ON"],
            docker_opts="--ipc=host",
            verbose=True,
        ),
    )

    img, command, docker_opts, dryrun = captured["entrypoint"]
    assert img == "holohub-smoke:latest"
    assert docker_opts == "--ipc=host"
    assert dryrun is True
    assert command.startswith("holoscan install smoke_app --local")
    assert "--build-type Debug" in command
    assert "--language python" in command
    assert "--build-with=op_a" in shlex.split(command)
    assert "--parallel 4" in command
    assert "--configure-args=-DDEV=ON" in command
    assert cli.container.run_calls[0]["extra_args"] == ["-c", command]


def test_handle_test_container_adds_coverage_build_args_and_ctest_options(tmp_path):
    cli = RecordingCLI(tmp_path)
    args = _container_args(
        coverage=True,
        clear_cache=False,
        no_xvfb=True,
        site_name="site-a",
        cdash_url="https://cdash.example",
        platform_name="linux",
        cmake_options=["-DFOO=ON"],
        ctest_options=["-DCASE=smoke"],
        ctest_script=None,
        build_name_suffix=None,
        language="python",
        local_sdk_root=str(tmp_path / "sdk"),
    )

    test_cmd.handle_test(cli, args)

    build_call = cli.container.build_calls[0]
    assert "--build-arg COVERAGE=ON" in build_call["build_args"]
    assert "coverage" in build_call["extra_scripts"]
    assert "xvfb" not in build_call["extra_scripts"]
    run_call = cli.container.run_calls[0]
    ctest_command = run_call["extra_args"][1]
    assert run_call["docker_opts"] == "--entrypoint=bash"
    assert run_call["as_root"] is True
    assert run_call["local_sdk_root"] == str(tmp_path / "sdk")
    assert "-DAPP=smoke_app" in ctest_command
    assert "-DTAG=latest" in ctest_command
    assert (
        '-DCONFIGURE_OPTIONS="-DFOO=ON;-DHOLOHUB_BUILD_PYTHON=ON;-DHOLOHUB_BUILD_CPP=OFF"'
        in ctest_command
    )
    assert "-DCTEST_SUBMIT_URL=https://cdash.example" in ctest_command
    assert "-DCOVERAGE=ON" in ctest_command
    # `--ctest-options` must propagate verbatim into the ctest invocation
    # (pre-consolidation `test_holohub_test_ctest_options`).
    assert "-DCASE=smoke" in ctest_command
    assert "command -v xvfb-run" not in ctest_command
    assert "xvfb-run -a" not in ctest_command


def test_handle_test_container_adds_xvfb_setup_layer_by_default(tmp_path):
    cli = RecordingCLI(tmp_path)
    args = _container_args(
        coverage=False,
        clear_cache=False,
        no_xvfb=False,
        site_name=None,
        cdash_url=None,
        platform_name=None,
        cmake_options=None,
        ctest_options=None,
        ctest_script=None,
        build_name_suffix=None,
    )

    test_cmd.handle_test(cli, args)

    assert cli.container.build_calls[0]["extra_scripts"] == ["xvfb"]
    ctest_command = cli.container.run_calls[0]["extra_args"][1]
    assert "command -v xvfb-run" in ctest_command
    assert "omitting --no-docker-build" in ctest_command
    assert "xvfb-run -a ctest" in ctest_command
    assert '-DCTEST_SOURCE_DIRECTORY="$PWD"' in ctest_command


def test_handle_test_container_does_not_duplicate_explicit_xvfb_setup_layer(tmp_path):
    cli = RecordingCLI(tmp_path)
    args = _container_args(
        coverage=False,
        clear_cache=False,
        no_xvfb=False,
        site_name=None,
        cdash_url=None,
        platform_name=None,
        cmake_options=None,
        ctest_options=None,
        ctest_script=None,
        build_name_suffix=None,
        extra_scripts=["xvfb"],
    )

    test_cmd.handle_test(cli, args)

    assert cli.container.build_calls[0]["extra_scripts"] == ["xvfb"]


def test_handle_test_skipped_container_build_has_actionable_xvfb_guard(tmp_path):
    cli = RecordingCLI(tmp_path)
    args = _container_args(
        coverage=False,
        clear_cache=False,
        no_xvfb=False,
        no_docker_build=True,
        site_name=None,
        cdash_url=None,
        platform_name=None,
        cmake_options=None,
        ctest_options=None,
        ctest_script=None,
        build_name_suffix=None,
    )

    test_cmd.handle_test(cli, args)

    assert cli.container.build_calls == []
    ctest_command = cli.container.run_calls[0]["extra_args"][1]
    assert "xvfb-run is unavailable" in ctest_command
    assert "omitting --no-docker-build" in ctest_command
    assert "exit 127" in ctest_command
    assert '-DCTEST_SOURCE_DIRECTORY="$PWD"' in ctest_command


def test_handle_test_forwards_explicit_local_sdk_root(tmp_path):
    cli = RecordingCLI(tmp_path)
    sdk_root = tmp_path / "sdk"
    args = _container_args(
        coverage=False,
        clear_cache=False,
        no_xvfb=True,
        site_name=None,
        cdash_url=None,
        platform_name=None,
        cmake_options=None,
        ctest_options=None,
        ctest_script=None,
        build_name_suffix=None,
        local_sdk_root=str(sdk_root),
    )

    test_cmd.handle_test(cli, args)

    assert cli.container.run_calls[0]["local_sdk_root"] == str(sdk_root)


def test_handle_test_local_runs_ctest_in_repo_with_environment(tmp_path, monkeypatch):
    cli = RecordingCLI(tmp_path)
    calls = []
    monkeypatch.setattr(test_cmd, "run_command", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    args = _container_args(
        local=True,
        clear_cache=False,
        no_xvfb=False,
        site_name=None,
        cdash_url=None,
        platform_name=None,
        cmake_options=None,
        ctest_options=None,
        ctest_script="local.ctest",
        coverage=False,
        build_name_suffix="manual",
        language=None,
    )

    test_cmd.handle_test(cli, args)

    command, kwargs = calls[0]
    assert command[0:2] == ["bash", "-c"]
    assert "command -v xvfb-run" in command[2]
    assert "xvfb-run -a ctest" in command[2]
    assert '-DCTEST_SOURCE_DIRECTORY="$PWD"' in command[2]
    assert "-DTAG=manual" in command[2]
    assert "-S local.ctest" in command[2]
    assert kwargs["dry_run"] is True
    assert str(cli.HOLOHUB_ROOT) in kwargs["env"]["PYTHONPATH"]
