#! /bin/bash

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

OUTPUT_LOG=$1
if [ -f "$2" ]; then
    EXPECTED_OUTPUT_FILES=("$2")
else
    EXPECTED_OUTPUT_FILES=("$2"/*)
fi

echo "--- Checking for expected blocks from $EXPECTED_OUTPUT_FILES ---"
EXIT_CODE=0
for expected_file in "${EXPECTED_OUTPUT_FILES[@]}"; do
    echo "Checking for block from: $expected_file"

    # Check if the expected file is empty or invalid
    if [ ! -s "$expected_file" ]; then
        echo "Warning: Expected file $expected_file is empty or does not exist. Skipping."
        continue
    fi

    # Read the entire expected block
    mapfile -t expected_lines < "$expected_file"
    num_expected=${#expected_lines[@]}
    first_line="${expected_lines[0]}"

    # Use grep -F to find fixed-string matches of the first line and get line numbers
    # Escape potential special characters in the first line for grep
    # first_line_escaped=$(sed 's/[^^]/[&]/g; s/\^/\\^/g' <<< "$first_line") # Overly complex, -F should handle it

    # Find line numbers where the first line matches
    # Using process substitution to avoid issues with pipelines and variable scope
    match_found=0
    while IFS=: read -r line_num _; do
        # echo "  Found first line '$first_line' at line $line_num in $OUTPUT_LOG"
        # Check if the subsequent lines match
        block_matches=1
        for (( i=1; i<num_expected; i++ )); do
            current_log_line_num=$((line_num + i))
            # Extract the specific line from the log file
            # Get the log line and strip ANSI escape sequences and non-printable chars
            log_line=$(sed -n "${current_log_line_num}p" "$OUTPUT_LOG" | sed 's/\x1B\[[0-9;]*[mK]//g' | tr -cd '\11\12\15\40-\176' | tr -d '\r')
            expected_line="${expected_lines[$i]}"

            # Compare the log line with the expected line
            if [ "$log_line" != "$expected_line" ]; then
                # echo "    Mismatch at log line $current_log_line_num: '$log_line' != '$expected_line'"
                block_matches=0
                break
            fi
        done

        if [ $block_matches -eq 1 ]; then
            echo "Block from $expected_file found starting at line $line_num in $OUTPUT_LOG"
            match_found=1
            break # Found the block, no need to check other potential start lines
        fi
    done < <(grep -F -n "$first_line" "$OUTPUT_LOG") # Use -F for fixed string, -x for full line match

    # If no match was found after checking all potential start lines
    if [ $match_found -eq 0 ]; then
        echo "Error: Block from $expected_file not found in $OUTPUT_LOG."
        EXIT_CODE=1
        break # Exit the loop over files on first failure
    fi
done

# Exit the script with the overall exit code
exit $EXIT_CODE
