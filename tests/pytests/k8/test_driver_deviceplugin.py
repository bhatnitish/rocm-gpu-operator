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

Logger = logging.getLogger("k8.test_driver_deviceplugin")

@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment, k8_helper):
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
        Logger.error(f"Stdout: {ret_stdout.strip()}")
        Logger.error(f"Stderr: {ret_stderr.strip()}")
    k8_helper.assert_or_debug(ret_code == 0, f"Failed to install helm-chart for {release_name}", False)
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
    k8_helper.assert_or_debug(ret_code == 0, f"Failed to uninstall {release_name} helm-chart, error: {ret_stderr}", False)
    return

def install_deviceconfig(gpu_cluster, images, environment, k8_helper):
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
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0, "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : False,
            'metricsExporter.enable' : False,
            'testRunner.enable' : False,
        }

    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, 'device-plugin', environment.amdgpu_driver_spec)
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
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)
        devicecfg_list.append(tcfg['metadata.name'])

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, devicecfg_list)
    for devcfg in devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devcfg_info = DeviceConfigCRInfo()
    setattr(devcfg_info, "test_cfg_map", test_cfg_map)
    setattr(devcfg_info, "exporter_port_map", exporter_port_map)
    setattr(devcfg_info, "devicecfg_list", devicecfg_list)
    return devcfg_info

@pytest.fixture(scope="module")
def deviceconfig_install(gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger

    # cleanup
    device_cfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, None)
    for devcfg_name, _ in device_cfg_info.items():
        k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)

    devcfg_info = install_deviceconfig(gpu_cluster, images, environment, k8_helper)
    yield devcfg_info

    device_cfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, None)
    for devcfg_name, _ in device_cfg_info.items():
        k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
    return

