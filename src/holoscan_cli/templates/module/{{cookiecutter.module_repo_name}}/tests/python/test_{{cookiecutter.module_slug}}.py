# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}
{%- set op_class = cookiecutter.operator_slug.split('_')|map('capitalize')|join('') %}

"""Check that the Python bindings register and run the Module's C++ operators."""

import subprocess
import sys
from pathlib import Path

import holoscan_{{ cookiecutter.module_slug }}
from holoscan_{{ cookiecutter.module_slug }}.operators import {{ op_class }}

import holoscan as hs

REGISTRY_NAME = "holoscan.{{ cookiecutter.module_slug }}.{{ op_class }}"
PIPELINE = (
    Path(__file__).resolve().parents[2]
    / "applications"
    / "{{ cookiecutter.module_slug }}_pipeline"
    / "python"
    / "{{ cookiecutter.module_slug }}_pipeline.py"
)


def test_extension_uses_the_stable_abi():
    assert holoscan_{{ cookiecutter.module_slug }}._{{ cookiecutter.module_slug }}.__file__.endswith(".abi3.so")


def test_operator_is_registered():
    assert REGISTRY_NAME in {operator.name for operator in hs.registry.operators()}


def test_proxy_authors_ports():
    graph = hs.Graph("test_proxy")
    handle = {{ op_class }}(graph, "op")
    assert handle.type_name == REGISTRY_NAME
    assert handle["in"] is not None
    assert handle.out is not None


def test_python_pipeline_runs():
    result = subprocess.run(
        [sys.executable, str(PIPELINE)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
