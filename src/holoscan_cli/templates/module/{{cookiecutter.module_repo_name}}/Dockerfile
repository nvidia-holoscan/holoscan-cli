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

# Holoscan SDK images may provide Python and pip without the distro venv
# package, so make the isolation prerequisite explicit.
RUN apt-get update \
    && apt-get install --no-install-recommends -y python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Install the Module's exact CLI requirement from the configured package index.
# PIP_INDEX_URL and PIP_EXTRA_INDEX_URL above are honored by pip, so an
# unpublished build can be resolved by pointing them at a local index.
COPY requirements-cli.txt /tmp/requirements-cli.txt
RUN python3 -m venv /opt/holoscan-cli \
    && /opt/holoscan-cli/bin/python -m pip install --no-cache-dir \
        -r /tmp/requirements-cli.txt \
    && ln -s /opt/holoscan-cli/bin/holoscan /usr/local/bin/holoscan \
    && command -v holoscan \
    && /opt/holoscan-cli/bin/python -c 'from importlib.metadata import version; from pathlib import Path; lines = [line.strip() for line in Path("/tmp/requirements-cli.txt").read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]; expected = lines[0].split("==", 1)[1]; actual = version("holoscan-cli"); assert actual == expected, f"installed {actual}, expected {expected}"' \
    && holoscan version

# TODO: add module-specific runtime / build dependencies below.
{% if cookiecutter.language == "cpp" %}RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libgtest-dev \
        clang-format \
        pybind11-dev \
    && rm -rf /var/lib/apt/lists/*
{% endif %}
# Python tooling: pytest-timeout for tests, build + scikit-build-core for
# `holoscan package --pkg-generator WHEEL` (drives `python -m build`).
RUN pip install --no-cache-dir pytest-timeout build scikit-build-core
