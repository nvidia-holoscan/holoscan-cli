# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Failure-oriented tests for publishing and verifying generated Module CI."""

import hashlib
import importlib.util
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml
from cookiecutter.main import cookiecutter

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("module_e2e", ROOT / ".github/scripts/module_e2e.py")
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)


@pytest.fixture
def manifest():
    return {
        "repository": "example/cli",
        "source_sha": "a" * 40,
        "parent_run_id": 12,
        "parent_attempt": 2,
        "language": "python",
        "branch": "module-ci/12-2/python",
        "cli_artifact_id": 34,
        "cli_version": "5.0.0a1",
        "wheel_sha256": "b" * 64,
        "archive_sha256": "c" * 64,
        "commit": "d" * 40,
    }


class API:
    repository = "example/cli"

    def __init__(self, responses=None, pages=None):
        self.responses = responses or {}
        self.list_responses = pages or {}
        self.calls = []

    def api(self, path, method="GET", data=None):
        self.calls.append((path, method, data))
        key = (path, method)
        if key not in self.responses:
            raise AssertionError(f"Unexpected API request: {key}")
        return self.responses[key]

    def pages(self, path, key=None):
        self.calls.append((path, "LIST", key))
        return iter(self.list_responses[path])


def make_archive(path, extra=None):
    with tarfile.open(path, "w") as archive:
        for name in (e2e.WORKFLOW, "metadata.json", "CMakeLists.txt", "requirements-cli.txt"):
            entry = tarfile.TarInfo(name)
            entry.size = 1
            archive.addfile(entry, io.BytesIO(b"x"))
        if extra:
            archive.addfile(extra, io.BytesIO(b""))
    return path


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/escape",
        ".git/config",
        "a/../escape",
        ".github/workflows/other.yml",
        "metadata.json",
    ],
)
def test_archive_rejects_unsafe_or_unexpected_files(tmp_path, path):
    archive = make_archive(tmp_path / "module.tar", tarfile.TarInfo(path))
    with pytest.raises(ValueError):
        e2e.archive_tree(archive)


def test_archive_rejects_links(tmp_path):
    entry = tarfile.TarInfo("link")
    entry.type = tarfile.SYMTYPE
    entry.linkname = "/etc/passwd"
    with pytest.raises(ValueError, match="Unsafe"):
        e2e.archive_tree(make_archive(tmp_path / "module.tar", entry))


