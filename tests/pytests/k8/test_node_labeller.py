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
import sys
import os
import time
import json
import logging
import lib.k8_util as k8_util
import lib.spec_util as spec_util
import lib.common as common

#pytestmark = pytest.mark.skip("debugging")
Logger = logging.getLogger("k8.test_k8_node_labeller")

EXPECTED_LABELS = {
    "amd.com/gpu.device-id",
    "amd.com/gpu.family",
    "amd.com/gpu.simd-count",
    "amd.com/gpu.vram",
    "beta.amd.com/gpu.device-id",
    "beta.amd.com/gpu.family",
    "beta.amd.com/gpu.simd-count",
    "beta.amd.com/gpu.vram",
}

@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment, k8_helper):
    global Logger
    if k8_util.is_helm_chart_healthy(gpu_cluster, release_name, environment.gpu_operator_namespace):
        Logger.info(f"{release_name} helm-chart is already installed/running - skip rest of setup/fixture")
        return

    # cleanup
    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    if ret_code != 0:
        k8_util.helm_cleanup(gpu_cluster, release_name, environment.gpu_operator_namespace)
    #k8_util.k8_delete_namespace(gpu_cluster, environment.gpu_operator_namespace)

    if images.get("gpu-operator.repo", None):
        k8_util.helm_add_repo(gpu_cluster, images.get("gpu-operator.repo-name"), images.get("gpu-operator.repo"))

    values_yaml = os.path.join(environment.sandbox_dir, f"values_{environment.gpu_operator_version}.yaml")
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
    k8_helper.assert_or_debug(ret_code == 0, f"Failed to install helm-chart for {release_name}", False)
    time.sleep(30)
    yield
    time.sleep(20)
    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Failed to install {release_name} helm-chart error: {ret_stderr}", False)

def deviceconfig_deploy(gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0, "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : True,
            'metricsExporter.enable' : False,
            'testRunner.enable' : False,
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, 'test_runner_deviceconfig')

    devicecfg_list = []
    for spec_name, tcfg in test_cfg_map.items():
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)
        devicecfg_list.append(tcfg['metadata.name'])

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, devicecfg_list)
    k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, gpu_nodes)

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
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    time.sleep(30) # Wait for exporter to start working

    return test_cfg_map

