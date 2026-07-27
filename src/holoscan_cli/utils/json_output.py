# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Single source of truth for the ``--json`` output contract.

Every ``--json`` payload the CLI emits is wrapped by :func:`dumps`, which
prepends an additive ``schema_version`` field. Agents key on this to detect
the payload shape; schema v1 is additive within a major CLI version
(fields may be added, never removed or renamed without a version bump).
"""

from __future__ import annotations

import json
from typing import Any

# Bump only for a breaking change (a removed or renamed field). Additive
# changes — new keys — keep the same version.
SCHEMA_VERSION = 1


def dumps(payload: dict[str, Any]) -> str:
    """Serialize ``payload`` as the CLI's standard indented JSON document.

    ``schema_version`` is injected as the first key so a reader can branch on
    it before parsing the rest.
    """
    return json.dumps({"schema_version": SCHEMA_VERSION, **payload}, indent=2)
