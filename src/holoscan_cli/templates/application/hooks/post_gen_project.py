#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remove the implementation folder of the language that was not selected."""

import shutil

LANGUAGE = {{ cookiecutter.language | tojson }}

shutil.rmtree("python" if LANGUAGE == "cpp" else "cpp")
