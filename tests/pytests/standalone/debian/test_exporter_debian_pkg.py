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
import copy
import logging
import requests
import random
import string
import subprocess
import lib.k8_util as k8_util
import lib.amdgpu as amdgpu
import lib.common as common
import lib.spec_util as spec_util
import lib.deb_util as deb_util
from lib.util import K8Helper

Logger = logging.getLogger("standalone.debian.test_exporter_debian_pkg")

@pytest.fixture(scope="module")
def reference_config(environment):
    # Use reference config.json https://raw.githubusercontent.com/ROCm/device-metrics-exporter/refs/heads/main/example/config.json
    config_json_file = os.path.join(environment.logdir, "reference-config.json")
    try:
        url = "https://raw.githubusercontent.com/ROCm/device-metrics-exporter/refs/heads/main/example/config.json"
        resp = requests.get(url)
        K8Helper.triage(environment, (resp.status_code == 200), f"Failed to download reference config.json file")
        with open(config_json_file, "wb") as fp:
            fp.write(resp.content)
        with open(config_json_file) as fp:
            config_data = json.load(fp)
    except Exception as ae:
        Logger.error(f"Failed to download config.json from {url}, error : {ae}")
    K8Helper.triage(environment, (os.path.exists(config_json_file)), f"Failed to download reference config.json file")
    yield (config_json_file, config_data)
    return

@pytest.fixture(scope="module")
def deploy_debian_package(gpu_cluster, images, amdgpu_driver_install, reference_config, environment):
    global Logger
    Logger.debug("Deploy exporter debian package on each node")
    config_json_file, _ = reference_config
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            image_name = f"exporter-debian-{node.host_os_name}-{node.host_os_version}.debian"
            if image_name in images:
                K8Helper.triage(environment, (node.put(config_json_file, "/tmp/config.json")), 
                                f"Unable to upload {config_json_file} to /tmp/config.json")
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

                    # Upload config.json
                    ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp /tmp/config.json /etc/metrics/config.json")
                    K8Helper.triage(environment, (ret_code == 0), f"Unable to create /etc/metrics folder")
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
    """
    Verify DME Debian package deployment

    Deploy debian package on the host and check for metrics endpoint to respond
    """
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

def test_nonstd_config_json_path(gpu_cluster, deploy_debian_package, reference_config, environment):
    """
    Verify amd-metrics-exporter -amd-metrics-config /non/std/config.json

    Check if amd-metrics-exporter honor -amd-metrics-config cmdline option
    """
    global Logger
    config_json_file, ref_config_data = reference_config
    config_data = copy.deepcopy(ref_config_data)

    # Confirm current behavior (port:5000)
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

    # Build/Modify reference config.json ServerPort from 5000 to 5001
    test_config_json = os.path.join(environment.logdir, "server_port_config.json")
    config_data['ServerPort'] = 5001
    with open(test_config_json, "w") as fp:
        fp.write(json.dumps(config_data, indent=4))

    service_file = "/lib/systemd/system/amd-metrics-exporter.service"
    old_line = "ExecStart=/usr/local/bin/amd-metrics-exporter"
    new_line = "ExecStart=/usr/local/bin/amd-metrics-exporter -amd-metrics-config /tmp/config.json"
    sed_command = f"sudo sed -i 's|^{old_line}$|{new_line}|' {service_file}"
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(test_config_json, "/tmp/config.json")), 
                            f"Unable to upload {test_config_json} to /tmp/config.json")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp {service_file} {service_file}.bak")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to take backup of {service_file}, error : {ret_stderr}")

            ret_code, ret_stdout, ret_stderr = node.run_command(sed_command)
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify {service_file}, error : {ret_stderr}")

            # Restart systemctl - do daemon-reload
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl daemon-reload")
            K8Helper.triage(environment, (ret_code == 0), f"Failed to run systemctl daemon-reload, error : {ret_stderr}")

            # Restart amd-metrics-exporter.service
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl restart amd-metrics-exporter.service")
            K8Helper.triage(environment, (ret_code == 0), f"Failed to start metrics-exporter debian, error : {ret_stderr}")

    time.sleep(30)

    failed_endpoints = set()
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.http_get(5001, "metrics")
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

            # Restart systemctl - do daemon-reload
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl daemon-reload")
            K8Helper.triage(environment, (ret_code == 0), f"Failed to run systemctl daemon-reload, error : {ret_stderr}")

            # Restart amd-metrics-exporter.service
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl restart amd-metrics-exporter.service")
            K8Helper.triage(environment, (ret_code == 0), f"Failed to start metrics-exporter debian, error : {ret_stderr}")


def test_modify_server_port(gpu_cluster, deploy_debian_package, reference_config, environment):
    """
    Verify DME with reference config.json

    Upload modified ROCm/device-metrics-exporter/refs/heads/main/example/config.json with new ServerPort and validate
    """
    global Logger

    config_json_file, ref_config_data = reference_config
    config_data = copy.deepcopy(ref_config_data)

    # Build/Modify reference config.json ServerPort from 5000 to 5001
    test_config_json = os.path.join(environment.logdir, "server_port_config.json")
    config_data['ServerPort'] = 5001
    with open(test_config_json, "w") as fp:
        fp.write(json.dumps(config_data, indent=4))

    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(test_config_json, "/tmp/config.json")), 
                            f"Unable to upload {test_config_json} to /tmp/config.json")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp /tmp/config.json /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify /etc/metrics/config.json, error : {ret_stderr}")

    time.sleep(30)
    failed_endpoints = set()
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.http_get(5001, "metrics")
            if ret_code != 0:
                failed_endpoints.add(node.ip_address)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {node.ip_address}, stdout: {ret_stdout} stderr: {ret_stderr}")
            else:
                Logger.debug("Check for all supported metrics in the output")
    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

    # Restore
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(config_json_file, "/tmp/config.json")), 
                            f"Unable to upload {config_json_file} to /tmp/config.json")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp /tmp/config.json /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify /etc/metrics/config.json, error : {ret_stderr}")
    time.sleep(30)

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

