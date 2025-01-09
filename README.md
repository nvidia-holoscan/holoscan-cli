[![Code Check](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/check.yaml/badge.svg)](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/check.yaml)
[![Coverage Status](https://coveralls.io/repos/github/nvidia-holoscan/holoscan-cli/badge.svg?branch=vchang/poetry-setup)](https://coveralls.io/github/nvidia-holoscan/holoscan-cli?branch=vchang/poetry-setup)

# Holoscan CLI

Command line interface for packaging and running Holoscan applications.

## Overview

This repository is the home for Holoscan CLI. It includes tools for packaging and running Holoscan applications.

## Prerequisites

You will need a platform supported by [NVIDIA Holoscan SDK](https://docs.nvidia.com/holoscan/sdk-user-guide/sdk_installation.html#prerequisites). Refer to the Holoscan SDK User Guide for the latest requirements. In general, Holoscan-supported platforms include:

- An x64 PC with an Ubuntu operating system and an NVIDIA GPU or
- A supported NVIDIA ARM development kit.

## Installation

Holoscan CLI is delivered as a Python package and can be installed from PyPI.org using one of the following commands:

| Holoscan SDK Version | Installation Command       |
| -------------------- | -------------------------- |
| 2.8 or earlier       | `pip install holoscan`     |
| 2.9 or later         | `pip install holoscan-cli` |

## Build From Source

### Prerequisites

To build the Holoscan CLI from source, you will need to clone this repository and install the following dependencies:

- Python 3.9 or higher.
- [poetry](https://python-poetry.org/docs/#installation)

### Development Environment

Holoscan CLI uses [Poetry](https://python-poetry.org/) for package and dependency management. After installing Poetry, run the following commands to get started:

```bash
# Create virtual environment
poetry shell

# Install dependencies
poetry install

# Configure pre-commmit hooks
pre-commit install

# Run pre-commit against all files
pre-commit run --all-files

# Build sdist package
poetry build

# Run tests
poetry run pytest
```

## Contributing to the Holoscan CLI

See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.
