# SPDX-FileCopyrightText: Copyright (c) {% now 'utc', '%Y' %} {{ cookiecutter.full_name }}{% if cookiecutter.affiliation %} / {{ cookiecutter.affiliation }}{% endif %}. All rights reserved.
# SPDX-License-Identifier: {{ cookiecutter._license }}

# Python bindings: a nanobind extension that registers this Module's C++ operators with the
# Holoscan SDK operator registry, wrapped in the holoscan_{{ cookiecutter.module_slug }} package.
# Python reaches the operators through the SDK's typed registry proxies.

include(GNUInstallDirs)

# Holoscan SDK 5.0 does not ship nanobind; use the version its own bindings are built with.
find_package(nanobind 3.0.1 CONFIG QUIET)
if(NOT nanobind_FOUND)
    include(FetchContent)
    FetchContent_Declare(nanobind
        GIT_REPOSITORY https://github.com/wjakob/nanobind.git
        GIT_TAG db4827f06f6f1680e5d4004c95fc8d69299dba8b  # v3.0.1
    )
    FetchContent_MakeAvailable(nanobind)
endif()

set(_package holoscan_{{ cookiecutter.module_slug }})
set(_python_root "${CMAKE_CURRENT_BINARY_DIR}/lib")
set(_package_dir "${_python_root}/${_package}")
set({{ cookiecutter.module_slug | upper }}_PYTHON_BUILD_DIR "${_python_root}" PARENT_SCOPE)
set({{ cookiecutter.module_slug | upper }}_PYTHON_INSTALL_DIR
    "${CMAKE_INSTALL_LIBDIR}/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}/site-packages"
    CACHE PATH "Install directory of the holoscan_{{ cookiecutter.module_slug }} Python package")
set(_python_install_var {{ cookiecutter.module_slug | upper }}_PYTHON_INSTALL_DIR)
set(_package_install "${${_python_install_var}}/${_package}")

foreach(package_file IN ITEMS __init__.py py.typed operators/__init__.py)
    configure_file("${_package}/${package_file}" "${_package_dir}/${package_file}" COPYONLY)
endforeach()

nanobind_add_module({{ cookiecutter.module_slug }}_python NB_STATIC STABLE_ABI
    _{{ cookiecutter.module_slug }}.cpp)
target_link_libraries({{ cookiecutter.module_slug }}_python PRIVATE
    holoscan::{{ cookiecutter.operator_slug }}
    holoscan::core)
file(RELATIVE_PATH _install_lib_relative "/${_package_install}" "/${CMAKE_INSTALL_LIBDIR}")
set_target_properties({{ cookiecutter.module_slug }}_python PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${_package_dir}"
    OUTPUT_NAME _{{ cookiecutter.module_slug }}
    INSTALL_RPATH "\$ORIGIN/${_install_lib_relative}"
    INSTALL_RPATH_USE_LINK_PATH TRUE)

set(_stub_files)
if(HOLOSCAN_PYTHON_STUBS)
    # Typed proxy stubs (operators/__init__.pyi) generated from the registry.
    holoscan_add_operator_stubs(
        TARGET {{ cookiecutter.module_slug }}_python_stubs
        ALL
        OUTPUT "${_package_dir}/operators/__init__.pyi"
        PROVIDER_MODULES ${_package}
        REGISTRY_PREFIX holoscan.{{ cookiecutter.module_slug }}.
        MODULE_DOC "Registered {{ cookiecutter.project_name }} operator proxies."
        PYTHON_EXECUTABLE "${Python_EXECUTABLE}"
        PYTHON_PATH "${_python_root}"
        EXTENSION_TARGETS {{ cookiecutter.module_slug }}_python)
    list(APPEND _stub_files "${_package_dir}/operators/__init__.pyi")
endif()

# A separate component, excluded from the default install and the Debian package:
#   cmake --install <build> --component {{ cookiecutter.module_repo_name }}-python
set(_component {{ cookiecutter.module_repo_name }}-python)
install(TARGETS {{ cookiecutter.module_slug }}_python
    LIBRARY DESTINATION "${_package_install}" COMPONENT ${_component} EXCLUDE_FROM_ALL)
install(FILES "${_package_dir}/__init__.py" "${_package_dir}/py.typed"
    DESTINATION "${_package_install}" COMPONENT ${_component} EXCLUDE_FROM_ALL)
install(FILES "${_package_dir}/operators/__init__.py" ${_stub_files}
    DESTINATION "${_package_install}/operators" COMPONENT ${_component} EXCLUDE_FROM_ALL)
