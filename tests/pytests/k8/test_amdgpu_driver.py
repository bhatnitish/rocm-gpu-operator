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
import json
import time
import logging
import lib.k8_util as k8_util
import lib.amdgpu as amdgpu
import lib.common as common
import lib.spec_util as spec_util

pytest.skip(allow_module_level=True)
Logger = logging.getLogger("k8.test_k8_amdgpu_driver")

@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment, k8_helper):
    global Logger
    # Check if gpu-operator is installed and good to use
    if k8_util.is_helm_chart_healthy(gpu_cluster,
                                     release_name,
                                     environment.gpu_operator_namespace):
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
        # TODO: Get all pods - especially cert-manager status etc to triage failure
    k8_helper.assert_or_debug(ret_code == 0, f"Failed to install helm-chart for {release_name}", False)
    time.sleep(30)
    yield

    # Teardown
    time.sleep(20)
    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Failed to uninstall {release_name} helm-chart", False)

@pytest.fixture(scope="module")
def deviceconfig_deploy(gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0, "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : False,
            'metricsExporter.enable' : False,
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, 'amdgpu_driver_deviceconfig')

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
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    time.sleep(30) # Wait for exporter to start working
    yield

    def _cleanup_deviceconfigs():
        for spec_name, tcfg in test_cfg_map.items():
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stderr, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, cr_spec)
            if ret_code != 0:
                Logger.warn(f"Failed to delete/cleanup deviceconfig, stderr: {ret_stderr}")
        return

    _cleanup_deviceconfigs()

def test_k8_amdgpu_driver_check_kmm_status(request, gpu_cluster, images, gpu_operator_install, deviceconfig_deploy, environment, k8_helper):
    global Logger
    pass



def test_k8_amdgpu_driver_lsmod(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0, "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    failed_nodes = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        ret_code, resp_stdout, resp_stderr = worker_node.run_command("sudo lsmod | grep amdgpu")
        if ret_code != 0:
            Logger.error(f"Failed to get 'lsmod | grep amdgpu' for node {node_ip}")
            failed_nodes.add(node_ip)
        elif not resp_stdout:
            Logger.error(f"Missing stdout 'lsmod | grep amdgpu' for node {node_ip}")
            failed_nodes.add(node_ip)
        elif len(resp_stdout.split('\n')) == 0:
            Logger.error(f"No meaningful info from 'lsmod | grep amdgpu' output for node {node_ip}")
            failed_nodes.add(node_ip)
        # Check for line with amdgpu and check for non-zero usage count (TODO)
    k8_helper.assert_or_debug(len(failed_nodes) == 0,
                              f"lsmod parse for amdgpu failed on nodes {failed_nodes}", environment.pause_on_failure)
    return

def test_k8_amdgpu_driver_dmesg(request, gpu_cluster, images, gpu_operator_install, deviceconfig_deploy, environment, k8_helper):
    global Logger
    """
    Sample captured output

    '[   30.508627] [drm] amdgpu kernel modesetting enabled.',
    '[   30.508653] [drm] amdgpu version: 6.8.5',
    '[   30.508980] amdgpu: Virtual CRAT table created for CPU',
    '[   30.509016] amdgpu: Topology: Add CPU node',
    '[   30.526076] amdgpu: PeerDirect support was initialized successfully',
    '[   30.544650] amdgpu 0000:cc:00.0: BAR 6: can't assign [??? 0x00000000 flags 0x20000000] (bogus alignment)',
    '[   30.557961] amdgpu 0000:cc:00.0: amdgpu: Fetched VBIOS from ROM',
    '[   30.557990] amdgpu: ATOM BIOS: 113-D67301-059',
    '[   30.565275] amdgpu 0000:cc:00.0: amdgpu: Trusted Memory Zone (TMZ) feature not supported',
    '[   30.565323] amdgpu 0000:cc:00.0: amdgpu: MEM ECC is active.',
    '[   30.565331] amdgpu 0000:cc:00.0: amdgpu: SRAM ECC is active.',
    '[   30.565350] amdgpu 0000:cc:00.0: amdgpu: RAS INFO: ras initialized '
    'successfully, hardware ability[7ff7f] ras_mask[7ff7f]',
    '[   30.565391] amdgpu 0000:cc:00.0: amdgpu: VRAM: 65520M 0x0000020000000000 - 0x0000020FFEFFFFFF (65520M used)',
    '[   30.565405] amdgpu 0000:cc:00.0: amdgpu: GART: 512M 0x0000000000000000 - 0x000000001FFFFFFF',
    '[   30.569771] [drm] amdgpu: 65520M of VRAM memory ready',
    '[   30.570044] [drm] amdgpu: 257703M of GTT memory ready.',
    """

    TEST_MATCHINGS = [
            'amdgpu kernel modesetting enabled',
            'amdgpu version',
            'Virtual CRAT table created for CPU',
            'Topology: Add CPU node',
            #'PeerDirect support was initialized successfully', Seen only with MI200, failed on MI300 (FIXME)
            'VRAM memory ready',
            'GTT memory ready',
    ]

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes), "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    failed_nodes = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        ret_code, resp_stdout, resp_stderr = worker_node.run_command("sudo dmesg | grep amdgpu")
        if ret_code != 0:
            failed_nodes.add(node_ip)
            Logger.error(f"Failed to get 'dmesg | grep amdgpu' for node {node_ip}")
            continue

        # TODO: Check for line with amdgpu and check for non-zero usage count
        dmesg_lines = resp_stdout.split('\n')
        for test_match in TEST_MATCHINGS:
            found = False
            for line in dmesg_lines:
                if test_match in line.strip():
                    found = True
                    break
            if not found:
                failed_nodes.add(node_ip)
                Logger.error(f"Failed to find {test_match} in dmesg-output from node with gpu")
    k8_helper.assert_or_debug(len(failed_nodes) == 0,
                              f"Failed to check amdgpu info on dmesg for nodes {failed_nodes}",
                              environment.pause_on_failure)
    return

