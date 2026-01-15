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
import pytest
import pprint
import sys
import os
import re
import time
import json
import logging
import requests
import lib.k8_util as k8_util
import lib.amdgpu as amdgpu
import lib.common as common
import lib.spec_util as spec_util
from lib.util import K8Helper

Logger = logging.getLogger("standalone.debian.test_exporter_debian_pkg")

@pytest.fixture(scope="module")
def deploy_debian_package(gpu_cluster, images, amdgpu_driver_install, environment):
    global Logger
    Logger.debug("Deploy exporter debian package on each node")
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            image_name = f"exporter-debian-{node.host_os_name}-{node.host_os_version}.debian"
            if image_name in images:
                Logger.info(f"Deploy debian package {images[image_name]} on {node.host_name}")
                remote_file = os.path.join("/tmp", os.path.basename(images[image_name]))
                node.run_command(f"rm -f {remote_file}")
                if node.put(images[image_name], remote_file):
                    # Install
                    ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo apt install -y {remote_file}")
                    K8Helper.triage(environment, (ret_code == 0), f"Failed to install metrics-exporter debian, error : {ret_stderr}")

                    # Check status
                    ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl status amd-metrics-exporter.service")
                    K8Helper.triage(environment, (ret_code != 0), f"Failed to check status metrics-exporter debian, error : {ret_stderr}")

                    # Enable systemctl service
                    ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl enable amd-metrics-exporter.service")
                    K8Helper.triage(environment, (ret_code == 0), f"Failed to enable metrics-exporter debian, error : {ret_stderr}")

                    # Start systemctl service
                    ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl start amd-metrics-exporter.service")
                    K8Helper.triage(environment, (ret_code == 0), f"Failed to start metrics-exporter debian, error : {ret_stderr}")

                    # Check status
                    ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl status amd-metrics-exporter.service")
                    K8Helper.triage(environment, (ret_code == 0), f"Failed to check status metrics-exporter debian, error : {ret_stderr}")
            else:
                Logger.error(f"Missing debian package for {image_name} for {node.host_name}")
    yield
    Logger.debug("Uninstall exporter debian package on each node")
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            image_name = f"exporter-debian-{node.host_os_name}-{node.host_os_version}.debian"
            if image_name in images:
                Logger.info(f"Remote debian package on {node.host_name}")
                remote_file = os.path.join("/tmp", os.path.basename(images[image_name]))
                # Remove package
                ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo dpkg -r amdgpu-exporter")
                K8Helper.triage(environment, (ret_code == 0), f"Failed to uninstall metrics-exporter debian, error : {ret_stderr}")

                node.run_command(f"rm -f {remote_file}")
            else:
                Logger.error(f"Missing debian package for {image_name} for {node.host_name}")
    return

def test_deploy_exporter_debian_package(gpu_cluster, deploy_debian_package, environment):
    global Logger
    failed_endpoints = set()
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.http_get(5000, "metrics")
            if ret_code != 0:
                failed_endpoints.add(node.ip_address)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {node.ip_address}, stdout: {ret_stdout} stderr: {ret_stderr}")
    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")


