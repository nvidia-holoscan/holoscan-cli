#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

# Provision a disposable Ubuntu 24.04 amd64 container, never the developer host.
set -euo pipefail
sdk_version=${1:?usage: install_ci_sdk.sh SDK_VERSION}
[[ "$sdk_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
test "$(dpkg --print-architecture)" = amd64
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl
curl --fail --silent --show-error --location \
  https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb \
  -o /tmp/cuda-keyring.deb
dpkg -i /tmp/cuda-keyring.deb
rm /tmp/cuda-keyring.deb
apt-get update
# SDK Debian versions include a fourth build component (e.g. 4.5.0.0-1).
# Match the requested SDK release; never silently install a newer release.
apt-get install -y --no-install-recommends "holoscan-cuda-13=${sdk_version}.*"