@pytest.mark.skip
def test_k8_amdgpu_driver_disable(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : False,
            'metricsExporter.enable' : False,
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, request.node.name)
    def _cleanup_deviceconfigs():
        for spec_name, tcfg in test_cfg_map.items():
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stderr, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, cr_spec)
            if ret_code != 0:
                Logger.warn(f"Failed to delete/cleanup device_config, stderr: {ret_stderr}")
        return
    request.addfinalizer(_cleanup_deviceconfigs)

    _cleanup_deviceconfigs() # Cleanup any previously deployed CRs

    devicecfg_list = []
    for spec_name, tcfg in test_cfg_map.items():
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr : {ret_stderr}", environment.pause_on_failure)
        devicecfg_list.append(tcfg['metadata.name'])

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, devicecfg_list)
    k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, gpu_nodes)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        ret_code, resp_stdout, resp_stderr = worker_node.run_command("sudo lsmod | grep amdgpu")
        k8_helper.assert_or_debug(ret_code == 0,
                                  f"Failed to get 'lsmod | grep amdgpu' for node {node_ip}",
                                  environment.pause_on_failure)
        if resp_stdout and len(resp_stdout.split('\n')) != 0:
            Logger.error(f"AMD/GPU driver is still loaded on {node_ip}, out:{resp_stdout}, err:{resp_stderr}")

    # Teardown (FIXME: Confirm that deleting CR is needed to unload driver - if this is a known limitation or an issue)
    _cleanup_deviceconfigs()
    running_pods = k8_util.k8_check_pod_terminated(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not running_pods,
                              f"Some of the pods are still running post uninstallation - {running_pods}",
                              environment.pause_on_failure)

    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        ret_code, resp_stdout, resp_stderr = worker_node.run_command("sudo lsmod | grep amdgpu")
        k8_helper.assert_or_debug(ret_code != 0,
                                  f"amdgpu driver is still loaded - 'lsmod | grep amdgpu' for node {node_ip}",
                                  environment.pause_on_failure)
        k8_helper.assert_or_debug(resp_stdout == '',
                                  f"AMD/GPU driver is still loaded on {node_ip}, out:{resp_stdout}, err:{resp_stderr}",
                                  environment.pause_on_failure)
    return
