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
├── scripts/                  ← release and smoke-test helpers
│   ├── assert_wheel_contents.sh
│   ├── cpu_cli_docker_smoke.sh
│   ├── module_e2e.py
│   ├── resolve_release_version.py
│   ├── smoke_test.sh
│   └── tool_runner_smoke.sh
└── workflows/
    ├── codeql.yaml           ← CodeQL Advanced (Python)
    ├── dependency-review.yml ← Dependency review on PRs
    ├── main.yaml             ← Code Check — push and PR CI
    ├── module-e2e.yaml       ← Generated Module workflow validation
    ├── module-e2e-cleanup.yaml ← Abandoned test-branch cleanup
    ├── ci.yml                ← Generated workflow dispatch registration
    └── release.yaml          ← Manual release flow (TestPyPI → NVIDIA promotion)
```

## How CI runs before merge

`workflows/main.yaml` (the **Code Check** workflow) runs on every push and on
pull requests targeting `main` or `release/*`, so the full lint/test/build/smoke
surface is exercised before merge. Jobs run in this order:

| Job                           | Purpose                                                                    |
| ----------------------------- | -------------------------------------------------------------------------- |
| `pre-commit`                  | Run all hooks listed in `.pre-commit-config.yaml` on Python 3.12.          |
| `test` matrix                 | `poetry run pytest` on Python 3.11, 3.12, 3.13, and 3.14 (Ubuntu).         |
| `HoloHub project integration` | Test current CLI against HoloHub's real project tree and wrapper suite.    |
| `build wheel + sdist`         | `poetry build` + `twine check` + `assert_wheel_contents.sh`.               |
| `installed artifact smoke`    | Test clean wheel and sdist installs, the `create` extra, uvx, and pipx.    |
| `CPU CLI + Docker smoke test` | Installed-wheel source-project dry-runs plus a tiny CPU Docker build.      |

The installed-artifact smoke matrix runs on Python 3.12, 3.13, and 3.14, using the
same wheel and sdist built on Python 3.12.

The 3.12 `test` entry uploads coverage to Coveralls; the other matrix entries
exist purely to catch version-specific regressions across supported runtimes.

`coveralls` itself is only pulled in for `python_version < '3.13'`; on Python
3.13 and 3.14 the test job skips the upload step.

## How a release publishes to TestPyPI and hands off for NVIDIA promotion

`workflows/release.yaml` (the **Release** workflow) is manual
(`workflow_dispatch`) and takes four inputs:

| Input     | Notes                                                                            |
| --------- | -------------------------------------------------------------------------------- |
| `version` | Base version, such as `v5.0.0`; also used for the workflow's temporary base tag. |
| `alpha`   | Optional positive alpha number; `1` resolves exactly to `5.0.0a1`.               |
| `rc`      | Optional positive RC number; `1` resolves exactly to `5.0.0rc1`.                 |
| `ga`      | `true` resolves exactly to the final version; otherwise leave it `false`.        |

`alpha`, `rc`, and `ga=true` are mutually exclusive. Explicit alpha, RC, and
GA releases must be dispatched from `release/*`. The workflow resolves the
exact PEP 440 version with `scripts/resolve_release_version.py` and passes it to
the build through `POETRY_DYNAMIC_VERSIONING_BYPASS`. This separates branch
lifecycle from package maturity: `release/5.0.0` can produce `5.0.0a1`, later
`5.0.0rc1`, and finally `5.0.0` without renaming the branch.

Pipeline:

1. **`pre-commit` + `test`** — run the same lint and test suites as
   `main.yaml`.
2. **`build wheel`** — validate inputs, create the temporary base tag at the
   dispatch SHA, build the wheel and sdist, assert that explicit release
   versions match the artifact filenames, validate metadata and contents, and
   upload `build-artifact` plus the wheel-only `wheel-artifact`. The temporary
   base tag is removed for non-GA dispatches.
3. **`smoke-test`** — test clean wheel and sdist installs and the `create`
   extra on Python 3.12, 3.13, and 3.14.
4. **`module-e2e`** — require generated Python/C++ workflows, including Debian
   package installation, to pass against the release wheel. See
   [activation and ownership](#generated-module-end-to-end-validation).
5. **`publish-test-pypi`** — after smoke and Module E2E succeed, publish both distributions to TestPyPI with
   trusted publishing. There is deliberately no public-PyPI deployment job.
6. **`testpypi-installed smoke test` — poll TestPyPI for the exact published
   version, install it into clean Python 3.12, 3.13, and 3.14 environments, and rerun
   the smoke checks.
7. **NVIDIA promotion** — outside this workflow, use the approved NVIDIA
   package-promotion process to copy the validated wheel to
   `pypi.nvidia.com`. For alpha and RC builds, select its prerelease-only policy
   and keep public PyPI disabled.

Alpha and RC artifacts are recorded with permanent annotated tags only after
staging, downstream validation, and NVIDIA promotion succeed. They do not need
separate GitHub Release pages. The GA GitHub Release remains an explicit
maintainer step and uses the previous GA tag as its changelog baseline.

### Dispatching a release from the CLI

For the first 5.0 integration alpha:

```bash
gh workflow run release.yaml --ref release/5.0.0 \
  -f version=v5.0.0 -f alpha=1 -f ga=false
```

For later RC and GA stages, omit `alpha`:

```bash
gh workflow run release.yaml --ref release/5.0.0 \
  -f version=v5.0.0 -f rc=1 -f ga=false

gh workflow run release.yaml --ref release/5.0.0 \
  -f version=v5.0.0 -f ga=true
```

Use `gh run list --workflow release.yaml --branch release/5.0.0 --limit 5`, then
`gh run watch <run-id> --exit-status` and `gh run view <run-id>` to inspect the
result.

Without an explicit release selector, the existing dynamic-versioning fallback
still applies:

* `main` → `serialize_pep440(base, stage, dev=distance)`
* `release/*` → `serialize_pep440(base, stage="rc", revision=distance)`
* anything else → `serialize_pep440(base, stage="alpha", revision=GITHUB_RUN_ID)`

Do not use that fallback for a release artifact; pass an explicit `alpha`, `rc`,
or `ga=true` so the published version is deterministic.

## Release procedure (alpha → RC → GA runbook)

All versions use [PEP 440](https://peps.python.org/pep-0440/). In particular,
`5.0.0a1` is an alpha earlier than `5.0.0rc1`; spell the package version and
tag without a hyphen. The release branch represents the stabilized code line,
not the maturity label.

### Version scheme at a glance

| Dispatch `--ref`   | `alpha` | `rc` | `ga`    | Published version       | Purpose                         |
| ------------------ | ------- | ---- | ------- | ----------------------- | ------------------------------- |
| `main`             | –       | –    | –       | `X.Y.Za0.devN`          | routine development build       |
| any feature branch | –       | –    | –       | `X.Y.ZaNNN`             | throwaway branch build          |
| `release/X.Y.Z`    | `N`     | –    | `false` | `X.Y.ZaN`               | downstream integration alpha    |
| `release/X.Y.Z`    | –       | `N`  | `false` | `X.Y.ZrcN`              | release candidate               |
| `release/X.Y.Z`    | –       | –    | `false` | `X.Y.Zrc<distance>`     | legacy fallback; do not publish |
| `release/X.Y.Z`    | –       | –    | `true`  | `X.Y.Z`                 | official GA                     |

Every workflow dispatch publishes to **TestPyPI**. The approved promotion step
copies only the validated wheel to **pypi.nvidia.com**. An alpha or RC must not
be sent to public PyPI. TestPyPI does not permit replacing a published file, so
once any `X.Y.ZaN` artifact reaches it, never reuse that `N`; fix the release
branch and increment to `a(N+1)`.

The workflow creates `vX.Y.Z` as a temporary version anchor. Non-GA runs remove
it, but a failure before cleanup can leave it behind. Before dispatch or retry,
inspect that exact tag and remove it only when it is the failed workflow's
temporary base tag. Never delete or move permanent `vX.Y.ZaN`, `vX.Y.ZrcN`, or
published GA tags.

### Steps

1. **Choose the release commit.** Merge the release tooling and every intended
   5.0 change to `main`, then confirm required CI and nightly validation are
   green.
2. **Create `release/5.0.0` at that exact `main` commit:**

   ```bash
   (
     set -euo pipefail
     git fetch origin --tags --prune
     release_sha=$(git rev-parse --verify origin/main)
     git show --no-patch --oneline "${release_sha}"
     git push origin "${release_sha}:refs/heads/release/5.0.0"
     remote_release_sha=$(git ls-remote --refs origin \
       refs/heads/release/5.0.0 | cut -f1)
     test "${remote_release_sha}" = "${release_sha}"
   )
   ```

   Continue merging normal contributions to `main`. Release fixes also merge
   to `main` first and are then cherry-picked to `release/5.0.0`.
3. **Advance the development anchor on `main` separately.** The existing
   `v5.0.0a0` tag remains fixed. After the first reviewed post-branch commit is
   on `main`, tag it for the next planned line—for example `v5.1.0a0` if 5.1 is
   next. That tag is a VCS development anchor, not the 5.0 integration alpha.
   Later `main` commits then derive `5.1.0a0.devN`.

   ```bash
   (
     set -euo pipefail
     git fetch origin --tags --prune
     branch_point=$(git merge-base origin/main origin/release/5.0.0)
     first_main_sha=$(git rev-list --first-parent --reverse \
       "${branch_point}"..origin/main | sed -n '1p')
     test -n "${first_main_sha}"
     git show --no-patch --oneline "${first_main_sha}"
     git tag -a v5.1.0a0 "${first_main_sha}" \
       -m "start 5.1 development on main"
     git push origin v5.1.0a0
     remote_tag_sha=$(git ls-remote origin \
       "refs/tags/v5.1.0a0^{}" | cut -f1)
     test "${remote_tag_sha}" = "${first_main_sha}"
   )
   ```

4. **Check for a stale temporary base tag, then dispatch alpha 1:**

   ```bash
   (
     set -euo pipefail
     alpha=1
     package_version="5.0.0a${alpha}"
     git fetch origin --tags --prune
     existing_tags=$(git ls-remote --refs origin \
       refs/tags/v5.0.0 "refs/tags/v${package_version}")
     if [[ -n "$existing_tags" ]]; then
       echo "Stop: base or alpha tag already exists: $existing_tags" >&2
       exit 1
     fi
     status=$(curl --silent --show-error --location --max-time 30 \
       --output /dev/null --write-out '%{http_code}' \
       "https://test.pypi.org/pypi/holoscan-cli/${package_version}/json")
     if [[ "$status" != 404 ]]; then
       echo "Stop: version exists or availability is unknown (HTTP $status)" >&2
       exit 1
     fi
     gh workflow run release.yaml --ref release/5.0.0 \
       -f version=v5.0.0 -f alpha="$alpha" -f ga=false
   )
   ```

   If `v5.0.0` exists, stop and determine whether it is a retained GA tag or a
   failed workflow's temporary tag before doing anything to it.
   If the alpha tag or TestPyPI version exists, select the next unused alpha
   number and repeat the preflight. Use that number consistently in the
   installation, promotion, and tagging steps below. Only HTTP 404 establishes
   that the TestPyPI version is absent; network errors and other responses stop
   the sequence.
5. **Watch the run and validate the TestPyPI package:**

   ```bash
   gh run list --workflow release.yaml --branch release/5.0.0 --limit 5
   gh run watch <run-id> --exit-status
   gh run view <run-id>

   python3 -m venv /tmp/holoscan-cli-5.0.0a1
   . /tmp/holoscan-cli-5.0.0a1/bin/activate
   python -m pip install --only-binary=holoscan-cli \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ "holoscan-cli==5.0.0a1"
   holoscan version
   ```

6. **Run downstream integration tests** against the exact installed
   `holoscan-cli==5.0.0a1` wheel. Record enough public-safe evidence to identify
   the tested commit and package version.
7. **Promote only the wheel** with the approved NVIDIA release tooling. Select
   the prerelease-only destination for `pypi.nvidia.com` and leave public PyPI
   disabled. Verify the promoted package independently:

   ```bash
   python3 -m venv /tmp/holoscan-cli-nvidia-5.0.0a1
   /tmp/holoscan-cli-nvidia-5.0.0a1/bin/pip install \
     --only-binary=holoscan-cli --index-url https://pypi.nvidia.com \
     "holoscan-cli==5.0.0a1"
   /tmp/holoscan-cli-nvidia-5.0.0a1/bin/holoscan version
   ```

   Verify that promotion preserved the exact wheel bytes. Stop if the digests
   differ; publishing different source under the same version breaks provenance.

   ```bash
   (
     set -euo pipefail
     audit_dir=$(mktemp -d /tmp/holoscan-cli-promotion.XXXXXX)
     python -m pip --isolated download --no-cache-dir --no-deps \
       --only-binary=:all: --index-url https://test.pypi.org/simple/ \
       --dest "$audit_dir/testpypi" "holoscan-cli==5.0.0a1"
     python -m pip --isolated download --no-cache-dir --no-deps \
       --only-binary=:all: --index-url https://pypi.nvidia.com \
       --dest "$audit_dir/nvidia" "holoscan-cli==5.0.0a1"
     wheel_name=holoscan_cli-5.0.0a1-py3-none-any.whl
     sha256sum "$audit_dir/testpypi/$wheel_name" "$audit_dir/nvidia/$wheel_name"
     cmp "$audit_dir/testpypi/$wheel_name" "$audit_dir/nvidia/$wheel_name"
   )
   ```

8. **Record the successful alpha** at the exact release-branch commit. Do this
   only after TestPyPI, downstream validation, and NVIDIA promotion succeed:

   ```bash
   (
     set -euo pipefail
     git fetch origin --tags --prune
     release_sha=$(gh run view <run-id> --json headSha --jq .headSha)
     git rev-parse --verify "${release_sha}^{commit}"
     git tag -a v5.0.0a1 "${release_sha}" \
       -m "holoscan-cli 5.0.0a1" \
       -m "TestPyPI: https://test.pypi.org/project/holoscan-cli/5.0.0a1/"
     git push origin v5.0.0a1
     remote_tag_sha=$(git ls-remote origin \
       "refs/tags/v5.0.0a1^{}" | cut -f1)
     test "${remote_tag_sha}" = "${release_sha}"
   )
   ```

   Select the successful **Release** run that built the validated alpha, and
   verify its branch, version inputs, and conclusion before using its run ID.
   The branch may have advanced since the build; always tag the run's `headSha`.

9. **Iterate with `a2`, `a3`, …** when fixes are needed. Merge each fix to
   `main`, cherry-pick its single-parent commit to `release/5.0.0`, push the
   branch, rerun branch CI, and repeat step 4 with the next unused alpha number:

   ```bash
   git switch release/5.0.0
   git pull --ff-only origin release/5.0.0
   git cherry-pick <single-parent-fix-sha>
   git push origin release/5.0.0
   ```

   Do not pass a merge commit to plain `git cherry-pick <sha>`.
10. **Advance to RC and GA without changing branches** when maturity warrants
    it:

    ```bash
    gh workflow run release.yaml --ref release/5.0.0 \
      -f version=v5.0.0 -f rc=1 -f ga=false

    gh workflow run release.yaml --ref release/5.0.0 \
      -f version=v5.0.0 -f ga=true
    ```

    Apply the same validation, promotion, and permanent-tag rules to
    `v5.0.0rcN`, using the successful RC run's `headSha` for its annotated tag.
    A successful GA dispatch retains `v5.0.0`; verify that existing tag against
    the successful GA run's `headSha` instead of recreating or moving it:

    ```bash
    (
      set -euo pipefail
      git fetch origin --tags --prune
      ga_sha=$(gh run view <ga-run-id> --json headSha --jq .headSha)
      test "$(git rev-parse --verify 'refs/tags/v5.0.0^{commit}')" = "$ga_sha"
    )
    ```

11. **Publish the cumulative GA changelog** only after the GA workflow,
    downstream validation, and approved promotion have succeeded. Compare the
    previous GA tag with the new GA tag, not with an alpha or RC tag:

    ```bash
    git fetch origin --tags --prune
    git rev-parse --verify 'refs/tags/vPREVIOUS.GA^{commit}'
    git rev-parse --verify 'refs/tags/v5.0.0^{commit}'
    git diff --stat vPREVIOUS.GA..v5.0.0
    git log --cherry-pick --right-only --no-merges --oneline \
      vPREVIOUS.GA...v5.0.0

    gh release create v5.0.0 \
      --repo nvidia-holoscan/holoscan-cli \
      --verify-tag \
      --draft \
      --title "holoscan-cli 5.0.0" \
      --generate-notes \
      --notes-start-tag vPREVIOUS.GA
    ```

    Review and curate the draft before publishing it. Check cherry-picked fixes
    against their original pull requests, and remove private or
    security-sensitive validation details.

## Shared release and smoke-test helpers

These live under `.github/scripts/` so `main.yaml` and `release.yaml` can call
the same logic and never drift.

### `resolve_release_version.py`

Validates the base version, maturity inputs, and release branch and returns an
exact PEP 440 version for an explicit alpha, RC, or GA build. The workflow also
runs equivalent fail-fast checks before creating its temporary tag. Unit tests
cover each maturity and reject ambiguous or invalid input combinations.

### `assert_wheel_contents.sh <wheel-dir>`

Unzips the wheel found in `<wheel-dir>` (default `dist/`) and grep-asserts
each pattern in two lists:

* **required** — files that must be present in the wheel:
  * `holoscan_cli/logging.json`
  * `holoscan_cli/py.typed`
  * `holoscan_cli/cmake/` (support copied into generated standalone Modules)
  * `holoscan_cli/metadata/*.schema.json`
  * `holoscan_cli/setup_scripts/*`
  * `holoscan_cli/templates/module/`
  * `holoscan_cli/testing/`
* **forbidden** — paths that must NOT be present (regressions from past
  cleanups):
  * `holoscan_cli/testing/test_all_applications/` (decoupled in `2d2f44a`)
  * `holoscan_cli/templates/module/*/holohub` (standalone Modules ship no wrapper)

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

## Generated Module end-to-end validation

`module-e2e.yaml` validates the packaged template by running its generated GitHub
workflow on disposable branches in this repository. Normal CI calls it after
building the candidate wheel when `MODULE_E2E_ENABLED=true`. Release CI always
requires it before TestPyPI publication; missing configuration fails that gate.

The controller on the default branch is resolved once to an immutable commit.
Both generation and publishing use that controller revision. The wheel under
test still comes from the caller's exact PR, push, or release run. Controller
changes receive unit coverage before merge and become active after reaching the
default branch.

### Files and branch ownership

* `workflows/module-e2e.yaml`: generation, publication, dispatch, evidence, and
  the aggregate `Module E2E` result.
* `scripts/module_e2e.py`: the corresponding commands, also usable for diagnosis.
* `workflows/ci.yml`: dispatch registration only. Dispatching this copy on the
  default branch fails intentionally. Generated branches contain the actual
  workflow at the same path, without rewriting its contents.
* `workflows/module-e2e-cleanup.yaml`: daily cleanup of abandoned branches.
* `src/holoscan_cli/templates/module/`: the only source of generated test jobs,
  SDK provisioning, and Debian verification.

The CLI maintainers own the controller, automation App, and branch namespace.
Each run creates `module-ci/<run-id>-<attempt>/python` and
`module-ci/<run-id>-<attempt>/cpp`. These are orphan branches containing only
fresh module source; never open PRs from them or merge them into a source branch.
The generated Git index determines the source archive, excluding Git state and
ignored caches such as bytecode created during wheel installation.

Generation runs without publisher credentials. A separate job reads the source
archive as data, rejects unsafe paths, links, additional workflows, and digest
mismatches, and publishes it through the Git data API. It never executes the
candidate's files. Existing branch names are not overwritten.

### One-time setup and activation

1. Merge the controller, dispatch registration, and template changes onto the
   default branch before enabling dispatch. Apply the caller integration to any
   existing release branches that need it.
2. Create a GitHub App installed only on this repository, with repository
   **Contents: write**, **Workflows: write**, and **Actions: write** permissions.
   Set repository variable `MODULE_E2E_APP_ID` to its App ID.
3. Create the `module-e2e` environment. Store the App private key there as
   `MODULE_E2E_PRIVATE_KEY`, not as an unrestricted repository secret. Configure
   required reviewers and deployment branch restrictions. Reviewers must vet
   the exact candidate revision before approving branch publication. Create a
   separate `module-e2e-cleanup` environment with the same private-key secret,
   restricted to the default branch and without required reviewers, so the
   scheduled janitor can run unattended. Its token requests only Contents and
   Actions write access. Both environments must be configured before activation.
4. Allow the pinned `actions/create-github-app-token` action in the repository's
   Actions allowlist. The other actions use the same pins as normal CLI CI.
   Permit generated workflows to use read-only contents and Actions access;
   the controller also needs Actions write access to dispatch and cancel runs.
   Ensure repository rulesets permit the automation App to create and delete
   refs in the generated `module-ci/` namespace.
5. Set `MODULE_E2E_ENABLED=true`, then rerun normal CI for a vetted source
   revision. Confirm both generated workflows complete, the parent result
   succeeds, evidence is available, and the two branches are removed.
6. Select the emitted `Generated Module E2E / Module E2E` check as a required PR
   check. Verify the displayed name against the first live run. A skipped
   controller before activation is not E2E validation.

Same-repository branches share repository settings, secrets, and runner access.
Do not publish unreviewed fork-generated workflows into this namespace. Direct
fork PR calls fail the controller's trust check; use the repository's vetted
same-repository contribution path for that exact revision. Never substitute
`pull_request_target` execution of untrusted code. The publishing environment
also gates same-repository candidates: changing a template changes executable
workflow code.

### What runs and what constitutes success

1. Download the caller's wheel artifact by ID, install its `create` extra in a
   clean venv, and generate Python and C++ modules with the packaged template.
   Record the source SHA, package version, wheel SHA256, and source archive SHA256.
2. Upload the generated archives for 14 days, publish their source trees on
   separate branches, and dispatch `ci.yml` on each branch. The CLI wheel remains
   an Actions artifact, not a committed file or a published package.
3. The generated lint job downloads that candidate artifact from the same
   repository and verifies its wheel digest and the generated exact version pin.
   Normal generated-repository push/PR CI uses the published pinned CLI instead.
4. Require `Lint`, `CPU build and package`, and `Debian install`, including their
   essential steps, to succeed for both languages. GPU tests must be explicitly
   skipped in these baseline runs. An absent workflow, wrong commit, unexpected
   skip, failed installation, cancellation, or timeout fails the aggregate check.
5. Retain run/job metadata, logs, generated commit identity, and links in parent
   artifacts and job summaries. The generated runs retain their Debian packages
   and CMake logs as separate artifacts.

The CPU job uses a small Ubuntu 24.04 amd64 container with the public CUDA 13
SDK Debian development package matching the generated SDK version. It compiles
C++ and Python bindings without executing a GPU graph. The package job uses a
fresh Ubuntu container and checks the actual Debian package name, version,
architecture, and SDK dependency before installing it. An x86_64 result does
not establish Jetson/ARM or CUDA 12 coverage. GPU runtime tests remain a separate
opt-in path in the generated workflow.

A normal run removes its branch only if its commit and ownership marker still
match and no workflow remains active. Interrupted runs request cancellation and
retain the branch until jobs stop. The daily sweep only considers correctly
marked orphan branches older than 24 hours whose parent attempt has completed.
It preserves changed branches, active parent attempts, and unrecognized refs.
API/access failures stop cleanup rather than being treated as absence.

### Reproduction and failure diagnosis

Run the controller and template regression tests locally:

```bash
poetry run pytest -q -o addopts='' \
  tests/unit/test_module_e2e.py tests/unit/test_create_module.py
