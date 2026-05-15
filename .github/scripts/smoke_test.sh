#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# End-to-end smoke checks on an installed holoscan-cli wheel:
#  * positive surface — `--help` for every registered subcommand
#  * negative surface — removed subcommands stay removed; legacy console
#    scripts are not re-introduced
#
# Both main.yaml and release.yaml invoke this so the two pipelines test
# the same contract on every push and every release.
#
# Usage: smoke_test.sh <venv-bin-dir>
set -euo pipefail

bin_dir=${1:?usage: smoke_test.sh <venv-bin-dir>}
holoscan="$bin_dir/holoscan"
python="$bin_dir/python"

"$holoscan" --help
"$holoscan" version
"$holoscan" lint --dryrun

# Every registered command must surface working `--help`. Pull the list
# from the registry so this cannot drift if a subcommand is renamed.
commands=$("$python" -c \
  'from holoscan_cli.commands import registry; print(" ".join(registry.project_command_names()))')
for cmd in $commands; do
  echo "--- holoscan $cmd --help"
  "$holoscan" "$cmd" --help > /dev/null
done

# Negative surface: removed subcommands must exit non-zero, and the
# legacy `holohub` / `monai-deploy` console scripts must not be installed.
if "$holoscan" package --help; then exit 1; fi
if "$holoscan" nics; then exit 1; fi
if [ -x "$bin_dir/holohub" ]; then exit 1; fi
if [ -x "$bin_dir/monai-deploy" ]; then exit 1; fi
