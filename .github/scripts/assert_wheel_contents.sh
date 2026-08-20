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
  'holoscan_cli/cmake/Config\.cmake\.in$'
  'holoscan_cli/cmake/HoloHubConfigHelpers\.cmake$'
  'holoscan_cli/cmake/holohub_configure_deb\.cmake$'
  'holoscan_cli/cmake/pybind11_add_holohub_module\.cmake$'
  'holoscan_cli/cmake/pybind11/__init__\.py\.in$'
  'holoscan_cli/cmake/pydoc/macros\.hpp$'
  'holoscan_cli/metadata/.+\.schema\.json$'
  'holoscan_cli/setup_scripts/.+'
  'holoscan_cli/setup_scripts/requirements\.template\.txt$'
  'holoscan_cli/templates/module/cookiecutter\.json$'
  'holoscan_cli/templates/module/hooks/pre_gen_project\.py$'
  'holoscan_cli/templates/module/hooks/post_gen_project\.py$'
  'holoscan_cli/templates/module/.+/requirements-cli\.txt$'
  'holoscan_cli/templates/module/.+/\.dockerignore$'
  'holoscan_cli/templates/module/.+/\.github/workflows/scripts/check_copyright\.py$'
  'holoscan_cli/testing/'
)
for pattern in "${required[@]}"; do
  if ! echo "$listing" | grep -qE "$pattern"; then
    echo "Missing from wheel: $pattern" >&2
    exit 1
  fi
done

forbidden=(
  'holoscan_cli/testing/test_all_applications/'
  'holoscan_cli/templates/module/.+/holohub$'
)
for pattern in "${forbidden[@]}"; do
  if echo "$listing" | grep -qE "$pattern"; then
    echo "Unexpectedly shipped in wheel: $pattern" >&2
    exit 1
  fi
done
