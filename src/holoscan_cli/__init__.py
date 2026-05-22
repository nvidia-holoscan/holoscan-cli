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

__title__ = "holoscan_cli"

try:
    __version__ = importlib.metadata.version("holoscan-cli")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0+local"
