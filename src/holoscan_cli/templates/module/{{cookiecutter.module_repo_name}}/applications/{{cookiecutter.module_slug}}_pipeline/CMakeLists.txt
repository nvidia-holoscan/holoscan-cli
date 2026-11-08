# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}
{%- if cookiecutter.__pure_python == 'yes' %}

# The Python implementation in python/ runs from source with the package that
# python/CMakeLists.txt stages in the build tree, so there is nothing to build.
# Its metadata.json lets the Holoscan CLI discover and run it
# (`holoscan run {{ cookiecutter.module_slug }}_pipeline`).
{%- else %}

# Each application implementation lives in its own language subdirectory with
# its own metadata.json so the Holoscan CLI can discover and run it
# (e.g. `holoscan run {{ cookiecutter.module_slug }}_pipeline`). Holoscan SDK 5.0
# is C++-first; a Python implementation returns in a later release.
# The language options in the root CMakeLists.txt select which ones build.
if(HOLOSCAN_{{ cookiecutter.module_slug | upper }}_BUILD_CPP)
    add_subdirectory(cpp)
endif()
{%- endif %}
