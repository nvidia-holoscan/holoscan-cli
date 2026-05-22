#!/usr/bin/env python3
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

import signal
from pathlib import Path
from typing import Optional


def _read_container_id(cidfile: Path) -> Optional[str]:
    """Read a Docker container ID from a cidfile if Docker has written it."""
    try:
        container_id = cidfile.read_text().strip()
    except OSError:
        return None
    return container_id or None


class _ContainerTerminationSignal(Exception):
    """Raised from the signal handler to return control to the parent CLI."""

    def __init__(self, signum: int):
        self.signum = signum
        super().__init__(signum)


class _ContainerTerminationHandler:
    """Record termination signals so the parent CLI can clean up its container.

    The handler intentionally only records the signal; it does not run subprocesses
    from the signal context. The caller is expected to perform cleanup (e.g.
    `docker stop`) on the main thread after the guarded block exits.
    """

    def __init__(self):
        self._previous_handlers = {}

    def __enter__(self):
        for signal_name in ("SIGINT", "SIGTERM", "SIGHUP"):
            signum = getattr(signal, signal_name, None)
            if signum is None:
                continue
            try:
                self._previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, self._handle_signal)
            except (OSError, RuntimeError, ValueError):
                continue
        return self

    def __exit__(self, exc_type, exc, tb):
        for signum, handler in self._previous_handlers.items():
            # signal.getsignal returns None for natively-installed handlers,
            # and signal.signal(None) raises TypeError — swallow it so we don't
            # mask the original termination exception during cleanup.
            try:
                signal.signal(signum, handler)
            except (OSError, RuntimeError, TypeError, ValueError):
                continue

    def _handle_signal(self, signum, _frame) -> None:
        raise _ContainerTerminationSignal(signum)
