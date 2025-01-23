#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.run_command
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

version=
test=$(realpath $1)
repository=""
path=""
language=""


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

get_config() {
    value=$(jq -r "$1" $test)
    if [[ "$value" == "null" ]]
    then
        value=""
    fi
    echo $value
}

# Parameters
#  Data Dir
run() {
    info "===== Run Application ====="
    local data_dir=$1
    info "Starting application with data directory: $data_dir"
    run_args=$(get_config '.run.args')
    tag_prefix=$(basename $(dirname $test))
    tag=$(docker images | grep "$tag_prefix" | awk '{print $1":"$2}' | head -n 1)
    info "Running application"
    info "  Tag: $tag"
    run_command xhost +local:docker
    run_command holoscan run -l DEBUG $run_args $tag --input $data_dir

    if [[ $? -ne 0 ]]
    then
        error "Failed to run application"
        exit 1
    fi
}

download_data() {
    info "===== Download Data ====="
    local source=$(get_config '.data.source')
    local target=$(get_config '.data.dirname')

    if [[ "$source" != "local-holohub" ]]
    then
        local tmp_dir=$1
        local data_dir=$2
        if [ -v target ]
        then
            data_dir="$data_dir/$target"
        fi
        [[ ! -d "$data_dir" ]] && run_command mkdir -p $data_dir
        for url in $(curl $source | jq -r .urls.[])
            do
                info "Downloading $url"
                run_command curl -S -# -LO --output-dir "$data_dir" "$url"
                if [[ $? -ne 0 ]]
                then
                    error "Failed to download test data"
                    exit 1
                fi
            done
        tree $data_dir
    fi
}

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

# Parameters:
#  Working Directory
#  Application Name
#  Application Language
build_holohub_app() {
    info "===== Build Holohub Application ====="
    pushd $1

    local platform_config=$(get_host_gpu)
    local build_image=$(jq -r --arg HSDKVERSION $version --arg PFC $platform_config '.[$HSDKVERSION].holoscan."build-images".[$PFC]."x64-workstation"' "$SCRIPT_DIR/artifacts.json")
    info "Using base image $build_image"
    run_command ./dev_container build_and_install $2 --base_img $build_image
    if [[ $? -ne 0 ]]
    then
        error "Failed to build Holohub application: $2"
        exit 1
    fi
    tree
    popd
}

# Parameters:
#  Working Directory
#  Source Code Directory
#  Relative Application Path
package() {
    info "===== Package Application ====="
    local run_args=$(get_config '.package.args')
    run_args=$(echo ${run_args//<src>/$2})
    local config_source=$(get_config '.config.source')
    local config_file_path=$(get_config '.config.path')
    local dir=
    local app_dir=

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
    run_command holoscan package -l DEBUG \
                     --config $config_file_path \
                     --tag $(basename $dir) \
                     --platform x64-workstation \
                     --source /home/vicchang/sc/github/holoscan-cli/tests/automation/artifacts.json \
                     --holoscan-sdk-file /home/vicchang/sc/github/holoscan-cli/dist/holoscan-2.9.0.1-cp310-cp310-manylinux_2_35_x86_64.whl \
                     $app_dir \
                     $run_args
                    #  --holoscan-sdk-file /home/vicchang/sc/github/holoscan-cli/dist/holoscan_2.9.0.1-1_amd64.deb \
                    #  --holoscan-sdk-file /home/vicchang/sc/github/holoscan-cli/dist/holoscan-2.9.0.1-cp310-cp310-manylinux_2_35_x86_64.whl \

    if [[ $? -ne 0 ]]
    then
        error "Failed to package application"
        exit 1
    fi
    popd
}

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
    else
        run_command git clone --filter=blob:none --no-checkout --depth 1 --sparse $2 .
        run_command git sparse-checkout add "$path"
        run_command git checkout
    fi
    run_command tree
    popd
}

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

main() {
    local repository=$(get_config '.source.repo')
    local path=$(get_config '.source.path')
    local language=$(get_config '.source.lang')
    local tmp_dir=$(mktemp -d)
    local source_dir="$tmp_dir/src"
    local data_dir="$tmp_dir/data"
    local app_name=$(get_config '.source.app')
    local package_path=$path

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

    check_field $repository ".source.repo"
    check_field $path ".source.path"
    check_field $language ".source.lang"

    clone "$source_dir" "$repository" "$path"

    if [[ "$language" == "cpp" && "$repository" != *"holohub"* ]]
    then
        prep_cpp_dir "$source_dir" "$path"
    fi

    if [[ "$repository" =~ "holohub" && "$language" == "cpp" ]]
    then
        package_path="install/bin/$path/$app_name"
    fi

    if [[ "$repository" =~ "holohub" ]]
    then
        build_holohub_app "$source_dir" "$app_name" "$language"
    fi

    package "$tmp_dir" "$source_dir" "$package_path"

    download_data "$tmp_dir" "$data_dir"

    if [[ "$repository" =~ "holohub" && "$(get_config '.data.source')" == "local-holohub" ]]
    then
        data_dir="$source_dir/data/$(get_config '.data.dirname')"
        tree $data_dir
    fi

    run "$data_dir"

    info "Cleaning source code..."
    run_command rm -rf $tmp_dir
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

version=$(holoscan version | tail -n 1 | awk '{print $3}')
info "Using test configuration $test with Holoscan CLI v${version}"

main
