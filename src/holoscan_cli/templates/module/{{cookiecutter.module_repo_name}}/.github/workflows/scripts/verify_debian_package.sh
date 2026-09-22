#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

set -euo pipefail
package=${1:?usage: verify_debian_package.sh PACKAGE.deb}
test "$(dpkg-deb --field "$package" Package)" = '{{ cookiecutter.module_repo_name }}'
test "$(dpkg-deb --field "$package" Version)" = '{{ cookiecutter.version }}'
test "$(dpkg-deb --field "$package" Architecture)" = amd64
# Keep the expected consumer dependency independent of the package CMake logic.
dpkg-deb --field "$package" Depends \
  | tr ',' '\n' \
  | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' \
  | grep -Fx 'holoscan-cuda-13 (>= {{ cookiecutter.holoscan_version }})'