def test_driver_deviceplugin_gpu_capacity_status(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger

    failed_nodes = {}
    for _ in range(3):
        ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
        k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
        for node in gpu_nodes:
            node_name = k8_util.k8_get_node_hostname(node)
            capacity = node['status']['capacity']
            if 'amd.com/gpu' in capacity:
                if capacity["amd.com/gpu"] == "0":
                    failed_nodes[node_name] = f"zero value for 'amd.com/gpu' in capacity"
            else:
                failed_nodes[node_name] = f"Missing 'amd.com/gpu' in capacity"

            allocatable = node['status']['allocatable']
            if 'amd.com/gpu' in allocatable:
                if allocatable["amd.com/gpu"] == "0":
                    failed_nodes[node_name] = f"zero value for 'amd.com/gpu' in allocatable"
            else:
                failed_nodes[node_name] = f"Missing 'amd.com/gpu' in allocatable"

            if len(failed_nodes) > 0:
                Logger.warn(f"Failed nodes for capacity/allocatable information : {failed_nodes} - retry after delay")
                failed_nodes.clear()
                time.sleep(10)
            else:
                break

    k8_helper.assert_or_debug(len(failed_nodes) == 0,
                              f"Some of the node(s) have incorrect capacity/allocatable info {failed_nodes}", 
                              environment.pause_on_failure)

def test_driver_deviceplugin_label(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)

    devicecfg_pods = [
        common.PodInfo('device-plugin', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)
    if environment.amdgpu_driver_spec["driver-deployment"] == "inbox":
        pytest.skip("Using inbox amdgpu driver - skip kmm label verification")

    '''
    Check for following label:
    beta.kmm.node.kubernetes.io/version-device-plugin.kube-amd-gpu.deviceconfig-clusterwide: 6.2.4
    '''
    label_missing = set()
    pattern = r"beta\.kmm\.node\.kubernetes\.io/version-device-plugin." + environment.gpu_operator_namespace + r"\.(.*?)"
    for _ in range(4):
        label_missing.clear()
        ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
        k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
        k8_helper.assert_or_debug(len(gpu_nodes), "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)
        for node in gpu_nodes:
            label_found = False
            for label, _ in node['metadata']['labels'].items():
                if re.match(pattern, label):
                    label_found = True
                    break
            if not label_found:
                label_missing.add(node['metadata']['name'])
        if len(label_missing) > 0:
            Logger.warn(f"Still waiting for device-plugin label for nodes : {label_missing}")
            time.sleep(30)

    k8_helper.assert_or_debug(len(label_missing) == 0,
                              f"One or more nodes missing kmm.version-device-plugin label : {label_missing}",
                              environment.pause_on_failure)

"""
def test_driver_deviceplugin_check_driver_version(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'driver.blacklist' : True,
            'driver.version' : driver_version,
            'devicePlugin.enableNodeLabeller' : True,
        }
    test_config.update(images)

    devcfg = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, test_config)
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, devcfg)

    def _cleanup_deviceconfigs():
        ret_code, ret_stderr, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg)
        if ret_code != 0:
            Logger.warn(f"Failed to delete/cleanup deviceconfig, stderr: {ret_stderr}")
        return
    request.addfinalizer(_cleanup_deviceconfigs)

    # check the version in the deviceconfig
    devcfg_name = devcfg['metadata']['name']
    devcfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
    device_config_version = devcfg_info[devcfg_name].get('spec').get('driver').get('version')
    Logger.info(f'Configured Version: {device_config_version}') 
    k8_helper.assert_or_debug(driver_version in device_config_version[1], f"Expected config_version: {config_version}, device_config: {device_config_version}", environment.pause_on_failure)
    
    # check the worker node driver version
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        version_module_label = f"kmm.node.kubernetes.io/version-module.{environment.gpu_operator_namespace}.{devcfg_name}"
        node_driver_version = node['metadata']['labels'][version_module_label]
        node_name = k8_util.k8_get_node_hostname(node)
        k8_helper.assert_or_debug(driver_version == node_driver_version, f"module version check failed for node {node_name}: {node_driver_version}", environment.pause_on_failure)
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        ret_code, resp_stdout, resp_stderr = worker_node.run_command("sudo dmesg -T | grep 'amdgpu version' | tail -1")
        Logger.info(f'{resp_stdout}')
        k8_helper.assert_or_debug(ret_code == 0, f"error getting dmesg from {node_name} {node_ip} {worker_node}", environment.pause_on_failure)
        k8_helper.assert_or_debug(resp_stdout and version_map[driver_version] in resp_stdout, f"can't find the right amdgpu version {resp_stdout}" , environment.pause_on_failure)

def test_driver_deviceplugin_blacklist_file_present(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version = version1, blacklist = True):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)

    # check the worker node blacklist
    filename = "/etc/modprobe.d/blacklist-amdgpu.conf"
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        k8_helper.assert_or_debug(amdgpu.check_host_blacklist_file(worker_node, expected = blacklist), f"blacklist file check failed on {node}:{worker_node}: {node_ip}", environment.pause_on_failure)

def test_driver_deviceplugin_apply_blacklist_false(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version = version1, blacklist = False):
    global Logger
    # check the worker node blacklist
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'driver.blacklist' : blacklist,
            'driver.version' : driver_version,
            'devicePlugin.enableNodeLabeller' : True,
        }
    test_config.update(images)

    devcfg = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, test_config)
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', 1, 1),
        common.PodInfo('node-labeller', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

def test_driver_deviceplugin_blacklist_file_absent(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version = version1, blacklist = False):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)

    # check the worker node blacklist
    filename = "/etc/modprobe.d/blacklist-amdgpu.conf"
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        k8_helper.assert_or_debug(amdgpu.check_host_blacklist_file(worker_node, expected = blacklist), f"blacklist file check failed on {node}:{worker_node}: {node_ip}", environment.pause_on_failure)

def test_driver_deviceplugin_revert_blacklist_true(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version = version1, blacklist = True):
    global Logger
    # check the worker node blacklist
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'driver.blacklist' : blacklist,
            'driver.version' : driver_version,
            'devicePlugin.enableNodeLabeller' : True,
        }
    test_config.update(images)

    devcfg = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, test_config)
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', 1, 1),
        common.PodInfo('node-labeller', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

def test_driver_deviceplugin_blacklist_file_present(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version = version1, blacklist = True):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)

    # check the worker node blacklist
    filename = "/etc/modprobe.d/blacklist-amdgpu.conf"
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        k8_helper.assert_or_debug(amdgpu.check_host_blacklist_file(worker_node, expected = blacklist), f"blacklist file check failed on {node}:{worker_node}: {node_ip}", environment.pause_on_failure)

def test_driver_deviceplugin_create_delete_workload_with_gpu(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    '''
    create the first workload pod requesting one gpu
    Assumption: no other workload pod with gpu has been instantiated
    '''
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    
    # Take one node with gpu
    gpu_node = gpu_nodes[0]
    node_name = k8_util.k8_get_node_hostname(gpu_node)

    # check gpu capacity
    initial_capacity, initial_allocatable = k8_util.k8_get_node_gpu_capacity(gpu_cluster, node_name)
    k8_helper.assert_or_debug(int(initial_capacity) != -1 or int(initial_allocatable) != -1, \
                      f'Err getting gpu capacity and allocatable values: initial_capacity: {initial_capacity} initial_allocatable: {initial_allocatable}', environment.pause_on_failure)

    # check if the node has allocatable gpus; if not fail
    k8_helper.assert_or_debug(initial_capacity != 0 or initial_allocatable != 0, f'no gpu available', environment.pause_on_failure)

    # create a workload requesting one gpu
    num_gpu_reqd = 1
    pod_name = "pytorch-gpu-pod-1"

    # launch 
    test_config = {
            'pod_name' : pod_name,
            'num_gpu' : num_gpu_reqd,
            'nodeSelector' : node_name,
        }
    wl_file = os.path.join(environment.sandbox_dir, f"{pod_name}.yaml")
    spec_util.generate_k8_workload_template(wl_file, test_config)
    Logger.info(f"Create the first workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_apply_cr(gpu_cluster, test_config, wl_file)

    devicecfg_pods = [
        common.PodInfo(pod_name, 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 10, total_attempts = 30)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    capacity, allocatable = k8_util.k8_get_node_gpu_capacity(gpu_cluster, node_name)
    k8_helper.assert_or_debug(int(capacity) != -1 or int(allocatable) != -1, \
                      f'Err getting gpu capacity and allocatable values: capacity: {capacity} allocatable: {allocatable}', environment.pause_on_failure)
    k8_helper.assert_or_debug(capacity == initial_capacity and allocatable == initial_allocatable, f'gpu status error: capacity, status initial/final :\
                                                                {initial_capacity},{initial_allocatable}/{capacity},{allocatable}', environment.pause_on_failure)

    # get allocated gpu status
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == num_gpu_reqd, f"requests {requests} is not requal to number of gpu requested: {num_gpu_reqd}", environment.pause_on_failure)
    Logger.info(f"gpu requested: {num_gpu_reqd}; alloc requests {requests}")

    # delete the workload
    Logger.info(f"Delete the first workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_cr(gpu_cluster, test_config, wl_file)
    num_gpu_reqd -= 1

    # get allocated gpu status
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == num_gpu_reqd, f"requests {requests} is not requal to number of gpu requested: {num_gpu_reqd}", environment.pause_on_failure)
    Logger.info(f"gpu requested: {num_gpu_reqd}; alloc requests {requests}")
    
def test_driver_deviceplugin_create_workload_with_max_gpu(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    '''
    Creates and deletes a workload with max number of gpus available on the node
    Get the capacity and create a workload with gpus equal to the capacity
    Check the gpu alloc status
    Delete the workload
    Check the gpu allow status again
    '''
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)

    # Take one node with gpu
    gpu_node = gpu_nodes[0]
    node_name = k8_util.k8_get_node_hostname(gpu_node)

    # check gpu capacity
    initial_capacity, initial_allocatable = k8_util.k8_get_node_gpu_capacity(gpu_cluster, node_name)
    k8_helper.assert_or_debug(int(initial_capacity) != -1 or int(initial_allocatable) != -1, \
                      f'Err getting gpu capacity and allocatable values: initial_capacity: {initial_capacity} initial_allocatable: {initial_allocatable}', environment.pause_on_failure)

    # check if the node has allocatable gpus; if not fail
    k8_helper.assert_or_debug(initial_capacity != 0 or initial_allocatable != 0, f'no gpu available', environment.pause_on_failure)

    # create a workload requesting all gpus
    num_gpu_reqd = int(initial_capacity)
    pod_name = "pytorch-gpu-pod-max"

    # launch 
    test_config = {
            'pod_name' : pod_name,
            'num_gpu' : num_gpu_reqd,
            'nodeSelector' : node_name,
        }
    wl_file = os.path.join(environment.sandbox_dir, f"{pod_name}.yaml")
    spec_util.generate_k8_workload_template(wl_file, test_config)
    Logger.info(f"Create the first workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_apply_cr(gpu_cluster, test_config, wl_file)

    devicecfg_pods = [
        common.PodInfo(pod_name, 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 10, total_attempts = 30)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    capacity, allocatable = k8_util.k8_get_node_gpu_capacity(gpu_cluster, node_name)
    k8_helper.assert_or_debug(int(capacity) != -1 or int(allocatable) != -1, \
                      f'Err getting gpu capacity and allocatable values: capacity: {capacity} allocatable: {allocatable}', environment.pause_on_failure)
    k8_helper.assert_or_debug(capacity == initial_capacity and allocatable == initial_allocatable, f'gpu status error: capacity, status initial/final :\
                                                                {initial_capacity},{initial_allocatable}/{capacity},{allocatable}', environment.pause_on_failure)

    # get allocated gpu status
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == num_gpu_reqd, f"requests {requests} is not requal to number of gpu requested: {num_gpu_reqd}", environment.pause_on_failure)
    Logger.info(f"gpu requested: {num_gpu_reqd}; alloc requests {requests}")

    # delete the workload
    Logger.info(f"Delete the first workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_cr(gpu_cluster, test_config, wl_file)
    num_gpu_reqd -= num_gpu_reqd

    # get allocated gpu status
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == num_gpu_reqd, f"requests {requests} is not requal to number of gpu requested: {num_gpu_reqd}", environment.pause_on_failure)
    Logger.info(f"gpu requested: {num_gpu_reqd}; alloc requests {requests}")

def test_driver_deviceplugin_create_workload_with_exceed_gpu_capacity(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    '''
    Create a workload requesting gpus > capacity
    Check if the pod is in unschedulable state
    Check gpu alloc status
    Delete the workload
    '''
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)

    # Take one node with gpu
    gpu_node = gpu_nodes[0]
    node_name = k8_util.k8_get_node_hostname(gpu_node)

    # check gpu capacity
    initial_capacity, initial_allocatable = k8_util.k8_get_node_gpu_capacity(gpu_cluster, node_name)
    k8_helper.assert_or_debug(int(initial_capacity) != -1 or int(initial_allocatable) != -1, \
                      f'Err getting gpu capacity and allocatable values: initial_capacity: {initial_capacity} initial_allocatable: {initial_allocatable}', environment.pause_on_failure)

    # check if the node has allocatable gpus; if not fail
    k8_helper.assert_or_debug(initial_capacity != 0 or initial_allocatable != 0, f'no gpu available', environment.pause_on_failure)

    # create a workload requesting max capacity + 1  gpus
    num_gpu_reqd = int(initial_capacity) + 1
    pod_name = "pytorch-gpu-pod-exceed"

    # launch 
    test_config = {
            'pod_name' : pod_name,
            'num_gpu' : num_gpu_reqd,
            'nodeSelector' : node_name,
        }
    wl_file = os.path.join(environment.sandbox_dir, f"{pod_name}.yaml")
    spec_util.generate_k8_workload_template(wl_file, test_config)
    Logger.info(f"Create a workload requesting gpus exceeding the capacity")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_apply_cr(gpu_cluster, test_config, wl_file)

    # the pod must be in unscheduble state
    # kubectl get pods pytorch-gpu-pod-exceed -n kube-amd-gpu -o json | jq .status 
    ret_code, resp_stdout, resp_stderr = gpu_cluster.k8_master.run_command(f"kubectl get pods {pod_name} \
                                                                            -n {environment.gpu_operator_namespace} -o json | jq .status")
    k8_helper.assert_or_debug(ret_code == 0, "Failed to get labels for node {node_name}: err: {resp_stderr}", environment.pause_on_failure)
    status_dict = json.loads(resp_stdout)
    Logger.info(f"Pod status: {status_dict}")
    k8_helper.assert_or_debug(status_dict["conditions"][0]["reason"] == "Unschedulable", f"Pod is not in Unschedulable state", environment.pause_on_failure)
    k8_helper.assert_or_debug("Insufficient amd.com/gpu" in status_dict["conditions"][0]["message"], f"reason doesn't reflect resource limit", environment.pause_on_failure)

    # get allocated gpu status
    Logger.info(f"Get gpu request status")
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == 0, f"after pod not schedulable, requests {requests} is not 0", environment.pause_on_failure)
    Logger.info(f"gpu requested: {num_gpu_reqd}; alloc requests {requests}")

    # delete the workload
    Logger.info(f"Delete the workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_cr(gpu_cluster, test_config, wl_file)
    num_gpu_reqd -= num_gpu_reqd

    # get allocated gpu status
    Logger.info(f"Get gpu request status")
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == num_gpu_reqd, f"after pod deletion, requests {requests} is not requal to number of gpu requested: {num_gpu_reqd}", environment.pause_on_failure)
    Logger.info(f"gpu requested: {num_gpu_reqd}; alloc requests {requests}")

def test_driver_deviceplugin_multiple_workloads_with_gpu(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    '''
    Create a workload wl1 with max gpu available
    Check pod status, alloc status
    Create a second workload wl2 with a gpu
    Check if the workload wl2 is unschedulable
    Delete the first workload wl1
    Second workload wl1 must be up and running now
    check pod status and alloc status
    '''

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    
    # Take one node with gpu
    gpu_node = gpu_nodes[0]
    node_name = k8_util.k8_get_node_hostname(gpu_node)

    # check gpu capacity
    initial_capacity, initial_allocatable = k8_util.k8_get_node_gpu_capacity(gpu_cluster, node_name)
    k8_helper.assert_or_debug(int(initial_capacity) != -1 or (initial_allocatable) != -1, \
                      f'Err getting gpu capacity and allocatable values: initial_capacity: {initial_capacity} initial_allocatable: {initial_allocatable}', environment.pause_on_failure)
    # check if the node has allocatable gpus; if not fail
    k8_helper.assert_or_debug(int(initial_capacity) != 0 or int(initial_allocatable) != 0, f'no gpu available', environment.pause_on_failure)

    # launch a workload wl1 with all available gpus
    wl1_num_gpu_reqd = int(initial_capacity)
    pod_name = "pytorch-gpu-pod-max"

    # launch 
    test_config = {
            'pod_name' : pod_name,
            'num_gpu' : wl1_num_gpu_reqd,
            'nodeSelector' : node_name,
        }
    wl1_file = os.path.join(environment.sandbox_dir, f"{pod_name}.yaml")
    spec_util.generate_k8_workload_template(wl1_file, test_config)
    Logger.info(f"Create the first workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_apply_cr(gpu_cluster, test_config, wl1_file)

    devicecfg_pods = [
        common.PodInfo(pod_name, 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 10, total_attempts = 30)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    # get allocated gpu status
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == wl1_num_gpu_reqd, f"requests {requests} is not requal to number of gpu requested: {wl1_num_gpu_reqd}", environment.pause_on_failure)
    Logger.info(f"gpu requested: {wl1_num_gpu_reqd}; alloc requests {requests}")

    # launch another workload wl2 requesting one gpu; should be in unschedulable state
    wl2_num_gpu_reqd = 1
    pod_name = "pytorch-gpu-pod-new"

    # launch 
    test_config = {
            'pod_name' : pod_name,
            'num_gpu' : wl2_num_gpu_reqd,
            'nodeSelector' : node_name,
        }
    wl2_file = os.path.join(environment.sandbox_dir, f"{pod_name}.yaml")
    spec_util.generate_k8_workload_template(wl2_file, test_config)
    Logger.info(f"Create the second workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_apply_cr(gpu_cluster, test_config, wl2_file)

    ret_code, resp_stdout, resp_stderr = gpu_cluster.k8_master.run_command(f"kubectl get pods {pod_name} \
                                                                            -n {environment.gpu_operator_namespace} -o json | jq .status")
    k8_helper.assert_or_debug(ret_code == 0, "Failed to get labels for node {node_name}: err: {resp_stderr}", environment.pause_on_failure)
    status_dict = json.loads(resp_stdout)
    Logger.info(f"Pod status: {status_dict}")
    k8_helper.assert_or_debug(status_dict["conditions"][0]["reason"] == "Unschedulable", f"Pod is not in Unschedulable state", environment.pause_on_failure)
    k8_helper.assert_or_debug("Insufficient amd.com/gpu" in status_dict["conditions"][0]["message"], f"reason doesn't reflect resource limit", environment.pause_on_failure)

    # delete workload wl1
    Logger.info(f"Delete the first workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_cr(gpu_cluster, test_config, wl1_file)

    # check workload wl2 status
    Logger.info(f"Check the status of the second workload with gpu")
    devicecfg_pods = [
        common.PodInfo(pod_name, 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    # get allocated gpu status
    Logger.info(f"Get gpu request status after second wl is running")
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == wl2_num_gpu_reqd, f"after pod deletion, requests {requests} is not requal to number of gpu requested: {wl2_num_gpu_reqd}", environment.pause_on_failure)
    Logger.info(f"gpu requested: {wl2_num_gpu_reqd}; alloc requests {requests}")

    # delete wl2
    Logger.info(f"Delete the second workload with gpu")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_cr(gpu_cluster, test_config, wl2_file)

    # get allocated gpu status
    Logger.info(f"Get gpu request status after second workload is also deleted")
    requests, limit = k8_util.k8_get_node_gpu_alloc_requests(gpu_cluster, node_name)
    k8_helper.assert_or_debug(requests != -1 or limit != -1, f"error getting allocate requests", environment.pause_on_failure)
    k8_helper.assert_or_debug(int(requests) == 0, f"after second pod deletion, requests {requests} is not 0 after deleting the second workload", environment.pause_on_failure)
    Logger.info(f"gpu requested: 0; alloc requests {requests}")

def test_driver_upgrade(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version=version2):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'driver.blacklist' : True,
            'driver.version' : driver_version,
            'devicePlugin.enableNodeLabeller' : True,
        }
    test_config.update(images)

    devcfg = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, test_config)
    # delete current deployment and add
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg)
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', 1, 1),
        common.PodInfo('node-labeller', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

def test_driver_version_post_upgrade(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version = version2):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)

    device_config = "test-deviceconfig"

    # check the version in the deviceconfig
    device_config_version = gpu_cluster.k8_master.run_command(f"kubectl get deviceconfigs {device_config} -n kube-amd-gpu -o yaml  | grep version:")
    Logger.info(f'Configured Version: {device_config_version}')
    k8_helper.assert_or_debug(driver_version in device_config_version[1], f"Expected config_version: {driver_version}, device_config: {device_config_version}", environment.pause_on_failure)

    # check the worker node driver version
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        node_name = k8_util.k8_get_node_hostname(node)
        ret_code, resp_stdout, resp_stderr = gpu_cluster.k8_master.run_command(f"kubectl get node {node_name} -o yaml | \
                                             grep version-module.{environment.gpu_operator_namespace}")
        Logger.info(f"err: {resp_stderr}")
        Logger.info(f"output: {resp_stdout}")
        k8_helper.assert_or_debug(driver_version in resp_stdout, f"module version check failed for node {node_name}: {resp_stdout}", environment.pause_on_failure)
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        ret_code, resp_stdout, resp_stderr = worker_node.run_command("sudo dmesg -T | grep 'amdgpu version' | tail -1")
        Logger.info(f'{resp_stdout}')
        k8_helper.assert_or_debug(ret_code == 0, f"error getting dmesg from {node_name} {node_ip} {worker_node}", environment.pause_on_failure)
        k8_helper.assert_or_debug(resp_stdout and version_map[driver_version] in resp_stdout, f"can't find the right amdgpu version {resp_stdout}", environment.pause_on_failure)

def test_driver_downgrade(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version=version1):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'driver.blacklist' : True,
            'driver.version' : driver_version,
            'devicePlugin.enableNodeLabeller' : True,
        }
    test_config.update(images)

    devcfg = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, test_config)
    # delete current deployment and add
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg)
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', 1, 1),
        common.PodInfo('node-labeller', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

def test_re_run_gpu_operator_driver_version_post_downgrade(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version=version1):
    global Logger
    test_gpu_operator_driver_version_post_upgrade(request, gpu_cluster, images, gpu_operator_install, environment, driver_version=version1)

def test_upgrade_driver_using_label(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version=version2):
    global Logger
    '''
    Upgrade driver using label update method
    '''
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        worker_node = gpu_cluster.get_worker_node(node_ip)
        node_name = k8_util.k8_get_node_hostname(node)
        ret_code, resp_stdout, resp_stderr = gpu_cluster.k8_master.run_command(f"kubectl label node {node_name} \
                  --overwrite kmm.node.kubernetes.io/version-module.kube-amd-gpu.test-device-config=driver_version")
        Logger.info(f"err: {resp_stderr}")
        Logger.info(f"output: {resp_stdout}")

    devicecfg_pods = [
        common.PodInfo('device-plugin', 1, 1),
        common.PodInfo('node-labeller', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

def test_re_run_gpu_operator_driver_version_post_upgrade(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper, driver_version=version2):
    global Logger
    test_gpu_operator_driver_version_post_upgrade(request, gpu_cluster, images, gpu_operator_install, environment, driver_version=version2)

def test_multi_deviceconfig_deploy(request, gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0,
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : True,
            'metricsExporter.enable' : True,
            'testRunner.enable' : True,
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, request.node.name, environment.amdgpu_driver_spec)
    def _cleanup_deviceconfigs():
        for spec_name, tcfg in test_cfg_map.items():
            ret_code, ret_stderr, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, spec_name)
            if ret_code != 0:
                Logger.warn(f"Failed to delete/cleanup deviceconfig, stderr: {ret_stderr}")
        return
    request.addfinalizer(_cleanup_deviceconfigs)

    if len(test_cfg_map) > 1:
        skip_sections = {'devicePlugin' : True, 'metricsExporter' : True, 'testRunner' : True}
    else:
        skip_sections = {}

    for spec_name, tcfg in test_cfg_map.items():
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg, skip_sections = skip_sections)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    if len(test_cfg_map) > 1:
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, test_config, skip_sections = {'driver' : True})
        test_cfg_map[request.node.name] = testcfg # for finalizer to do cleanup
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed create deviceconfig", environment.pause_on_failure)

    k8_helper.wait_kmm_worker_completion(gpu_cluster, environment)

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
        common.PodInfo('test-runner', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, gpu_nodes, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    time.sleep(30) # Wait for exporter to start working

    failed_endpoints = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        ret_code, ret_stdout, ret_stderr = cluster_node.http_get(32500, "metrics")
        if ret_code != 0:
            failed_endpoints.add(node_ip)
            Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}", environment.pause_on_failure)

"""
