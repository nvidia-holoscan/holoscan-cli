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

"""Compatibility facade for ``holoscan_cli.utils.*``.

All implementation lives under :mod:`holoscan_cli.utils`. This module
re-exports the public surface so existing callers that wrote
``import holoscan_cli.util as holohub_cli_util`` and reached for
``holohub_cli_util.<foo>`` keep working unchanged.

New code should import from the canonical sub-module directly, e.g.:

* :mod:`holoscan_cli.utils.io`         — colors, ``run_command``, ``info``/``warn``/``fatal``
* :mod:`holoscan_cli.utils.text`       — string/version/env helpers
* :mod:`holoscan_cli.utils.sdk`        — SDK / GPU / CUDA detection
* :mod:`holoscan_cli.utils.docker`     — docker inspection + VS Code dev-container launcher
* :mod:`holoscan_cli.utils.host_setup` — apt + ``setup_*`` host setup helpers
* :mod:`holoscan_cli.utils.env_info`   — ``collect_*`` printers for ``env-info``
* :mod:`holoscan_cli.utils.holohub`    — HoloHub root/paths/prefix/placeholders + git tag helpers

The facade is part of the v1 public surface; do not remove it without a
deprecation cycle. Add new helpers to the appropriate sub-module above
and re-export them here only when an existing caller needs the alias.
"""

# ---- docker host inspection + VS Code launcher (utils/docker.py) ------------
from holoscan_cli.utils.docker import (  # noqa: F401
    docker_args_to_devcontainer_format,
    get_container_entrypoint,
    get_devcontainer_config,
    get_entrypoint_command_args,
    get_image_pythonpath,
    is_running_in_docker,
    launch_vscode,
    launch_vscode_devcontainer,
    open_url,
)

# ---- env-info collectors (utils/env_info.py) --------------------------------
from holoscan_cli.utils.env_info import (  # noqa: F401
    collect_cuda_gpu_info,
    collect_docker_info,
    collect_env_info,
    collect_environment_variables,
    collect_git_info,
    collect_holohub_info,
    collect_python_info,
    collect_sccache_info,
    collect_system_info,
)

# ---- HoloHub source-project paths / prefixes + git (utils/holohub.py) -------
from holoscan_cli.utils.holohub import (  # noqa: F401
    BUILD_TYPES,
    DEFAULT_GIT_REF,
    HOLOHUB_ROOT,
    PROJECT_PREFIXES,
    _get_holohub_root,
    build_holohub_path_mapping,
    check_skip_builds,
    determine_project_prefix,
    get_buildtype_str,
    get_component_search_paths,
    get_current_branch_slug,
    get_git_short_sha,
    get_group_id,
    get_holohub_root,
    get_holohub_setup_scripts_dir,
    get_sccache_dir,
    replace_placeholders,
    resolve_path_prefix,
    update_env,
)

# ---- apt-based package management + setup helpers (utils/host_setup.py) -----
from holoscan_cli.utils.host_setup import (  # noqa: F401
    PackageInstallationError,
    ensure_apt_updated,
    get_available_package_versions,
    get_installed_package_version,
    get_ubuntu_codename,
    install_cuda_dependencies_package,
    install_packages_if_missing,
    setup_cmake,
    setup_cuda_dependencies,
    setup_cuda_packages,
    setup_ngc_cli,
    setup_python_dev,
    setup_sccache,
)

# ---- terminal I/O + subprocess (utils/io.py) --------------------------------
from holoscan_cli.utils.io import (  # noqa: F401
    Color,
    _classify_sudo_requirement,
    _get_maybe_sudo,
    _process_command_with_sudo,
    fatal,
    format_cmd,
    format_long_command,
    get_timestamp,
    info,
    run_command,
    run_info_command,
    warn,
)

# ---- SDK / GPU / CUDA detection (utils/sdk.py) ------------------------------
from holoscan_cli.utils.sdk import (  # noqa: F401
    DEFAULT_BASE_SDK_VERSION,
    check_nvidia_ctk,
    cuda_major_from_driver,
    find_hsdk_build_rel_dir,
    get_arch_gpu_str,
    get_compute_capacity,
    get_cuda_runtime_version,
    get_cuda_tag,
    get_default_cuda_version,
    get_gpu_name,
    get_host_arch,
    get_host_gpu,
    get_sdk_version,
    is_valid_sdk_installation,
)

# ---- string / version / env parsing (utils/text.py) -------------------------
from holoscan_cli.utils.text import (  # noqa: F401
    _slugify,
    dir_size_mb,
    format_size,
    get_cli_arg_value,
    get_env_bool,
    levenshtein_distance,
    normalize_args_str,
    parse_semantic_version,
    relative_time,
)
