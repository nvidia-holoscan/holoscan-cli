![Build](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yml/badge.svg?branch=$%7BGH_BRANCH%7D)
[![Coverage Status](https://coveralls.io/repos/github/nvidia-holoscan/holoscan-cli/badge.svg?branch=vchang/poetry-setup)](https://coveralls.io/github/nvidia-holoscan/holoscan-cli?branch=vchang/poetry-setup)

# Holoscan CLI

Command line interface for packaging and running Holoscan applications.

# Overview

This repository is the home for Holoscan CLI. It includes tools for packaging and running Holoscan applications.

# Prerequisites

You will need a platform supported by [NVIDIA Holoscan SDK](https://docs.nvidia.com/holoscan/sdk-user-guide/sdk_installation.html#prerequisites). Refer to the Holoscan SDK User Guide for the latest requirements. In general, Holoscan-supported platforms include:

- An x64 PC with an Ubuntu operating system and an NVIDIA GPU or
- A supported NVIDIA ARM development kit.

# Installation

Holoscan CLI is delivered as a Python package and can be installed from PyPI.org using one of the following commands:

| Holoscan SDK Version | Installation Command       |
| -------------------- | -------------------------- |
| 2.8 or earlier       | `pip install holoscan`     |
| 2.9 or later         | `pip install holoscan-cli` |

# Contributing to the Holoscan CLI

See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.
