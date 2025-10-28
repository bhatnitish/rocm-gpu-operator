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

import pytest
import pprint
import pdb
import sys
import os
import time
import json
import logging
import lib.k8_util as k8_util
import lib.spec_util as spec_util
import lib.common as common
from lib.util import K8Helper

#pytestmark = pytest.mark.skip("debugging")
Logger = logging.getLogger("k8.test_node_labeller")

@pytest.fixture(scope="function", autouse=True)
def setup_testcase_info(request, environment):
    setattr(environment, 'current_tc_name', request.node.name)
    yield
    delattr(environment, 'current_tc_name')

EXPECTED_GA_LABELS = {
    "amd.com/gpu.device-id",
    "amd.com/gpu.family",
    "amd.com/gpu.simd-count",
    "amd.com/gpu.vram",
}

EXPECTED_BETA_LABELS = {
    "beta.amd.com/gpu.device-id",
    "beta.amd.com/gpu.family",
    "beta.amd.com/gpu.simd-count",
    "beta.amd.com/gpu.vram",
}

@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment):
    global Logger
    if k8_util.is_helm_chart_healthy(gpu_cluster, release_name, environment.gpu_operator_namespace):
        Logger.info(f"{release_name} helm-chart is already installed/running - skip rest of setup/fixture")
        yield
        return

    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    if ret_code != 0:
        k8_util.helm_cleanup(gpu_cluster, release_name, environment.gpu_operator_namespace)
    #k8_util.k8_delete_namespace(environment.gpu_operator_namespace)

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
        Logger.error(f"Stdout: {ret_stdout}")
        Logger.error(f"Stderr: {ret_stderr}")
    K8Helper.triage(environment, (ret_code == 0), f"Failed to install helm-chart for {release_name}")
    time.sleep(30)
    yield
    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    # Uninstall gpu-operator helm-chart
    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to install {release_name} helm-chart error: {ret_stderr}")

@pytest.fixture(scope="module")
def deviceconfig_install(images, gpu_operator_install, environment):
    global Logger

    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    class DeviceConfigCRInfo(object):
        pass

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : True,
            'metricsExporter.enable' : False,
            'testRunner.enable' : False,
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_nodes, 'node_labeller', environment.amdgpu_driver_spec)
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
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")
        devicecfg_list.append(tcfg['metadata.name'])

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, devicecfg_list)
    for devcfg in devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devcfg_info = DeviceConfigCRInfo()
    setattr(devcfg_info, "test_cfg_map", test_cfg_map)
    setattr(devcfg_info, "exporter_port_map", exporter_port_map)
    setattr(devcfg_info, "devicecfg_list", devicecfg_list)
    yield devcfg_info

    device_cfg_info = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace, None)
    for devcfg_name, _ in device_cfg_info.items():
        k8_util.k8_delete_deviceconfig_cr(environment.gpu_operator_namespace, devcfg_name)
    return

