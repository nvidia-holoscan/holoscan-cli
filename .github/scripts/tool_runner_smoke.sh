#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Verify that package-name based tool runners can execute holoscan-cli
# directly from the wheel built by this workflow.
#
# Usage: tool_runner_smoke.sh <wheel-dir-or-wheel-path>
set -euo pipefail

wheel_input=${1:-dist}
if [[ -d "$wheel_input" ]]; then
  wheel=$(find "$wheel_input" -name 'holoscan_cli-*.whl' | head -n1)
else
  wheel="$wheel_input"
fi

if [[ -z "${wheel:-}" || ! -f "$wheel" ]]; then
  echo "no holoscan_cli-*.whl found at $wheel_input" >&2
  exit 1
fi

if ! command -v uvx >/dev/null; then
  echo "uvx is required for tool-runner smoke tests" >&2
  exit 1
fi
if ! command -v pipx >/dev/null; then
  echo "pipx is required for tool-runner smoke tests" >&2
  exit 1
fi

wheel=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$wheel")
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

export UV_TOOL_DIR="$tmp_dir/uv/tools"
export UV_CACHE_DIR="$tmp_dir/uv/cache"
export PIPX_HOME="$tmp_dir/pipx/home"
export PIPX_BIN_DIR="$tmp_dir/pipx/bin"
mkdir -p "$UV_TOOL_DIR" "$UV_CACHE_DIR" "$PIPX_HOME" "$PIPX_BIN_DIR"

echo "--- uvx --from $wheel holoscan-cli version"
uvx --from "$wheel" holoscan-cli version

echo "--- pipx run --spec $wheel holoscan-cli version"
pipx run --spec "$wheel" holoscan-cli version
