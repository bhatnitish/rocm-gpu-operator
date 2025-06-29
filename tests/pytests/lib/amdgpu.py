#!/usr/bin/python3

'''
 Copyright (c) Advanced Micro Devices, Inc. All rights reserved.

 Licensed under the Apache License, Version 2.0 (the \"License\");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an \"AS IS\" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
'''

import os
import sys
import logging
import lib.common
from datetime import datetime
from collections import defaultdict

Logger = logging.getLogger("lib.amdgpu")

def is_amdgpu_driver_installed(worker_node):
    # TODO:
    # Scan /proc/moddules of this node to check if amdgpu is loaded or not.
    global Logger
    local_filename = f'{worker_node.ip_address}_proc_modules'
    ret_code = worker_node.get('/proc/modules', local_filename)
    assert ret_code == 0, f'Failed to download /proc/modules from ip: {worker_node.ip_address}'
    with open(local_filename) as fp:
        for line in fp.readlines():
            if line.split(' ')[0] == 'amdgpu':
                return True
    return False

def get_dmesg_lines(worker_node, pattern = None):
    # Collect/Generate latest dmesg for given node
    global Logger

    dmesg_file = f'/tmp/dmesg_{int(datetime.now().timestamp())}'
    ret_code, _, _ = worker_node.run_command(f'sudo dmesg > {dmesg_file}')
    assert ret_code == 0, f'Failed to generate dmesg file'

    ret_code = worker_node.get(dmesg_file, os.path.basename(dmesg_file))
    assert ret_code == 0, f'Failed to download {dmesg_file} from ip {worker_node.ip_address}'

    with open(os.path.basename(dmesg_file)) as fp:
        contents = fp.readlines()
        if pattern == None:
            return contents

        matching_lines = list()
        for line in contents:
            if pattern in line:
                matching_lines.append(line)

        return matching_lines

def check_host_blacklist_file(worker_node, expected = True):
    global Logger
    
    filename = "/etc/modprobe.d/blacklist-amdgpu.conf"
    ret_code, resp_stdout, resp_stderr = worker_node.run_command(f"sudo ls -al {filename}")
    Logger.info(f'{resp_stdout}')
    present = filename in resp_stdout
    Logger.info(f'blacklist file expected {expected}, present = {present}')
    return expected == present 