def test_node_labeller_enable_flag(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger

    test_cfg_map = deviceconfig_deploy(gpu_cluster, images, gpu_operator_install, environment, k8_helper)
    def _cleanup_deviceconfigs():
        for spec_name, tcfg in test_cfg_map.items():
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stderr, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, cr_spec)
            if ret_code != 0:
                Logger.warn(f"Failed to delete/cleanup deviceconfig, stderr: {ret_stderr}")
        return
    request.addfinalizer(_cleanup_deviceconfigs)

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0,
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    # Check each worker node for annotations applied by node-labeller
    ret_code, node_info_list = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "", environment.pause_on_failure)
    for node_info in node_info_list:
        node_name = node_info["metadata"]["name"]
        k8_helper.assert_or_debug('metadata' in node_info,
                                  f"Metadata missing in node_info for {node_info}", environment.pause_on_failure)
        k8_helper.assert_or_debug('labels' in node_info['metadata'],
                                  f'Labels not found for node: {node_name}', environment.pause_on_failure)
        assigned_labels = set(filter(lambda x: 'amd.com' in x, node_info['metadata']['labels'].keys()))
        k8_helper.assert_or_debug(EXPECTED_LABELS.issubset(assigned_labels),
                                  f"Missing {EXPECTED_LABELS - assigned_labels} for node {node_name}", environment.pause_on_failure)

    # Now disable labeller
    for spec_name, tcfg in test_cfg_map.items():
        tcfg['devicePlugin.enableNodeLabeller'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0,
                                  "Failed apply CR with devicePlugin.enableNodeLabeller disabled", environment.pause_on_failure)

    labeller_pods = [
        common.PodInfo('node-labeller', 1, 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(gpu_cluster, environment.gpu_operator_namespace, labeller_pods)
    k8_helper.assert_or_debug(not running_pods,
                              f"Some of the pods are still running - {running_pods}", environment.pause_on_failure)

    # Check absense of annotations for each worker node after removal of node-labeller
    ret_code, node_info_list = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "", environment.pause_on_failure)
    for node_info in node_info_list:
        node_name = node_info["metadata"]["name"]
        k8_helper.assert_or_debug('metadata' in node_info,
                                  f"Metadata missing in node_info for {node_info}", environment.pause_on_failure)
        k8_helper.assert_or_debug('labels' in node_info['metadata'],
                                  f'Labels not found for node: {node_info["metadata"]["name"]}', environment.pause_on_failure)
        assigned_labels = list(filter(lambda x: 'amd.com' in x, node_info['metadata']['labels'].keys()))
        for exp_label in EXPECTED_LABELS:
            found = False
            for node_label in assigned_labels:
                if exp_label in node_label:
                    found = True
                    break
            k8_helper.assert_or_debug(not found,
                                      "Unexpected label {exp_label} assigned to node {node_name}", environment.pause_on_failure)

@pytest.mark.skip()
def test_node_labeller_check_labels(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    test_cfg_map = deviceconfig_deploy(gpu_cluster, images, gpu_operator_install, environment, k8_helper)
    def _cleanup_deviceconfigs():
        for spec_name, tcfg in test_cfg_map.items():
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stderr, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, cr_spec)
            if ret_code != 0:
                Logger.warn(f"Failed to delete/cleanup deviceconfig, stderr: {ret_stderr}")
        return
    request.addfinalizer(_cleanup_deviceconfigs)

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    for node in gpu_nodes:
        node_name = k8_util.k8_get_node_hostname(node)
        # expected labels list
        exp_label_list = ["amd.com/gpu.family", "amd.com/gpu.device-id", "amd.com/gpu.vram", "amd.com/gpu.simd-count"]
        # get node labels
        ret_code, resp_stdout, resp_stderr = gpu_cluster.k8_master.run_command(f"kubectl get node {node_name} -o json | jq .metadata.labels")
        k8_helper.assert_or_debug(ret_code == 0, "Failed to get labels for node {node_name}: err: {resp_stderr}", environment.pause_on_failure)
        labels_dict = json.loads(resp_stdout)
        Logger.info(f'labels: {labels_dict}') 
        for label in exp_label_list:
            Logger.info(f'Check label: {label}')
            k8_helper.assert_or_debug(labels_dict.get(label, False) != False, "", environment.pause_on_failure)
            k8_helper.assert_or_debug(labels_dict[label] != "", f'labels.{label}: labels_dict[label]', environment.pause_on_failure)
        
        k8_helper.assert_or_debug(labels_dict["amd.com/gpu.family"] == "AI", "", environment.pause_on_failure)
        k8_helper.assert_or_debug(int(labels_dict["amd.com/gpu.simd-count"]) > 0, "", environment.pause_on_failure)

        # check the device id and count
        Logger.info("Check device-id label is present with a count")
        device_id = labels_dict["amd.com/gpu.device-id"]
        device_id_count = labels_dict.get(f'beta.amd.com/gpu.device-id.{device_id}', False)
        Logger.info(f'amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}')
        k8_helper.assert_or_debug(device_id_count != False, "", environment.pause_on_failure)
        k8_helper.assert_or_debug(int(device_id_count) > 0, f'amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}', environment.pause_on_failure)

        # check beta labels
        beta_label_list = ['beta.amd.com/gpu.device-id', 
                           'beta.amd.com/gpu.family', 'beta.amd.com/gpu.simd-count', 'beta.amd.com/gpu.vram' ]
        for label in beta_label_list:
            Logger.info(f'Check label: {label}')
            k8_helper.assert_or_debug(labels_dict.get(label, False) != False, "", environment.pause_on_failure)
            k8_helper.assert_or_debug(labels_dict[label] != "", f'labels.{label}: labels_dict[label]', environment.pause_on_failure)
        k8_helper.assert_or_debug(int(labels_dict['beta.amd.com/gpu.simd-count']) > 0, "", environment.pause_on_failure)

        gpu_family = labels_dict['beta.amd.com/gpu.family']
        k8_helper.assert_or_debug(gpu_family == "AI", "", environment.pause_on_failure)
        gpu_family_count = labels_dict.get(f'beta.amd.com/gpu.family.{gpu_family}', False)
        Logger.info(f'beta.amd.com/gpu.family: {gpu_family}, beta.amd.com/gpu.family.{gpu_family}: {gpu_family_count}')
        k8_helper.assert_or_debug(gpu_family_count != False, "", environment.pause_on_failure)
        k8_helper.assert_or_debug(int(gpu_family_count) > 0, f'beta.amd.com/gpu.family: {gpu_family}, beta.amd.com/gpu.family.{gpu_family}: {gpu_family_count}', environment.pause_on_failure)

        # check the device id and count
        Logger.info("Check device-id label is present with a count")
        device_id = labels_dict["beta.amd.com/gpu.device-id"]
        device_id_count = labels_dict.get(f'beta.amd.com/gpu.device-id.{device_id}', False)
        Logger.info(f'beta.amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}')
        k8_helper.assert_or_debug(device_id_count != False and int(device_id_count) > 0, f'amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}', environment.pause_on_failure)

        # check vram
        # eg: 'beta.amd.com/gpu.vram': '64G', 'beta.amd.com/gpu.vram.64G': '1'
        Logger.info("Check gpu-vram label is present with a count")
        vram = labels_dict['beta.amd.com/gpu.vram']
        vram_count = labels_dict.get(f'beta.amd.com/gpu.vram.{vram}', False)
        Logger.info(f'beta.amd.com/gpu.vram: {vram}, beta.amd.com/gpu.vram.{vram}: {vram_count}')
        k8_helper.assert_or_debug(vram_count != False and  int(vram_count) > 0, f'beta.amd.com/gpu.vram: {vram}, beta.amd.com/gpu.vram.{vram}: {vram_count}', environment.pause_on_failure)

@pytest.mark.skip()
def test_gpu_operator_labels_check(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    test_cfg_map = deviceconfig_deploy(gpu_cluster, images, gpu_operator_install, environment, k8_helper)
    def _cleanup_deviceconfigs():
        for spec_name, tcfg in test_cfg_map.items():
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stderr, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, cr_spec)
            if ret_code != 0:
                Logger.warn(f"Failed to delete/cleanup deviceconfig, stderr: {ret_stderr}")
        return
    request.addfinalizer(_cleanup_deviceconfigs)

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    for node in gpu_nodes:
        node_name = k8_util.k8_get_node_hostname(node)
        # expected labels list
        exp_label_list = ["amd.com/gpu.family", "amd.com/gpu.device-id", "amd.com/gpu.vram", "amd.com/gpu.simd-count"]
        # get node labels
        ret_code, resp_stdout, resp_stderr = gpu_cluster.k8_master.run_command(f"kubectl get node {node_name} -o json | jq .metadata.labels")
        k8_helper.assert_or_debug(ret_code == 0, "Failed to get labels for node {node_name}: err: {resp_stderr}", environment.pause_on_failure)
        labels_dict = json.loads(resp_stdout)
        Logger.info(f'labels: {labels_dict}') 
        for label in exp_label_list:
            Logger.info(f'Check label: {label}')
            k8_helper.assert_or_debug(labels_dict.get(label, False) != False, "", environment.pause_on_failure)
            k8_helper.assert_or_debug(labels_dict[label] != "", f'labels.{label}: labels_dict[label]', environment.pause_on_failure)
        
        k8_helper.assert_or_debug(labels_dict["amd.com/gpu.family"] == "AI", "", environment.pause_on_failure)
        k8_helper.assert_or_debug(int(labels_dict["amd.com/gpu.simd-count"]) > 0, "", environment.pause_on_failure)

        # check the device id and count
        Logger.info("Check device-id label is present with a count")
        device_id = labels_dict["amd.com/gpu.device-id"]
        device_id_count = labels_dict.get(f'beta.amd.com/gpu.device-id.{device_id}', False)
        Logger.info(f'amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}')
        k8_helper.assert_or_debug(device_id_count != False, "", environment.pause_on_failure)
        k8_helper.assert_or_debug(int(device_id_count) > 0, f'amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}', environment.pause_on_failure)

        # check beta labels
        beta_label_list = ['beta.amd.com/gpu.device-id', 
                           'beta.amd.com/gpu.family', 'beta.amd.com/gpu.simd-count', 'beta.amd.com/gpu.vram' ]
        for label in beta_label_list:
            Logger.info(f'Check label: {label}')
            k8_helper.assert_or_debug(labels_dict.get(label, False) != False, "", environment.pause_on_failure)
            k8_helper.assert_or_debug(labels_dict[label] != "", f'labels.{label}: labels_dict[label]', environment.pause_on_failure)
        k8_helper.assert_or_debug(int(labels_dict['beta.amd.com/gpu.simd-count']) > 0, "", environment.pause_on_failure)

        gpu_family = labels_dict['beta.amd.com/gpu.family']
        k8_helper.assert_or_debug(gpu_family == "AI", "", environment.pause_on_failure)
        gpu_family_count = labels_dict.get(f'beta.amd.com/gpu.family.{gpu_family}', False)
        Logger.info(f'beta.amd.com/gpu.family: {gpu_family}, beta.amd.com/gpu.family.{gpu_family}: {gpu_family_count}')
        k8_helper.assert_or_debug(gpu_family_count != False, "", environment.pause_on_failure)
        k8_helper.assert_or_debug(int(gpu_family_count) > 0, f'beta.amd.com/gpu.family: {gpu_family}, beta.amd.com/gpu.family.{gpu_family}: {gpu_family_count}', environment.pause_on_failure)

        # check the device id and count
        Logger.info("Check device-id label is present with a count")
        device_id = labels_dict["beta.amd.com/gpu.device-id"]
        device_id_count = labels_dict.get(f'beta.amd.com/gpu.device-id.{device_id}', False)
        Logger.info(f'beta.amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}')
        k8_helper.assert_or_debug(device_id_count != False and int(device_id_count) > 0, f'amd.com/gpu.device-id: {device_id}, beta.amd.com/gpu.device-id.{device_id}: {device_id_count}', environment.pause_on_failure)

        # check vram
        # eg: 'beta.amd.com/gpu.vram': '64G', 'beta.amd.com/gpu.vram.64G': '1'
        Logger.info("Check gpu-vram label is present with a count")
        vram = labels_dict['beta.amd.com/gpu.vram']
        vram_count = labels_dict.get(f'beta.amd.com/gpu.vram.{vram}', False)
        Logger.info(f'beta.amd.com/gpu.vram: {vram}, beta.amd.com/gpu.vram.{vram}: {vram_count}')
        k8_helper.assert_or_debug(vram_count != False and  int(vram_count) > 0, f'beta.amd.com/gpu.vram: {vram}, beta.amd.com/gpu.vram.{vram}: {vram_count}', environment.pause_on_failure)
