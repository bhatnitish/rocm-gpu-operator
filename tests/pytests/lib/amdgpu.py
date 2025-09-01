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
import pdb
import logging
import json
import lib.common
from datetime import datetime
from collections import defaultdict

Logger = logging.getLogger("lib.amdgpu")

def get_rocm_version(devcfg_driver_version):
    with open("lib/files/gpu-operator-rocm-info.json", "r") as fp:
        rocm_info = json.load(fp)

    for entry in rocm_info['deviceconfig-driver']:
        if entry['deviceconfig-version'] == devcfg_driver_version:
            return entry['rocm-version']
    return None

def extract_amdgpu_info(node, k8_node, amd_smi_info):
    if not amd_smi_info:
        Logger.error(f"amd_smi_info is invalid")
        return False
    smi_data = json.loads(amd_smi_info.replace("'", "\""))
    if isinstance(smi_data, list):
        gpu_data = smi_data
    elif isinstance(smi_data, dict):
        gpu_data = smi_data['gpu_data']
    else:
        Logger.error(f"Failed to parse amd-smi information, {amd_smi_info}")
        return False

    if len(gpu_data) == 0:
        Logger.error(f"Failed to parse amd-smi information, {amd_smi_info}")
        return False

    num_gpus = len(gpu_data)
    if num_gpus == 0:
        Logger.error(f"No gpu information found")
        return False
    node.num_gpus = num_gpus
    gpu_0 = gpu_data[0]
    node.device_id = gpu_0['asic']['device_id']
    return True

