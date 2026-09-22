#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise generated Module workflows using disposable branches in this repository.

prepare executes the candidate and unpack materializes its source for an
unprivileged job. Publishing commands never execute generated files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from datetime import datetime, timedelta, timezone
from email.parser import Parser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlencode

BRANCH_RE = re.compile(r"module-ci/([1-9][0-9]*)-([1-9][0-9]*)/(python|cpp)")
WORKFLOW = ".github/workflows/ci.yml"
REQUIRED_STEPS = {
    "Lint": {"Python lint", "Validate metadata"},
    "CPU build and package": {"CMake configure", "Build", "Build Debian package"},
    "Debian install": {"Verify Debian metadata", "Install Debian package"},
}
MAX_ARCHIVE_SIZE = 10 * 1024 * 1024


class GitHub:
    def __init__(self, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository
        self.prefix = f"repos/{repository}"

    def api(self, path, method="GET", data=None):
        command = ["gh", "api", f"{self.prefix}/{path}", "--method", method]
        if data is not None:
            command.extend(["--input", "-"])
        result = subprocess.run(
            command,
            input=json.dumps(data) if data is not None else None,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(f"GitHub API {method} {path} failed: {result.stderr.strip()}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def pages(self, path, key=None):
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            response = self.api(f"{path}{separator}per_page=100&page={page}")
            items = response[key] if key else response
            yield from items
            if len(items) < 100:
                return
        raise RuntimeError("GitHub pagination limit exceeded; refusing an incomplete result")


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def validate_manifest(data):
    branch = data.get("branch", "")
    match = BRANCH_RE.fullmatch(branch)
    if not match or list(match.groups()) != [
        str(data.get("parent_run_id")),
        str(data.get("parent_attempt")),
        data.get("language"),
    ]:
        raise ValueError("Invalid branch ownership in manifest")
    GitHub(data.get("repository", ""))
    for key, size in (("source_sha", 40), ("wheel_sha256", 64), ("archive_sha256", 64)):
        if not re.fullmatch(rf"[0-9a-f]{{{size}}}", data.get(key, "")):
            raise ValueError(f"Invalid {key}")
    if not re.fullmatch(r"[A-Za-z0-9.!+_-]+", data.get("cli_version", "")):
        raise ValueError("Invalid CLI version")
    if not str(data.get("cli_artifact_id", "")).isdigit() or int(data["cli_artifact_id"]) <= 0:
        raise ValueError("Invalid CLI artifact ID")
    if "commit" in data and not re.fullmatch(r"[0-9a-f]{40}", data["commit"]):
        raise ValueError("Invalid generated commit")
    return data


def load(path):
    return validate_manifest(json.loads(Path(path).read_text(encoding="utf-8")))


def archive_tree(archive_path):
    """Read regular UTF-8 files directly; never extract candidate paths or Git state."""
    entries = []
    total = 0
    seen = set()
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or ".git" in path.parts
                or str(path) != member.name
                or member.name in seen
                or not path.parts
                or any(ord(c) < 32 for c in member.name)
            ):
                raise ValueError(f"Unsafe generated archive entry: {member.name!r}")
            seen.add(member.name)
            total += member.size
            if total > MAX_ARCHIVE_SIZE:
                raise ValueError("Generated module exceeds archive size limit")
            if str(path.parent) == ".github/workflows" and path.suffix in {".yml", ".yaml"}:
                if str(path) != WORKFLOW:
                    raise ValueError("Unexpected additional generated workflow")
            content = archive.extractfile(member).read().decode("utf-8")
            entries.append(
                {
                    "path": member.name,
                    "mode": "100755" if member.mode & 0o111 else "100644",
                    "type": "blob",
                    "content": content,
                }
            )
    if not {WORKFLOW, "metadata.json", "CMakeLists.txt", "requirements-cli.txt"} <= seen:
        raise ValueError("Generated module is missing required files")
    return entries


def prepare(args):
    wheels = list(Path(args.wheel_dir).glob("holoscan_cli-*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected exactly one CLI wheel")
    wheel = wheels[0].resolve()
    with zipfile.ZipFile(wheel) as archive:
        metadata = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("Ambiguous wheel metadata")
        version = Parser().parsestr(archive.read(metadata[0]).decode())["Version"]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Neither the checkout nor an ambient wrapper may override the packaged template.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("HOLOSCAN_CLI_", "GIT_")) and k != "PYTHONPATH"
    }
    with tempfile.TemporaryDirectory(prefix="module-e2e-") as temporary:
        root = Path(temporary)
        config = root / "cookiecutter.json"
        config.write_text(
            json.dumps(
                {
                    "cookiecutters_dir": str(root / "cookiecutters"),
                    "replay_dir": str(root / "replay"),
                }
            ),
            encoding="utf-8",
        )
        env["COOKIECUTTER_CONFIG"] = str(config)
        subprocess.run([sys.executable, "-m", "venv", str(root / "venv")], check=True)
        python = root / "venv/bin/python"
        subprocess.run(
            [str(python), "-m", "pip", "install", f"{wheel}[create]"], env=env, cwd=root, check=True
        )
        command = [
            str(root / "venv/bin/holoscan"),
            "create",
            f"E2E {args.language}",
            "--language",
            args.language,
            "--interactive",
            "false",
            "--directory",
            str(root),
        ]
        subprocess.run([*command, "--dryrun"], env=env, cwd=root, check=True)
        subprocess.run(command, env=env, cwd=root, check=True)
        project = root / f"holoscan-e2e-{args.language}"
        pin = [
            line
            for line in (project / "requirements-cli.txt").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        if pin != [f"holoscan-cli=={version}"]:
            raise ValueError("Generated module does not pin the candidate wheel")
        # create stages the standalone scaffold with its generated .gitignore.
        # pip may compile template helpers when installing the wheel; ignored
        # __pycache__ files are not part of the source a user would commit.
        tracked = subprocess.run(
            ["git", "-C", str(project), "ls-files", "--cached", "-z"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split("\0")
        with tarfile.open(output / "module.tar", "w") as archive:
            for name in sorted(tracked):
                if not name:
                    continue
                relative = Path(name)
                file = project / relative
                if file.is_symlink():
                    raise ValueError("Generated module contains a symlink")
                if file.is_file():
                    archive.add(file, arcname=relative.as_posix(), recursive=False)
    archive_tree(output / "module.tar")
    manifest = {
        "repository": args.repository,
        "source_sha": args.source_sha,
        "parent_run_id": args.parent_run_id,
        "parent_attempt": args.parent_attempt,
        "language": args.language,
        "branch": f"module-ci/{args.parent_run_id}-{args.parent_attempt}/{args.language}",
        "cli_artifact_id": args.cli_artifact_id,
        "cli_version": version,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "archive_sha256": hashlib.sha256((output / "module.tar").read_bytes()).hexdigest(),
    }
    save(output / "manifest.json", validate_manifest(manifest))


def unpack(data, archive, output):
    """Materialize validated source for CPU checks without credentials or Git state."""
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != data["archive_sha256"]:
        raise ValueError("Generated archive digest mismatch")
    entries = archive_tree(archive)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for entry in entries:
        path = output / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry["content"], encoding="utf-8")
        path.chmod(int(entry["mode"], 8) & 0o777)


def provenance(data):
    return (
        f"Generated Module CI: {data['branch']}\n\n"
        f"Module-CI-Parent: {data['parent_run_id']}/{data['parent_attempt']}\n"
        f"Module-CI-Source: {data['source_sha']}\n"
        f"Module-CI-Archive: {data['archive_sha256']}\n"
    )


def publish(api, data, archive, state):
    if api.repository != data["repository"]:
        raise ValueError("Repository mismatch")
    # Persist ownership before any mutation, including an interrupted createRef request.
    save(state, data)
    workflow = api.api("actions/workflows/ci.yml")
    if workflow["path"] != WORKFLOW or workflow["state"] != "active":
        raise ValueError("Dispatch registration on the default branch is missing or inactive")
    artifact = api.api(f"actions/artifacts/{data['cli_artifact_id']}")
    if artifact["expired"] or artifact["workflow_run"]["id"] != data["parent_run_id"]:
        raise ValueError("Candidate artifact does not belong to the parent run")
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != data["archive_sha256"]:
        raise ValueError("Generated archive digest mismatch")
    tree = api.api("git/trees", "POST", {"tree": archive_tree(archive)})
    commit = api.api(
        "git/commits",
        "POST",
        {
            "message": provenance(data),
            "tree": tree["sha"],
            "parents": [],
        },
    )
    data = {**data, "commit": commit["sha"]}
    save(state, data)
    # createRef fails on collisions: never force-push a test branch.
    api.api("git/refs", "POST", {"ref": f"refs/heads/{data['branch']}", "sha": data["commit"]})
    return data


def branch_runs(api, data):
    query = urlencode({"branch": data["branch"], "event": "workflow_dispatch"})
    return list(api.pages(f"actions/workflows/ci.yml/runs?{query}", "workflow_runs"))


def matching_run(run, data):
    return (
        run["head_sha"] == data["commit"]
        and run["head_branch"] == data["branch"]
        and run["event"] == "workflow_dispatch"
        and run["path"].split("@")[0] == WORKFLOW
        and run["display_title"] == f"Module CI / {data['branch']}"
        and run["head_repository"]["full_name"] == data["repository"]
    )


def verify_jobs(run, jobs, language):
    if run["status"] != "completed" or run["conclusion"] != "success":
        raise ValueError(f"Generated workflow did not succeed: {run['conclusion']}")
    by_name = {job["name"]: job for job in jobs}
    if len(by_name) != len(jobs):
        raise ValueError("Duplicate generated job names")
    for name, required in REQUIRED_STEPS.items():
        job = by_name.get(name)
        if job is None or job["conclusion"] != "success":
            raise ValueError(f"Required job missing or unsuccessful: {name}")
        successful = {step["name"] for step in job["steps"] if step["conclusion"] == "success"}
        if name == "Lint":
            required = required | {"Download candidate CLI"}
            if language == "cpp":
                required = required | {"C++ format check"}
        if not required <= successful:
            raise ValueError(
                f"Required steps missing or skipped in {name}: {required - successful}"
            )
    gpu = by_name.get("GPU build and test")
    if gpu is None or gpu["conclusion"] != "skipped":
        raise ValueError("E2E requires an explicitly skipped GPU job")


def dispatch(api, data):
    api.api(
        "actions/workflows/ci.yml/dispatches",
        "POST",
        {
            "ref": data["branch"],
            "inputs": {
                "e2e_id": data["branch"],
                "cli_run_id": str(data["parent_run_id"]),
                "cli_artifact_id": str(data["cli_artifact_id"]),
                "cli_wheel_sha256": data["wheel_sha256"],
                "cli_version": data["cli_version"],
                "run_gpu": "false",
            },
        },
    )


def wait(api, data, evidence, timeout, poll_seconds=15):
    deadline = time.monotonic() + timeout
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    selected = None
    while time.monotonic() < deadline:
        runs = branch_runs(api, data)
        matches = [run for run in runs if matching_run(run, data)]
        if len(matches) > 1:
            raise ValueError("Multiple runs match this dispatch; refusing ambiguous evidence")
        if matches:
            selected = matches[0]
            save(evidence / "run.json", selected)
            if selected["status"] == "completed":
                run_id = selected["id"]
                jobs = list(
                    api.pages(
                        f"actions/runs/{run_id}/attempts/{selected['run_attempt']}/jobs", "jobs"
                    )
                )
                save(evidence / "jobs.json", jobs)
                url = f"https://github.com/{api.repository}/actions/runs/{run_id}"
                print(url, flush=True)
                summary = os.environ.get("GITHUB_STEP_SUMMARY")
                if summary:
                    with open(summary, "a", encoding="utf-8") as stream:
                        stream.write(
                            f"\n- [{data['language']} Module CI]({url}): "
                            f"{selected['conclusion']} (`{data['commit']}`)\n"
                        )
                with (evidence / "workflow.log").open("w", encoding="utf-8") as stream:
                    subprocess.run(
                        [
                            "gh",
                            "run",
                            "view",
                            str(run_id),
                            "--repo",
                            api.repository,
                            "--attempt",
                            str(selected["run_attempt"]),
                            "--log",
                        ],
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        check=False,
                        timeout=120,
                    )
                verify_jobs(selected, jobs, data["language"])
                return
        elif runs:
            raise ValueError("Found a workflow run for the wrong commit or dispatch identity")
        time.sleep(poll_seconds)
    raise TimeoutError(f"Generated workflow did not complete within {timeout}s")


def cleanup(api, data, cancel=False):
    if "commit" not in data:
        return False
    # Enumerate instead of treating authentication/API failures as an absent branch.
    # Unlike Actions list endpoints, matching-refs has no pagination parameters.
    refs = api.api("git/matching-refs/heads/module-ci/")
    ref = next((r for r in refs if r["ref"] == f"refs/heads/{data['branch']}"), None)
    if ref is None:
        return True
    if ref["object"]["sha"] != data["commit"]:
        raise ValueError("Test branch changed; refusing to delete it")
    commit = api.api(f"git/commits/{data['commit']}")
    if commit["parents"] or commit["message"].rstrip("\n") != provenance(data).rstrip("\n"):
        raise ValueError("Test branch ownership could not be established")
    query = urlencode({"branch": data["branch"]})
    active = [
        r for r in api.pages(f"actions/runs?{query}", "workflow_runs") if r["status"] != "completed"
    ]
    if active:
        if cancel:
            for run in active:
                api.api(f"actions/runs/{run['id']}/cancel", "POST")
        print(f"Retaining {data['branch']} until all runs have stopped", flush=True)
        return False
    api.api(f"git/refs/heads/{quote(data['branch'], safe='/')}", "DELETE")
    return True


def sweep(api, older_than_hours):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    for ref in api.api("git/matching-refs/heads/module-ci/"):
        branch = ref["ref"].removeprefix("refs/heads/")
        match = BRANCH_RE.fullmatch(branch)
        if not match:
            continue
        commit = api.api(f"git/commits/{ref['object']['sha']}")
        if (
            commit["parents"]
            or datetime.fromisoformat(commit["committer"]["date"].replace("Z", "+00:00")) >= cutoff
        ):
            continue
        parent_id, attempt, language = match.groups()
        parent = api.api(f"actions/runs/{parent_id}/attempts/{attempt}")
        if parent["status"] != "completed":
            continue
        source = re.search(r"^Module-CI-Source: ([0-9a-f]{40})$", commit["message"], re.M)
        archive = re.search(r"^Module-CI-Archive: ([0-9a-f]{64})$", commit["message"], re.M)
        if not source or not archive:
            continue
        data = {
            "branch": branch,
            "parent_run_id": int(parent_id),
            "parent_attempt": int(attempt),
            "source_sha": source[1],
            "archive_sha256": archive[1],
            "language": language,
            "commit": ref["object"]["sha"],
        }
        if commit["message"].rstrip("\n") == provenance(data).rstrip("\n"):
            cleanup(api, data, cancel=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("prepare")
    generate.add_argument("--wheel-dir", required=True)
    generate.add_argument("--output", required=True)
    generate.add_argument("--repository", required=True)
    generate.add_argument("--source-sha", required=True)
    generate.add_argument("--parent-run-id", type=int, required=True)
    generate.add_argument("--parent-attempt", type=int, required=True)
    generate.add_argument("--cli-artifact-id", type=int, required=True)
    generate.add_argument("--language", choices=["python", "cpp"], required=True)
    extract = commands.add_parser("unpack")
    extract.add_argument("--manifest", required=True)
    extract.add_argument("--archive", required=True)
    extract.add_argument("--output", required=True)
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--manifest", required=True)
    publish_parser.add_argument("--archive", required=True)
    publish_parser.add_argument("--state", required=True)
    publish_parser.add_argument("--repository", required=True)
    publish_parser.add_argument("--source-sha", required=True)
    publish_parser.add_argument("--parent-run-id", type=int, required=True)
    publish_parser.add_argument("--parent-attempt", type=int, required=True)
    publish_parser.add_argument("--cli-artifact-id", type=int, required=True)
    publish_parser.add_argument("--language", choices=["python", "cpp"], required=True)
    for name in ("dispatch", "wait", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument("--state", required=True)
        if name == "wait":
            command.add_argument("--evidence", required=True)
            command.add_argument("--timeout", type=int, default=2700)
    janitor = commands.add_parser("sweep")
    janitor.add_argument("--repository", required=True)
    janitor.add_argument("--older-than-hours", type=int, default=24)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "unpack":
        unpack(load(args.manifest), args.archive, args.output)
    elif args.command == "sweep":
        if args.older_than_hours < 24:
            raise ValueError("Cleanup grace period must be at least 24 hours")
        sweep(GitHub(args.repository), args.older_than_hours)
    elif args.command == "publish":
        data = load(args.manifest)
        for key in (
            "repository",
            "source_sha",
            "parent_run_id",
            "parent_attempt",
            "language",
            "cli_artifact_id",
        ):
            if data[key] != getattr(args, key):
                raise ValueError(f"Generated manifest does not match trusted {key}")
        publish(GitHub(args.repository), data, args.archive, args.state)
    else:
        data = load(args.state)
        api = GitHub(data["repository"])
        if args.command == "dispatch":
            dispatch(api, data)
        elif args.command == "wait":
            wait(api, data, args.evidence, args.timeout)
        else:
            cleanup(api, data, cancel=True)


if __name__ == "__main__":
    main()
