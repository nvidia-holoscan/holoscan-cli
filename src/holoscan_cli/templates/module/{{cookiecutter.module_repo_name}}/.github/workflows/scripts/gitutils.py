"""
SPDX-FileCopyrightText: Copyright (c) 2022-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import os
import re
import subprocess


def is_file_empty(f):
    return os.stat(f).st_size == 0


def __git(*opts):
    """Runs a git command and returns its output"""
    ret = subprocess.check_output(["git", *opts], shell=False)
    return ret.decode("UTF-8").rstrip("\n")


def __gitdiff(*opts):
    """Runs a git diff command with no pager set"""
    return __git("--no-pager", "diff", *opts)


def _resolve_commit(ref):
    """Resolve a caller-provided revision without treating it as a Git option."""
    if not isinstance(ref, str) or not ref or ref.startswith("-") or "\0" in ref:
        raise ValueError(f"Invalid Git revision: {ref!r}")
    return __git("rev-parse", "--verify", "--end-of-options", f"{ref}^0")


def branch():
    """Returns the name of the current branch"""
    name = __git("rev-parse", "--abbrev-ref", "HEAD")
    name = name.rstrip()
    return name


def dir_():
    """Returns the top level directory of the repository"""
    git_dir = __git("rev-parse", "--show-toplevel")
    git_dir = git_dir.rstrip()
    return git_dir


def repo_version():
    """
    Determines the version of the repo by using `git describe`

    Returns
    -------
    str
        The full version of the repo in the format 'v#.#.#{a|b|rc}'
    """
    return __git("describe", "--tags", "--abbrev=0")


def repo_version_major_minor():
    """
    Determines the version of the repo using `git describe` and returns only
    the major and minor portion

    Returns
    -------
    str
        The partial version of the repo in the format '{major}.{minor}'
    """

    full_repo_version = repo_version()

    match = re.match(r"^v?(?P<major>[0-9]+)(?:\.(?P<minor>[0-9]+))?", full_repo_version)

    if match is None:
        print(
            "   [DEBUG] Could not determine repo major minor version. "
            f"Full repo version: {full_repo_version}."
        )
        return None

    out_version = match.group("major")

    if match.group("minor"):
        out_version += "." + match.group("minor")

    return out_version


def uncommitted_files():
    """
    Returns a list of all changed files that are not yet committed. This
    means both untracked/unstaged as well as uncommitted files too.
    """
    entries = __git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    ret = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        ret.append(path)
        if "R" in status or "C" in status:
            index += 1  # porcelain -z adds the original rename/copy path next
    return ret


def changed_files_between(base_ref, new_ref):
    """
    Returns a list of files changed between base_ref and new_ref
    """
    base_commit = _resolve_commit(base_ref)
    new_commit = _resolve_commit(new_ref)
    files = __gitdiff("--name-only", "--ignore-submodules", f"{base_commit}..{new_commit}")
    return files.splitlines()


def changes_in_file_between(file, b1, b2, filter=None):
    """Filters the changed lines to a file between the branches b1 and b2"""
    b1_commit = _resolve_commit(b1)
    b2_commit = _resolve_commit(b2)
    path = os.fspath(file)
    if "\0" in path:
        raise ValueError("Git paths cannot contain NUL bytes")
    diffs = __gitdiff(
        "--ignore-submodules",
        "-w",
        "--minimal",
        "-U0",
        f"{b1_commit}...{b2_commit}",
        "--",
        f":(literal){path}",
    )
    return [line for line in diffs.splitlines() if (filter is None or filter(line))]


def modified_files(target=None, absolute_path=False):
    """
    If target is passed, then lists out all files modified between that git
    reference and HEAD. If this fails, this function will list out all
    the uncommitted files in the current branch.
    """
    all_files = changed_files_between(target, "HEAD") if target else uncommitted_files()

    if absolute_path:
        git_dir = dir_()
        return [os.path.join(git_dir, fn) for fn in all_files]
    else:
        return all_files
