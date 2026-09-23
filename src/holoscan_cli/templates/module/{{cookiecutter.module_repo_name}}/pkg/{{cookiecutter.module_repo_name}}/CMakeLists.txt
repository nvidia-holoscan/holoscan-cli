# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

# This file is entered via add_holohub_package({{ cookiecutter.module_repo_name }} ...) in
# pkg/CMakeLists.txt, which only fires when PKG_{{ cookiecutter.module_repo_name.replace('-', '_') }} is ON.
include(holohub_configure_deb)

if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
  set(HOLOSCAN_DEB_DEPENDENCY
      "holoscan (>= {{ cookiecutter.holoscan_version }}), holoscan (<< 5.0)")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64)$")
  set(HOLOSCAN_DEB_DEPENDENCY
      "holoscan-cuda-13 (>= {{ cookiecutter.holoscan_version }}), holoscan-cuda-13 (<< 5.0)")
else()
  message(FATAL_ERROR "Unsupported Debian package architecture: ${CMAKE_SYSTEM_PROCESSOR}")
endif()

holohub_configure_deb(
    NAME        "{{ cookiecutter.module_repo_name }}"
    DESCRIPTION "${PROJECT_DESCRIPTION}"
    VERSION     "${PROJECT_VERSION}"
    VENDOR      "{% if cookiecutter.affiliation %}{{ cookiecutter.affiliation }}{% else %}NVIDIA{% endif %}"
    CONTACT     "{{ cookiecutter.contact_email }}"
    # Match the platform-specific SDK package for the CUDA 13 base image.
    DEPENDS     "${HOLOSCAN_DEB_DEPENDENCY}"
{% if cookiecutter.language == 'cpp' %}    EXPORT_NAME "holoscan_{{ cookiecutter.module_slug }}_targets"
{% endif %})
