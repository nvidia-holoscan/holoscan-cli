[![Code Check](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yaml/badge.svg)](https://github.com/nvidia-holoscan/holoscan-cli/actions/workflows/main.yaml)
[![Coverage Status](https://coveralls.io/repos/github/nvidia-holoscan/holoscan-cli/badge.svg)](https://coveralls.io/github/nvidia-holoscan/holoscan-cli)

# Holoscan CLI

Command line interface for HoloHub-style Holoscan source-project development workflows.

## Overview

This repository is the home for Holoscan CLI. It includes tools for discovering,
building, running, testing, and linting HoloHub-style Holoscan source projects.

HAP/MAP application packaging and packaged-image runtime commands are no longer
provided by this CLI. Commands such as `holoscan package`, `holoscan hap-run`,
`holoscan nics`, and the `monai-deploy` console script are intentionally not
supported.

## Prerequisites

You will need a platform supported by [NVIDIA Holoscan SDK](https://docs.nvidia.com/holoscan/sdk-user-guide/sdk_installation.html#prerequisites). Refer to the Holoscan SDK User Guide for the latest requirements. In general, Holoscan-supported platforms include:

- An x64 PC with an Ubuntu operating system and an NVIDIA GPU or
- A supported NVIDIA ARM development kit.

## Installation

Holoscan CLI is delivered as a Python package and can be installed from PyPI.org using one of the following commands:

```bash
pip install holoscan-cli
```

## Build From Source

### Prerequisites

To build the Holoscan CLI from source, you will need to clone this repository and install the following dependencies:

- Python 3.10+.
- [poetry 2.0+](https://python-poetry.org/docs/#installation)

### Development Environment

Holoscan CLI uses [Poetry](https://python-poetry.org/) for package and dependency management. After installing Poetry, run the following commands to get started:

```bash
# Create virtual environment
poetry env use python3.12

# Activate virtual environment
eval $(poetry env activate)

# Install dependencies
poetry install

# Configure pre-commit hooks
pre-commit install

# Run pre-commit against all files
pre-commit run --all-files

# Build sdist package
poetry build

# Run tests
poetry run pytest
```

For more information on Poetry and its usages, see the [Poetry documentation](https://python-poetry.org/docs/).

## Contributing to the Holoscan CLI

See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.
