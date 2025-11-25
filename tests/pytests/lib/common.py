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

import sys
import os
import time
import paramiko
import shutil
import logging
import requests
import hashlib
from datetime import datetime
from fabric import Connection
from invoke.exceptions import UnexpectedExit
from invoke.exceptions import CommandTimedOut
from collections import namedtuple
from enum import Enum

Logger = logging.getLogger("lib.common")

def log_struct_members(struct):
    Logger.info("Struct contents: " + ", ".join(f"{k}={v}" for k, v in vars(struct).items()))

Node = namedtuple("Node", ["IpAddress", "Username", "Password", "Identity", "NodeType", "GPUSeries"])
PodInfo = namedtuple("PodInfo", ["PodName", "NumInstances", "ContainerCount"])

class TestbedType(Enum):
    K8          = 1
    OPENSHIFT   = 2
    STANDALONE  = 3

class cluster_node(object):
    def __init__(self, ip_address = "localhost", user_name = None, password = None, identity = None):
        self._ip_address = ip_address
        self._user_name = user_name
        self._password = password
        self._identity = identity
        self._node_type = None
        self._gpu_series = None
        self._host_name = None
        self._device_id = None
        self._num_gpus = 0
        self._connect_kwargs = {}
        if self._password:
            self._connect_kwargs['password'] = self._password 
        elif self._identity:
            self._connect_kwargs['key_filename'] = self._identity

    @property
    def ip_address(self):
        return self._ip_address

    @property
    def user_name(self):
        return self._user_name

    @property
    def password(self):
        return self._password

    @property
    def identity(self):
        return self._identity

    @property
    def node_type(self):
        return self._node_type

    @node_type.setter
    def node_type(self, node_type):
        self._node_type = node_type

    @property
    def gpu_series(self):
        return self._gpu_series

    @gpu_series.setter
    def gpu_series(self, gpu_series):
        self._gpu_series = gpu_series
        
    @property
    def host_name(self):                
        return self._host_name

    @host_name.setter
    def host_name(self, host_name):   
        self._host_name = host_name

    @property
    def num_gpus(self):
        return self._num_gpus

    @num_gpus.setter
    def num_gpus(self, gpu_count):
        self._num_gpus = gpu_count

    @property
    def device_id(self):
        return self._device_id

    @device_id.setter
    def device_id(self, device_id):
        self._device_id = device_id
        if device_id in ['0x7408']:
            self._gpu_series = 'MI250X'
        if device_id in ['0x740f']:
            self._gpu_series = 'MI210'
        elif device_id in ['0x7410']:
            self._gpu_series = 'MI210-VF'
        elif device_id in ['0x740c']:
            self._gpu_series = 'MI250'
        elif device_id in ['0x74a1']:
            self._gpu_series = 'MI300X'
        elif device_id in ['0x74b5']:
            self._gpu_series = 'MI300X-VF'
        elif device_id in ['0x74a2', '0x74a8']:
            self._gpu_series = 'MI308X'
        elif device_id in ['0x74b5', '0x74b6', '0x74bc']:
            self._gpu_series = 'MI308X-VF'
        elif device_id in ['0x75a0']:
            self._gpu_series = 'MI350X'
        elif device_id in ['0x75a5', '0x74a5']:
            self._gpu_series = 'MI325X'
        elif device_id in ['0x75b0']:
            self._gpu_series = 'MI350X-VF'
        elif device_id in ['0x74b9']:
            self._gpu_series = 'MI325X-VF'
        elif device_id in ['0x75a3']:
            self._gpu_series = 'MI355X'
        elif device_id in ['0x75b3']:
            self._gpu_series = 'MI355X-VF'
        else:
            self._gpu_series = 'UNKNOWN'

    def is_local(self):
        return self._ip_address == "localhost"

    def run_command(self, cmd, timeout = 90):
        global Logger
        Logger.debug(f"Running Cmd: {cmd} on {self._ip_address}")
        with Connection(self._ip_address, user = self._user_name, connect_kwargs = self._connect_kwargs) as conn:
            try:
                if self.is_local():
                    result = conn.local(cmd, hide = True, in_stream=False, timeout = timeout)
                else:
                    result = conn.run(cmd, hide = True, in_stream=False, timeout = timeout)
                return result.return_code, result.stdout, result.stderr
            except UnexpectedExit as ue:
                return ue.result.exited, ue.result.stdout, ue.result.stderr
            except CommandTimedOut as to:
                return to.result.exited, to.result.stdout, to.result.stderr
        return -1, "", ""

    def run_commands(self, cmd_list, timeout = 90):
        global Logger
        overall_result = 0
        combined_result = {}
        with Connection(self._ip_address, user = self._user_name, connect_kwargs = self._connect_kwargs) as conn:
            for idx, cmd in enumerate(cmd_list):
                Logger.debug(f"Running Cmd: {cmd} on {self._ip_address}")
                try:
                    if self.is_local():
                        result = conn.local(cmd, hide = True, in_stream=False, timeout = timeout)
                    else:
                        result = conn.run(cmd, hide = True, in_stream=False, timeout = timeout)
                    if result.return_code != 0:
                        overall_result = 1
                    combined_result[cmd] = (result.return_code, result.stdout, result.stderr)
                except UnexpectedExit as ue:
                    overall_result = 1
                    combined_result[cmd] = (ue.result.exited, ue.result.stdout, ue.result.stderr)
                except CommandTimedOut as to:
                    overall_result = 1
                    combined_result[cmd] = (to.result.exited, to.result.stdout, to.result.stderr)
        return overall_result, combined_result

    def get(self, remote_file, local_file):
        if not os.path.exists(os.path.dirname(local_file)):
            os.makedirs(os.path.dirname(local_file))
        if self.is_local():
            # Using shutil to copy 
            shutil.copy(remote_file, local_file)
            return True
        else:
            with Connection(self._ip_address, user = self._user_name, connect_kwargs = self._connect_kwargs) as conn:
                conn.get(remote_file, local_file)
            return True
        return False

    def put(self, local_file, remote_file):
        assert os.path.exists(local_file), f"Could not find file : {local_file}"
        if self.is_local():
            os.makedirs(os.path.dirname(remote_file))
            shutil.copy(local_file, remote_file)
            return True
        else:
            with Connection(self._ip_address, user = self._user_name, connect_kwargs = self._connect_kwargs) as conn:
                result = conn.run(f"mkdir -p {os.path.dirname(remote_file)}", in_stream=False)
                if result.return_code == 0:
                    conn.put(local_file, remote_file)
                return result.return_code == 0
        return False

    def http_get(self, http_port, url_suffix, token = None, retries = 5):
        headers = {}
        if token:
            headers = {"Authorization": f"Bearer {token}"}
        url = f"http://{self._ip_address}:{http_port}/{url_suffix}"
        ret_code = 0
        ret_stdout = ""
        ret_stderr = ""
        for _ in range(retries):
            try:
                resp = requests.get(url, headers = headers, verify = False)
                if resp.status_code == 200:
                    return 0, resp.content, ""
                else:
                    ret_code = -1
                    ret_stderr = f"Error : {resp}"
            except Exception as e:
                ret_code = -1
                ret_stderr = f"Exception : {e}"
            time.sleep(5)
        return ret_code, ret_stdout, ret_stderr

    def https_get(self, http_port, url_suffix, token = None, retries = 5):
        headers = {}
        if token:
            headers = {"Authorization": f"Bearer {token}"}
        url = f"https://{self._ip_address}:{http_port}/{url_suffix}"
        ret_code = 0
        ret_stdout = ""
        ret_stderr = ""
        for _ in range(retries):
            try:
                resp = requests.get(url, headers=headers, verify = False)
                if resp.status_code == 200:
                    return 0, resp.content, None
                else:
                    ret_code = -1
                    ret_stderr = f"Error : {resp}"
            except Exception as e:
                ret_code = -1
                ret_stderr = f"Exception : {e}"
            time.sleep(5)
        return ret_code, ret_stdout, ret_stderr

    def proxy_http_get(self, http_ip, http_port, url_suffix, token = None, retries = 5):
        url = f"http://{http_ip}:{http_port}/{url_suffix}"
        ret_code = 0
        ret_stdout = ""
        ret_stderr = ""
        for _ in range(retries):
            if self.is_local():
                headers = {}
                if token:
                    headers = {"Authorization": f"Bearer {token}"}
                try:
                    resp = requests.get(url, headers=headers, verify = False)
                    if resp.status_code == 200:
                        return 0, resp.content, None
                    else:
                        ret_code = -1
                        ret_stderr = f"Error : {resp}"
                except Exception as e:
                    ret_code = -1
                    ret_stderr = f"Exception : {e}"
            else:
                '''
                curl -s -k -H "Authorization: Bearer $TOKEN" http://10.11.130.28:32500/metrics
                '''
                cmd = ['curl', '-s']
                if token:
                    cmd.extend(['-k', '-H', f'"Authorization: Bearer {token}"'])
                cmd.append(url)
                ret_code, ret_stdout, ret_stderr = self.run_command(" ".join(cmd))
                if ret_code == 0:
                    return ret_code, ret_stdout, ret_stderr
            time.sleep(5)
        return ret_code, ret_stdout, ret_stderr

    def proxy_https_get(self, http_ip, http_port, url_suffix, token = None, retries = 5):
        url = f"https://{http_ip}:{http_port}/{url_suffix}"
        ret_code = 0
        ret_stdout = ""
        ret_stderr = ""
        for _ in range(retries):
            if self.is_local():
                headers = {}
                if token:
                    headers = {"Authorization": f"Bearer {token}"}
                try:
                    resp = requests.get(url)
                    if resp.status_code == 200:
                        return 0, resp.content, None
                    else:
                        ret_code = -1
                        ret_stderr = f"Error : {resp}"
                except Exception as e:
                    ret_code = -1
                    ret_stderr = f"Exception : {e}"
            else:
                '''
                curl -s -k -H "Authorization: Bearer $TOKEN" https://10.11.130.28:32500/metrics
                '''
                cmd = ['curl', '-s']
                if token:
                    cmd.extend(['-k', '-H', f'"Authorization: Bearer {token}"'])
                cmd.append(url)
                ret_code, ret_stdout, ret_stderr = self.run_command(" ".join(cmd))
                if ret_code == 0:
                    return ret_code, ret_stdout, ret_stderr
            time.sleep(5)
        return ret_code, ret_stdout, ret_stderr

