# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from argparse import Namespace

from holoscan_cli.commands import build as build_cmd
from holoscan_cli.commands import containers as containers_cmd
from holoscan_cli.commands import install as install_cmd
from holoscan_cli.commands import run as run_cmd
from holoscan_cli.commands import test_cmd


class RecordingContainer:
    def __init__(self, project_metadata: dict | None = None):
        self.project_metadata = project_metadata or {
            "project_name": "smoke_app",
            "project_type": "application",
            "metadata": {"language": "python"},
        }
        self.image_name = "holohub-smoke:latest"
        self.dryrun = False
        self.verbose = False
        self.cuda_version = None
        self.build_calls = []
        self.run_calls = []

    def build(self, **kwargs):
        self.build_calls.append(kwargs)

    def run(self, **kwargs):
        self.run_calls.append(kwargs)

    def default_base_image(self):
        return "nvcr.io/nvidia/holoscan:v4.2.0-cuda13"


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
            "build_args": build.get("build_args", getattr(args, "build_args", None)),
            "docker_opts": run.get("docker_opts", getattr(args, "docker_opts", "")),
        }

    def get_effective_run_config(self, args, mode_config):
        run = mode_config.get("run", {})
        return {"run_args": getattr(args, "run_args", None) or run.get("run_args")}

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
            "build_args": "--build-arg MODE=dev",
            "cuda_version": "13",
            "extra_scripts": [],
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
    assert run_call["extra_args"] == ["-c", "echo hello world"]


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
    assert project_data is cli.project_data
    assert "-DAPP_smoke_app=ON" in cmake_args
    assert "-DCMAKE_BUILD_TYPE=Debug" in cmake_args
    assert '-DHOLOHUB_BUILD_OPERATORS="op_a;op_b"' in cmake_args
    assert "-DHOLOHUB_BUILD_PYTHON=ON" in cmake_args
    assert "-DHOLOHUB_BUILD_CPP=OFF" in cmake_args
    assert "-DFEATURE=ON" in cmake_args
    assert calls[1] == ["cmake", "--build", str(build_dir), "--config", "Debug", "-j", "3"]


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
    calls = []
    monkeypatch.setenv("HOLOSCAN_CLI_ENABLE_SCCACHE", "true")
    monkeypatch.setattr(build_cmd, "run_command", lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(
        build_cmd.shutil, "which", lambda name: "/usr/bin/sccache" if name == "sccache" else None
    )

    build_cmd.build_project_locally(cli, "holoscan-smoke", language="cpp", dryrun=True)

    cmake_args = " ".join(str(part) for part in calls[0])
    assert "-DMODULE_holoscan_smoke=ON" in cmake_args
    assert "-DOP_smoke_op=ON" in cmake_args
    assert "-DAPP_smoke_app=ON" in cmake_args
    assert "-DCMAKE_CXX_COMPILER_LAUNCHER=/usr/bin/sccache" in cmake_args
    assert calls[-1] == ["sccache", "--show-stats"]
    assert "Building module 'holoscan-smoke'" in capsys.readouterr().out


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

    assert cli.container.build_calls[0]["build_args"] == "--build-arg MODE=dev"
    img, command, docker_opts, dryrun = captured["entrypoint"]
    assert img == "holohub-smoke:latest"
    assert docker_opts == "--ipc=host"
    assert dryrun is True
    assert command == (
        "holoscan build smoke_app dev --local --build-type rel-debug"
        ' --build-with "cli_op" --pkg-generator DEB --language python'
        " --parallel 2 --verbose --benchmark --configure-args=-DCLI=ON"
    )
    assert cli.container.run_calls


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
    assert "--build-type debug" in command
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
            docker_opts="--ipc=host --user root --detach",
        ),
    )

    assert len(cli.container.run_calls) == 2
    build_command, build_opts = entrypoints[0]
    assert build_command.startswith("holoscan build smoke_app --local")
    assert "--build-type debug" in build_command
    assert "--configure-args=-DDEV=ON" in build_command
    assert "--run-args" not in build_command
    # blocking, user-mapped builder: name/detach/user overrides stripped
    assert "--user 12345:23456" in build_opts
    assert "-it" in build_opts
    assert "--ipc=host" in build_opts and "--network host" in build_opts
    for stripped in ("--name", "--detach", "--user root"):
        assert stripped not in build_opts

    build_run, app_run = cli.container.run_calls
    assert build_run["as_root"] is False
    assert build_run["include_default_run_args"] is False
    run_command, _ = entrypoints[1]
    assert "--no-local-build" in run_command
    assert "--run-args=--once" in run_command
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
    assert "--build-type debug" in command
    assert "--language python" in command
    assert '--build-with "op_a"' in command
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
    )

    test_cmd.handle_test(cli, args)

    build_call = cli.container.build_calls[0]
    assert "--build-arg COVERAGE=ON" in build_call["build_args"]
    assert "coverage" in build_call["extra_scripts"]
    run_call = cli.container.run_calls[0]
    ctest_command = run_call["extra_args"][1]
    assert run_call["docker_opts"] == "--entrypoint=bash"
    assert run_call["as_root"] is True
    assert "-DAPP=smoke_app" in ctest_command
    assert "-DTAG=image" in ctest_command
    assert (
        '-DCONFIGURE_OPTIONS="-DFOO=ON;-DHOLOHUB_BUILD_PYTHON=ON;-DHOLOHUB_BUILD_CPP=OFF"'
        in ctest_command
    )
    assert "-DCTEST_SUBMIT_URL=https://cdash.example" in ctest_command
    assert "-DCOVERAGE=ON" in ctest_command
    # `--ctest-options` must propagate verbatim into the ctest invocation
    # (pre-consolidation `test_holohub_test_ctest_options`).
    assert "-DCASE=smoke" in ctest_command


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
    assert "xvfb-run -a ctest" in command[2]
    assert "-DTAG=manual" in command[2]
    assert "-S local.ctest" in command[2]
    assert kwargs["dry_run"] is True
    assert str(cli.HOLOHUB_ROOT) in kwargs["env"]["PYTHONPATH"]
