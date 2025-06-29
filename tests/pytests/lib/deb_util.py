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

import pdb
import os
import sys
import time
import json
import glob
import logging

Logger = logging.getLogger("lib.debutil")

'''
assuming:
1. amdgpu kernel module is loaded already
2. rdc service is at running state
'''
def deb_install(image,node):
    Logger.info(f"Install {image} on {node.ip_address}")
    node.put(image, image)
    node.run_command("sudo dpkg -i " + image + "")
        
def deb_uninstall(name,node):
    Logger.info(f"Uninstall {name} on {node.ip_address}")
    node.run_command("sudo dpkg -r " + name)
