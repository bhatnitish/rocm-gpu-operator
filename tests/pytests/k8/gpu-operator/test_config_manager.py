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
import pprint
import pytest
import sys
import os
import time
import json
import logging
import random
import datetime
import yaml
import copy
import lib.common as common
import lib.k8_util as k8_util
import lib.spec_util as spec_util
import lib.metric_util as metric_util
import lib.amdgpu as amdgpu_util
from lib.util import K8Helper
from kubernetes import client, config, utils

Logger = logging.getLogger("k8.test_config_manager")
LogPrettyPrinter = pprint.PrettyPrinter(indent = 2)

debug_on_failure = K8Helper.triage
#def debug_on_failure(environment, condition, message):
#    if not condition:
#        pdb.set_trace()

@pytest.fixture(scope="module", autouse=True)
def setup_testcase_info(request, environment):
    setattr(environment, 'current_tc_name', request.node.name)
    K8Helper.delete_debug_pods(["default", environment.gpu_operator_namespace, environment.exporter_namespace])
    yield
    delattr(environment, 'current_tc_name')

@pytest.fixture(autouse=True, scope="module")
def skip_module(environment):
    if environment.gpu_operator_version in ["v1.0.0", "v1.1.0", "v1.2.0", "v1.2.1"]:
        pytest.skip(f"Skipping config-manager for current version {environment.gpu_operator_version}")
    return

@pytest.fixture(scope="module")
def add_tolerations(environment, effect="NoSchedule"):
    toleration_to_add = {
        "key": "amd-dcm",
        "operator": "Equal",
        "value": "up",
        "effect": effect
    }

    for ns in {"kube-system", "cert-manager", "kube-flannel"}:
        k8_util.k8_patch_tolerations(ns, toleration_to_add, tolerate_add=True)
    yield

    for ns in {"kube-system", "cert-manager", "kube-flannel"}:
        k8_util.k8_patch_tolerations(ns, toleration_to_add, tolerate_add=False)


@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment):
    global Logger
    if k8_util.is_helm_chart_healthy(gpu_cluster,
                                     environment.gpu_operator_namespace,
                                     release_name):
        Logger.info("gpu-operator helm-chart is already installed/running - skip rest of setup/fixture")
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
        Logger.error(f"Stdout: {ret_stdout.strip()}")
        Logger.error(f"Stderr: {ret_stderr.strip()}")
    debug_on_failure(environment, (ret_code == 0), f"Failed to install helm-chart for {release_name}")
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
    debug_on_failure(environment, (ret_code == 0), f"Failed to uninstall {release_name} helm-chart, error: {ret_stderr}")
    return

@pytest.fixture
def verify_events(gpu_cluster, environment, profile, amd_smi_collect):
    global Logger

    gpu_series = get_gpu_series(gpu_cluster, environment)
    if not gpu_series or 'MI2' in gpu_series:
        pytest.skip(f"testcase not supported")
    file_path = os.path.join("lib", "files", f"partitioning_check_{gpu_series}.yaml")
    with open(file_path) as fp:
        profiles = json.load(fp)
        if not profiles.get("gpu-config-profiles"):
            pytest.fail(f"check {file_path}, something wrong with the configmap")
        elif not profiles["gpu-config-profiles"].get(profile, False):
            pytest.skip(f"testcase not supported")

    before = k8_util.k8_get_events(namespace=environment.gpu_operator_namespace)
    yield
    after = k8_util.k8_get_events(namespace=environment.gpu_operator_namespace)

    before_events = before[1].items
    after_events = after[1].items

    # 1. Extract the unique UIDs from the 'before' list and put them in a set
    before_uids = {event.metadata.uid for event in before_events}

    # 2. Iterate through the 'after' list and find any event whose UID is NOT in the 'before' set
    Logger.info("Following are the events observed during this testcase:-")
    new_events = []
    flag = False
    for event in after_events:
        if event.metadata.uid not in before_uids:
            Logger.info(f"=============={event.metadata.uid}=================")
            Logger.info(f"{pprint.pformat(event.reason)}")
            Logger.info(f"{pprint.pformat(event.type)}")
            Logger.info(f"{pprint.pformat(event.involved_object.name)}")
            Logger.info(f"{pprint.pformat(event.message)}")
            if profile in event.message and "Success" in event.message:
                flag = True
    debug_on_failure(environment, "ail" not in event.message, f"Fail found in {event.message}")
    debug_on_failure(environment, flag,
                     f"Successful profile change has not happened with {profile}")


