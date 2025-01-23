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

echo "Checking system requirements..."

status=0
if ! command -v curl 2>&1 >/dev/null
then
    echo "jq could not be found, use the following command to install curl"
    echo "$ sudo apt install curl"
    status=-1
fi

if ! command -v jq 2>&1 >/dev/null
then
    echo "jq could not be found, use the following command to install jq"
    echo "$ sudo apt install jq"
    status=-1
fi

if ! command -v holoscan 2>&1 >/dev/null
then
    echo "Holoscan CLI could not be found, use the following command to install holoscan"
    echo "$ pip install holoscan-cli"
    status=-1
fi

if ! docker login nvcr.io < /dev/null >& /dev/null
then
    echo "Please login to nvcr.io. For example:"
    echo "$ docker login nvcr.io"
    status=-1
fi

exit $status