def test_unpack_materializes_validated_source_without_git_state(tmp_path, manifest):
    archive = make_archive(tmp_path / "module.tar")
    manifest["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    output = tmp_path / "project"
    e2e.unpack(manifest, archive, output)
    assert (output / e2e.WORKFLOW).read_text() == "x"
    assert not (output / ".git").exists()
    with pytest.raises(FileExistsError):
        e2e.unpack(manifest, archive, output)


def test_unpack_rejects_tampering_before_writing_source(tmp_path, manifest):
    output = tmp_path / "project"
    with pytest.raises(ValueError, match="digest"):
        e2e.unpack(manifest, make_archive(tmp_path / "module.tar"), output)
    assert not output.exists()


def test_unpack_rejects_unsafe_paths_before_writing_source(tmp_path, manifest):
    archive = make_archive(tmp_path / "module.tar", tarfile.TarInfo("../escape"))
    manifest["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    output = tmp_path / "project"
    with pytest.raises(ValueError, match="Unsafe"):
        e2e.unpack(manifest, archive, output)
    assert not output.exists()


def test_publish_uses_exact_generated_tree_and_persists_ownership(tmp_path, manifest):
    archive = make_archive(tmp_path / "module.tar")
    manifest.pop("commit")
    manifest["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    api = API(
        {
            ("actions/workflows/ci.yml", "GET"): {"path": e2e.WORKFLOW, "state": "active"},
            ("actions/artifacts/34", "GET"): {"expired": False, "workflow_run": {"id": 12}},
            ("git/trees", "POST"): {"sha": "e" * 40},
            ("git/commits", "POST"): {"sha": "d" * 40},
            ("git/refs", "POST"): {},
        }
    )
    state = tmp_path / "state.json"
    result = e2e.publish(api, manifest, archive, state)
    assert e2e.load(state) == result
    tree = next(data for path, method, data in api.calls if path == "git/trees")
    assert tree == {"tree": e2e.archive_tree(archive)}
    commit = next(data for path, method, data in api.calls if path == "git/commits")
    assert commit["parents"] == []
    assert commit["message"] == e2e.provenance(manifest)
    assert api.calls[-1] == (
        "git/refs",
        "POST",
        {
            "ref": "refs/heads/module-ci/12-2/python",
            "sha": "d" * 40,
        },
    )


@pytest.mark.parametrize("expired,parent", [(True, 12), (False, 99)])
def test_publish_rejects_unrelated_or_expired_artifact(tmp_path, manifest, expired, parent):
    api = API(
        {
            ("actions/workflows/ci.yml", "GET"): {"path": e2e.WORKFLOW, "state": "active"},
            ("actions/artifacts/34", "GET"): {"expired": expired, "workflow_run": {"id": parent}},
        }
    )
    with pytest.raises(ValueError, match="artifact"):
        e2e.publish(api, manifest, tmp_path / "unused", tmp_path / "state.json")
    assert all(method == "GET" for _, method, _ in api.calls)


def test_publish_rejects_tampered_archive_before_creating_branch(tmp_path, manifest):
    api = API(
        {
            ("actions/workflows/ci.yml", "GET"): {"path": e2e.WORKFLOW, "state": "active"},
            ("actions/artifacts/34", "GET"): {"expired": False, "workflow_run": {"id": 12}},
        }
    )
    with pytest.raises(ValueError, match="digest"):
        e2e.publish(api, manifest, make_archive(tmp_path / "module.tar"), tmp_path / "state.json")
    assert all(method == "GET" for _, method, _ in api.calls)


@pytest.mark.parametrize(
    "change",
    [
        {"branch": "main"},
        {"parent_run_id": 99},
        {"source_sha": "main"},
        {"cli_version": "bad\nversion"},
    ],
)
def test_manifest_rejects_unsafe_identity(manifest, change):
    with pytest.raises(ValueError):
        e2e.validate_manifest({**manifest, **change})


@pytest.fixture
def run(manifest):
    return {
        "id": 56,
        "run_attempt": 1,
        "head_sha": manifest["commit"],
        "head_branch": manifest["branch"],
        "event": "workflow_dispatch",
        "path": e2e.WORKFLOW,
        "display_title": f"Module CI / {manifest['branch']}",
        "head_repository": {"full_name": "example/cli"},
        "status": "completed",
        "conclusion": "success",
    }


@pytest.fixture
def jobs():
    result = [
        {
            "name": name,
            "conclusion": "success",
            "steps": [{"name": step, "conclusion": "success"} for step in steps],
        }
        for name, steps in e2e.REQUIRED_STEPS.items()
    ]
    result[0]["steps"].extend(
        [
            {"name": "Download candidate CLI", "conclusion": "success"},
            {"name": "C++ format check", "conclusion": "success"},
        ]
    )
    return result + [{"name": "GPU build and test", "conclusion": "skipped", "steps": []}]


def test_success_requires_real_jobs_and_candidate_wheel(run, jobs):
    for language in ("python", "cpp"):
        e2e.verify_jobs(run, jobs, language)


@pytest.mark.parametrize("name", list(e2e.REQUIRED_STEPS))
def test_successful_workflow_with_missing_job_is_rejected(run, jobs, name):
    with pytest.raises(ValueError, match="Required job"):
        e2e.verify_jobs(run, [job for job in jobs if job["name"] != name], "python")


@pytest.mark.parametrize(
    "step_name",
    [
        "Download candidate CLI",
        "Build Debian package",
        "Verify Debian metadata",
        "Install Debian package",
        "C++ format check",
    ],
)
def test_skipped_required_step_is_rejected(run, jobs, step_name):
    for job in jobs:
        for step in job["steps"]:
            if step["name"] == step_name:
                step["conclusion"] = "skipped"
    with pytest.raises(ValueError, match="steps missing or skipped"):
        e2e.verify_jobs(run, jobs, "cpp")


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "neutral"])
def test_non_success_conclusions_are_rejected(run, jobs, conclusion):
    run["conclusion"] = conclusion
    with pytest.raises(ValueError, match="did not succeed"):
        e2e.verify_jobs(run, jobs, "python")


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "e" * 40),
        ("head_branch", "main"),
        ("event", "push"),
        ("display_title", "old run"),
        ("path", ".github/workflows/main.yaml"),
    ],
)
def test_old_or_unrelated_run_cannot_satisfy_gate(manifest, run, field, value):
    assert e2e.matching_run(run, manifest)
    run[field] = value
    assert not e2e.matching_run(run, manifest)