@pytest.fixture(scope="module")
def deviceconfig_install(gpu_cluster, images, gpu_operator_install, add_tolerations, environment):
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
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : True,
            'metricsExporter.enable' : True,
            'testRunner.enable' : False,
            'configManager.enable' : True,
        }
    test_config.update(images)
    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_nodes, 'config-manager', environment.amdgpu_driver_spec)
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
        debug_on_failure(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")
        devicecfg_list.append(tcfg['metadata.name'])

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, devicecfg_list)
    for devcfg in devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devcfg_info = DeviceConfigCRInfo()
    setattr(devcfg_info, "test_cfg_map", test_cfg_map)
    setattr(devcfg_info, "exporter_port_map", exporter_port_map)
    setattr(devcfg_info, "devicecfg_list", devicecfg_list)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('config-manager', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")

    yield devcfg_info

    cleanup_configmanager(environment, devcfg_info)
    device_cfg_info = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace, None)
    for devcfg_name, _ in device_cfg_info.items():
        k8_util.k8_delete_deviceconfig_cr(environment.gpu_operator_namespace, devcfg_name)
    return

def get_gpu_series(gpu_cluster, environment):
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    gpu_series = gpu_cluster.worker_nodes[0].gpu_series
    Logger.info(f"found gpu_series {gpu_series}")
    debug_on_failure(environment, gpu_series, f"didn't find gpu_series")
    return gpu_series

@pytest.fixture(scope="module")
def amd_smi_collect(gpu_cluster, gpu_operator_install, deviceconfig_install, environment):
    # Derive gpu information using amd-smi information
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # Watch for all pod creation
    '''
    test-deviceconfig-device-plugin-8f7px                        1/1     Running       0                 12d
    test-deviceconfig-metrics-exporter-27gq9                     2/2     Running       0                 12d
    '''
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    time.sleep(30) # Wait for exporter to start working
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_name = k8_util.k8_get_node_hostname(node)
        exporter_pod_name = k8_util.k8_get_pod_name("metrics-exporter", environment.gpu_operator_namespace, node_name)
        # Collect gpu information from the node
        cmd = [K8Helper.get_amd_smi_path(environment), "static", "--json"]
        ret_code, amd_smi_info, resp_stderr = k8_util.exec_command_in_pod(environment.gpu_operator_namespace,
                                                                          cmd, exporter_pod_name, "metrics-exporter-container")
        K8Helper.triage(environment, (ret_code == 0 and len(amd_smi_info) > 0),
                        f"Unable to collect amd-smi static information from node {node_name}, error : {resp_stderr}")
        amdgpu_util.extract_amdgpu_info(cluster_node, node, amd_smi_info)


@pytest.fixture(scope="module")
def create_configmap(deviceconfig_install, gpu_cluster, environment, amd_smi_collect):
    namespace = environment.gpu_operator_namespace
    configmap = "config-map-config-manager"

    gpu_series = get_gpu_series(gpu_cluster, environment)
    if gpu_series and 'MI2' in gpu_series:
        pytest.skip("skipping tests for gpu_series = {gpu_series}")

    file_path = os.path.join("lib", "files", f"partitioning_check_{gpu_series}.yaml")

    k8_util.k8_create_configmap(namespace, configmap, file_path)
    yield
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_configmap(namespace, configmap)

