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
import lib.k8_util as k8_util
import lib.amdgpu as amdgpu
import lib.common as common
import lib.spec_util as spec_util
from k8.util import K8Helper

Logger = logging.getLogger("k8.test_driver_deviceplugin")

@pytest.fixture(scope="function", autouse=True)
def setup_testcase_info(request, environment):
    setattr(environment, 'current_tc_name', request.node.name)
    yield
    delattr(environment, 'current_tc_name')

@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment):
    global Logger
    if k8_util.is_helm_chart_healthy(gpu_cluster,
                                     release_name,
                                     environment.gpu_operator_namespace):
        Logger.info("gpu-operator helm-chart is already installed/running - skip rest of setup/fixture")
        yield
        return

    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    if ret_code != 0:
        k8_util.helm_cleanup(gpu_cluster, release_name, environment.gpu_operator_namespace)
    #k8_util.k8_delete_namespace(gpu_cluster, environment.gpu_operator_namespace)

    if images.get("gpu-operator.repo", None):
        k8_util.helm_add_repo(gpu_cluster, images.get("gpu-operator.repo-name"), images.get("gpu-operator.repo"))

    values_yaml = os.path.join(environment.logdir, f"values_{environment.gpu_operator_version}.yaml")
    if spec_util.generate_helmchart_deployment_config(environment.gpu_operator_version, images, values_yaml):
        Logger.debug(f"Generated values.yaml for helm-chart install command, {values_yaml}")
    else:
        values_yaml = None

    ret_code, ret_stdout, ret_stderr = k8_util.helm_install(gpu_cluster, release_name,
                                                            environment.gpu_operator_namespace,
                                                            images.get('gpu-operator.helm-chart', None),
                                                            environment.gpu_operator_version, values_yaml)
    if ret_code != 0:
        Logger.error(f"Failed to install helm chart for {release_name}")
        Logger.error(f"Stdout: {ret_stdout.strip()}")
        Logger.error(f"Stderr: {ret_stderr.strip()}")
    K8Helper.triage(environment, (ret_code == 0), f"Failed to install helm-chart for {release_name}")
    time.sleep(30)
    yield
    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to uninstall {release_name} helm-chart, error: {ret_stderr}")
    return

def install_deviceconfig(gpu_cluster, images, environment):
    global Logger

    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    class DeviceConfigCRInfo(object):
        pass

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : True,
            'metricsExporter.enable' : True,
        }

    if environment.gpu_operator_version not in ["v1.0.0", "v1.1.0"]:
        test_config['testRunner.enable'] = True
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfigs_by_hostname(test_config, gpu_cluster, gpu_nodes, 'multi-devcfg', environment.amdgpu_driver_spec)
    exporter_port_map = {}
    devicecfg_list = []
    if len(test_cfg_map) > 1:
        # Assign unique NodePorts for each deviceconfig instance
        for idx, cfg_name in enumerate(test_cfg_map.keys()):
            cfg = test_cfg_map[cfg_name]
            cfg['metricsExporter.nodePort'] = 32500 + idx * 100
            exporter_port_map[cfg['selector.value']] = cfg['metricsExporter.nodePort']
    else:
        for node in gpu_nodes:
            node_hostname = k8_util.k8_get_node_hostname(node)
            exporter_port_map[node_hostname] = 32500

    for spec_name, tcfg in test_cfg_map.items():
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")
        devicecfg_list.append(tcfg['metadata.name'])

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(gpu_cluster, environment, devicecfg_list)
    for devcfg in devicecfg_list:
        K8Helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devcfg_info = DeviceConfigCRInfo()
    setattr(devcfg_info, "test_cfg_map", test_cfg_map)
    setattr(devcfg_info, "exporter_port_map", exporter_port_map)
    setattr(devcfg_info, "devicecfg_list", devicecfg_list)
    return devcfg_info

@pytest.fixture(scope="module")
def deviceconfig_install(gpu_cluster, images, gpu_operator_install, environment):
    global Logger

    # cleanup
    device_cfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, None)
    for devcfg_name, _ in device_cfg_info.items():
        k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)

    devcfg_info = install_deviceconfig(gpu_cluster, images, environment)
    yield devcfg_info

    device_cfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, None)
    for devcfg_name, _ in device_cfg_info.items():
        k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
    return

def test_multi_deviceconfig_deploy(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # Watch for all pod creation
    '''
    test-deviceconfig-device-plugin-8f7px                        1/1     Running       0                 12d
    test-deviceconfig-metrics-exporter-27gq9                     2/2     Running       0                 12d
    test-deviceconfig-node-labeller-54vpd                        1/1     Running       0                 12d
    '''
    devicecfg_pods = [
        common.PodInfo('device-plugin', 1, 1),
        common.PodInfo('metrics-exporter', 1, 1),
        common.PodInfo('node-labeller', 1, 1),
    ]
    if environment.gpu_operator_version not in ["v1.0.0", "v1.1.0"]:
        devicecfg_pods.append(common.PodInfo('test-runner', 1, 1))

    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    time.sleep(30) # Wait for exporter to start working

    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        K8Helper.triage(environment, (service_name in endpoint_values),
                        f"No endpoint address found for {service_name}")
        K8Helper.triage(environment, (len(endpoint_values[service_name]) > 0),
                        f"No endpoint address found for {service_name}")
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")
