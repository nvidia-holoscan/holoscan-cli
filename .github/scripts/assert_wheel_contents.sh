#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Verify that a built holoscan-cli wheel ships the required package data
# (and does not accidentally re-introduce content we deliberately removed).
# Both main.yaml and release.yaml invoke this so the two pipelines cannot
# drift on what a release wheel must contain.
#
# Usage: assert_wheel_contents.sh <wheel-dir>
set -euo pipefail

wheel_dir=${1:-dist}
wheel=$(find "$wheel_dir" -name 'holoscan_cli-*.whl' | head -n1)
if [[ -z "$wheel" ]]; then
  echo "no holoscan_cli-*.whl found under $wheel_dir" >&2
  exit 1
fi
echo "Inspecting $wheel"
listing=$(unzip -l "$wheel")

required=(
  'holoscan_cli/logging\.json$'
  'holoscan_cli/py\.typed$'
  'holoscan_cli/metadata/.+\.schema\.json$'
  'holoscan_cli/testing/'
)
for pattern in "${required[@]}"; do
  if ! echo "$listing" | grep -qE "$pattern"; then
    echo "Missing from wheel: $pattern" >&2
    exit 1
  fi
done

forbidden=(
  'holoscan_cli/cmake/'
  'holoscan_cli/testing/test_all_applications/'
)
for pattern in "${forbidden[@]}"; do
  if echo "$listing" | grep -qE "$pattern"; then
    echo "Unexpectedly shipped in wheel: $pattern" >&2
    exit 1
  fi
done