def cleanup_configmanager(environment, devcfg_info):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    labels_dict = {
                      "dcm.amd.com/gpu-config-profile" : None,
                      "dcm.amd.com/gpu-config-profile-state" : None
                  }
    for node in gpu_nodes:
        node_name = node['metadata']['labels']['kubernetes.io/hostname']
        k8_util.k8_label_node(node_name, labels_dict, overwrite=True)
        k8_util.k8_untaint_node(node_name)
    # Watch for all pod creation

    patch_body = {
        "spec": {
            "configManager": {
                "config": None
            }
        }
    }

    api_client = client.ApiClient()
    custom_objects_api = client.CustomObjectsApi(api_client)
    devcfg_map = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        try:
            custom_objects_api.patch_namespaced_custom_object(
                group="amd.com",
                version='v1alpha1',
                name=devcfg_name,
                namespace=environment.gpu_operator_namespace,
                plural='deviceconfigs',
                body=patch_body
            )
            print(f"Successfully patched")
        except client.ApiException as e:
            pytest.fail(f"Failed to patch custom object: {e}")
 

    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('config-manager', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")

 
def parse_amd_smi_json(environment, output, profile, gpu_series):
    global Logger
    factor_dict = {
            "SPX_NPS1": 1,
            "CPX_NPS1": 8,
            "CPX_NPS4": 8,
            "DPX_NPS2": 2,
            "DPX_NPS1": 2,
            "QPX_NPS1": 4,
            "QPX_NPS4": 4
    }
    factor = factor_dict[profile]
    uuid = None
    jsonout = json.loads(output.replace("'", '"'))
    gpus = len(jsonout)
    if "MI300" in gpu_series:
        if 'SPX' in profile:
            debug_on_failure(environment, len(jsonout) == 1, f"no. of GPUs should be 1, found {len(jsonout)}")
        elif 'CPX' in profile:
            debug_on_failure(environment, len(jsonout) == 8, f"no. of GPUs should be 8, found {len(jsonout)}")
    elif "MI350" in gpu_series:
        if 'SPX' in profile:
            debug_on_failure(environment, len(jsonout) == 8, f"no. of GPUs should be 8, found {len(jsonout)}")
        elif 'CPX' in profile:
            debug_on_failure(environment, len(jsonout) == 63, f"no. of GPUs should be 63, found {len(jsonout)}")
        elif 'QPX' in profile:
            debug_on_failure(environment, len(jsonout) == 32, f"no. of GPUs should be 32, found {len(jsonout)}")
        elif 'DPX' in profile:
            debug_on_failure(environment, len(jsonout) == 16, f"no. of GPUs should be 16, found {len(jsonout)}")
        else:
            pytest.fail(f"unknown profile {profile}")
    GPUs = {}
    partitions = {}
    for gpu in jsonout:
        i = gpu.get("gpu")
        this_uuid = gpu.get("uuid")
        if i % factor == 0 or i == 47:
             uuid = this_uuid

        partition_id = gpu.get("partition_id")
        debug_on_failure(environment, partition_id != None, f'didnt find partition_id in {pprint.pprint(gpu)}')
        partitions[i] = partition_id
        GPUs[i] = True
        #TODO Praveen kumar Shanmugam: That's a limitation from day 1. Iirc there is a tracking bug on swdev
        debug_on_failure(environment, this_uuid == uuid, f'didnt find uuid=={this_uuid} in {pprint.pprint(gpu)}')
        debug_on_failure(environment, gpu.get("node_id") != None, f'didnt find node_id in {pprint.pprint(gpu)}')
        debug_on_failure(environment, gpu.get("bdf") != None, f'didnt find bdf in {pprint.pprint(gpu)}')
        debug_on_failure(environment, gpu.get("kfd_id") != None, f'didnt find kfd_id in {pprint.pprint(gpu)}')
    Logger.info(f"profile is {profile} GPUS {pprint.pprint(GPUs)}")
    Logger.info(f"{pprint.pprint(partitions)}")




@pytest.mark.level11
def test_deviceconfig_config_manager_deploy(deviceconfig_install, environment):
    
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('config-manager', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")

def verify_gpu_capacity_status(environment, worker):
    i = 0
    while i < 10:
        cap, alloc = k8_util.k8_get_node_gpu_capacity(worker)
        if cap == alloc:
            return
        time.sleep(10)
        i = i + 1
    debug_on_failure(environment, i < 10,
                     f"capacity = allocatable {cap} != {alloc}")

def verify_no_label(environment, profile):
    i = 0
    while i < 30:
        ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
        if gpu_nodes and gpu_nodes[0]['metadata']['labels'].get('dcm.amd.com/gpu-config-profile', 'NA') == profile and \
                gpu_nodes[0]['metadata']['labels'].get('dcm.amd.com/gpu-config-profile-state', 'NA') == "failure":
            break
        i += 1
        time.sleep(2)
    debug_on_failure(environment, i < 30,
            f"didn't find {profile} or state=failure in labels:\n{pprint.pprint(gpu_nodes[0]['metadata']['labels'])}")

 
def verify_label(environment, profile):
    i = 0
    prof = "NA"
    stat = "unknown"
    while i < 30:
        ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
        if gpu_nodes:
            prof = gpu_nodes[0]['metadata']['labels'].get('dcm.amd.com/gpu-config-profile', 'NA')
            stat = gpu_nodes[0]['metadata']['labels'].get('dcm.amd.com/gpu-config-profile-state', 'unknown')
            if prof == profile and stat == "success":
                break
        i += 1
        time.sleep(10)
    debug_on_failure(environment, i < 30,
                     f"Didn't find gpu-config-profile-state=success, found {prof} or\
                       Didn't find gpu-config-profile={profile}, found {stat}")


def verify_logs(environment, log_msg_list, pod_str="config-manager", since="1800s", container=None, optional=False):
    global Logger
    global LogPrettyPrinter
    namespace = environment.gpu_operator_namespace

    i = 0
    ret_code, stdout, stderr = k8_util.k8_get_pod_logs(pod_str, namespace, since, container)

    flag = False
    for log_msg in log_msg_list:
        while log_msg not in stdout and i < 3:
            time.sleep(30)
            i = i + 1
            ret_code, stdout, stderr = k8_util.k8_get_pod_logs(pod_str, namespace, since, container)
        if optional and log_msg in stdout:
            flag = True
            break
        debug_on_failure(environment, log_msg in stdout,
                         f"didn't find {log_msg} in\n" + LogPrettyPrinter.pformat(stdout.split('\n')))
        if optional:
            debug_on_failure(environment, flag,
                             f"didn't find one of {log_msg_list} in\n" + LogPrettyPrinter.pformat(stdout.split('\n')))

def wait_for_pods(local_workload_ctxts):
    workload_pods = []
    status_info = None
    for ctxt in local_workload_ctxts:
        workload_pods.append(common.PodInfo(ctxt['pod_name'], 1, 1))

    for _ in range(2):
        status_info = k8_util.k8_check_pod_status("default", workload_pods)
        if "Pending" in status_info.values():
            time.sleep(5)
        else:
            break
    return status_info

#Unsupported compute partition combination
@pytest.mark.level12
@pytest.mark.parametrize("profile", ["SPX_NPS4", "invalidgpucount", "invalidmissingfields", "highgpucount_mostly_invalid"])
def test_negative_partitioning(gpu_cluster, deviceconfig_install, create_configmap, environment, profile, amd_smi_collect):
    global Logger
    gpu_series = get_gpu_series(gpu_cluster, environment)
    if not gpu_series or 'MI2' in gpu_series:
        pytest.skip(f"skipping tests for gpu_series = {gpu_series}")
    local_workload_ctxts = []
    namespace = environment.gpu_operator_namespace
    configmap = "config-map-config-manager"
    file_path = os.path.join("lib", "files", f"partitioning_check_{gpu_series}.yaml")
    with open(file_path) as fp:
        profiles = json.load(fp)
        if not profiles.get("gpu-config-profiles"):
            pytest.fail(f"check {file_path}, something wrong with the configmap")
        elif not profiles["gpu-config-profiles"].get(profile, False):
            pytest.skip(f"Profile {profile} is not supported for {gpu_series}. Refer {file_path}")
        else:
            memory = profiles["gpu-config-profiles"][profile]["profiles"][0]["memoryPartition"]
            partition = profiles["gpu-config-profiles"][profile]["profiles"][0]["computePartition"]

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    for node in gpu_nodes:
        worker = k8_util.k8_get_node_hostname(node)
        if node['metadata']['labels'].get('dcm.amd.com/gpu-config-profile'):
            Logger.info(f"Record existing profile = {node['metadata']['labels']['dcm.amd.com/gpu-config-profile']}")
        else:
            Logger.info("Didn't find any existing profile")
        if node['metadata']['labels'].get('dcm.amd.com/gpu-config-profile-state'):
            Logger.info(f"Record existing state = {node['metadata']['labels']['dcm.amd.com/gpu-config-profile-state']}")
        else:
            Logger.info("Didn't find any existing profile state")
    Logger.info(f"to be changed to profile: {profile}")

    patch_body = {
        "spec": {
            "configManager": {
                "config": {
                    "name": configmap
                },
                "configManagerTolerations": [
                    {
                        "effect": "NoSchedule",
                        "key": "amd-dcm",
                        "operator": "Equal",
                        "value": "up"
                    }
                ]
            }
        }
    }

    api_client = client.ApiClient()
    custom_objects_api = client.CustomObjectsApi(api_client)
    devcfg_map = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        try:
            custom_objects_api.patch_namespaced_custom_object(
                group="amd.com",
                version='v1alpha1',
                name=devcfg_name,
                namespace=namespace,
                plural='deviceconfigs',
                body=patch_body
            )
            Logger.info(f"Successfully patched with {patch_body}")
        except client.ApiException as e:
            debug_on_failure(environment, False, f"Failed to patch custom object: {e}")

    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('config-manager', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")


    labels_dict = {"dcm.amd.com/gpu-config-profile" : profile}
    for node in gpu_nodes:
        node_name = node['metadata']['labels']['kubernetes.io/hostname']
        k8_util.k8_taint_node(node_name, taint_add=True)
        k8_util.k8_label_node(node_name, labels_dict, overwrite=True)
        verify_no_label(environment, profile)

    verify_logs(environment,
                [
                    "Unsupported compute partition combination",
                    "Error occurred in PartitionGPU: partition failed"
                ],
                optional=True)
    verify_logs(environment, [f"Selected Profile {profile} found in the configmap"])

    for node in gpu_nodes:
        node_name = node['metadata']['labels']['kubernetes.io/hostname']
        k8_util.k8_untaint_node(node_name)


@pytest.mark.level11
@pytest.mark.parametrize("profile, workload", [
    ("QPX_NPS1", False),
    ("DPX_NPS2", True),
    ("SPX_NPS1", False),
    ("DPX_NPS1", True),
    ("CPX_NPS1", True),
    ("SPX_NPS1", True),
    ("DPX_NPS2", False),
    ("CPX_NPS4", False),
    ("QPX_NPS1", True)
])
def test_partitioning(
        gpu_cluster,
        deviceconfig_install,
        environment,
        request,
        create_configmap,
        verify_events,
        amd_smi_collect,
        profile,
        workload):
    global Logger
    gpu_series = get_gpu_series(gpu_cluster, environment)
    if not gpu_series or 'MI2' in gpu_series:
        pytest.skip(f"skipping tests for gpu_series = {gpu_series}")
    local_workload_ctxts = []
    namespace = environment.gpu_operator_namespace
    configmap = "config-map-config-manager"
    file_path = os.path.join("lib", "files", f"partitioning_check_{gpu_series}.yaml")
    with open(file_path) as fp:
        profiles = json.load(fp)
        if not profiles.get("gpu-config-profiles"):
            pytest.fail(f"check {file_path}, something wrong with the configmap")
        elif not profiles["gpu-config-profiles"].get(profile, False):
            pytest.skip(f"Profile {profile} is not supported for {gpu_series}. Refer {file_path}")
        else:
            memory = profiles["gpu-config-profiles"][profile]["profiles"][0]["memoryPartition"]
            partition = profiles["gpu-config-profiles"][profile]["profiles"][0]["computePartition"]
            GPUs = profiles["gpu-config-profiles"][profile]["profiles"][0]["numGPUsAssigned"]

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    for node in gpu_nodes:
        worker = k8_util.k8_get_node_hostname(node)
        if node['metadata']['labels'].get('dcm.amd.com/gpu-config-profile'):
            Logger.info(f"Record existing profile = {node['metadata']['labels']['dcm.amd.com/gpu-config-profile']}")
        else:
            Logger.info("Didn't find any existing profile")
        if node['metadata']['labels'].get('dcm.amd.com/gpu-config-profile-state'):
            Logger.info(f"Record existing state = {node['metadata']['labels']['dcm.amd.com/gpu-config-profile-state']}")
        else:
            Logger.info("Didn't find any existing profile state")
    Logger.info(f"to be changed to profile: {profile}")

    #add_tolerations(environment)

    if workload:
        def _start_workload():
            params = {
                "node_name" : worker,
                "num_gpu_reqd" : 1,
                "workload_selection" : "busybox-workload",
            }
            wl_ctxt = K8Helper.workload_operation(environment, K8Helper.WorkloadOp.START_WORKLOAD, **params)
            local_workload_ctxts.append(wl_ctxt)
        def _cleanup_workload():
            for ctxt in local_workload_ctxts:
                K8Helper.workload_operation(environment, K8Helper.WorkloadOp.STOP_WORKLOAD, **ctxt)
            return

        request.addfinalizer(_cleanup_workload)
        _start_workload()
        status_info = wait_for_pods(local_workload_ctxts)
        for status in status_info.values():
            debug_on_failure(environment, status == 'Running',
                             f"Workload not in RUNNING state, {pprint.pformat(status_info)}")


    patch_body = {
        "spec": {
            "configManager": {
                "config": {
                    "name": configmap
                },
                "configManagerTolerations": [
                    {
                        "effect": "NoSchedule",
                        "key": "amd-dcm",
                        "operator": "Equal",
                        "value": "up"
                    }
                ]
            }
        }
    }

    api_client = client.ApiClient()
    custom_objects_api = client.CustomObjectsApi(api_client)
    devcfg_map = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        try:
            custom_objects_api.patch_namespaced_custom_object(
                group="amd.com",
                version='v1alpha1',
                name=devcfg_name,
                namespace=namespace,
                plural='deviceconfigs',
                body=patch_body
            )
            Logger.info(f"Successfully patched with {patch_body}")
        except client.ApiException as e:
            debug_on_failure(environment, False, f"Failed to patch custom object: {e}")

    labels_dict = {"dcm.amd.com/gpu-config-profile" : profile}
    for node in gpu_nodes:
        node_name = node['metadata']['labels']['kubernetes.io/hostname']
        k8_util.k8_taint_node(node_name, taint_add=True)
        k8_util.k8_label_node(node_name, labels_dict, overwrite=True)
        verify_label(environment, profile)
    time.sleep(30)


    if workload:
        _start_workload()

        status_info = wait_for_pods(local_workload_ctxts)

        debug_on_failure(environment, status_info[local_workload_ctxts[-1]['pod_name']] == 'Pending',
                         f"Workload not in PENDING state, {pprint.pformat(local_workload_ctxts[-1])}")
        debug_on_failure(environment, status_info[local_workload_ctxts[0]['pod_name']] == 'Running',
                         f"Workload not in RUNNING state, {pprint.pformat(local_workload_ctxts[0])}")

    for node in gpu_nodes:
        node_name = node['metadata']['labels']['kubernetes.io/hostname']
        k8_util.k8_untaint_node(node_name)

    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('config-manager', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")

    match_logs = [
            f"Requested compute partition {partition}",
            f"Requested memory partition {memory}",
            f"Selected Profile {profile} found in the configmap",
            "Gpu-config-profile-state label added successfully",
            "AMD SMI shutdown successfully",
            "ServicesList"]

    for gpu in range(GPUs):
        match_logs.append(f"GPU ID {gpu}")

    verify_logs(environment, match_logs)


    pod_name = k8_util.k8_get_pod_name("config-manager", namespace, node_name)

    ret_code, output, resp_stderr = k8_util.exec_command_in_pod(namespace, ["amd-smi", "list"], pod_name)
    Logger.info(f"amd-smi list output:{output}")

    time.sleep(20)

    ret_code, output, resp_stderr = k8_util.exec_command_in_pod(namespace, ["amd-smi", "list", "--json"], pod_name)
    parse_amd_smi_json(environment, output, profile, gpu_series)


    if workload:
        status_info = wait_for_pods(local_workload_ctxts)
        flag = False
        for status in status_info.values():
            if status == 'Running':
                flag = True
                break
        debug_on_failure(environment, flag, 
                         f"found no running workloads in {pprint.pformat(local_workload_ctxts)}")
    Logger.info("verify events in the testcase")
    worker = k8_util.k8_get_node_hostname(gpu_nodes[0])
    verify_gpu_capacity_status(environment, worker)
 
@pytest.mark.level1
def test_deviceconfig_config_manager_disable(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # disable config-manager
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['configManager.enable'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        debug_on_failure(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    export_pods = [
        common.PodInfo('config-manager', 1, 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(environment.gpu_operator_namespace, export_pods)
    debug_on_failure(environment, not running_pods,
                              f"Some of the pods are still running post uninstallation - {running_pods}")
    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")

    # re-enable config-manager
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['configManager.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        debug_on_failure(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('config-manager', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")
