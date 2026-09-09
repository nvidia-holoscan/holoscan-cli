# syntax=docker/dockerfile:1

# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}
#
# Development container for {{ cookiecutter.project_name }}.
#
# Extends the Holoscan SDK image with the build tools needed to configure,
# compile, and test the module from a live source mount. No source is copied
# into the image; the project tree is bind-mounted by the holoscan-cli at
# /workspace/{{ cookiecutter.module_slug }} when the container is launched.
#
# Build & run via the installed Holoscan CLI:
#   holoscan run-container
#
# Manual build (without the CLI):
#   docker build -t holoscan-{{ cookiecutter.module_slug.replace('_', '-') }} .

ARG BASE_IMAGE=nvcr.io/nvidia/clara-holoscan/holoscan:v{{ cookiecutter.holoscan_version }}-cuda13
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive

# Install the exact CLI pin. holoscan-cli has no runtime dependencies, so
# this adds nothing else to the image.
COPY requirements-cli.txt /tmp/requirements-cli.txt
RUN python3 -m pip install --no-cache-dir \
        --extra-index-url https://pypi.nvidia.com \
        -r /tmp/requirements-cli.txt \
    && holoscan version

# TODO: add module-specific runtime / build dependencies below.
{% if cookiecutter.language == "cpp" %}RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libgtest-dev \
        clang-format \
        pybind11-dev \
    && rm -rf /var/lib/apt/lists/*
{% endif %}
# Test and wheel-build tooling. Must be in the same interpreter the CLI runs
# on: build and package pass it to CMake as Python3_EXECUTABLE.
RUN python3 -m pip install --no-cache-dir \
        'pytest>=8.2' pytest-timeout build scikit-build-core
