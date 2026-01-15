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
def run_exporter_docker_container(gpu_cluster, images, amdgpu_driver_install, environment):
    global Logger
    Logger.debug("Deploy exporter debian package on each node")
    img = None
    if images.get('metricsExporter.image.repository', None):
        img = f"{images['metricsExporter.image.repository']}:{images['metricsExporter.image.version']}"
    else:
        pytest.fail(f"Missing device-metrics-exporter container image")

    registry_credentials = None
    if images.get('metricsExporter.image.secret', None):
        secret_name = images['metricsExporter.image.secret'] 
        for entry in gpu_cluster.k8_secrets["secrets"]:
            if entry['name'] == secret_name:
                registry_credentials = (entry["username"], entry["password"])

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
    remote_file = "/tmp/etc/metrics/config.json"
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.run_command(f"rm -rf /tmp/etc && mkdir -p /tmp/etc/metrics")
            K8Helper.triage(environment, (ret_code == 0), f"Failed init tmp folder /tmp/etc/metrics, error: {ret_stderr}")
            K8Helper.triage(environment, (node.put(config_json_file, remote_file)), 
                            f"Unable to upload reference config.json")
            if registry_credentials:
                ret_code, ret_stdout, reg_stderr = node.run_command(f"docker login -u {registry_credentials[0]} -p {registry_credentials[1]}")
                Logger.debug(f"Result of docker login - retcode: {ret_code}")

            # deploy docker in daemon mode
            cmd = f"docker run -d --device=/dev/dri --device=/dev/kfd -p 5000:5000 -v /tmp/etc/metrics:/etc/metrics --name device-metrics-exporter {img}"
            ret_code, ret_stdout, ret_stderr = node.run_command(cmd)
            K8Helper.triage(environment, (ret_code == 0), f"Failed to deploy metrics-exporter container, error : {ret_stderr}")

            if registry_credentials:
                ret_code, ret_stdout, reg_stderr = node.run_command(f"docker logout")
                Logger.debug(f"Result of docker login - retcode: {ret_code}")
    yield
    Logger.debug("Uninstall exporter debian package on each node")
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            cmd = f"docker stop device-metrics-exporter"
            ret_code, ret_stdout, ret_stderr = node.run_command(cmd)
            K8Helper.triage(environment, (ret_code == 0), f"Failed to stop metrics-exporter container, error : {ret_stderr}")

            cmd = f"docker rm -f device-metrics-exporter"
            ret_code, ret_stdout, ret_stderr = node.run_command(cmd)
            K8Helper.triage(environment, (ret_code == 0), f"Failed to cleanup metrics-exporter container, error : {ret_stderr}")
    return

def test_deploy_exporter_docker_container(gpu_cluster, run_exporter_docker_container, environment):
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

def test_apply_exporter_config(gpu_cluster, run_exporter_docker_container, environment):
    global Logger

    # With reference config.json https://raw.githubusercontent.com/ROCm/device-metrics-exporter/refs/heads/main/example/config.json
    # Check for all metrics
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

def test_enable_profiler_metrics(gpu_cluster, run_exporter_docker_container, environment):
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

    K8Helper.triage(environment, (os.path.exists(config_json_file)), f"Failed to create profiler-metrics-config.json file")
    remote_file = "/tmp/etc/metrics/config.json"
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(config_json_file, remote_file)), 
                            f"Unable to upload profiler-metrics config.json")

    failed_endpoints = set()
    for node in gpu_cluster.cluster_nodes:
        if node.is_gpu_node():
            ret_code, ret_stdout, ret_stderr = node.http_get(5000, "metrics")
            if ret_code != 0:
                failed_endpoints.add(node.ip_address)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {node.ip_address}, stdout: {ret_stdout} stderr: {ret_stderr}")
            else:
                Logger.debug("Check for all profiler metrics in the output")
    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

    # Restore
    reference_cfg_json_file = os.path.join(environment.logdir, "reference-config.json")
    K8Helper.triage(environment, (os.path.exists(reference_cfg_json_file)), f"Failed to download reference config.json file")
    for node in gpu_cluster.cluster_nodes:
        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host
        if node.is_gpu_node():
            K8Helper.triage(environment, (node.put(reference_cfg_json_file, remote_file)), 
                            f"Unable to upload reference config.json")