class k8_master_node(cluster_node):

    def __init__(self, ip_address, user_name, password, identity):
        super().__init__(ip_address, user_name, password, identity)
        self._local_registry_enabled = False

    def set_local_registry_status(self, status):
        self._local_registry_enabled = status

    def is_local_registry_available(self):
        return self._local_registry_enabled

class cluster(object):

    def __init__(self, nodes, testbed_type):
        self._worker_nodes = list()
        self._gpu_series_set = set()
        for node in nodes:
            assert node.NodeType == "worker"
            worker_node = cluster_node(node.IpAddress, node.Username, node.Password, node.Identity)
            worker_node.gpu_series = node.GPUSeries
            self._worker_nodes.append(worker_node)
            self._gpu_series_set.add(node.GPUSeries)
        self._testbed_type = testbed_type

    @property
    def testbed_type(self):
        return self._testbed_type

    @property
    def worker_nodes(self):
        return self._worker_nodes

    def get_worker_node(self, node_ip):
        filtered_nodes = list(filter(lambda x: x.ip_address == node_ip, self._worker_nodes))
        if len(filtered_nodes) == 1:
            return filtered_nodes[0]
        return None

    def has_same_gpu_devices(self):
        return len(self._gpu_series_set) == 1

    def add_worker_node(self, node_ip, username = None, password = None):
        worker_node = cluster_node(node_ip, username, password, None)
        self._worker_nodes.append(worker_node)
        return

    def update_cluster_insights(self, node_ip, gpu_series):
        worker_node = get_worker_node(node_ip)
        if worker_node:
            worker_node.gpu_series = node.GPUSeries
            self._gpu_series_set.add(node.GPUSeries)
            return True
        return False

