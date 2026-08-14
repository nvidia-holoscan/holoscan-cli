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

ARG BASE_IMAGE=nvcr.io/nvidia/clara-holoscan/holoscan:v{{ cookiecutter.holoscan_version }}-cuda13-dgpu
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG PIP_INDEX_URL
ARG PIP_EXTRA_INDEX_URL
ARG PIP_NO_INDEX

# Install the Module's exact CLI requirement from the configured package index.
# PIP_INDEX_URL and PIP_EXTRA_INDEX_URL above are honored by pip, so an
# unpublished build can be resolved by pointing them at a local index.
# holoscan-cli has no runtime dependencies on Python 3.11+, so installing it
# into the image's interpreter adds nothing else.
COPY requirements-cli.txt /tmp/requirements-cli.txt
RUN python3 -m pip install --no-cache-dir \
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
# pytest-timeout for tests, build + scikit-build-core for
# `holoscan package --pkg-generator WHEEL`. These must live in the same
# interpreter the CLI runs on, because build and package configure CMake with
# -DPython3_EXECUTABLE=<that interpreter> and the wheel build shells out to it.
RUN python3 -m pip install --no-cache-dir \
        pytest-timeout build scikit-build-core
