#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#===============================================================================
set -u
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

if ! ./check.sh
then
    exit 1
fi

ci_package_args=${ci_package_args:-}
ci_run_args=${ci_run_args:-}

test=$(realpath $1)
repository=""
path=""
language=""
tmp_dir=""
tag=""

artifact_source_path=${ARTIFACT_PATH:-}
version=${VERSION:-}

#===============================================================================
# Logging utils
#===============================================================================

c_str() {
    local old_color=39
    local old_attr=0
    local color=39
    local attr=0
    local text=""
    local mode="color"
    if [ "${1:-}" = "color" ]; then
        mode="color"
        shift
    elif [ "${1:-}" = "nocolor" ]; then
        mode="nocolor"
        shift
    fi

    for i in "$@"; do
        case "$i" in
            r|R)
                color=31
                ;;
            g|G)
                color=32
                ;;
            y|Y)
                color=33
                ;;
            b|B)
                color=34
                ;;
            p|P)
                color=35
                ;;
            c|C)
                color=36
                ;;
            w|W)
                color=37
                ;;

            z|Z)
                color=0
                ;;
        esac
        case "$i" in
            l|L|R|G|Y|B|P|C|W)
                attr=1
                ;;
            n|N|r|g|y|b|p|c|w)
                attr=0
                ;;
            z|Z)
                attr=0
                ;;
            *)
                text="${text}$i"
        esac
        if [ "${mode}" = "color" ]; then
            if [ ${old_color} -ne ${color} ] || [ ${old_attr} -ne ${attr} ]; then
                text="${text}\033[${attr};${color}m"
                old_color=$color
                old_attr=$attr
            fi
        fi
    done
    /bin/echo -en "$text"
}

c_echo() {
    # Select color/nocolor based on the first argument
    local mode="color"
    if [ "${1:-}" = "color" ]; then
        mode="color"
        shift
    elif [ "${1:-}" = "nocolor" ]; then
        mode="nocolor"
        shift
    else
        if [ ! -t 1 ]; then
            mode="nocolor"
        fi
    fi

    local old_opt="$(shopt -op xtrace)" # save old xtrace option
    set +x # unset xtrace

    if [ "${mode}" = "color" ]; then
        local text="$(c_str color "$@")"
        /bin/echo -e "$text\033[0m"
    else
        local text="$(c_str nocolor "$@")"
        /bin/echo -e "$text"
    fi
    eval "${old_opt}" # restore old xtrace option
}


cecho() {
    >&2 c_echo "$@"
}

info() {
    cecho B "$(date -u '+%Y-%m-%d %H:%M:%S') [INFO] " Z "$@"
}

error() {
    cecho R "$(date -u '+%Y-%m-%d %H:%M:%S') [ERROR] " Z "$@"
}

fatal() {
    if [ -n "$*" ]; then
        cecho R "$(date -u '+%Y-%m-%d %H:%M:%S') [FATAL] " Z "$@"
        echo_err
    fi
    if [ -z "${CALLER-}" ]; then
        return 1
    else
        kill -INT $$  # kill the current process instead of exit in shell environment.
    fi
}

#===============================================================================

# Parameters
#  $1 Exit Code
#  $2 Error Message
#  $3 Exit if true
#  $4 Function to call if exit code is not 0
check_exit_code() {
    if [[ $1 -ne 0 ]]
    then
        error "$2"
        if [ -n "$4" ]
        then
            $4
        fi
        if [ -n "$3" -a "$3" -eq 1 ]
        then
            exit $1
        fi
    fi
}

# Executes a specified command via bash shell
# Parameters
#  $@ accept any number of parameters
run_command() {
    local status=0
    local cmd="$*"

    info "[command] ${cmd}"

    [ "$(echo -n "$@")" = "" ] && return 1 # return 1 if there is no command available

    "$@"
    status=$?
    info "[command] exited with status: ${status}"
    return $status
}

# Parse the specified JSON Path from the configuration file
# Returns empty string if JSON path does not exist.
get_config() {
    value=$(jq -r "$1" $test)
    if [[ "$value" == "null" ]]
    then
        value=""
    fi
    echo $value
}

