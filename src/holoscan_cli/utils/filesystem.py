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

"""Small, reusable filesystem operations that never overwrite existing data."""

import os
import shutil
import stat
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path


class DirectoryMaterializationError(RuntimeError):
    """A directory cannot be safely populated without replacing existing data."""


@dataclass(frozen=True)
class DirectorySnapshot:
    """Identity of a missing, empty, or explicitly preserved directory."""

    exists: bool
    entries: tuple[tuple[str, tuple[int, int, int, int, int]], ...] = ()

    @property
    def kind(self) -> str:
        if not self.exists:
            return "missing"
        return "preserved-only" if self.entries else "empty"


def inspect_directory(path: Path, *, allowed_entries: Collection[str] = ()) -> DirectorySnapshot:
    """Snapshot a missing or empty directory, preserving only named entries."""
    if path.is_symlink():
        raise DirectoryMaterializationError(f"Destination {path} is a symlink.")
    if not path.exists():
        return DirectorySnapshot(exists=False)
    if not path.is_dir():
        raise DirectoryMaterializationError(f"Destination {path} is not a directory.")

    try:
        entries = sorted(path.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise DirectoryMaterializationError(f"Could not inspect destination {path}: {exc}") from exc

    unexpected = [entry.name for entry in entries if entry.name not in allowed_entries]
    if unexpected:
        names = ", ".join(repr(name) for name in unexpected)
        raise DirectoryMaterializationError(
            f"Destination {path} is not empty; existing entries: {names}."
        )

    identities = []
    for entry in entries:
        if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
            raise DirectoryMaterializationError(
                f"Preserved destination entry {entry} must be a real file or directory."
            )
        metadata = entry.lstat()
        identities.append(
            (
                entry.name,
                (
                    metadata.st_dev,
                    metadata.st_ino,
                    stat.S_IFMT(metadata.st_mode),
                    metadata.st_size,
                    metadata.st_mtime_ns,
                ),
            )
        )
    return DirectorySnapshot(exists=True, entries=tuple(identities))


def materialize_tree(
    source: Path,
    destination: Path,
    expected: DirectorySnapshot,
    *,
    allowed_entries: Collection[str] = (),
) -> None:
    """Copy a tree with no-replace operations and roll back paths created on failure."""
    try:
        current = inspect_directory(destination, allowed_entries=allowed_entries)
    except DirectoryMaterializationError as exc:
        raise DirectoryMaterializationError(
            f"Destination {destination} changed during generation; nothing was overwritten."
        ) from exc
    if current != expected:
        raise DirectoryMaterializationError(
            f"Destination {destination} changed during generation; nothing was overwritten."
        )

    created: list[Path] = []

    def copy_directory(source_dir: Path, destination_dir: Path) -> None:
        for source_path in sorted(source_dir.iterdir(), key=lambda item: item.name):
            destination_path = destination_dir / source_path.name
            if source_path.is_symlink():
                destination_path.symlink_to(os.readlink(source_path))
                created.append(destination_path)
            elif source_path.is_dir():
                destination_path.mkdir()
                created.append(destination_path)
                copy_directory(source_path, destination_path)
                shutil.copystat(source_path, destination_path, follow_symlinks=False)
            elif source_path.is_file():
                with (
                    source_path.open("rb") as source_file,
                    destination_path.open("xb") as destination_file,
                ):
                    created.append(destination_path)
                    shutil.copyfileobj(source_file, destination_file)
                shutil.copystat(source_path, destination_path, follow_symlinks=False)
            else:
                raise DirectoryMaterializationError(
                    f"Source tree contains unsupported filesystem entry {source_path}."
                )

    try:
        if not expected.exists:
            destination.mkdir()
            created.append(destination)
        copy_directory(source, destination)
    except BaseException as exc:
        for path in reversed(created):
            try:
                path.unlink() if path.is_symlink() or path.is_file() else path.rmdir()
            except OSError:
                # Never recursively remove a directory that another process may have changed.
                pass
        if isinstance(exc, (DirectoryMaterializationError, KeyboardInterrupt, SystemExit)):
            raise
        raise DirectoryMaterializationError(
            f"Could not populate {destination} without overwriting existing data: {exc}"
        ) from exc
