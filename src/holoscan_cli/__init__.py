# SPDX-FileCopyrightText: Copyright (c) 2023-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Top-level package marker for ``holoscan_cli``.

This module is intentionally minimal: it exposes ``__title__`` and
``__version__`` for ``holoscan version`` consumers and otherwise leaves
import resolution untouched. In particular, it deliberately does **not**
mutate ``sys.path`` — for an installed PyPI distribution the package
should always be importable as ``holoscan_cli`` and adding its directory
to ``sys.path`` would silently shadow unrelated top-level modules
(``cli``, ``util``, ``status``, ...). The submodules use absolute imports
of ``holoscan_cli.<module>`` so the standard import machinery is enough.

.. autosummary::
    :toctree: _autosummary

    cli
    version
"""

import importlib.metadata
import os
import sys

__title__ = "holoscan_cli"

try:
    __version__ = importlib.metadata.version("holoscan-cli")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0+local"


# ---- HOLOHUB_* -> HOLOSCAN_CLI_* deprecation alias --------------------------
#
# This release migrates all CLI-read environment variables from the historical
# HOLOHUB_<suffix> spelling to HOLOSCAN_CLI_<suffix> so they match the package
# name (holoscan-cli), console script (holoscan), and module (holoscan_cli).
# For one release the CLI honors both names — the new name wins; if only the
# old name is set we copy it to the new name on first import and emit a
# one-line deprecation warning. Old names stop being honored in the next minor
# version. Keep this list sorted so additions are easy to review.
_DEPRECATED_HOLOHUB_ENV_SUFFIXES = (
    "ALWAYS_BUILD",
    "APP_NAME",
    "BASE_IMAGE",
    "BASE_IMAGE_FORMAT",
    "BASE_SDK_VERSION",
    "BENCHMARKING_SUBDIR",
    "BUILD_LOCAL",
    "BUILD_PARENT_DIR",
    "CMD_NAME",
    "CONTAINER_PREFIX",
    "CTEST_SCRIPT",
    "DATA_DIR",
    "DATA_PATH",
    "DEFAULT_DOCKER_BUILD_ARGS",
    "DEFAULT_DOCKER_RUN_ARGS",
    "DEFAULT_DOCKERFILE",
    "DEFAULT_HSDK_DIR",
    "DEFAULT_IMAGE_FORMAT",
    "DOCKER_EXE",
    "ENABLE_SCCACHE",
    "HOSTNAME_PREFIX",
    "PATH_PREFIX",
    "REPO_PREFIX",
    "ROOT",
    "SEARCH_PATH",
    "SETUP_SCRIPTS_DIR",
    "WORKSPACE_NAME",
)


def _migrate_deprecated_env_aliases() -> None:
    """Copy any user-set HOLOHUB_X into HOLOSCAN_CLI_X and warn.

    Runs once, on first import of ``holoscan_cli``. The new spelling always
    wins; we only copy when the new name is unset. The warning intentionally
    bypasses the logging stack — many callers configure logging *after* the
    CLI has already started reading env vars, so going through ``logging``
    here would swallow the message.
    """
    pending = []
    for suffix in _DEPRECATED_HOLOHUB_ENV_SUFFIXES:
        old = f"HOLOHUB_{suffix}"
        new = f"HOLOSCAN_CLI_{suffix}"
        if new in os.environ:
            continue
        if old in os.environ:
            os.environ[new] = os.environ[old]
            pending.append((old, new))
    for old, new in pending:
        print(
            f"WARNING: {old} is deprecated; use {new} instead. "
            f"Both names work in this release; only {new} will be honored next.",
            file=sys.stderr,
        )


_migrate_deprecated_env_aliases()