def test_apply_reference_exporter_config(gpu_cluster, deploy_debian_package, environment):
    global Logger

    # Use reference config.json https://raw.githubusercontent.com/ROCm/device-metrics-exporter/refs/heads/main/example/config.json
    config_json_file = os.path.join(environment.logdir, "reference-config.json")
    try:
        url = "https://raw.githubusercontent.com/ROCm/device-metrics-exporter/refs/heads/main/example/config.json"
        resp = requests.get(url)
        K8Helper.triage(environment, (resp.status_code == 200), f"Failed to download reference config.json file")
        with open(config_json_file, "w") as fp:
            fp.write(resp.content)
    except Exception as ae:
        Logger.error(f"Failed to download config.json from {url}, error : {ae}")

    K8Helper.triage(environment, (os.path.exists(config_json_file)), f"Failed to download reference config.json file")
    remote_file = "/tmp/config.json"
    service_file = "/lib/systemd/system/amd-metrics-exporter.service"
    old_line = "ExecStart=/usr/local/bin/amd-metrics-exporter"
    new_line = "ExecStart=/usr/local/bin/amd-metrics-exporter -amd-metrics-config /etc/metrics/config.json"
    sed_command = f"sudo sed -i 's|^{old_line}$|{new_line}|' {service_file}"
    reload_command = "sudo systemctl daemon-reload && sudo systemctl restart amd-metrics-exporter"
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(config_json_file, remote_file)), 
                            f"Unable to upload {config_json_file} to {remote_file}")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp {service_file} {service_file}.bak")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to take backup of {service_file}, error : {ret_stderr}")

            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo mkdir -p /etc/metrics")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to create /etc/metrics folder")

            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp {remote_file} /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to create /etc/metrics folder")

            ret_code, ret_stdout, ret_stderr = node.run_command(sed_command)
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify {service_file}, error : {ret_stderr}")

            ret_code, ret_stdout, ret_stderr = node.run_command(reload_command)
            K8Helper.triage(environment, (ret_code == 0), f"Unable to perform systemctl reload, error : {ret_stderr}")

    failed_endpoints = set()
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.http_get(5000, "metrics")
            if ret_code != 0:
                failed_endpoints.add(node.ip_address)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {node.ip_address}, stdout: {ret_stdout} stderr: {ret_stderr}")
            else:
                Logger.debug("Check for all supported metrics in the output")
    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

    # Restore
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp {service_file}.bak {service_file}")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to take backup of {service_file}")

            ret_code, ret_stdout, ret_stderr = node.run_command(reload_command)
            K8Helper.triage(environment, (ret_code == 0), f"Unable to reload amdgpu-exporter daemon")

            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo rm -f /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to cleanup /etc/metrics folder")

def test_enable_profiler_metrics(gpu_cluster, deploy_debian_package, environment):
    global Logger
    # Build config.json with profiler enabled
    config_json_file = os.path.join(environment.logdir, "profiler-metrics-config.json")
    config_map = {
        "CommonConfig" : {
            "HealthService" : {
                "Enable" : False,
            },
        },
        "GPUConfig" : {
            "ProfilerMetrics": {
                "all": True,
            }
        },
    }
    with open(config_json_file, "w") as fp:
        fp.write(json.dumps(config_map, indent=4))

    K8Helper.triage(environment, (os.path.exists(config_json_file)), f"Failed to download reference config.json file")
    remote_file = "/tmp/config.json"
    service_file = "/lib/systemd/system/amd-metrics-exporter.service"
    old_line = "ExecStart=/usr/local/bin/amd-metrics-exporter"
    new_line = "ExecStart=/usr/local/bin/amd-metrics-exporter -amd-metrics-config /etc/metrics/config.json"
    sed_command = f"sudo sed -i 's|^{old_line}$|{new_line}|' {service_file}"
    reload_command = "sudo systemctl daemon-reload && sudo systemctl restart amd-metrics-exporter"
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(config_json_file, remote_file)), 
                            f"Unable to upload {config_json_file} to {remote_file}")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp {service_file} {service_file}.bak")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to take backup of {service_file}, error : {ret_stderr}")

            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo mkdir -p /etc/metrics")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to create /etc/metrics folder")

            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp {remote_file} /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to create /etc/metrics folder")

            ret_code, ret_stdout, ret_stderr = node.run_command(sed_command)
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify {service_file}, error : {ret_stderr}")

            ret_code, ret_stdout, ret_stderr = node.run_command(reload_command)
            K8Helper.triage(environment, (ret_code == 0), f"Unable to perform systemctl reload, error : {ret_stderr}")

    failed_endpoints = set()
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.http_get(5000, "metrics")
            if ret_code != 0:
                failed_endpoints.add(node.ip_address)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {node.ip_address}, stdout: {ret_stdout} stderr: {ret_stderr}")
            else:
                Logger.debug("Check for ProfilerMetrics in the output")
    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

    # Restore
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp {service_file}.bak {service_file}")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to take backup of {service_file}")

            ret_code, ret_stdout, ret_stderr = node.run_command(reload_command)
            K8Helper.triage(environment, (ret_code == 0), f"Unable to reload amdgpu-exporter daemon")

            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo rm -f /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to cleanup /etc/metrics folder")

