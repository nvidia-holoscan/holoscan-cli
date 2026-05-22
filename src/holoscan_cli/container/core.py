#!/usr/bin/env python3
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

import glob
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Union

from holoscan_cli.metadata.utils import list_normalized_languages

from ..utils.docker import get_image_pythonpath
from ..utils.holohub import (
    build_holohub_path_mapping,
    get_current_branch_slug,
    get_git_short_sha,
    get_group_id,
    get_holohub_root,
    get_holohub_setup_scripts_dir,
    get_sccache_dir,
    replace_placeholders,
)
from ..utils.io import fatal, info, run_command, warn
from ..utils.sdk import (
    DEFAULT_BASE_SDK_VERSION,
    check_nvidia_ctk,
    find_hsdk_build_rel_dir,
    get_arch_gpu_str,
    get_compute_capacity,
    get_cuda_tag,
    get_default_cuda_version,
    get_host_gpu,
    is_valid_sdk_installation,
)
from ..utils.text import get_cli_arg_value, get_env_bool
from .signals import (
    _ContainerTerminationHandler,
    _ContainerTerminationSignal,
    _read_container_id,
)

SCCACHE_CONTAINER_DIR = "/.cache/sccache"


class HoloscanContainer:
    """
    Describes the container environment for a HoloHub project.

    This class is responsible for common container operations and environment configuration,
    which may differ across different projects.

    Default attributes may be overridden by a project-specific implementation.
    """

    HOLOHUB_ROOT = get_holohub_root()  # Repository root directory
    # Primary repository prefix - sets defaults for container, workspace, and hostname
    REPO_PREFIX = os.environ.get("HOLOSCAN_CLI_REPO_PREFIX", "holohub")
    CONTAINER_PREFIX = os.environ.get("HOLOSCAN_CLI_CONTAINER_PREFIX", REPO_PREFIX)
    WORKSPACE_NAME = os.environ.get("HOLOSCAN_CLI_WORKSPACE_NAME", REPO_PREFIX)
    HOSTNAME_PREFIX = os.environ.get("HOLOSCAN_CLI_HOSTNAME_PREFIX", REPO_PREFIX.replace("_", "-"))

    # Docker and runtime configuration
    DOCKER_EXE = os.environ.get("HOLOSCAN_CLI_DOCKER_EXE", "docker")  # Docker executable

    # SDK and path configuration
    SDK_PATH = os.environ.get("HOLOSCAN_CLI_DEFAULT_HSDK_DIR", "/opt/nvidia/holoscan")
    BASE_SDK_VERSION = os.environ.get("HOLOSCAN_CLI_BASE_SDK_VERSION", DEFAULT_BASE_SDK_VERSION)
    BENCHMARKING_SUBDIR = os.environ.get(
        "HOLOSCAN_CLI_BENCHMARKING_SUBDIR", "benchmarks/holoscan_flow_benchmarking"
    )
    DEFAULT_DOCKERFILE = os.environ.get(
        "HOLOSCAN_CLI_DEFAULT_DOCKERFILE", HOLOHUB_ROOT / "Dockerfile"
    )

    # Image naming format templates
    BASE_IMAGE_NAME = os.environ.get(
        "HOLOSCAN_CLI_BASE_IMAGE", "nvcr.io/nvidia/clara-holoscan/holoscan"
    )
    BASE_IMAGE_FORMAT = os.environ.get(
        "HOLOSCAN_CLI_BASE_IMAGE_FORMAT", "{base_image}:v{sdk_version}-{cuda_tag}"
    )
    DEFAULT_IMAGE_FORMAT = os.environ.get(
        "HOLOSCAN_CLI_DEFAULT_IMAGE_FORMAT", "{container_prefix}:ngc-v{sdk_version}-{cuda_tag}"
    )
    # Additional Default build arguments for docker build command (e.g., --build-context flags)
    DEFAULT_DOCKER_BUILD_ARGS = os.environ.get("HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS", "")
    # Additional Default run arguments for docker run command
    DEFAULT_DOCKER_RUN_ARGS = os.environ.get("HOLOSCAN_CLI_DEFAULT_DOCKER_RUN_ARGS", "")
    DISPLAY_FORWARDING_DISABLED_MESSAGE = (
        "No DISPLAY or WAYLAND_DISPLAY set; skipping display forwarding."
    )

    @staticmethod
    def local_source_build_context_args() -> List[str]:
        """Docker build --build-context args for a local holoscan-cli checkout.

        Returns an empty list when ``HOLOSCAN_CLI_SOURCE`` is unset. When set,
        exposes the checkout as a named ``holoscan-cli-src`` build context so
        downstream Dockerfiles can mount it (``RUN --mount=from=holoscan-cli-src
        ...``) and pip-install the working tree instead of pulling from PyPI or
        git. Used during prototype validation to exercise an in-progress branch
        end-to-end without publishing it first.
        """
        source = os.environ.get("HOLOSCAN_CLI_SOURCE")
        if not source:
            return []
        return ["--build-context", f"holoscan-cli-src={source}"]

    @classmethod
    def default_base_image(cls, cuda_version: Optional[Union[str, int]] = None) -> str:
        return cls.BASE_IMAGE_FORMAT.format(
            base_image=cls.BASE_IMAGE_NAME,
            sdk_version=cls.BASE_SDK_VERSION,
            cuda_tag=get_cuda_tag(cuda_version, cls.BASE_SDK_VERSION),
        )

    @classmethod
    def default_image(cls, cuda_version: Optional[Union[str, int]] = None) -> str:
        return cls.DEFAULT_IMAGE_FORMAT.format(
            container_prefix=cls.CONTAINER_PREFIX,
            sdk_version=cls.BASE_SDK_VERSION,
            cuda_tag=get_cuda_tag(cuda_version, cls.BASE_SDK_VERSION),
        )

    @classmethod
    def default_dockerfile(cls) -> Path:
        return cls.DEFAULT_DOCKERFILE

    @staticmethod
    def ucx_args() -> List[str]:
        """UCX-related docker run arguments"""
        return [
            "--ipc=host",
            "--cap-add=CAP_SYS_PTRACE",
            "--ulimit=memlock=-1",
            "--ulimit=stack=67108864",
        ]

    @staticmethod
    def get_device_mounts() -> List[str]:
        """Get docker run arguments for mounting specialized hardware devices and libraries"""
        options = []

        for video_dev in glob.glob("/dev/video[0-9]*"):
            options.extend(["--device", video_dev])

        for capture_dev in glob.glob("/dev/capture-vi-channel[0-9]*"):
            options.extend(["--device", capture_dev])

        for video_dev in glob.glob("/dev/ajantv2[0-9]*"):
            options.extend(["--device", f"{video_dev}:{video_dev}"])

        # Deltacast capture boards and Videomaster SDK
        for i in range(4):
            # Deltacast SDI capture board
            delta_sdi = f"/dev/delta-x380{i}"
            if os.path.exists(delta_sdi):
                options.extend(["--device", f"{delta_sdi}:{delta_sdi}"])

            delta_sdi = f"/dev/delta-x370{i}"
            if os.path.exists(delta_sdi):
                options.extend(["--device", f"{delta_sdi}:{delta_sdi}"])

            # Deltacast HDMI capture board
            delta_hdmi = f"/dev/delta-x350{i}"
            if os.path.exists(delta_hdmi):
                options.extend(["--device", f"{delta_hdmi}:{delta_hdmi}"])

        # Find and mount all audio devices
        if os.path.isdir("/dev/snd"):
            # Only mount specific audio device patterns, exclude directories
            audio_patterns = [
                "/dev/snd/control*",
                "/dev/snd/pcm*",
                "/dev/snd/timer",
                "/dev/snd/seq",
                "/dev/snd/midi*",
            ]
            for pattern in audio_patterns:
                for audio_dev in glob.glob(pattern):
                    try:
                        # Check if it's a character device using stat module
                        if stat.S_ISCHR(os.stat(audio_dev).st_mode):
                            options.extend(["--device", audio_dev])
                    except OSError:
                        continue

        # Mount ALSA configuration
        if os.path.exists("/etc/asound.conf"):
            options.extend(
                ["--mount", "source=/etc/asound.conf,target=/etc/asound.conf,readonly,type=bind"]
            )

        # Mount ConnectX device nodes
        if os.path.exists("/dev/infiniband/rdma_cm"):
            options.extend(["--device", "/dev/infiniband/rdma_cm"])

        for uverbs_dev in glob.glob("/dev/infiniband/uverbs[0-9]*"):
            options.extend(["--device", uverbs_dev])

        conditional_mounts = [
            "/usr/local/cmake/VideoMasterHDConfigVersion.cmake",
            "/usr/local/cmake/VideoMasterHDConfig.cmake",
            "/usr/lib/libvideomasterhd.so",
            "/usr/lib/libvideomasterhd_audio.so",
            "/usr/lib/libvideomasterhd_vbi.so",
            "/usr/lib/libvideomasterhd_vbidata.so",
            "/usr/include/videomaster",
            "/opt/yuan/qcap/include",
            "/opt/yuan/qcap/lib",
            "/usr/lib/aarch64-linux-gnu/tegra",
            "/usr/lib/aarch64-linux-gnu/nvidia",
        ]

        for path in conditional_mounts:
            if os.path.exists(path):
                options.extend(["-v", f"{path}:{path}"])

        if os.path.exists("/dev/nvgpu/igpu0/nvsched"):
            options.extend(["--device", "/dev/nvgpu/igpu0/nvsched"])
        if os.path.exists("/dev/nvhost-ctrl-nvdec"):
            options.extend(["--device", "/dev/nvhost-ctrl-nvdec"])
        if os.path.exists("/dev/nvhost-ctxsw-gpu"):
            options.extend(["--device", "/dev/nvhost-ctxsw-gpu"])
        if os.path.exists("/dev/nvhost-nvsched-gpu"):
            options.extend(["--device", "/dev/nvhost-nvsched-gpu"])
        if os.path.exists("/dev/nvhost-sched-gpu"):
            options.extend(["--device", "/dev/nvhost-sched-gpu"])
        if os.path.exists("/dev/nvidia-modeset"):
            options.extend(["--device", "/dev/nvidia-modeset"])
        if os.path.exists("/usr/share/nvidia/nvoptix.bin"):
            options.extend(["-v", "/usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro"])
        return options

    @staticmethod
    def group_args() -> List[str]:
        """Get docker run arguments for adding groups to the container"""
        options = []
        for group in ["video", "render", "docker", "audio"]:
            gid = get_group_id(group)
            if gid is None:
                continue
            options.extend(["--group-add", str(gid)])
        return options

    def get_conditional_options(
        self, use_tini: bool = False, persistent: bool = False
    ) -> List[str]:
        options = []
        if use_tini:
            options.append("--init")
        if not persistent:
            options.append("--rm")
        return options

    @property
    def image_name(self) -> str:
        if self.dockerfile_path != HoloscanContainer.default_dockerfile():
            project_tag = self.get_project_name()
            if project_tag:
                return f"{self.CONTAINER_PREFIX}:{project_tag}"
            return self.CONTAINER_PREFIX
        return HoloscanContainer.default_image(self.cuda_version)

    @property
    def image_names(self) -> List[str]:
        """Return list of image tags to apply: branch-tag, sha-tag, and legacy tag."""
        project = self.get_project_name()
        repo = f"{self.CONTAINER_PREFIX}-{project}" if project else self.CONTAINER_PREFIX
        sha_tag = f"{repo}:{get_git_short_sha()}"
        branch_tag = f"{repo}:{get_current_branch_slug()}"
        legacy_tag = self.image_name
        # Deduplicate while preserving order.
        seen = set()
        result = []
        for tag in [branch_tag, sha_tag, legacy_tag]:
            if tag and tag not in seen:
                result.append(tag)
                seen.add(tag)
        return result

    @property
    def dockerfile_path(self) -> Path:
        """
        Get Dockerfile path for the project according to the search strategy:
        1. As specified in metadata.json
        2. <app_source>/<language>/Dockerfile
        3. <app_source>/Dockerfile
        4. <app_source>/../Dockerfile (traverse up to HOLOHUB_ROOT)
        5. `HOLOSCAN_CLI_DEFAULT_DOCKERFILE` env variable
        6. `<HOLOHUB_ROOT>/Dockerfile`
        """
        if not self.project_metadata:
            return HoloscanContainer.default_dockerfile()

        # Strategy 1: Check metadata for explicit dockerfile path
        dockerfile_from_metadata = self.project_metadata.get("metadata", {}).get("dockerfile")
        if dockerfile_from_metadata:
            # Build path mapping for this project
            path_mapping = build_holohub_path_mapping(
                holohub_root=HoloscanContainer.HOLOHUB_ROOT,
                project_data=self.project_metadata,
            )

            dockerfile_str = replace_placeholders(dockerfile_from_metadata, path_mapping)
            dockerfile = Path(dockerfile_str)

            # If the path is not absolute, make it relative to HOLOHUB_ROOT
            if not dockerfile.is_absolute():
                dockerfile = HoloscanContainer.HOLOHUB_ROOT / dockerfile

            # Validate that the Dockerfile exists
            if dockerfile.exists():
                return dockerfile
            else:
                warn(
                    f"Dockerfile specified in metadata.json not found: {dockerfile}\n"
                    "Falling back to default Dockerfile search strategy."
                )

        # Strategy 2-4: Search in source_folder hierarchy
        source_folder = self.project_metadata.get("source_folder")
        if source_folder:
            source_folder = Path(source_folder).resolve()

            # Strategy 2: Check language-specific Dockerfile
            dockerfile_path = source_folder / self.language / "Dockerfile"
            if dockerfile_path.exists():
                return dockerfile_path

            # Strategy 3: Check Dockerfile in source folder
            dockerfile_path = source_folder / "Dockerfile"
            if dockerfile_path.exists():
                return dockerfile_path

            # Strategy 4: Traverse up parent directories to HOLOHUB_ROOT
            for parent in source_folder.parents:
                # Stop at the root directory
                if parent == HoloscanContainer.HOLOHUB_ROOT:
                    break
                dockerfile_path = parent / "Dockerfile"
                if dockerfile_path.exists():
                    return dockerfile_path

        # Strategy 5-6: Fall back to default Dockerfile
        return HoloscanContainer.default_dockerfile()

    def get_project_name(self) -> str:
        """Return docker-safe project name."""
        project_name = (self.project_metadata or {}).get("project_name", "")
        if not project_name:
            return ""
        sanitized = project_name.lower()
        sanitized = re.sub(r"[^a-z0-9._-]", "-", sanitized)
        sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
        sanitized = re.sub(r"^[^a-z0-9]+", "", sanitized)  # Docker tags must start alnum
        return sanitized or ""

    def __init__(self, project_metadata: Optional[dict[str, Any]], language: Optional[str] = None):
        if not isinstance(project_metadata, dict):
            print("No project provided, proceeding with default container")

        self.project_metadata = project_metadata
        # Get first language from project metadata if not provided.
        if language is None and self.project_metadata:
            language = self.project_metadata.get("metadata", {}).get("language", "")
        self.language = list_normalized_languages(language, strict=True)[0]

        self.cuda_version = None  # None means use default from get_cuda_tag
        self.dryrun = False
        self.verbose = False
        self._display_temp_files: List[Path] = []

    def build(
        self,
        docker_file: Optional[str] = None,
        base_img: Optional[str] = None,
        img: Optional[str] = None,
        no_cache: bool = False,
        build_args: Optional[str] = None,
        extra_scripts: Optional[List[str]] = None,
        cuda_version: Optional[Union[str, int]] = None,
    ) -> None:
        """
        Build the container image according to the procedure:

        1. Build the Dockerfile provided environment with the given BASE_IMAGE and given tag.
            If extra_scripts are provided, also tag this image as {img}-base.
        2. If extra_scripts are provided, build an additional Docker layer for each script.
            Tag each iterative layer as {img}-{script} and {img}.

        Result: Docker image named {img} based on the Dockerfile and any additional scripts.
        """

        if cuda_version is not None:
            self.cuda_version = cuda_version

        # Get Dockerfile path
        docker_file_path = docker_file or self.dockerfile_path
        base_img = base_img or self.default_base_image(self.cuda_version)
        tags = [img] if img else self.image_names
        gpu_type = get_host_gpu()
        compute_capacity = get_compute_capacity()

        cuda_major = (
            self.cuda_version if self.cuda_version is not None else get_default_cuda_version()
        )

        # Check if buildx exists
        if not self.dryrun:
            try:
                run_command([self.DOCKER_EXE, "buildx", "version"], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                fatal(
                    "docker buildx plugin is missing. Please install docker-buildx-plugin:\n"
                    "https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository"
                )

        # Set DOCKER_BUILDKIT environment variable
        os.environ["DOCKER_BUILDKIT"] = "1"

        cmd = [
            self.DOCKER_EXE,
            "build",
            "--build-arg",
            "BUILDKIT_INLINE_CACHE=1",
            "--build-arg",
            f"BASE_IMAGE={base_img}",
            "--build-arg",
            f"GPU_TYPE={gpu_type}",
            "--build-arg",
            f"BASE_SDK_VERSION={self.BASE_SDK_VERSION}",
            "--build-arg",
            f"COMPUTE_CAPACITY={compute_capacity}",
            "--build-arg",
            f"CUDA_MAJOR={cuda_major}",
            "--network=host",
        ]

        if no_cache:
            cmd.append("--no-cache")

        cmd.extend(self.local_source_build_context_args())

        full_build_args = " ".join(
            filter(None, [HoloscanContainer.DEFAULT_DOCKER_BUILD_ARGS, build_args])
        )
        if full_build_args:
            cmd.extend(shlex.split(full_build_args))

        cmd.extend(["-f", str(docker_file_path)])
        for tag_name in tags:
            cmd.extend(["-t", tag_name])
        if extra_scripts:
            # Tag the base (pre-scripts) image for all tags for consistency
            for tag_name in tags:
                cmd.extend(["-t", f"{tag_name}-base"])
        cmd.append(str(HoloscanContainer.HOLOHUB_ROOT))

        run_command(cmd, dry_run=self.dryrun)

        if extra_scripts:
            for script in extra_scripts:
                script_path = get_holohub_setup_scripts_dir() / f"{script}.sh"
                if not script_path.exists():
                    fatal(f"Script {script}.sh not found in {get_holohub_setup_scripts_dir()}")
                try:
                    relative_script_path = script_path.relative_to(HoloscanContainer.HOLOHUB_ROOT)
                except ValueError:
                    fatal(
                        f"Script {script}.sh at {script_path} is not within {HoloscanContainer.HOLOHUB_ROOT}. "
                        f"The HOLOSCAN_CLI_SETUP_SCRIPTS_DIR environment variable must resolve to a subdirectory within the project scope."
                    )
                cmd = [
                    self.DOCKER_EXE,
                    "build",
                    "--build-arg",
                    "BUILDKIT_INLINE_CACHE=1",
                    "--build-arg",
                    f"BASE_IMAGE={tags[0]}",  # reuse the default tag to sequentially add the scripts on top of each other.
                    "--network=host",
                    "--build-arg",
                    f"SCRIPT={relative_script_path}",
                    "-f",
                    str(get_holohub_setup_scripts_dir() / "Dockerfile.util"),
                    str(HoloscanContainer.HOLOHUB_ROOT),
                ]
                for tag_name in tags:
                    # We override the default tag so we can add the next scripts on top of this.
                    cmd.extend(["-t", f"{tag_name}-{script}", "-t", f"{tag_name}"])
                run_command(cmd, dry_run=self.dryrun)

    def run(
        self,
        img: Optional[str] = None,
        local_sdk_root: Optional[Path] = None,
        enable_x11: bool = True,
        ssh_x11: bool = False,
        use_tini: bool = False,
        persistent: bool = False,
        nsys_profile: bool = False,
        nsys_location: str = "",
        as_root: bool = False,
        docker_opts: str = "",
        add_volumes: List[str] = None,
        enable_mps: bool = False,
        extra_args: List[str] = None,
    ) -> None:
        """Launch the container"""

        if not self.dryrun:
            check_nvidia_ctk()

        if local_sdk_root is not None:
            local_sdk_root = Path(local_sdk_root)

        img = img or self.image_names[0]
        add_volumes = add_volumes or []
        extra_args = extra_args or []

        # If the caller already supplies --cidfile (via DEFAULT_DOCKER_RUN_ARGS or
        # docker_opts), use that path for cleanup and skip injecting our own —
        # Docker rejects duplicate --cidfile flags.
        default_run_args = shlex.split(HoloscanContainer.DEFAULT_DOCKER_RUN_ARGS or "")
        extra_run_args = shlex.split(docker_opts or "")
        explicit_cidfile = get_cli_arg_value(default_run_args + extra_run_args, "--cidfile")
        internal_cidfile: Optional[Path] = None
        if explicit_cidfile:
            cidfile = Path(explicit_cidfile)
        else:
            internal_cidfile = Path(tempfile.gettempdir()) / f"holohub-container-{os.getpid()}.cid"
            cidfile = internal_cidfile

        cmd = [self.DOCKER_EXE, "run"]

        cmd.extend(self.get_basic_args())
        if internal_cidfile is not None:
            cmd.extend(["--cidfile", str(internal_cidfile)])
        cmd.extend(self.get_security_args(as_root))
        cmd.extend(self.get_volume_args(add_volumes, enable_mps))
        cmd.extend(self.get_gpu_runtime_args())
        cmd.extend(self.get_environment_args())

        cmd.extend(self.get_conditional_options(use_tini, persistent))
        cmd.extend(self.ucx_args())
        cmd.extend(self.get_device_mounts())
        cmd.extend(self.group_args())
        self._display_temp_files = []
        cmd.extend(self.get_display_options(enable_x11, ssh_x11))
        cmd.extend(self.get_nsys_options(nsys_profile, nsys_location))
        cmd.extend(self.get_pythonpath_options(local_sdk_root, img))
        cmd.extend(self.get_ngc_options())

        if local_sdk_root or os.environ.get("HOLOSCAN_SDK_ROOT"):
            cmd.extend(self.get_local_sdk_options(local_sdk_root))

        # Default docker run arguments and caller-supplied docker_opts (parsed above).
        cmd.extend(default_run_args)
        cmd.extend(extra_run_args)

        cmd.append(img)
        cmd.extend(extra_args)

        if self.verbose:
            cmd_list = [f'"{arg}"' if " " in str(arg) else str(arg) for arg in cmd]
            print(f"Launch command: {' '.join(cmd_list)}")

        try:
            if self.dryrun:
                run_command(cmd, dry_run=self.dryrun)
                return

            # Docker refuses to start if --cidfile already exists; clear stale internal
            # files left by a prior crashed run that happened to share this PID. Caller-
            # provided cidfiles are the caller's responsibility — never remove them.
            if internal_cidfile is not None:
                internal_cidfile.unlink(missing_ok=True)

            try:
                try:
                    with _ContainerTerminationHandler():
                        run_command(cmd)
                    return
                except _ContainerTerminationSignal as exc:
                    sig = exc.signum

                try:
                    signal_name = signal.Signals(sig).name
                except ValueError:
                    signal_name = str(sig)
                container_id = _read_container_id(cidfile)
                if container_id:
                    warn(f"Received {signal_name}; stopping HoloHub container {container_id}")
                    subprocess.run(
                        [self.DOCKER_EXE, "stop", "--time", "10", container_id],
                        check=False,
                        stdout=subprocess.DEVNULL,
                    )
                else:
                    warn(
                        f"Received {signal_name}; no container ID was written to {cidfile} yet — "
                        "the container may still be starting. Run `docker ps` to check and stop it manually."
                    )
                # os.kill below may terminate the process before the outer `finally`
                # blocks run, so unlink the cidfile and clean display temp files here.
                if internal_cidfile is not None:
                    internal_cidfile.unlink(missing_ok=True)
                self._cleanup_display_temp_files()
                # Re-raise via default handler so we exit with the conventional 128+N status.
                signal.signal(sig, signal.SIG_DFL)
                os.kill(os.getpid(), sig)
                sys.exit(128 + sig)
            finally:
                if internal_cidfile is not None:
                    internal_cidfile.unlink(missing_ok=True)
        finally:
            self._cleanup_display_temp_files()

    def get_basic_args(self) -> List[str]:
        """Basic container runtime arguments"""
        args = ["--net", "host", "--interactive"]
        if sys.stdout.isatty():
            args.append("--tty")
        return args

    def get_security_args(self, as_root: bool) -> List[str]:
        """User and security arguments"""
        args = []

        if not as_root:
            args.extend(["-u", f"{os.getuid()}:{os.getgid()}"])

        args.extend(["-v", "/etc/group:/etc/group:ro", "-v", "/etc/passwd:/etc/passwd:ro"])

        return args

    def get_volume_args(self, add_volumes: List[str], enable_mps: bool) -> List[str]:
        """Volume mounting arguments"""
        args = []

        args.extend(
            [
                "-v",
                f"{HoloscanContainer.HOLOHUB_ROOT}:/workspace/{self.WORKSPACE_NAME}",
                "-w",
                f"/workspace/{self.WORKSPACE_NAME}",
            ]
        )

        for volume in add_volumes:
            volume = os.path.abspath(volume)
            base = os.path.basename(volume)
            args.extend(["-v", f"{volume}:/workspace/volumes/{base}"])

        if enable_mps:
            if os.path.isdir("/tmp/nvidia-mps") and os.path.isdir("/tmp/nvidia-log"):
                args.extend(
                    [
                        "-v",
                        "/tmp/nvidia-mps:/tmp/nvidia-mps",
                        "-v",
                        "/tmp/nvidia-log:/tmp/nvidia-log",
                    ]
                )
            else:
                print("Warning: MPS directories not found. MPS may not be enabled on the host.")

        # sccache mounting
        _, enable_sccache = get_env_bool("HOLOSCAN_CLI_ENABLE_SCCACHE", default=False)
        has_host_sccache_env = any(k.startswith("SCCACHE_") for k in os.environ)
        if enable_sccache:
            sccache_host_dir = get_sccache_dir()
            info(f"Host SCCACHE_DIR: {sccache_host_dir}")
            info(f"Container mount point: {SCCACHE_CONTAINER_DIR}")
            os.makedirs(sccache_host_dir, exist_ok=True)  # Pre-create for the current user to own
            args.extend(["-v", f"{sccache_host_dir}:{SCCACHE_CONTAINER_DIR}"])
        elif has_host_sccache_env:
            warn(
                "SCCACHE_* environment variables detected but HOLOSCAN_CLI_ENABLE_SCCACHE is "
                "disabled; not mounting sccache cache into the container."
            )
        return args

    def get_nvidia_runtime_args(self) -> List[str]:
        return ["--runtime", "nvidia"]

    def get_device_cgroup_args(self) -> List[str]:
        return [
            "--device-cgroup-rule",
            "c 81:* rmw",  # /dev/video*
            "--device-cgroup-rule",
            "c 189:* rmw",  # /dev/bus/usb/*
        ]

    def get_gpu_runtime_args(self) -> List[str]:
        args = []
        args.extend(self.get_nvidia_runtime_args())
        args.extend(
            [
                "--cap-add",
                "CAP_SYS_PTRACE",
                "--ipc=host",
                "-v",
                "/dev:/dev",
            ]
        )
        args.extend(self.get_device_cgroup_args())
        return args

    def get_environment_args(self) -> List[str]:
        """Environment variable arguments"""
        # Default GPU visibility is controlled via NVIDIA_VISIBLE_DEVICES (from the image and/or
        # environment args). This keeps the default behavior ("all") while allowing users to
        # override with `--gpus=...` or CDI `--device nvidia.com/gpu=...` in `--docker-opts`.
        nvidia_visible_devices = os.environ.get("NVIDIA_VISIBLE_DEVICES", "all")
        args = [
            "-e",
            "NVIDIA_DRIVER_CAPABILITIES=graphics,video,compute,utility,display",
            "-e",
            f"NVIDIA_VISIBLE_DEVICES={nvidia_visible_devices}",
            "-e",
            f"HOME=/workspace/{self.WORKSPACE_NAME}",
            "-e",
            f"CUPY_CACHE_DIR=/workspace/{self.WORKSPACE_NAME}/.cupy/kernel_cache",
            "-e",
            "HOLOSCAN_CLI_BUILD_LOCAL=1",
        ]
        # Pass CMAKE_BUILD_PARALLEL_LEVEL to container if set on host
        cmake_parallel_level = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL")
        if cmake_parallel_level:
            args.extend(["-e", f"CMAKE_BUILD_PARALLEL_LEVEL={cmake_parallel_level}"])
        # Forward host-side wrapper customizations that the in-container CLI needs
        # to reproduce project discovery and command routing decisions.
        for new_name in (
            "HOLOSCAN_CLI_PATH_PREFIX",
            "HOLOSCAN_CLI_SEARCH_PATH",
            "HOLOSCAN_CLI_CTEST_SCRIPT",
        ):
            value = os.environ.get(new_name)
            if value:
                args.extend(["-e", f"{new_name}={value}"])

        # Pass adequate variables for SCCACHE
        _, enable_sccache = get_env_bool("HOLOSCAN_CLI_ENABLE_SCCACHE", default=False)
        sccache_keys = [k for k in os.environ if k.startswith("SCCACHE_")]
        if enable_sccache:
            # Forward HOLOSCAN_CLI_ENABLE_SCCACHE so the in-container launcher
            # enables sccache before cmake build.
            args.extend(["-e", "HOLOSCAN_CLI_ENABLE_SCCACHE"])
            # Always set SCCACHE_DIR inside container to mounted path
            args.extend(["-e", f"SCCACHE_DIR={SCCACHE_CONTAINER_DIR}"])
            # Forward other SCCACHE_* environment variables present on host
            for k in sccache_keys:
                if k != "SCCACHE_DIR":
                    args.extend(["-e", k])
        elif len(sccache_keys) > 0:
            warn(
                "SCCACHE_* environment variables detected but HOLOSCAN_CLI_ENABLE_SCCACHE is "
                "disabled; not forwarding sccache environment variables into the container: "
                f"{', '.join(sccache_keys)}"
            )
        return args

    def get_display_options(self, enable_x11: bool, ssh_x11: bool) -> List[str]:
        """Get display-related Docker options from DISPLAY and WAYLAND_DISPLAY."""
        options = []
        del enable_x11, ssh_x11

        display = os.environ.get("DISPLAY")
        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        if not display and not wayland_display:
            info(self.DISPLAY_FORWARDING_DISABLED_MESSAGE)
            return options

        if os.environ.get("XDG_SESSION_TYPE"):
            options.extend(["-e", "XDG_SESSION_TYPE"])

        # Required by Vulkan, dconf, pipewire, etc. on both X11 and Wayland.
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir and Path(runtime_dir).is_dir():
            options.extend(["-e", "XDG_RUNTIME_DIR", "-v", f"{runtime_dir}:{runtime_dir}"])

        if wayland_display:
            options.extend(["-e", "WAYLAND_DISPLAY"])

        if display:
            if Path("/tmp/.X11-unix").is_dir() and not self._is_ssh_x11_display(display):
                options.extend(["-v", "/tmp/.X11-unix:/tmp/.X11-unix:ro"])
            options.extend(["-e", "DISPLAY"])
            options.extend(self._get_xauth_options(display))

        return options

    @staticmethod
    def _is_ssh_x11_display(display: str) -> bool:
        return display.startswith(("localhost:", "127.0.0.1:", "[::1]:", "::1:"))

    def _get_xauth_options(self, display: str) -> List[str]:
        if not shutil.which("xauth"):
            warn(
                "xauth not found on host; install xauth (or x11-xauth) so X11 "
                "applications can authenticate inside the container."
            )
            return []

        if self.dryrun:
            placeholder = "/tmp/.docker.xauth"
            return ["-v", f"{placeholder}:{placeholder}:ro", "-e", f"XAUTHORITY={placeholder}"]

        result = run_command(
            ["xauth", "nlist", display],
            check=False,
            capture_output=True,
            text=True,
            dry_run=self.dryrun,
        )
        if result.returncode != 0 or not result.stdout:
            warn(
                f"xauth nlist returned no entries for DISPLAY={display}; "
                "X11 may not authenticate inside the container."
            )
            return []

        xauth_fd, xauth_file = tempfile.mkstemp(prefix=".docker.xauth-")
        os.close(xauth_fd)
        xauth_path = Path(xauth_file)

        xauth_entries = "".join(
            f"ffff{line[4:]}" for line in result.stdout.splitlines(keepends=True) if len(line) >= 4
        )
        merge_result = run_command(
            ["xauth", "-f", str(xauth_path), "nmerge", "-"],
            check=False,
            input=xauth_entries,
            text=True,
            dry_run=self.dryrun,
        )
        if merge_result.returncode != 0:
            xauth_path.unlink(missing_ok=True)
            warn(
                f"xauth nmerge failed for DISPLAY={display}; "
                "X11 may not authenticate inside the container."
            )
            return []

        self._display_temp_files.append(xauth_path)
        return ["-v", f"{xauth_path}:{xauth_path}:ro", "-e", f"XAUTHORITY={xauth_path}"]

    def _cleanup_display_temp_files(self) -> None:
        for path in self._display_temp_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # Suppress I/O errors so cleanup doesn't mask the original exception.
                pass
        self._display_temp_files.clear()

    def get_ngc_options(self) -> List[str]:
        """Get NGC-related options"""
        options = []
        if os.environ.get("NGC_CLI_API_KEY"):
            options.extend(["-e", "NGC_CLI_API_KEY"])
        if os.environ.get("NGC_CLI_ORG"):
            options.extend(["-e", "NGC_CLI_ORG"])
        if os.environ.get("NGC_CLI_TEAM"):
            options.extend(["-e", "NGC_CLI_TEAM"])
        # If NGC_CLI_API_KEY is set, the org is required even for public resources
        # Thus, set a default org if NGC_CLI_ORG is not set.
        if os.environ.get("NGC_CLI_API_KEY") and not os.environ.get("NGC_CLI_ORG"):
            options.extend(["-e", "NGC_CLI_ORG=nvidia"])
        return options

    def get_nsys_options(self, nsys_profile: bool, nsys_location: str) -> List[str]:
        """Get nsys-related options"""
        options = []
        if nsys_profile:
            options.extend(["--cap-add=SYS_ADMIN"])
        if nsys_location:
            options.extend(["-v", f"{nsys_location}:/opt/nvidia/nsys-host"])
        return options

    def get_pythonpath_options(
        self, local_sdk_root: Optional[Union[str, Path]], img: Optional[str] = None
    ) -> List[str]:
        """Build the PYTHONPATH docker environment flag for the container.

        Merges paths from three sources (SDK python lib, benchmarking dir, and
        any paths already baked into the Docker image) into a single,
        deduplicated PYTHONPATH value.

        When a local SDK is in use (via *local_sdk_root* or ``HOLOSCAN_SDK_ROOT``),
        its paths are placed **before** the image paths so the locally-built
        ``holoscan`` package is imported instead of the one shipped in the base image.
        """
        using_local_sdk = bool(local_sdk_root or os.environ.get("HOLOSCAN_SDK_ROOT"))
        benchmarking_path = f"/workspace/{self.WORKSPACE_NAME}/{self.BENCHMARKING_SUBDIR}"

        # Resolve SDK python/lib path
        if using_local_sdk:
            sdk_dir = find_hsdk_build_rel_dir(local_sdk_root)
            root = Path(local_sdk_root) if local_sdk_root else Path(os.environ["HOLOSCAN_SDK_ROOT"])
            if not Path(sdk_dir).is_absolute() and not is_valid_sdk_installation(root / sdk_dir):
                arch_gpu = get_arch_gpu_str()
                info(
                    f"Valid SDK installation not found."
                    f" Looking for 'install-{arch_gpu}' or 'build-{arch_gpu}'."
                )
            if Path(sdk_dir).is_absolute():
                sdk_python_lib = "/workspace/holoscan-sdk/python/lib"
            else:
                sdk_python_lib = f"/workspace/holoscan-sdk/{sdk_dir}/python/lib"
        else:
            sdk_python_lib = f"{self.SDK_PATH}/python/lib"

        image_paths = []
        if img:
            image_pythonpath = get_image_pythonpath(img, self.dryrun)
            if image_pythonpath:
                image_paths = [p for p in image_pythonpath.split(":") if p]

        # Local SDK paths first (if configured);
        # then image paths (preserving upstream defaults) and benchmarking path.
        if using_local_sdk:
            primary, secondary = [sdk_python_lib], image_paths
        else:
            primary, secondary = image_paths, [sdk_python_lib]

        all_paths = list(primary)
        all_paths.extend(p for p in secondary if p not in all_paths)
        if benchmarking_path not in all_paths:
            all_paths.append(benchmarking_path)
        return ["-e", f"PYTHONPATH={':'.join(all_paths)}"]

    def get_local_sdk_options(self, local_sdk_root: Optional[Union[str, Path]]) -> List[str]:
        """Get Holoscan SDK-related options"""
        if local_sdk_root is None:
            env_root = os.environ.get("HOLOSCAN_SDK_ROOT")
            if not env_root:
                fatal(
                    "Local Holoscan SDK root is not specified. "
                    "Please provide --local-sdk-root or set the HOLOSCAN_SDK_ROOT environment variable."
                )
            local_sdk_root = Path(env_root)
        else:
            local_sdk_root = Path(local_sdk_root)
        build_dir = find_hsdk_build_rel_dir(local_sdk_root)
        if not Path(build_dir).is_absolute() and not is_valid_sdk_installation(
            local_sdk_root / build_dir
        ):
            arch_gpu = get_arch_gpu_str()
            info(
                f"Valid SDK installation not found."
                f" Looking for 'install-{arch_gpu}' or 'build-{arch_gpu}'."
            )
        if Path(build_dir).is_absolute():
            lib_path = "/workspace/holoscan-sdk/lib"
        else:
            lib_path = f"/workspace/holoscan-sdk/{build_dir}/lib"
        return [
            "-v",
            f"{local_sdk_root}:/workspace/holoscan-sdk",
            "-e",
            f"HOLOSCAN_LIB_PATH={lib_path}",
            "-e",
            "HOLOSCAN_SAMPLE_DATA_PATH=/workspace/holoscan-sdk/data",
            "-e",
            "HOLOSCAN_TESTS_DATA_PATH=/workspace/holoscan-sdk/tests/data",
        ]
