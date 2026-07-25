# CI / release pipeline reference

This file is the documentation for everything under `.github/`: CI workflow
definitions, the shared scripts they invoke, Dependabot config, and the NVIDIA
`copy-pr-bot` config. It is **not** shipped with the `holoscan-cli` wheel, and
is intentionally named `CI.md` (not `README.md`) so it doesn't compete with the
[repo's root `README.md`](../README.md) for the GitHub front-page render.

## Layout

```text
.github/
├── CI.md                     ← you are here
├── copy-pr-bot.yaml          ← NVIDIA copy-pr-bot config
├── dependabot.yml            ← daily updates for pip + github-actions
├── scripts/                  ← shell helpers shared by workflows
│   ├── assert_wheel_contents.sh
│   ├── cpu_cli_docker_smoke.sh
│   ├── smoke_test.sh
│   └── tool_runner_smoke.sh
└── workflows/
    ├── blossom-ci.yml        ← NVIDIA Blossom hybrid CI bridge (/build comments)
    ├── codeql.yaml           ← CodeQL Advanced (Python)
    ├── dependency-review.yml ← Dependency review on PRs
    ├── main.yaml             ← Code Check — push and PR CI
    └── release.yaml          ← Manual release flow (TestPyPI publish → K2 Kitmaker)
```

## How CI runs before merge

`workflows/main.yaml` (the **Code Check** workflow) runs on every push and on
pull requests targeting `main` or `release/*`, so the full lint/test/build/smoke
surface is exercised before merge. Jobs run in this order:

| Job                           | Purpose                                                                    |
| ----------------------------- | -------------------------------------------------------------------------- |
| `pre-commit`                  | Run all hooks listed in `.pre-commit-config.yaml` on Python 3.12.          |
| `test` matrix                 | `poetry run pytest` on Python 3.10, 3.11, 3.12, and 3.13 (Ubuntu).         |
| `HoloHub project integration` | Test current CLI against HoloHub's real project tree and wrapper suite.    |
| `build wheel + sdist`         | `poetry build` + `twine check` + `assert_wheel_contents.sh`.               |
| `installed artifact smoke`    | Test clean wheel and sdist installs, the `create` extra, uvx, and pipx.    |
| `CPU CLI + Docker smoke test` | Installed-wheel source-project dry-runs plus a tiny CPU Docker build.      |

The 3.12 `test` entry uploads coverage to Coveralls; the other matrix entries
exist purely to catch version-specific regressions (e.g. `tomllib` is stdlib
on 3.11+ but missing on 3.10).

`coveralls` itself is only pulled in for `python_version < '3.13'`; on Python
3.13 the test job skips the upload step.

## How a release publishes to TestPyPI / hands off to K2 Kitmaker

`workflows/release.yaml` (the **Release** workflow) is manual
(`workflow_dispatch`) and takes three inputs:

| Input     | Notes                                                                              |
| --------- | ---------------------------------------------------------------------------------- |
| `version` | Tag name to use, e.g. `v4.3.0`. The workflow creates this tag at the dispatch SHA. |
| `rc`      | Optional RC build number (used by the dynamic-versioning Jinja format).            |
| `ga`      | `true` for an official GA dispatch; `false` otherwise. Both publish to TestPyPI.   |

Pipeline:

1. **`pre-commit` + `test`** — same as `main.yaml`, gated as `needs:`.
2. **`build wheel`** — validates that `version` looks like `vX.Y.Z`, creates
   the tag, runs `poetry build --clean`, validates package metadata with
   `twine check`, asserts the wheel contents with
   `scripts/assert_wheel_contents.sh`, uploads `dist/*` (both wheel and sdist)
   as the `build-artifact`, and uploads the `.whl` separately as
   `wheel-artifact`. The `wheel-artifact` upload is kept as a fallback path for
   the K2 Kitmaker wheel-release flow (via its GitHub Actions artifact URL
   shape); the preferred path is to consume the staged wheel from TestPyPI (see
   step 4). Use the published wheel version from TestPyPI (for example,
   `X.Y.ZrcN` for RCs) in the Kitmaker `--wheel-url`, not necessarily the
   transient tag name. The tag is auto-removed at the end when `ga == false` so
   RC dispatches do not leave stray refs.
3. **`smoke-test`** — runs `scripts/smoke_test.sh` against clean installs of
   both the wheel and sdist, and verifies the wheel's `create` extra resolves.
4. **`publish-test-pypi`** — runs for both GA and non-GA dispatches.
   Publishes via PyPA's trusted-publisher action
   (`pypa/gh-action-pypi-publish@release/v1`), no API token. Trust is
   configured on TestPyPI's side; the workflow filename (`release.yaml`)
   must match what TestPyPI has registered. K2 Kitmaker then promotes the
   staged wheel to Artifactory via
   `release_kitmaker_wheel.py upload --wheel-url https://test.pypi.org/project/holoscan-cli/<v>/ --artifactory-repo-url …`.

### Dispatching a release from the CLI

```bash
gh workflow run release.yaml --ref <branch> \
  -f version=vX.Y.Z \
  -f rc=<optional-rc-number> \
  -f ga=false                                       # true only for an official GA
```

`gh run list --workflow release.yaml --limit 1` then `gh run view <id>` to
watch progress. The `testpypi-installed smoke test` job at the end of the
pipeline polls `https://test.pypi.org/simple/` for the just-published
version, pip-installs it into a fresh venv, and re-runs `smoke_test.sh`, so
a green release run is equivalent to "kitmaker can fetch this wheel and it
passes the same checks CI runs on push."

Branch naming feeds into the version string via
`tool.poetry-dynamic-versioning.format-jinja` in `pyproject.toml`:

* `main` → `serialize_pep440(base, stage, dev=distance)`
* `release/*` → `serialize_pep440(base, stage="rc", revision=...)`
* anything else → `serialize_pep440(base, stage="alpha", revision=GITHUB_RUN_ID)`

so dispatching from a feature branch always emits a unique alpha that cannot
collide with a published RC.

## Release procedure (RC → GA runbook)

End-to-end steps a maintainer follows to ship a release. Versions are **derived
automatically** from the dispatch branch + inputs (see the format-jinja mapping
above) — you never hand-edit a version. All versions are
[PEP 440](https://peps.python.org/pep-0440/) (what PyPI requires), e.g. the RC
is `4.3.0rc1`, the PEP 440 spelling of SemVer's `4.3.0-rc.1`.

### Version scheme at a glance

| Dispatch `--ref` | `ga` | `rc` | Published version | Purpose |
| --- | --- | --- | --- | --- |
| `main` | – | – | `X.Y.Z.devN` | dev snapshots of `main` |
| any feature branch | – | – | `X.Y.ZaNNN` (`NNN` = run id) | throwaway per-branch alphas |
| `release/X.Y.0` | `false` | `N` | `X.Y.ZrcN` | release candidates |
| `release/X.Y.0` | `false` | – | `X.Y.Zrc<distance>` | RC without an explicit number |
| `release/X.Y.0` | `true` | – | `X.Y.Z` | official GA |

Every dispatch publishes to **TestPyPI**. Non-GA dispatches auto-remove the
temporary `vX.Y.Z` tag; a **GA** dispatch keeps the `vX.Y.Z` tag and is the one
K2 Kitmaker promotes to the release registry (Artifactory). The cutover to
public PyPI happens out of band — until then, installs use the TestPyPI index.

Release-candidate fixes follow the normal review path first: create a PR
against `main`, wait for it to merge, cherry-pick the merged commit onto
`release/X.Y.0`, and only then dispatch the next RC from the release branch.
Do not direct-push unreviewed fixes to `release/X.Y.0`, and do not submit an RC
workflow or Kitmaker release before the fix has merged to `main` and has been
picked onto the release branch.

### Steps

1. **Land everything on `main`** and confirm it is green.
2. **Cut the release branch (once per minor line):**

   ```bash
   git push origin origin/main:refs/heads/release/X.Y.0
   ```

   This branch is what flips the version scheme from `.dev` to `rc`.
3. **Cut RC1:**

   ```bash
   gh workflow run release.yaml --ref release/X.Y.0 \
     -f version=vX.Y.Z -f rc=1 -f ga=false        # → X.Y.Zrc1 on TestPyPI
   ```

   The run's `testpypi-installed smoke test` job installs the just-published
   wheel from TestPyPI and re-runs the smoke checks, so a green run means the
   RC is fetchable and passes the same checks CI runs on push.
4. **Validate the RC** (e.g. against downstream HoloHub usage) in a throwaway venv:

   ```bash
   python3 -m venv /tmp/rc && . /tmp/rc/bin/activate
   pip install --pre --index-url https://test.pypi.org/simple/ \
       --extra-index-url https://pypi.org/simple/ "holoscan-cli==X.Y.Zrc1"
   ```

5. **Iterate** if fixes are needed: merge the fix to `main`, cherry-pick the
   merged commit onto `release/X.Y.0`, then dispatch with `-f rc=2`,
   `-f rc=3`, … (bump each time).
6. **Cut GA** once an RC is accepted:

   ```bash
   gh workflow run release.yaml --ref release/X.Y.0 \
     -f version=vX.Y.Z -f ga=true                 # → X.Y.Z, keeps the vX.Y.Z tag
   ```

### Worked example (4.3.0)

```bash
git push origin origin/main:refs/heads/release/4.3.0          # cut the branch
gh workflow run release.yaml --ref release/4.3.0 \
    -f version=v4.3.0 -f rc=1 -f ga=false                     # → 4.3.0rc1 (TestPyPI)
# …validate, iterate -f rc=2 as needed… then:
gh workflow run release.yaml --ref release/4.3.0 \
    -f version=v4.3.0 -f ga=true                              # → 4.3.0 (GA)
```

## Shared shell scripts

These live under `.github/scripts/` so `main.yaml` and `release.yaml` can call
the same logic and never drift.

### `assert_wheel_contents.sh <wheel-dir>`

Unzips the wheel found in `<wheel-dir>` (default `dist/`) and grep-asserts
each pattern in two lists:

* **required** — files that must be present in the wheel:
  * `holoscan_cli/logging.json`
  * `holoscan_cli/py.typed`
  * `holoscan_cli/metadata/*.schema.json`
  * `holoscan_cli/setup_scripts/*`
  * `holoscan_cli/testing/`
* **forbidden** — paths that must NOT be present (regressions from past
  cleanups):
  * `holoscan_cli/cmake/` (moved to HoloHub in commit `6aeb611`)
  * `holoscan_cli/testing/test_all_applications/` (decoupled in `2d2f44a`)

The same script runs in both pipelines so a wheel that passes
`main.yaml` will pass `release.yaml`.

### `smoke_test.sh <venv-bin-dir>`

Given the bin/ directory of a venv that has `holoscan-cli` installed:

* Calls `holoscan --help`, `holoscan version`, `holoscan lint --dryrun`.
* Loops `holoscan <cmd> --help` for every name in
  `holoscan_cli.commands.registry.project_command_names()`, so a regression
  in any subcommand's parser surfaces immediately.
* Negative surface: asserts that the removed command `nics` exits non-zero,
  and that the legacy `holohub` / `monai-deploy` console
  scripts are **not** installed alongside `holoscan`.
* Positive source-project surface: points `HOLOSCAN_CLI_ROOT` at the in-tree
  fixture `tests/fixtures/holohub_smoke/` and runs `holoscan list` +
  `holoscan modes smoke_app`. The fixture is one HoloHub-style application
  whose `metadata.json` validates against the application schema, so a wheel
  that ships but breaks project discovery (missing schema files, broken
  `iter_metadata_paths`, etc.) fails this check before kitmaker sees it.

### `cpu_cli_docker_smoke.sh <venv-bin-dir>`

Runs only in `main.yaml` against the built wheel. It is intentionally CPU-only:

* Points `HOLOSCAN_CLI_ROOT` at `tests/fixtures/holohub_smoke/` and dry-runs
  `build`, `run`, `install`, and `test` for `smoke_app`.
* Dry-runs `build-container` and `run-container`, including `--docker-opts`,
  `--add-volume`, and trailing command forwarding.
* Exercises the installed-wheel entrypoint helper directly.
* If Docker is available, builds one tiny image from `busybox:1.36`; it never
  pulls Holoscan SDK, CUDA, or NGC images. Set
  `HOLOSCAN_CLI_CPU_SMOKE_SKIP_DOCKER_BUILD=1` to skip even that tiny build.

## Other workflows

* **`codeql.yaml`** — GitHub CodeQL Advanced for Python on push/PR to `main`
  and `release/*`, plus a weekly cron.
* **`dependency-review.yml`** — Blocks PRs that introduce vulnerable
  dependencies (`fail-on-severity: moderate`) or copyleft licenses. Uses
  `allow-licenses` rather than the deprecated `deny-licenses` option (see
  actions/dependency-review-action#997); add new SPDX identifiers there if
  a vetted permissive license isn't already on the list.
* **`blossom-ci.yml`** — NVIDIA-internal bridge: an authorized maintainer
  commenting `/build` on a PR kicks off a vulnerability scan and a Jenkins
  job on Blossom-managed runners. Configuration is org-managed; do not edit
  the authorization list without going through the Blossom CI team.

## GitHub Actions allowlist

The repo is configured with an org-level Actions allowlist (Settings →
Actions → General → Allow select actions). Some entries are wildcard
(`actions/checkout@*`); others pin a single SHA (e.g.
`coverallsapp/github-action@cfd0633e...`, which corresponds to v2.3.4 — bumping
requires extending the allowlist). Adding a new third-party action, or
upgrading past a SHA-pinned entry, will make the workflow fail to start at
all: every run shows `startup_failure` with no jobs scheduled and no log
output.

Dump the current allowlist before introducing a new action:

```bash
gh api repos/nvidia-holoscan/holoscan-cli/actions/permissions/selected-actions
```

If the action you need is not on the list, ask a repository admin to extend
it before merging the workflow change.

## Adding or removing a subcommand

Both shared scripts read from `holoscan_cli.commands.registry.PROJECT_COMMANDS`,
so adding or removing a `holoscan <cmd>` only requires editing
`src/holoscan_cli/commands/registry.py`. The CI surface (smoke-test loop,
top-level `--help` listing, full parser) follows automatically.
