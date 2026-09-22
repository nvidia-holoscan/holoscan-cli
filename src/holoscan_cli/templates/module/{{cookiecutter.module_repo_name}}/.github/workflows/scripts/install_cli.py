# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

"""Install the pinned CLI, optionally from an E2E candidate artifact."""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path


def main():
    digest = os.environ.get("CLI_WHEEL_SHA256", "")
    wheel_dir = os.environ.get("CLI_WHEEL_DIR", "")
    version = os.environ.get("CLI_VERSION", "")
    if any((digest, wheel_dir, version)):
        if not (re.fullmatch(r"[0-9a-f]{64}", digest) and wheel_dir and version):
            raise SystemExit("Candidate wheel requires directory, SHA256, and version")
        wheels = list(Path(wheel_dir).glob("holoscan_cli-*.whl"))
        if len(wheels) != 1:
            raise SystemExit("Expected exactly one candidate CLI wheel")
        wheel = wheels[0].resolve()
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != digest:
            raise SystemExit("Candidate CLI wheel digest mismatch")
        pins = [
            line.strip() for line in Path("requirements-cli.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if pins != [f"holoscan-cli=={version}"]:
            raise SystemExit("Candidate CLI does not match the generated version pin")
        requirement = f"{wheel}[create]"
    else:
        requirement = "holoscan-cli[create]"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", requirement, "-c", "requirements-cli.txt"],
        check=True,
    )
    if version:
        subprocess.run(
            [sys.executable, "-c",
             "from importlib.metadata import version; import sys; "
             "assert version('holoscan-cli') == sys.argv[1]", version],
            check=True,
        )


if __name__ == "__main__":
    main()
