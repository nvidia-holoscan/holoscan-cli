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
nics() {
  for each in $(ip address | grep -oP '(^[\d]+:\s)\K[\d\w]+'); do
    ip_address=$(ip address show ${each} | grep -oP '(?<=inet\s)\K[\d.]+')
    ip_v6=$(ip address show ${each} | grep -oP '(?<=inet6\s)\K[\da-f:]+')

    if [ -z $ip_address ]; then
      ip_address=$ip_v6
    fi

    test -n "$(echo "$nics" | grep "$each")"

    for address in $ip_address; do
      test -n "$(echo "$nics" | grep "$address")"
    done
  done
}
