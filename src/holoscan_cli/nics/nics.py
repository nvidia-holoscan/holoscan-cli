# SPDX-FileCopyrightText: Copyright (c) 2023-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
import logging
import sys
from argparse import Namespace

from ..common.utils import get_host_ip_addresses

logger = logging.getLogger("nics")


def execute_nics_command(args: Namespace):
    try:
        ipv4, ipv6 = get_host_ip_addresses()
        ip_addresses = ipv4 if ipv4 else ipv6
        strs = [f"\n\t{item[0]:<15} : {item[1]}" for item in ip_addresses]
        print(f"Available network interface cards/IP addresses: \n{''.join(strs)}")
    except Exception as ex:
        logger.error("Error executing nics command.")
        logger.debug(ex)
        sys.exit(4)