def test_missing_workflow_times_out(tmp_path, manifest, monkeypatch):
    api = API(
        pages={
            "actions/workflows/ci.yml/runs?branch=module-ci%2F12-2%2Fpython&event=workflow_dispatch": [],
        }
    )
    times = iter([0, 0, 2])
    monkeypatch.setattr(e2e.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(e2e.time, "sleep", lambda _: None)
    with pytest.raises(TimeoutError):
        e2e.wait(api, manifest, tmp_path, timeout=1)


def test_wait_rejects_wrong_commit(tmp_path, manifest, run):
    run["head_sha"] = "e" * 40
    api = API(
        pages={
            "actions/workflows/ci.yml/runs?branch=module-ci%2F12-2%2Fpython&event=workflow_dispatch": [
                run
            ],
        }
    )
    with pytest.raises(ValueError, match="wrong commit"):
        e2e.wait(api, manifest, tmp_path, timeout=1)


def cleanup_api(manifest, active=None):
    ref = {"ref": f"refs/heads/{manifest['branch']}", "object": {"sha": manifest["commit"]}}
    commit = {"parents": [], "message": e2e.provenance(manifest)}
    return API(
        {
            ("git/matching-refs/heads/module-ci/", "GET"): [ref],
            (f"git/commits/{manifest['commit']}", "GET"): commit,
            (f"git/refs/heads/{manifest['branch']}", "DELETE"): None,
            ("actions/runs/56/cancel", "POST"): None,
        },
        {
            "actions/runs?branch=module-ci%2F12-2%2Fpython": active or [],
        },
    )


def test_cleanup_only_deletes_owned_inactive_branch(manifest):
    api = cleanup_api(manifest)
    assert e2e.cleanup(api, manifest)
    assert api.calls[-1][:2] == ("git/refs/heads/module-ci/12-2/python", "DELETE")


def test_cleanup_cancels_but_retains_active_branch(manifest):
    api = cleanup_api(manifest, [{"id": 56, "status": "queued"}])
    assert not e2e.cleanup(api, manifest, cancel=True)
    assert api.calls[-1][:2] == ("actions/runs/56/cancel", "POST")
    assert all(method != "DELETE" for _, method, _ in api.calls)


def test_cleanup_preserves_changed_branch(manifest):
    api = cleanup_api(manifest)
    api.responses[("git/matching-refs/heads/module-ci/", "GET")][0]["object"]["sha"] = "e" * 40
    with pytest.raises(ValueError, match="changed"):
        e2e.cleanup(api, manifest)
    assert all(method != "DELETE" for _, method, _ in api.calls)


def test_cleanup_preserves_branch_without_ownership(manifest):
    api = cleanup_api(manifest)
    api.responses[(f"git/commits/{manifest['commit']}", "GET")]["parents"] = [{"sha": "e" * 40}]
    with pytest.raises(ValueError, match="ownership"):
        e2e.cleanup(api, manifest)
    assert all(method != "DELETE" for _, method, _ in api.calls)


@pytest.fixture(params=["python", "cpp"])
def generated(tmp_path, request):
    return Path(
        cookiecutter(
            str(ROOT / "src/holoscan_cli/templates/module"),
            no_input=True,
            output_dir=str(tmp_path),
            default_config={
                "cookiecutters_dir": str(tmp_path / "cookiecutters"),
                "replay_dir": str(tmp_path / "replay"),
            },
            extra_context={"project_name": "CI Probe", "language": request.param},
        )
    )


def test_rendered_dispatch_matches_registration_and_required_contract(generated):
    workflow = yaml.load((generated / e2e.WORKFLOW).read_text(), Loader=yaml.BaseLoader)
    registration = yaml.load((ROOT / e2e.WORKFLOW).read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"]["workflow_dispatch"] == registration["on"]["workflow_dispatch"]
    jobs = {job["name"]: job for job in workflow["jobs"].values()}
    for name, steps in e2e.REQUIRED_STEPS.items():
        assert steps <= {step.get("name") for step in jobs[name]["steps"]}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["run_gpu"]["default"] == "false"
    assert "inputs.run_gpu" in jobs["GPU build and test"]["if"]
    assert jobs["Debian install"]["container"] == "ubuntu:24.04"
    assert jobs["CPU build and package"]["runs-on"] == "ubuntu-24.04"
    assert "--gpus" not in str(jobs["CPU build and package"])
    if shutil.which("actionlint"):
        subprocess.run(
            [
                "actionlint",
                "-shellcheck=",
                "-ignore",
                "label .* is unknown",
                str(generated / e2e.WORKFLOW),
            ],
            check=True,
        )


@pytest.mark.skipif(shutil.which("clang-format") is None, reason="clang-format required")
def test_generated_cpp_passes_its_format_check(generated):
    sources = [str(path) for path in generated.rglob("*") if path.suffix in {".cpp", ".hpp"}]
    if sources:
        subprocess.run(["clang-format", "--dry-run", "--Werror", *sources], check=True)


@pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="Debian package tools required")
def test_actual_debian_metadata_rejects_old_dependency(generated, tmp_path):
    package = tmp_path / "package"
    (package / "DEBIAN").mkdir(parents=True)
    control = package / "DEBIAN/control"
    template = (
        "Package: holoscan-ci-probe\nVersion: 0.1.0\nArchitecture: amd64\n"
        "Maintainer: CI <ci@example.com>\nDescription: CI probe\nDepends: {}\n"
    )
    script = generated / ".github/workflows/scripts/verify_debian_package.sh"
    for dependency, expected in [
        ("holoscan (>= 4.5.0)", False),
        ("holoscan-cuda-13 (>= 4.4.0)", False),
        ("libc6 (>= 2.0), holoscan-cuda-13 (>= 4.5.0)", True),
    ]:
        control.write_text(template.format(dependency))
        deb = tmp_path / "probe.deb"
        subprocess.run(
            ["dpkg-deb", "--build", str(package), str(deb)], capture_output=True, check=True
        )
        result = subprocess.run(["bash", str(script), str(deb)], capture_output=True)
        assert (result.returncode == 0) is expected
        shared = generated / ".github/workflows/scripts/cpu_ci.sh"
        result = subprocess.run(["bash", str(shared), "verify", str(tmp_path)], capture_output=True)
        assert (result.returncode == 0) is expected


def test_pr_e2e_runs_without_opt_in_or_publisher_permissions():
    workflow = yaml.load((ROOT / ".github/workflows/main.yaml").read_text(), Loader=yaml.BaseLoader)
    caller = workflow["jobs"]["module-e2e"]
    assert "if" not in caller
    assert caller["permissions"] == {"contents": "read"}
    assert "secrets" not in caller
    cpu = yaml.load(
        (ROOT / ".github/workflows/module-e2e.yaml").read_text(), Loader=yaml.BaseLoader
    )
    assert cpu["permissions"] == {"contents": "read"}
    job = cpu["jobs"]["cpu"]
    assert job["strategy"]["matrix"]["language"] == ["python", "cpp"]
    assert "environment" not in job
    assert "if" not in job
    text = (ROOT / ".github/workflows/module-e2e.yaml").read_text()
    assert "secrets." not in text
    assert "vars." not in text
    assert "default_branch" not in text
    assert cpu["jobs"]["result"]["if"] == "always()"
    assert cpu["jobs"]["result"]["needs"] == "cpu"


def test_pr_and_generated_workflow_use_the_same_cpu_commands(generated):
    candidate = yaml.load((generated / e2e.WORKFLOW).read_text(), Loader=yaml.BaseLoader)
    baseline = yaml.load(
        (ROOT / ".github/workflows/module-e2e.yaml").read_text(), Loader=yaml.BaseLoader
    )
    steps = {step.get("name"): step for step in baseline["jobs"]["cpu"]["steps"]}
    for step in candidate["jobs"]["build-only"]["steps"]:
        if "run" in step:
            assert step["run"] == steps[step["name"]]["run"]
            assert "if" not in steps[step["name"]]
    for name in ("Verify Debian metadata", "Install Debian package in a fresh container"):
        assert "if" not in steps[name]
    install = steps["Install Debian package in a fresh container"]["run"]
    assert install.endswith("cpu_ci.sh install-clean build/packages")


def test_shared_cpu_helper_preserves_build_failure(generated, tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/bin/sh\nexit 23\n")
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:/usr/bin:/bin")
    result = subprocess.run(
        ["bash", str(generated / ".github/workflows/scripts/cpu_ci.sh"), "build"],
        capture_output=True,
    )
    assert result.returncode == 23


def test_sweep_preserves_active_parent_attempt(manifest):
    api = cleanup_api(manifest)
    api.responses[(f"git/commits/{manifest['commit']}", "GET")]["committer"] = {
        "date": "2020-01-01T00:00:00Z"
    }
    api.responses[("actions/runs/12/attempts/2", "GET")] = {"status": "in_progress"}
    e2e.sweep(api, 24)
    assert all(method not in {"DELETE", "POST"} for _, method, _ in api.calls)


def test_sweep_removes_only_completed_owned_old_branch(manifest):
    api = cleanup_api(manifest)
    api.responses[(f"git/commits/{manifest['commit']}", "GET")]["committer"] = {
        "date": "2020-01-01T00:00:00Z"
    }
    api.responses[("actions/runs/12/attempts/2", "GET")] = {"status": "completed"}
    api.responses[("git/matching-refs/heads/module-ci/", "GET")].append(
        {"ref": "refs/heads/module-ci/manual-work", "object": {"sha": "f" * 40}}
    )
    e2e.sweep(api, 24)
    assert [path for path, method, _ in api.calls if method == "DELETE"] == [
        "git/refs/heads/module-ci/12-2/python"
    ]


def test_sweep_does_not_treat_access_failure_as_completed_parent(manifest):
    api = cleanup_api(manifest)
    api.responses[(f"git/commits/{manifest['commit']}", "GET")]["committer"] = {
        "date": "2020-01-01T00:00:00Z"
    }
    with pytest.raises(AssertionError, match="Unexpected API request"):
        e2e.sweep(api, 24)
    assert all(method != "DELETE" for _, method, _ in api.calls)


def test_release_publication_requires_module_e2e():
    workflow = yaml.load(
        (ROOT / ".github/workflows/release.yaml").read_text(), Loader=yaml.BaseLoader
    )
    for job in ("module-e2e", "module-github-ci"):
        assert job in workflow["jobs"]["testpypi-deploy"]["needs"]
        assert "if" not in workflow["jobs"][job]
        assert workflow["jobs"][job]["needs"] == "build"


@pytest.mark.parametrize("bad_field", ["CLI_WHEEL_SHA256", "CLI_VERSION"])
def test_candidate_installer_rejects_mismatched_artifact(
    generated, tmp_path, monkeypatch, bad_field
):
    import runpy

    wheel = tmp_path / "wheels/holoscan_cli-0-py3-none-any.whl"
    wheel.parent.mkdir()
    wheel.write_bytes(b"candidate")
    monkeypatch.chdir(generated)
    monkeypatch.setenv("CLI_WHEEL_DIR", str(wheel.parent))
    monkeypatch.setenv("CLI_WHEEL_SHA256", hashlib.sha256(wheel.read_bytes()).hexdigest())
    monkeypatch.setenv("CLI_VERSION", "0")
    monkeypatch.setenv(bad_field, "f" * 64 if bad_field.endswith("SHA256") else "9.9.9")
    installer = runpy.run_path(str(generated / ".github/workflows/scripts/install_cli.py"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("pip must not run"))
    with pytest.raises(SystemExit, match="mismatch|does not match"):
        installer["main"]()