# Run the HAP container using Holoscan CLI Runner
# Parameters
#  $1 Container Tag Prefix
run_application() {
    info "===== Run Application ====="
    run_args=$(get_config '.run.args')
    tag_prefix=$1
    local tag=$(docker images | grep "$tag_prefix" | awk '{print $1":"$2}' | head -n 1)
    info "Running application"
    info "  Tag: $tag"
    run_command xhost +local:docker
    run_command holoscan run -l DEBUG $run_args $tag $ci_run_args
    check_exit_code $? "Failed to run the application" 1 clean_up
}

# Download user defined data.
#  NOTE: Only NGC is supported at the moment: the script parses the JSON returned by the NGC files API.
#  E.g. https://api.ngc.nvidia.com/v2/resources/org/nvidia/team/clara-holoscan/holoscan_racerx_video/20231009/files
# Parameters
#  $1 Path to save the data to
download_data() {
    info "===== Download Data ====="
    local source=$(get_config '.data.source')
    local target=$(get_config '.data.dirname')
    echo "Downloading data from $source to $target"

    ## return if no data to download
    if [ -z "$source" ]
    then
        info "No data to download"
        return
    fi

    if [[ "$source" != "local-holohub" ]]
    then
        local data_dir=$1
        if [ -v target ]
        then
            data_dir="$data_dir/$target"
        fi
        [[ ! -d "$data_dir" ]] && run_command mkdir -p $data_dir

        local json_response=$(curl -s $source)

        local urls=($(echo "$json_response" | jq -r '.urls[]'))

        # Download each file with its corresponding name
        for i in "${!urls[@]}"; do
            local url="${urls[$i]}"
            local filepath=$(echo "$json_response" | jq -r ".filepath[$i]")
            info "Downloading $filepath from $url"
            run_command curl -S -# -L "$url" -o "$data_dir/$filepath"
            check_exit_code $? "Failed to download test data: $filepath" 1 clean_up
        done
        run_command ls -l $data_dir
        check_exit_code $? "Failed to list data directory"
    fi
}

# Get type of GPU running on the system
get_host_gpu() {
    if ! command -v nvidia-smi >/dev/null; then
        error Y "Could not find any GPU drivers on host. Defaulting build to target dGPU/CPU stack."
        echo -n "dgpu"
    elif nvidia-smi  2>/dev/null | grep nvgpu -q; then
        echo -n "igpu"
    else
        echo -n "dgpu"
    fi
}

# Parameters
#  $1 Container Name
#  $2 Volume Name
clean_up_holohub_build() {
    info "Cleaning up Holohub build"
    run_command docker container kill $1
    run_command docker container rm -f $1
    run_command docker volume rm -f $2
}