class k8_cluster(cluster):

    def __init__(self, master_node = None, nodes = list(), mini_kube_cluster = False):
        super().__init__(nodes, TestbedType.K8)
        self._k8_master = None
        self._k8_kube_config = None
        self._k8_secrets = {}
        self._k8_registry = 'docker.io'
        self._mini_kube_cluster = mini_kube_cluster
        if master_node:
            assert master_node.NodeType == "master"
            self._k8_master = k8_master_node(master_node.IpAddress, master_node.Username, master_node.Password, master_node.Identity)

    @property
    def k8_master(self):
        return self._k8_master

    @property
    def mini_kube_cluster(self):
        return self._mini_kube_cluster

    @property
    def k8_kube_config(self):
        return self._k8_kube_config

    @k8_kube_config.setter
    def k8_kube_config(self, kube_config_path):
        self._k8_kube_config = kube_config_path
 
    @property
    def k8_secrets(self):
        return self._k8_secrets

    @k8_secrets.setter
    def k8_secrets(self, secrets):
        self._k8_secrets = secrets

    @property
    def k8_registry(self):
        return self._k8_registry

    @k8_registry.setter
    def k8_registry(self, registry):
        self._k8_registry = registry

 
class standalone_gpu_nodes(cluster):

    def __init__(self, ip_info_list):
        super().__init__(ip_info_list, TestbedType.STANDALONE)

class OpenShiftGpuCluster(cluster):

    def __init__(self):
        pass

    def testbed_type(self):
        return TestbedType.OPENSHIFT

class SlurmGpuCluster(cluster):

    def __init__(self):
        pass

def generate_8byte_sha(seed : str) -> str:
    """
    Generates an 8-byte SHA-256 hash from an input string.
    """
    # Encode the input string to bytes (UTF-8 is common)
    input_str = f"{seed}@{time.time()}"
    input_bytes = input_str.encode('utf-8')
    # Create a SHA-256 hash object
    sha256_hash = hashlib.sha256()
    # Update the hash object with the input bytes
    sha256_hash.update(input_bytes)
    # Get the hexadecimal representation of the full hash
    full_hex_digest = sha256_hash.hexdigest()
    # Truncate the hexadecimal string to the first 16 characters (8 bytes * 2 hex chars/byte)
    eight_byte_hex_digest = full_hex_digest[:16]
    return eight_byte_hex_digest