def test_enable_profiler_metrics(gpu_cluster, deploy_debian_package, reference_config, environment):
    """
    Verify DME Profile Metrics

    Change /etc/metrics/config.json with GPUConfig.Profile.all = True and check for profiler metrics exported by DME
    """
    global Logger

    config_json_file, ref_config_data = reference_config
    config_data = copy.deepcopy(ref_config_data)

    # Build/Modify reference config.json GPUConfig.ProfilerMetrics.all from False to True
    test_config_json = os.path.join(environment.logdir, "profiler_metrics_config.json")
    config_data['GPUConfig']['ProfilerMetrics']['all'] = True
    with open(test_config_json, "w") as fp:
        fp.write(json.dumps(config_data, indent=4))

    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(test_config_json, "/tmp/config.json")), 
                            f"Unable to upload {test_config_json} to /tmp/config.json")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp /tmp/config.json /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify /etc/metrics/config.json, error : {ret_stderr}")

    time.sleep(30)
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
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(config_json_file, "/tmp/config.json")), 
                            f"Unable to upload {config_json_file} to /tmp/config.json")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp /tmp/config.json /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify /etc/metrics/config.json, error : {ret_stderr}")
    time.sleep(30)

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

def test_change_custom_labels(gpu_cluster, deploy_debian_package, reference_config, environment):
    """
    Verify DME Profile Metrics

    Change /etc/metrics/config.json with GPUConfig.CustomLabels and check for profiler metrics exported by DME
    """
    global Logger

    config_json_file, ref_config_data = reference_config
    config_data = copy.deepcopy(ref_config_data)

    # Build/Modify reference config.json GPUConfig.ProfilerMetrics.all from False to True
    test_config_json = os.path.join(environment.logdir, "profiler_metrics_config.json")
    config_data['GPUConfig']['CustomLabels']['CLUSTER_NAME'] = "test-cluster-name"
    test_label_value = ''.join(random.choices(string.ascii_letters, k=15)).title()
    config_data['GPUConfig']['CustomLabels']['test-label'] = test_label_value
    with open(test_config_json, "w") as fp:
        fp.write(json.dumps(config_data, indent=4))

    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(test_config_json, "/tmp/config.json")), 
                            f"Unable to upload {test_config_json} to /tmp/config.json")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp /tmp/config.json /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify /etc/metrics/config.json, error : {ret_stderr}")

    time.sleep(30)
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
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(config_json_file, "/tmp/config.json")), 
                            f"Unable to upload {config_json_file} to /tmp/config.json")
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo cp /tmp/config.json /etc/metrics/config.json")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to modify /etc/metrics/config.json, error : {ret_stderr}")
    time.sleep(30)

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

def test_gpuagent_port_scan(gpu_cluster, deploy_debian_package, environment):
    global Logger
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            # Collect the PID
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl show -p MainPID --value gpuagent.service")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to get PID of gpuagent.service, error : {ret_stderr}")

            # Collect ss cmd output for this PID
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo ss -tunlp | grep {ret_stdout.strip()}")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to collect ss-cmd output, error : {ret_stderr}")
            address_port_map = deb_util.parse_ss_output(ret_stdout)
            #
            # [{'address': '[::ffff:127.0.0.1]', 'port': '50061'}]
            #
            K8Helper.triage(environment, (len(address_port_map) == 1),
                            f"More than one port opened by gpuagent.service, {address_port_map}")
            K8Helper.triage(environment, (int(address_port_map[0]['port']) == 50061),
                            f"Unexpected port opened by gpuagent.service in default deployment, {address_port_map}")
            K8Helper.triage(environment, ('0.0.0.0' not in address_port_map[0]['address']), 
                            f"GPUAgent Port opened on 0.0.0.0 - security violation found")

def test_exporter_port_scan(gpu_cluster, deploy_debian_package, environment):
    global Logger
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            # Collect the PID
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo systemctl show -p MainPID --value amd-metrics-exporter.service")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to get PID of amd-metrics-exporter.service, error : {ret_stderr}")

            # Collect ss cmd output for this PID
            ret_code, ret_stdout, ret_stderr = node.run_command(f"sudo ss -tunlp | grep {ret_stdout.strip()}")
            K8Helper.triage(environment, (ret_code == 0), f"Unable to collect ss-cmd output, error : {ret_stderr}")
            address_port_map = deb_util.parse_ss_output(ret_stdout)
            K8Helper.triage(environment, (len(address_port_map) == 1),
                            f"More than one port opened by amd-metrics-exporter.service, {address_port_map}")
            K8Helper.triage(environment, (int(address_port_map[0]['port']) == 5000),
                            f"Unexpected port opened by amd-metrics-exporter.service in default deployment, {address_port_map}")

