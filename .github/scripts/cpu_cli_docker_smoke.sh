#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# CPU-only integration smoke test for the installed holoscan-cli wheel.
# It mirrors the intent of HoloHub's check_cli/check_docker workflows without
# pulling Holoscan SDK, CUDA, or NGC images.
#
# Usage: cpu_cli_docker_smoke.sh <venv-bin-dir>
set -euo pipefail

bin_dir=${1:?usage: cpu_cli_docker_smoke.sh <venv-bin-dir>}
holoscan="$bin_dir/holoscan"
python="$bin_dir/python"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_fixture_root="$(realpath "$script_dir/../../tests/fixtures/holohub_smoke")"
tiny_base="${HOLOSCAN_CLI_CPU_SMOKE_BASE_IMAGE:-busybox:1.36}"

tmpdir="$(mktemp -d)"
fixture_root="$tmpdir/holohub_smoke"
image="holoscan-cli-cpu-smoke:${GITHUB_RUN_ID:-local}-$$"
cleanup() {
  rm -rf "$tmpdir"
  if command -v docker >/dev/null 2>&1; then
    docker rmi "$image" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

cp -R "$source_fixture_root" "$fixture_root"

cat > "$tmpdir/Dockerfile" <<'EOF'
ARG BASE_IMAGE=busybox:1.36
FROM ${BASE_IMAGE}
LABEL org.opencontainers.image.title="holoscan-cli-cpu-smoke"
EOF

run_fixture() {
  HOLOSCAN_CLI_ROOT="$fixture_root" \
    HOLOSCAN_CLI_BUILD_PARENT_DIR="$tmpdir/build" \
    HOLOSCAN_CLI_DATA_DIR="$tmpdir/data" \
    "$holoscan" "$@"
}

check_id=0
assert_run_fixture_contains() {
  local needle=$1
  shift
  local output="$tmpdir/check-${check_id}.log"
  check_id=$((check_id + 1))
  run_fixture "$@" > "$output"
  grep -q -- "$needle" "$output"
}

echo "--- CPU CLI fixture checks"
mkdir -p "$tmpdir/build/smoke_app" "$tmpdir/data"
assert_run_fixture_contains "smoke_app" list
assert_run_fixture_contains "smoke_app" autocompletion_list
run_fixture modes smoke_app >/dev/null
assert_run_fixture_contains "smoke_app" run smoke_app --local --language python --no-local-build
run_fixture clear-cache --build
test ! -e "$tmpdir/build"
test -d "$tmpdir/data"
assert_run_fixture_contains "-DAPP_smoke_app=ON" \
  build smoke_app --local --dryrun --language python --configure-args=-DSMOKE=ON
assert_run_fixture_contains "--frames" \
  run smoke_app --local --dryrun --language python --no-local-build --run-args="--frames 1"
assert_run_fixture_contains "--install" \
  install smoke_app --local --dryrun --language python
assert_run_fixture_contains "-DAPP=smoke_app" \
  test smoke_app --local --dryrun --language python --no-xvfb --ctest-script "$tmpdir/container.ctest"

echo "--- CPU Docker dry-run checks"
assert_run_fixture_contains "BASE_IMAGE=$tiny_base" \
  build-container --dryrun --docker-file "$tmpdir/Dockerfile" --base-img "$tiny_base" --img "$image"

run_fixture run-container --dryrun --no-docker-build --img "$image" \
  --docker-opts "--memory 128m" --add-volume "$tmpdir" -- echo hello \
  > "$tmpdir/run-container.log"
grep -q -- "docker run" "$tmpdir/run-container.log"
grep -q -- "--memory 128m" "$tmpdir/run-container.log"
grep -q -- "$tmpdir" "$tmpdir/run-container.log"
grep -q -- "echo hello" "$tmpdir/run-container.log"

echo "--- installed-wheel entrypoint helper checks"
"$python" - <<'PY'
from holoscan_cli.utils.docker import get_entrypoint_command_args

assert get_entrypoint_command_args("img", "echo hello", "--entrypoint=/bin/sh") == (
    "",
    ["-c", "echo hello"],
)
assert get_entrypoint_command_args("img", "python -m holoscan_cli list", "--entrypoint=/usr/bin/python3") == (
    "",
    ["python", "-m", "holoscan_cli", "list"],
)
PY

if [ "${HOLOSCAN_CLI_CPU_SMOKE_SKIP_DOCKER_BUILD:-0}" = "1" ]; then
  echo "--- skipping tiny Docker build by request"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "--- docker unavailable; skipping tiny Docker build"
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  echo "--- docker daemon unavailable; skipping tiny Docker build"
  exit 0
fi

echo "--- tiny CPU Docker build using $tiny_base"
run_fixture build-container --docker-file "$tmpdir/Dockerfile" --base-img "$tiny_base" --img "$image"
docker inspect "$image" --format='{{ index .Config.Labels "org.opencontainers.image.title" }}' \
  | grep -q "holoscan-cli-cpu-smoke"