def test_node_labeller_enable_flag(deviceconfig_install, environment):
    global Logger

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while collecting gpu-nodes")
    # Watch for all pod creation
    '''
    test-deviceconfig-device-plugin-8f7px                        1/1     Running       0                 12d
    test-deviceconfig-metrics-exporter-27gq9                     2/2     Running       0                 12d
    test-deviceconfig-node-labeller-54vpd                        1/1     Running       0                 12d
    '''
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('node-labeller', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # Check each worker node for annotations applied by node-labeller
    for node_info in gpu_nodes:
        node_name = node_info["metadata"]["name"]
        K8Helper.triage(environment, ('metadata' in node_info), f"Metadata missing in node_info for {node_info}")
        K8Helper.triage(environment, ('labels' in node_info['metadata']), f'Labels not found for node: {node_name}')
        assigned_labels = set(filter(lambda x: 'amd.com' in x, node_info['metadata']['labels'].keys()))
        K8Helper.triage(environment, (EXPECTED_GA_LABELS.issubset(assigned_labels)),
                        f"Missing {EXPECTED_GA_LABELS - assigned_labels} for node {node_name}")
        K8Helper.triage(environment, (EXPECTED_BETA_LABELS.issubset(assigned_labels)),
                        f"Missing {EXPECTED_BETA_LABELS - assigned_labels} for node {node_name}", expected_to_fail=True)

    # Now disable labeller
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['devicePlugin.enableNodeLabeller'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed apply CR with devicePlugin.enableNodeLabeller disabled")

    labeller_pods = [
        common.PodInfo('node-labeller', 1, 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(environment.gpu_operator_namespace, labeller_pods)
    K8Helper.triage(environment, not running_pods, f"Some of the pods are still running - {running_pods}")

    # Check absense of annotations for each worker node after removal of node-labeller
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Failed to get nodes from cluster")
    for node_info in gpu_nodes:
        node_name = node_info["metadata"]["name"]
        K8Helper.triage(environment, ('metadata' in node_info), f"Metadata missing in node_info for {node_info}")
        K8Helper.triage(environment, ('labels' in node_info['metadata']),
                        f'Labels not found for node: {node_info["metadata"]["name"]}')
        assigned_labels = list(filter(lambda x: 'amd.com' in x, node_info['metadata']['labels'].keys()))
        for exp_label in EXPECTED_GA_LABELS:
            found = False
            for node_label in assigned_labels:
                if exp_label in node_label:
                    found = True
                    break
            K8Helper.triage(environment, (not found), f"{exp_label} still assigned to node {node_name} after node-labeller is disabled")

        for exp_label in EXPECTED_BETA_LABELS:
            found = False
            for node_label in assigned_labels:
                if exp_label in node_label:
                    found = True
                    break
            K8Helper.triage(environment, (not found), f"{exp_label} still assigned to node {node_name} after node-labeller is disabled")

    # Re-enable node-labeller
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['devicePlugin.enableNodeLabeller'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('node-labeller', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

def test_node_labeller_check_labels(deviceconfig_install, environment):
    global Logger

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while collecting gpu-nodes")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['devicePlugin.enableNodeLabeller'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('node-labeller', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Failed to find amd/gpu nodes in the cluster")
    for node in gpu_nodes:
        node_name = k8_util.k8_get_node_hostname(node)
        # expected labels list
        exp_label_list = ["amd.com/gpu.family", "amd.com/gpu.device-id", "amd.com/gpu.vram", "amd.com/gpu.simd-count"]
        # get node labels
        labels = k8_util.k8_get_node_labels(node_name)
        K8Helper.triage(environment, (labels != None), "Failed to get labels for node {node_name}")
        labels_dict = labels
        Logger.info(f'labels: {labels_dict}') 
        for label in exp_label_list:
            Logger.info(f'Check label: {label}')
            K8Helper.triage(environment, (label in labels_dict.keys()), f"Missing label - {label}")
            K8Helper.triage(environment, (labels_dict[label] != ""), f'labels.{label}: labels_dict[label]')
        
        K8Helper.triage(environment, (labels_dict["amd.com/gpu.family"] == "AI"), "Incorrect value for label: amd.com/gpu.family")
        K8Helper.triage(environment, (int(labels_dict["amd.com/gpu.simd-count"]) > 0), "Incorrect value of amd.com/gpu.simd-count")

        # check the device id and count
        Logger.info("Check device-id label is present with a count")
        device_id = labels_dict["amd.com/gpu.device-id"]
        K8Helper.triage(environment, f'amd.com/gpu.device-id.{device_id}' in labels_dict.keys(),
                        f"Missing label: amd.com/gpu.device-id.{device_id}", expected_to_fail=True)
        device_id_count = labels_dict[f'amd.com/gpu.device-id.{device_id}']
        K8Helper.triage(environment, int(device_id_count) > 0,
                        f'amd.com/gpu.device-id: {device_id}, amd.com/gpu.device-id.{device_id}: {device_id_count}', expected_to_fail=True)

        # check beta labels
        beta_label_list = ['beta.amd.com/gpu.device-id', 
                           'beta.amd.com/gpu.family', 'beta.amd.com/gpu.simd-count', 'beta.amd.com/gpu.vram' ]
        for label in beta_label_list:
            Logger.info(f'Check label: {label}')
            K8Helper.triage(environment, (label in labels_dict.keys()), f"Missing label : {label}", expected_to_fail=True)
            K8Helper.triage(environment, (labels_dict[label] != None), f'labels.{label}: labels_dict[label]', expected_to_fail=True)
        K8Helper.triage(environment, (int(labels_dict['beta.amd.com/gpu.simd-count']) > 0),
                        "Invalid value for label: beta.amd.com/gpu.simd-count", expected_to_fail=True)

        gpu_family = labels_dict['beta.amd.com/gpu.family']
        K8Helper.triage(environment, (gpu_family == "AI"), f"Invalid value for label beta.amd.com/gpu.family:{gpu_family}", expected_to_fail=True)
        K8Helper.triage(environment, (f'beta.amd.com/gpu.family.{gpu_family}' in labels_dict.keys()),
                        f"Missing label: beta.amd.com/gpu.family.{gpu_family}", expected_to_fail=True)
        gpu_family_count = labels_dict[f"beta.amd.com/gpu.family.{gpu_family}"]
        K8Helper.triage(environment, (int(gpu_family_count) > 0),
                        f'beta.amd.com/gpu.family: {gpu_family}, beta.amd.com/gpu.family.{gpu_family}: {gpu_family_count}', expected_to_fail=True)

        # check the device id and count
        Logger.info("Check device-id label is present with a count")
        device_id = labels_dict["beta.amd.com/gpu.device-id"]
        device_id_count_label = f'beta.amd.com/gpu.device-id.{device_id}'
        K8Helper.triage(environment, (device_id_count_label in labels_dict.keys()), f"Missing {device_id_count_label}", expected_to_fail=True)
        device_id_count = labels_dict[f'beta.amd.com/gpu.device-id.{device_id}']
        K8Helper.triage(environment, (int(device_id_count) > 0),
                        f'amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}', expected_to_fail=True)

        # check vram
        # eg: 'beta.amd.com/gpu.vram': '64G', 'beta.amd.com/gpu.vram.64G': '1'
        Logger.info("Check gpu-vram label is present with a count")
        vram = labels_dict['beta.amd.com/gpu.vram']
        vram_label = f'beta.amd.com/gpu.vram.{vram}'
        K8Helper.triage(environment, (vram_label in labels_dict), f"Missing vram-label : {vram_label}", expected_to_fail=True)
        vram_count = labels_dict[vram_label]
        K8Helper.triage(environment, (int(vram_count) > 0),
                        f'beta.amd.com/gpu.vram: {vram}, beta.amd.com/gpu.vram.{vram}: {vram_count}', expected_to_fail=True)