# Build Holohub applications using Holohub's devcontainer script.
# Since the devcontainer script embeds the version of the HSDK container to use, we must explicitly set the base image based on the version of the running CLI.
# Next, we create a Docker volume to store the Holohub source code because we cannot a new container with a mount inside a container, when running on GitHub Actions.
# Finally, we run the build command inside the container.
#
# Parameters:
#  $1 Working Directory
#  $2 Application Name
#  $3 Application Language
#  $4 Data Directory
build_holohub_app() {
    info "===== Build Holohub Application ====="
    pushd $1

    local platform_config=$(get_host_gpu)

    info "Reading CLI manifest for version=${version} and platform=${platform_config}"
    local build_image=$(curl -L -s https://raw.githubusercontent.com/nvidia-holoscan/holoscan-cli/refs/heads/main/releases/${version}/artifacts.json | jq -r --arg HSDKVERSION "$version" --arg PFC "$platform_config" '.[$HSDKVERSION|tostring].holoscan."build-images"[$PFC|tostring]."x64-workstation"')
    local docker_file=$(./run get_app_dockerfile $2)

    info "Building Holohub image using $build_image and $docker_file"
    local image_name=holohub_builder:${version}
    run_command ./dev_container build --base_img $build_image --img $image_name --docker_file $docker_file
    check_exit_code $? "Failed to build Holohub image" 1 clean_up

    local volume_name="repo_data_$(date +%s%N)"
    local container_name="holohub_$(date +%s%N)"
    info "Creating volume (${volume_name}) to store Holohub source code"
    run_command docker volume create $volume_name
    check_exit_code $? "Failed to create volume" 1 clean_up

    run_command docker container create --name $container_name -v $volume_name:/workspace/holohub alpine:latest
    check_exit_code $? "Failed to create data copy container" 1 clean_up

    info "Copying Holohub source code to volume (${volume_name})"
    run_command docker cp $1/. $container_name:/workspace/holohub
    check_exit_code $? "Failed to copy Holohub source code to volume" 1 clean_up

    run_command docker run --net host --interactive --rm -v $volume_name:/workspace/holohub -w /workspace/holohub --runtime=nvidia --gpus all --entrypoint=bash $image_name -c "pwd && ls -l && ./run build $2 --install"
    exit_code=$?
    check_exit_code $exit_code "Failed to build Holohub application: $2" 0
    if [ $exit_code -ne 0 ]
    then
        clean_up_holohub_build "$container_name" "$volume_name"
        clean_up
        exit
    fi

    info "Copy built application to $1"
    run_command docker cp $container_name:/workspace/holohub/install $1
    check_exit_code $? "Failed to copy built application to $1" 1 clean_up
    run_command ls -lR $1/install

    info "Copy data to $4"
    run_command docker cp $container_name:/workspace/holohub/data $4
    check_exit_code $? "Failed to copy data to $4" 1 clean_up
    run_command ls -lR $4

    clean_up_holohub_build "$container_name" "$volume_name"
    popd
}

# Package the application using Holoscan CLI Packager
# Parameters:
#  $1 Working Directory
#  $2 Source Code Directory
#  $3 Relative Application Path
#  $4 Container Tag Prefix
#  $5 Input Data Directory Path
package() {
    info "===== Package Application ====="
    local run_args=$(get_config '.package.args')
    run_args=$(echo ${run_args//<src>/$2})
    local config_source=$(get_config '.config.source')
    local config_file_path=$(get_config '.config.path')
    local dir=
    local app_dir=
    local input_data_dir=$5

    if [[ "$run_args" == "null" ]]
    then
        run_args=""
    fi

    dir=$(dirname $test)
    if [ "$config_source" == "local" ]
    then
        config_file_path="$dir/$config_file_path"
    else
        config_file_path="$2/$config_file_path"
    fi

    app_dir="$2/$3"
    pushd $1
    info "Packaging application from $app_dir"
    info "  App config: $config_file_path"

    artifact_source=""

    if [ -n artifact_source_path ]
    then
        info "Using artifact source path: $artifact_source_path"
        artifact_source="--source $artifact_source_path"
    fi

    run_command holoscan package -l DEBUG \
                        --config $config_file_path \
                        --tag $4 \
                        --platform x86_64 \
                        --input-data $input_data_dir \
                        --sdk-version $version \
                    $app_dir \
                    $run_args \
                    $ci_package_args \
                    $artifact_source
    check_exit_code $? "Failed to package application" 1 clean_up
    popd
}

# Clone the user-defined repository.
#  For Holohub, clone entire repository. Otherwise, do a sparse clone of the application directory.
# Parameters
#  $1 Directory to clone to
#  $2 Git Repository
#  $3 Relative Application Path
clone() {
    info "===== Clone Repository ====="
    info "Cloning repository $2 to $1"
    info "Dir:          $1"
    info "Repository:   $2"
    info "Path:         $3"
    mkdir -p $1
    pushd $1

    local path=$3
    if [ -f $3 ]
    then
        path=$(basename $3)
    fi

    if [[ "$2" =~ "holohub" ]]
    then
        run_command git clone --depth 1 $2 .
        check_exit_code $? "Failed to clone repository" 1 clean_up
    else
        run_command git clone --filter=blob:none --no-checkout --depth 1 --sparse $2 .
        check_exit_code $? "Failed to clone repository" 1 clean_up
        run_command git sparse-checkout add "$path"
        check_exit_code $? "Sparse checkout failed" 1 clean_up
        run_command git checkout
        check_exit_code $? "Failed to checkout repository" 1 clean_up
    fi
    run_command ls -l
    popd
}

# For Holoscan SDK example C++ applications, rename CMakeLists.min.txt to CMakeLists.txt if exists.
#  This enables the Packager process to build the C++ application.
# Parameters
#  $1 Source Code Directory Path
#  $2 Relative Path to the Application
prep_cpp_dir() {
    info "Preparing C++ source directory for packaging"
    info "  Source Dir: $1"
    info "  Path:       $2"
    pushd $1

    local path="$1/$2"
    info "Searching $path for CMakeLists.min.txt"
    if [[ $(find $path -type f -name "CMakeLists.min.txt" | wc -l) -eq 1 ]]
    then
        info "Overwriting CMakeLists.txt with CMakeLists.min.txt"
        run_command mv -f $path/CMakeLists.min.txt $path/CMakeLists.txt
        check_exit_code $? "Failed to overwrite CMakeLists.txt with CMakeLists.min.txt" 1 clean_up
    fi
    popd
}

# Parameters
#  Value
#  Value query path
check_field() {
    if [ -z "$1" ]
    then
        info "$test test configuration is missing the '$2' field"
        exit 1
    fi
}

clean_up() {
    # Clean up the temporary directory
    info "Cleaning source code..."
    run_command rm -rf $tmp_dir
    local image=$(docker images --filter=reference="${tag}*:*" -q)
    if [ -n "$image" ]
    then
        info "Deleting Containerized Application..."
        run_command docker rmi --force $image
    fi
}

# Entrypoint of the scriptS
main() {
    local repository=$(get_config '.source.repo')
    local path=$(get_config '.source.path')
    local language=$(get_config '.source.lang')
    tmp_dir=$(mktemp -d)
    local source_dir="$tmp_dir/src"
    local data_dir="$tmp_dir/data"
    local app_name=$(get_config '.source.app')
    local package_path=$path
    tag="$(basename $(dirname $test))-$((1 + $RANDOM % 1000))"

    if [[ "$repository" =~ "holohub" ]]
    then
        path=${path//applications\//}
        info "Application:  $app_name"
    fi
    info "Repository:   $repository"
    info "Path:         $path"
    info "Language:     $language"
    info "Working Dir:  $tmp_dir"
    info "Source Dir:   $source_dir"
    info "Data Dir:     $data_dir"
    info "Tag Prefix:   $tag"

    check_field $repository ".source.repo"
    check_field $path ".source.path"
    check_field $language ".source.lang"

    # Clone configured git repository
    clone "$source_dir" "$repository" "$path"

    # For non-Holohub repositories and C++ projects
    if [[ "$language" == "cpp" && "$repository" != *"holohub"* ]]
    then
        prep_cpp_dir "$source_dir" "$path"
    fi

    # For Holohub C++ applications, append the application binary name to the package path
    if [[ "$repository" =~ "holohub" && "$language" == "cpp" ]]
    then
        package_path="install/bin/$path/$app_name"
    fi

    # For Holohub applications, call the build script. Assume Holohub downloads the data.
    if [[ "$repository" =~ "holohub" ]]
    then
        build_holohub_app "$source_dir" "$app_name" "$language" "$data_dir"
    else
        # Download specified data
        download_data "$data_dir"
    fi

    # Use test data downloaded by Holohub build script
    if [[ "$repository" =~ "holohub" && "$(get_config '.data.source')" == "local-holohub" ]]
    then
        data_dir="$data_dir/$(get_config '.data.dirname')"
        info "Switching to data directory $data_dir for Holohub"
        run_command ls -l $data_dir
    fi

    # Call Holoscan CLI Packager
    package "$tmp_dir" "$source_dir" "$package_path" "$tag" "$data_dir"

    # Call Holoscan CLI Runner
    run_application "$tag"

    # Clean up
    clean_up
}

if [ -z "$test" ]
then
    info "Please provide the test configuration path"
    exit 1
fi

if [ -d "$test" ]
then
    info "Looking for test configuration in $test"
    test="$test/config.json"
    if [ ! -f "$test" ]
    then
        info "No configuration found, expecting $test"
        exit 1
    fi
fi
if [ -z "$version" ]
then
    version=$(holoscan version | tail -n 1 | awk '{print $3}')
fi

# if version is 0.0.0, then we use the latest artifacts.json from the release directory
if [[ "$version" == "0.0.0" ]]
then
    artifact_source_path=$(find ${SCRIPT_DIR}/../../releases -type f -exec realpath {} \; | sort | tail -n 1)
    version=$(jq -r 'keys | sort_by(split(".") | map(tonumber)) | reverse | first' ${artifact_source_path})
fi
info "Using test configuration $test with Holoscan CLI v${version}"

main
