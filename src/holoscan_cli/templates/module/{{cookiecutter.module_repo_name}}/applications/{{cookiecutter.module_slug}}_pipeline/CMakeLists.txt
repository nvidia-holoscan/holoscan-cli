# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

# Each application implementation lives in its own language subdirectory with
# its own metadata.json so the Holoscan CLI can discover and run it
# (e.g. `holoscan run {{ cookiecutter.module_slug }}_pipeline`). Holoscan SDK 5.0
# is C++-first; a Python implementation returns in a later release.
add_subdirectory(cpp)
