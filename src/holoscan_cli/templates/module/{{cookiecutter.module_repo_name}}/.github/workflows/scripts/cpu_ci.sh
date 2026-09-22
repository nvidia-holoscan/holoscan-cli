#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

# Shared by this Module's workflow and the CLI's unprivileged PR validation.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
phase=${1:?usage: cpu_ci.sh PHASE [PACKAGE_DIRECTORY]}
package_dir=${2:-packages}
image=module-ci-build

case "$phase" in
  image)
    docker build -f .github/workflows/Dockerfile.cpu -t "$image" .github/workflows
    ;;
  configure)
    docker run --rm -v "$PWD:/work" "$image" \
      cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -D{{ cookiecutter.module_slug | upper }}_BUILD_TESTING=OFF -DBUILD_ALL=ON
    ;;
  build)
    docker run --rm -v "$PWD:/work" "$image" cmake --build build --parallel 2
    ;;
  package)
    docker run --rm -v "$PWD:/work" "$image" \
      cpack --config build/pkg/CPackConfig-{{ cookiecutter.module_repo_name }}.cmake \
      -B build/packages -G DEB
    ;;
  verify)
    packages=("$package_dir"/*.deb)
    test "{% raw %}${#packages[@]}{% endraw %}" = 1
    bash .github/workflows/scripts/verify_debian_package.sh "${packages[0]}"
    ;;
  install)
    # Run only inside a disposable Ubuntu container.
    bash .github/workflows/scripts/cpu_ci.sh verify "$package_dir"
    bash .github/workflows/scripts/install_ci_sdk.sh '{{ cookiecutter.holoscan_version }}'
    apt-get install -y --no-install-recommends "$(realpath "$package_dir")"/*.deb
    dpkg-query --show --showformat='${Status}\n' \
      {{ cookiecutter.module_repo_name }} | grep -Fx 'install ok installed'
    dpkg --audit
    ;;
  install-clean)
    # Mount only the scripts and packages: no build tree or preinstalled Module.
    docker run --rm \
      -v "$PWD/.github/workflows/scripts:/work/.github/workflows/scripts:ro" \
      -v "$(realpath "$package_dir"):/work/packages:ro" \
      --workdir /work ubuntu:24.04 \
      bash .github/workflows/scripts/cpu_ci.sh install packages
    ;;
  *)
    echo "Unknown CPU CI phase: $phase" >&2
    exit 2
    ;;
esac