```

To exercise wheel installation and generation without publishing any branches:

```bash
poetry build
python .github/scripts/module_e2e.py prepare \
  --wheel-dir dist --output /tmp/module-e2e-python \
  --repository nvidia-holoscan/holoscan-cli --source-sha "$(git rev-parse HEAD)" \
  --parent-run-id 1 --parent-attempt 1 --cli-artifact-id 1 --language python
```

Use a missing output directory and repeat with `--language cpp` and another
output path. The numeric IDs above are local placeholders; publication requires
an existing artifact belonging to the real parent run. Network access is needed
to install creation dependencies. The `publish`, `dispatch`, `cleanup`, and
`sweep` commands write to GitHub and should only run for authorized validation.

For a failed live run, start with the original CLI job summary and its evidence
artifact, then inspect the linked module run. Do not select an unrelated latest
successful run or treat a successful lint job as successful packaging. Rerun the
parent workflow with a new attempt to regenerate both modules and avoid stale
branch/artifact state. The automated Debian regression test builds real control
metadata and proves that an incorrect SDK dependency or minimum version is
rejected even when an unrelated valid dependency is present.

## Other workflows

* **`codeql.yaml`** — GitHub CodeQL Advanced for Python on push/PR to `main`
  and `release/*`, plus a weekly cron.
* **`dependency-review.yml`** — Blocks PRs that introduce vulnerable
  dependencies (`fail-on-severity: moderate`) or copyleft licenses. Uses
  `allow-licenses` rather than the deprecated `deny-licenses` option (see
  actions/dependency-review-action#997); add new SPDX identifiers there if
  a vetted permissive license isn't already on the list.

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
