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
import lib.common as common
import lib.k8_util as k8_util
import lib.spec_util as spec_util
import lib.metric_util as metric_util
from k8.util import K8Helper

#pytestmark = pytest.mark.skip("debugging")
Logger = logging.getLogger("k8.test_test_runner")
LogPrettyPrinter = pprint.PrettyPrinter(indent = 2)

metrics_fields = {
      'GPU_ECC_UNCORRECT_SDMA'      : 0,
      'GPU_ECC_UNCORRECT_GFX'       : 0,
      'GPU_ECC_UNCORRECT_MMHUB'     : 0,
      'GPU_ECC_UNCORRECT_ATHUB'     : 0,
      'GPU_ECC_UNCORRECT_BIF'       : 0,
      'GPU_ECC_UNCORRECT_HDP'       : 0,
      'GPU_ECC_UNCORRECT_XGMI_WAFL' : 0,
      'GPU_ECC_UNCORRECT_DF'        : 0,
      'GPU_ECC_UNCORRECT_SMN'       : 0,
      'GPU_ECC_UNCORRECT_SEM'       : 0,
      'GPU_ECC_UNCORRECT_MP0'       : 0,
      'GPU_ECC_UNCORRECT_MP1'       : 0,
      'GPU_ECC_UNCORRECT_FUSE'      : 0,
      'GPU_ECC_UNCORRECT_UMC'       : 0,
      'GPU_ECC_UNCORRECT_MCA'       : 0,
      'GPU_ECC_UNCORRECT_VCN'       : 0,
      'GPU_ECC_UNCORRECT_JPEG'      : 0,
      'GPU_ECC_UNCORRECT_IH'        : 0,
      'GPU_ECC_UNCORRECT_MPIO'      : 0
}

#def debug_on_failure(environment, condition, message):
#    K8Helper.triage(environment, condition, message)
debug_on_failure = K8Helper.triage

@pytest.fixture(scope="module", autouse=True)
def setup_testcase_info(request, environment):
    setattr(environment, 'current_tc_name', request.node.name)
    yield
    delattr(environment, 'current_tc_name')

@pytest.fixture(autouse=True, scope="module")
def skip_module(environment):
    if environment.gpu_operator_version in ["v1.0.0", "v1.1.0"]:
        pytest.skip(f"Skipping test-runner for current version {environment.gpu_operator_version}")
    return

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
    debug_on_failure(environment, (ret_code == 0), f"Failed to install helm-chart for {release_name}")
    time.sleep(30)
    yield
    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    # Uninst-operator helm-chart
    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    debug_on_failure(environment, (ret_code == 0), f"Failed to uninstall {release_name} helm-chart, error: {ret_stderr}")
    return

@pytest.fixture(scope="module")
def deviceconfig_install(gpu_cluster, images, gpu_operator_install, environment):
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
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : False,
            'metricsExporter.enable' : True,
            'testRunner.enable' : True,
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, 'test_runner', environment.amdgpu_driver_spec)
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
        debug_on_failure(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")
        devicecfg_list.append(tcfg['metadata.name'])

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(gpu_cluster, environment, devicecfg_list)
    for devcfg in devicecfg_list:
        K8Helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devcfg_info = DeviceConfigCRInfo()
    setattr(devcfg_info, "test_cfg_map", test_cfg_map)
    setattr(devcfg_info, "exporter_port_map", exporter_port_map)
    setattr(devcfg_info, "devicecfg_list", devicecfg_list)
    yield devcfg_info

    device_cfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, None)
    for devcfg_name, _ in device_cfg_info.items():
        k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
    return

@pytest.mark.level1
def test_deviceconfig_test_runner_deploy(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
        common.PodInfo('test-runner', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")

    '''
    failed_endpoints = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        ret_code, ret_stdout, ret_stderr = cluster_node.http_get(32500, "metrics")
        if ret_code != 0:
            failed_endpoints.add(node_ip)
            Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")

    debug_on_failure(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")
    '''

@pytest.mark.level1
def test_deviceconfig_test_runner_disable(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # disable test-runner
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['testRunner.enable'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        debug_on_failure(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    export_pods = [
        common.PodInfo('test-runner', 1, 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(gpu_cluster, environment.gpu_operator_namespace, export_pods)
    debug_on_failure(environment, not running_pods,
                     f"Some of the pods are still running post uninstallation - {running_pods}")
    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    # re-enable test-runner
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['testRunner.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        debug_on_failure(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    # Watch for all pod creation
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
        common.PodInfo('test-runner', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

@pytest.mark.level1
def test_deviceconfig_testrunner_disable_exporter(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # disable exporter and check for metrics
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        debug_on_failure(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    export_pods = [
        common.PodInfo('test-runner', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(gpu_cluster, environment.gpu_operator_namespace, export_pods)
    debug_on_failure(environment, not running_pods, f"Some of the pods are still running post uninstallation - {running_pods}")
    devplugin_pods = [
        common.PodInfo('device-plugin', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devplugin_pods)
    debug_on_failure(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    # Re enable exporter and check for test-runner
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        debug_on_failure(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
        common.PodInfo('test-runner', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    debug_on_failure(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

#Verify gpu capacity and allocated is correct. TODO - more checks
"""
def verify_gpu_capacity_status(gpu_cluster, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "gpu-operator failed to find amd/gpu nodes in the cluster")
    for node in gpu_nodes:
        node_name = k8_util.k8_get_node_hostname(node)
        # get status.capacity
        ret_code, resp_stdout, resp_stderr = gpu_cluster.k8_master.run_command(f"kubectl get node {node_name} -o json | jq .status.capacity")
        debug_on_failure(environment, (ret_code == 0), "Failed to get labels for node {node_name}: err: {resp_stderr}")
        capacity_dict = json.loads(resp_stdout)
        Logger.info(f'status.capacity: {capacity_dict}')
        debug_on_failure(environment, (capacity_dict["amd.com/gpu"] != "0"), f'gpu capacity status: {capacity_dict["amd.com/gpu"]}')
                                                                                                                                                                              # get status.allocatable
        ret_code, resp_stdout, resp_stderr = gpu_cluster.k8_master.run_command(f"kubectl get node {node_name} -o json | jq .status.allocatable")
        debug_on_failure(environment, (ret_code == 0), "Failed to get labels for node {node_name}: err: {resp_stderr}")
        allocatable_dict = json.loads(resp_stdout)
        Logger.info(f'status.allocatable: {allocatable_dict}')
        debug_on_failure(environment, (allocatable_dict["amd.com/gpu"] != "0"), f'gpu allocatable status: allocatable_dict["amd.com/gpu"]')
        debug_on_failure(environment, (allocatable_dict["amd.com/gpu"] == capacity_dict["amd.com/gpu"]),
                         f'capacity and alloc gpu values not equal')
        Logger.info(f'amd.com/gpu capacity: {capacity_dict["amd.com/gpu"]}, amd.com/gpu allocatable {allocatable_dict["amd.com/gpu"]}')
"""

def update_metrics_exporter_configmap(config_map):

    # Generate set of config-maps in the k8 cluster with different set of labels and metrics
    sample_size = random.randint(4,len(metrics_fields.keys())-1)
    error_list = random.sample(metrics_fields.keys(), sample_size)

    health_thresholds_dict = {}
    for error in error_list:
        health_thresholds_dict.update({error: metrics_fields.get(error) + random.randint(5,10)})

    config_map.update(
        {"GPUConfig": { "HealthThresholds": health_thresholds_dict }}
    )

def update_test_runner_configmap(recipe, worker, config_map=dict()):
    config_map.update(
        {"TestConfig": {
            "GPU_HEALTH_CHECK": {
                "TestLocationTrigger": {
                    worker: {
                        "TestParameters": {
                            "AUTO_UNHEALTHY_GPU_WATCH": {
                                "TestCases": [
                                    {
                                        "Recipe": recipe,
                                        "Iterations": 1,
                                        "StopOnFailure": True,
                                        "TimeoutSeconds": 600
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }}
    )


def create_configmap(request, gpu_cluster, deviceconfig_install, environment, recipe, worker, config_map):
    global Logger
    global LogPrettyPrinter
    configmap_name = "config"
    configmap_file = os.path.join(environment.logdir, f"{configmap_name}.json")
    with open(configmap_file, "w") as fp:
        fp.write(json.dumps(config_map, indent=4))

    # Delete if there is any previous instance with same name
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_configmap(gpu_cluster,
								   environment.gpu_operator_namespace,
								   configmap_name)
    Logger.info(f"Result of configmap delete operation, ret_code:{ret_code}, ret_stdout: {ret_stdout.strip()}, err: {ret_stderr.strip()}")
    # ignore ret_code
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_configmap(gpu_cluster,
                                                                   environment.gpu_operator_namespace,
                                                                   configmap_name,
                                                                   configmap_file)
    debug_on_failure(environment, (ret_code == 0),
                     f"Failed to create configmap {configmap_name} for {configmap_file}, err: {ret_stderr.strip()}")

    def _cleanup_configmap():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_configmap(gpu_cluster,
                                                                       environment.gpu_operator_namespace,
                                                                       configmap_name)
        if ret_code != 0:
            Logger.warn(f"Failed to delete test runner configmap {configmap_name}")
        return

    request.addfinalizer(_cleanup_configmap)

    # re-enable test-runner
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['testRunner.enable'] = True
        tcfg['testRunner.config'] = configmap_name
        tcfg['metricsExporter.config'] = configmap_name
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        #TODO should we be using modify OR create? For cmdline modify is defaulting to create
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        #ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, cr_spec)
        debug_on_failure(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    # Watch for all pod creation
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
        common.PodInfo('test-runner', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
    debug_on_failure(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    Logger.info(f"This node {worker} will be tainted")
    # TODO figure out timing on this testcases
    #k8_util.k8_taint_node(gpu_cluster, worker)

def verify_logs(gpu_cluster, environment, log_msg_list, pod_str="test-runner", since="180s", switch="and", negate=False):
    global Logger
    global LogPrettyPrinter
    namespace = environment.gpu_operator_namespace

    i = 0
    ret_code, stdout, stderr = k8_util.k8_get_pod_logs(gpu_cluster, pod_str, namespace, since)

    if negate:
        for log_msg in log_msg_list:
            debug_on_failure(environment, (log_msg not in stdout),
                             f"found {log_msg} in\n" + LogPrettyPrinter.pformat(stdout.split('\n')))
    elif switch == "or":
        while i < 4:
            for log_msg in log_msg_list:
                if log_msg in stdout:
                    return
            time.sleep(30)
            i = i + 1
            ret_code, stdout, stderr = k8_util.k8_get_pod_logs(gpu_cluster, pod_str, namespace, since)
        debug_on_failure(environment, False, f"didn't find any of {log_msg_list} in\n" + LogPrettyPrinter.pformat(stdout.split('\n')))
    else:
        for log_msg in log_msg_list:
            while log_msg not in stdout and i < 4:
                time.sleep(30)
                i = i + 1
                ret_code, stdout, stderr = k8_util.k8_get_pod_logs(gpu_cluster, pod_str, namespace, since)
            debug_on_failure(environment, (log_msg in stdout),
                             f"didn't find {log_msg} in\n" + LogPrettyPrinter.pformat(stdout.split('\n')))

def verify_events(gpu_cluster, namespace, pod_name="test-runner"):
    global Logger
    global LogPrettyPrinter
    #cmd = f"kubectl get events -n {namespace}" + " -o=jsonpath='{.items[?(@.source.component==\"amd-test-runner\")]}' | jq -r .message | jq ."
    #Logger.debug(LogPrettyPrinter.pformat(gpu_cluster.k8_master.run_command(cmd)))

    events = k8_util.k8_get_events(gpu_cluster, namespace, k8_util.k8_get_pod_name(gpu_cluster, pod_name, namespace))
    for event in events[1].items:
        Logger.debug(LogPrettyPrinter.pformat(f"{event.involved_object.name}\n{event.metadata.labels}\n{event.message}"))
    #Logger.debug(LogPrettyPrinter.pformat(gpu_cluster.k8_master.run_command(f"kubectl get events -n {namespace}")))


#@pytest.mark.parametrize("recipe", ["babel", "gpup_single", "gst_single", "iet_single"])
@pytest.mark.level3
@pytest.mark.parametrize("recipe", ["babel"])
def test_deviceconfig_unhealthy(request, gpu_cluster, deviceconfig_install, environment, recipe):
    namespace = environment.gpu_operator_namespace
    global Logger
    global LogPrettyPrinter
    global metrics_fields
    # Generate set of config-maps in the k8 cluster with different set of labels and metrics
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    gpu_node = gpu_nodes[0]
    worker = k8_util.k8_get_node_hostname(gpu_node)

    configmap = {}
    update_test_runner_configmap(recipe, worker, configmap)
    create_configmap(request, gpu_cluster, deviceconfig_install, environment, recipe, worker, configmap)
    sample_size = random.randint(1,len(metrics_fields.keys())-1)
    error_list = random.sample(metrics_fields.keys(), sample_size)
    thresholds = []
    for error in error_list:
        thresholds.append(metrics_fields.get(error) + random.randint(1,10))

    verify_logs(gpu_cluster, environment, ["serving requests on"], "metrics-exporter")
    time.sleep(30)
    k8_util.k8_metrics_error(gpu_cluster, thresholds, error_list, environment.gpu_operator_namespace)

    debug_on_failure(environment, 
                     (k8_util.k8_get_node_health(gpu_cluster, worker, environment.gpu_operator_namespace) == "unhealthy"),
                     f"result of kubectl describe node $NODE_NAME | grep unhealthy")
    Logger.info(f"This workload should not get created, state = Pending? or Running?")
    time.sleep(10) # give some delay

    local_workload_ctxts = []
    def _cleanup():
        for ctxt in local_workload_ctxts:
            K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.STOP_WORKLOAD, workload_config=ctxt)
        k8_util.k8_metrics_error(gpu_cluster, [0] * sample_size, error_list, environment.gpu_operator_namespace)
        return
    request.addfinalizer(_cleanup)

    wl_ctxt = K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.START_WORKLOAD, node_name=worker)
    local_workload_ctxts.append(wl_ctxt)
    debug_on_failure(environment, (wl_ctxt['podStatus'] == K8Helper.PodStatus.PENDING),
                     f"Workload not in PENDING state, {wl_ctxt}")

    Logger.info(f"Test runner worker logs\n===================\n")
    ret_code, stdout, stderr = k8_util.k8_get_pod_logs(gpu_cluster, "test-runner", environment.gpu_operator_namespace)
    Logger.info(f"Test runner worker logs\n==================={stdout}\n")

    Logger.info(f"found {recipe} in test runner logs\n{LogPrettyPrinter.pformat(stdout)}\n")

    time.sleep(30)
    verify_logs(gpu_cluster, environment, ["found existing completed test, skip for now"])
    verify_logs(gpu_cluster, environment, ["found GPU with unhealthy state"])
    verify_events(gpu_cluster, namespace)

    debug_on_failure(environment,
                     (k8_util.k8_get_node_health(gpu_cluster, worker, environment.gpu_operator_namespace) == "unhealthy"),
                     f"result of kubectl describe node $NODE_NAME | grep unhealthy")

    match  = []
    for i in range(sample_size):
        match.append(f"unhealthy for ecc field [{error_list[i]}] error crossing threshold {metrics_fields.get(error_list[i])}, current value {thresholds[i]}")
    verify_logs(gpu_cluster, environment, match, pod_str="metrics-exporter")

    #TODO figure out later
    #k8_util.k8_untaint_node(gpu_cluster, worker)

    k8_util.k8_metrics_error(gpu_cluster, [0] * sample_size, error_list, environment.gpu_operator_namespace)

    verify_logs(gpu_cluster, environment, [f"s are healthy"])

    Logger.info(f"This workload should get created, since the node {worker}, is now untainted")
    verify_events(gpu_cluster, namespace)

@pytest.mark.level3
@pytest.mark.parametrize("recipe", ["pbqt_single"])
def test_workload_running_make_node_unhealthy(request, gpu_cluster, deviceconfig_install, environment, recipe):
    #recipe = "babel"
    namespace = environment.gpu_operator_namespace
    global Logger
    global LogPrettyPrinter
    global metrics_fields
    # Generate set of config-maps in the k8 cluster with different set of labels and metrics
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    gpu_node = gpu_nodes[0]
    worker = k8_util.k8_get_node_hostname(gpu_node)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
	    common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
	    common.PodInfo('test-runner', len(gpu_nodes), 1),
    ]

    configmap = {}
    update_test_runner_configmap(recipe, worker, configmap)
    create_configmap(request, gpu_cluster, deviceconfig_install, environment, recipe, worker, configmap)
    sample_size = random.randint(1,len(metrics_fields.keys())-1)
    error_list = random.sample(metrics_fields.keys(), sample_size)
    thresholds = []
    for error in error_list:
        thresholds.append(metrics_fields.get(error) + random.randint(1,10))

    Logger.info(f"This workload should get created")
    local_workload_ctxts = []
    def _cleanup():
        for ctxt in local_workload_ctxts:
            K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.STOP_WORKLOAD, workload_config=ctxt)
        k8_util.k8_metrics_error(gpu_cluster, [0] * sample_size, error_list, environment.gpu_operator_namespace)
        return
    request.addfinalizer(_cleanup)
    verify_logs(gpu_cluster, environment, ["serving requests on"], "metrics-exporter")
    wl_ctxt = K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.START_WORKLOAD, node_name=worker)
    local_workload_ctxts.append(wl_ctxt)
    debug_on_failure(environment, (wl_ctxt['podStatus'] == K8Helper.PodStatus.RUNNING),
                     f"Workload not in running state, {wl_ctxt}")
    k8_util.k8_metrics_error(gpu_cluster, thresholds, error_list, environment.gpu_operator_namespace)

    Logger.info(f"Test runner worker logs\n===================\n")
    ret_code, stdout, stderr = k8_util.k8_get_pod_logs(gpu_cluster, "test-runner", environment.gpu_operator_namespace)
    Logger.info(f"Test runner worker logs\n==================={stdout}\n")
    time.sleep(30)
    verify_events(gpu_cluster, namespace)

    verify_logs(gpu_cluster, environment,
               [f'AssociatedWorkload:"pod : pytorch-gpu-pod-1, namespace : {environment.gpu_operator_namespace}'])
    debug_on_failure(environment, k8_util.k8_get_node_health(gpu_cluster, worker, environment.gpu_operator_namespace) == "unhealthy",
                     f"result of kubectl describe node $NODE_NAME | grep unhealthy")

    match = []
    for i in range(sample_size):
        match.append(f"unhealthy for ecc field [{error_list[i]}] error crossing threshold {metrics_fields.get(error_list[i])}, current value {thresholds[i]}")
    verify_logs(gpu_cluster, environment, match, pod_str="metrics-exporter")

    #TODO figure out later
    #k8_util.k8_untaint_node(gpu_cluster, worker)

    K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.STOP_WORKLOAD, workload_config=wl_ctxt)
    verify_logs(gpu_cluster, environment,
                [f"Starting iteration 1 of 1 for test: {recipe}", f"trigger AUTO_UNHEALTHY_GPU_WATCH is trying to run test {recipe}"],
                since="180s", switch="or")
    verify_logs(gpu_cluster, environment,
               [f"trigger AUTO_UNHEALTHY_GPU_WATCH is trying to run test {recipe} on device"])

    k8_util.k8_metrics_error(gpu_cluster, [0] * sample_size, error_list, environment.gpu_operator_namespace)
    verify_logs(gpu_cluster, environment,
                ["all GPUs are healthy"])
    wl_ctxt = K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.START_WORKLOAD, node_name=worker)
    local_workload_ctxts.append(wl_ctxt)
    debug_on_failure(environment, (wl_ctxt['podStatus'] == K8Helper.PodStatus.RUNNING),
                     f"Workload not in RUNNING state, {wl_ctxt}")
    verify_events(gpu_cluster, namespace)
    K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.STOP_WORKLOAD, workload_config=wl_ctxt)


@pytest.mark.level3
@pytest.mark.parametrize("recipe", ["pebb_single"])
def test_update_metric_exporter_and_test_runner(request, gpu_cluster, deviceconfig_install, environment, recipe):
    namespace = environment.gpu_operator_namespace
    global Logger
    global LogPrettyPrinter
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    gpu_node = gpu_nodes[0]
    worker = k8_util.k8_get_node_hostname(gpu_node)

    configmap = dict()
    update_test_runner_configmap(recipe, worker, configmap)
    update_metrics_exporter_configmap(configmap)
    create_configmap(request, gpu_cluster, deviceconfig_install, environment, recipe, worker, configmap)

    health_thresholds = configmap.get('GPUConfig').get('HealthThresholds')
    sample_size = random.randint(2, len(health_thresholds.keys())-1)
    error_list = random.sample(health_thresholds.keys(), sample_size)

    local_workload_ctxts = []
    def _delete_workload():
        for ctxt in local_workload_ctxts:
            K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.STOP_WORKLOAD, workload_config=ctxt)
        k8_util.k8_metrics_error(gpu_cluster, [0] * sample_size, error_list, environment.gpu_operator_namespace)
        return
    request.addfinalizer(_delete_workload)

    verify_logs(gpu_cluster, environment, ["serving requests on"], "metrics-exporter")
    wl_ctxt = K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.START_WORKLOAD, node_name=worker)
    local_workload_ctxts.append(wl_ctxt)
    debug_on_failure(environment, (wl_ctxt['podStatus'] == K8Helper.PodStatus.RUNNING),
                     f"Workload is not running, {wl_ctxt}")

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
        common.PodInfo('test-runner', len(gpu_nodes), 1),
    ]

    thresholds = list()
    for error in error_list:
        thresholds.append(random.randint(0, health_thresholds.get(error)-1))
        Logger.info(f"injecting {thresholds[-1]} errors for {error}, threshold is {health_thresholds.get(error)}")


    time.sleep(30)
    verify_logs(gpu_cluster, environment,
               ["all GPUs are healthy"])
    k8_util.k8_metrics_error(gpu_cluster, thresholds, error_list, environment.gpu_operator_namespace)

    Logger.info(f"Test runner worker logs\n===================\n")
    ret_code, stdout, stderr = k8_util.k8_get_pod_logs(gpu_cluster, "test-runner", environment.gpu_operator_namespace)
    Logger.info(f"Test runner worker logs\n==================={stdout}\n")
    verify_events(gpu_cluster, namespace)

    rand_i = random.randint(0, len(thresholds)-1)
    error = error_list[rand_i]
    thresholds[rand_i] = health_thresholds.get(error) + random.randint(1, 3)
    Logger.info(f"injecting {thresholds[rand_i]} errors for {error}, threshold is {health_thresholds.get(error)}")
    k8_util.k8_metrics_error(gpu_cluster, thresholds, error_list, environment.gpu_operator_namespace)
    time.sleep(30)
    #TODO - this check fails in jobd
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    debug_on_failure(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    match = list()
    nomatch = list()
    for i in range(sample_size):
        log = f"unhealthy for ecc field [{error_list[i]}] error crossing threshold {health_thresholds.get(error_list[i])}, current value {thresholds[i]}"
        if thresholds[i] > health_thresholds.get(error_list[i]):
            Logger.info(f"Looking for the occurence of:\n{log}")
            match.append(log)
        else:
            Logger.info(f"Looking for non occurence of:\n{log}")
            nomatch.append(f"unhealthy for ecc field [{error_list[i]}] error crossing threshold")

    verify_logs(gpu_cluster, environment, match, "metrics-exporter", "60s")
    time.sleep(30)
    verify_logs(gpu_cluster, environment, nomatch, "metrics-exporter", "30s", "and", True)

    verify_logs(gpu_cluster, environment,
               [f"associated with workload"])

    debug_on_failure(environment,
                     (k8_util.k8_get_node_health(gpu_cluster, worker, environment.gpu_operator_namespace) == "unhealthy"),
                     f"result of kubectl describe node $NODE_NAME | grep unhealthy")
    K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.STOP_WORKLOAD, workload_config=wl_ctxt)
    time.sleep(30)
    verify_logs(gpu_cluster, environment,
               [f"trigger AUTO_UNHEALTHY_GPU_WATCH is trying to run test {recipe}"])

    k8_util.k8_metrics_error(gpu_cluster, [0] * len(error_list), error_list, environment.gpu_operator_namespace)

    verify_logs(gpu_cluster, environment,
               ["all GPUs are healthy"])
    ret_code, stdout, stderr = k8_util.k8_get_pod_logs(gpu_cluster, "test-runner", environment.gpu_operator_namespace)
    Logger.info(f"Test runner worker logs\n==================={stdout}\n")
    verify_events(gpu_cluster, namespace)


@pytest.mark.level4
@pytest.mark.parametrize("schedule, healthy", [
    (False, True),
    (False, False),
    (True, True)
])
def test_manual_job(request, gpu_cluster, images, deviceconfig_install, environment, schedule, healthy):
    global Logger
    global LogPrettyPrinter
    global metrics_fields
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    gpu_node = gpu_nodes[0]
    worker = k8_util.k8_get_node_hostname(gpu_node)

    job_name = "test-runner-manual-trigger"
    if schedule:
        job_name = "test-runner-manual-trigger-cron-job-midnight"
    namespace = "default"
    sa_name = "test-run"
    cluster_role_name = "test-run-cluster-role"
    crb_name = 'test-run-rb'
    sample_size = random.randint(1,len(metrics_fields.keys())-1)
    error_list = random.sample(metrics_fields.keys(), sample_size)
    local_workload_ctxts = []
    
    def _cleanup_jobs():
        if schedule:
            k8_util.k8_delete_job(gpu_cluster, namespace, job_name)
        else:
            k8_util.k8_delete_cron_job(gpu_cluster, namespace, job_name)
        k8_util.k8_delete_cluster_role_binding(gpu_cluster, crb_name)
        k8_util.k8_delete_cluster_role(gpu_cluster, cluster_role_name)
        k8_util.k8_delete_service_account(gpu_cluster, sa_name, namespace)

    def _delete_workload():
        for ctxt in local_workload_ctxts:
            K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.STOP_WORKLOAD, workload_config=ctxt)
        k8_util.k8_metrics_error(gpu_cluster, [0] * sample_size, error_list, environment.gpu_operator_namespace)
        return
    request.addfinalizer(_delete_workload)
    request.addfinalizer(_cleanup_jobs)

    wl_ctxt = K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.START_WORKLOAD, node_name=worker)
    local_workload_ctxts.append(wl_ctxt)
    debug_on_failure(environment, (wl_ctxt['podStatus'] == K8Helper.PodStatus.RUNNING),
                     f"Workload not in running state, {wl_ctxt}")
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    debug_on_failure(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    debug_on_failure(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    if not healthy:
        thresholds = []
        for error in error_list:
            thresholds.append(metrics_fields.get(error) + random.randint(1,10))
        k8_util.k8_metrics_error(gpu_cluster, thresholds, error_list, environment.gpu_operator_namespace)
        time.sleep(30)

    if not gpu_cluster.k8_kube_config:
        if schedule:
            ret, minute, err = gpu_cluster.k8_master.run_command(f"date +%M")
            minute = int(minute.strip()) + 2
            file_path = "lib/files/manual_scheduled_job.yaml"
        elif healthy:
            file_path = "lib/files/manual_healthy_job.yaml"
        else:
            file_path = "lib/files/manual_unhealthy_job.yaml"
        with open(file_path, 'r') as fp:
            data = fp.read()
            data = data.replace("image_name", f"{images.get('testRunner.image.repository')}:{images.get('testRunner.image.version')}")
            data = data.replace("node1", worker)
            if schedule:
                data = data.replace("MINUTE", str(minute))
            gpu_cluster.k8_master.run_command(f"echo '{data}' > workspace/job.yaml")
            gpu_cluster.k8_master.run_command(f"kubectl delete -f workspace/job.yaml")
            gpu_cluster.k8_master.run_command(f"kubectl apply -f workspace/job.yaml")
            out = gpu_cluster.k8_master.run_command(f"kubectl get job")
            Logger.debug(LogPrettyPrinter.pformat(out))
            if schedule:
                out = gpu_cluster.k8_master.run_command(f"kubectl get cronjob")
                Logger.debug(LogPrettyPrinter.pformat(out))
    else:
        # Delete ClusterRole and service account if previous/stale version exists
        ret_code, namespace_info_list = k8_util.k8_get_namespaces(gpu_cluster)
        _cleanup_jobs()

        """
        if healthy:
            failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
            debug_on_failure(environment, not failed_pods,
                             f"One or more pods are not ready - {failed_pods}")
        """
        # Check if test_runner namespace exists or not
        namespace_exists = False
        for ninfo in namespace_info_list:
            if ninfo['metadata']['name'] == namespace:
                namespace_exists = True

        if not namespace_exists and namespace != "default":
            # Create metrics-reader namespace
            ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(gpu_cluster, namespace)
            debug_on_failure(environment, (ret_code == 0),
                             f"Failed to create namespace:{namespace}, error: {ret_stderr}")

        # Create ServiceAccount
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(gpu_cluster, sa_name, namespace)
        debug_on_failure(environment, (ret_code == 0), f"Failed to create service-account, error:{ret_stderr}")

        # Define ClusterRole: verb=get
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(gpu_cluster, cluster_role_name, [("/test_runner", "get")])
        debug_on_failure(environment, (ret_code == 0), f"Failed to create test_runner clusterrole with GET, error:{ret_stderr}")

        # Define ClusterRoleBinding: verb=get
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(gpu_cluster, crb_name, namespace, cluster_role_name, sa_name)
        debug_on_failure(environment, (ret_code == 0), f"Failed to create test_runner clusterrole with GET, error:{ret_stderr}")

        # Create token for ServiceAccount
        token = k8_util.k8_create_token(gpu_cluster, namespace, sa_name, "1h")
        debug_on_failure(environment, (token != None), f"Failed to create token for the service-account : {sa_name}")
        Logger.info(f"TOKEN={token}")

        time.sleep(30) # Wait for exporter to start working
        # Get endpoint for each node

        # Create Job
        k8_util.k8_create_test_runner_job(namespace, images, worker, sa_name, job_name, healthy, schedule, datetime.datetime.utcnow().minute + 1)

    time.sleep(10)
    if not schedule:
        job_status = k8_util.k8_get_job_status(gpu_cluster, namespace, job_name)
        if healthy:
            debug_on_failure(environment, (job_status == "Pending"),
                             f"job should be in Running state or at least in Pending state, found {job_status}")
        else:
            debug_on_failure(environment, (job_status == "Running"),
                             f"job should be in Running state or at least in Pending state, found {job_status}")

    else:
        job_status = k8_util.k8_get_cron_job_status(gpu_cluster, namespace, job_name)
        debug_on_failure(environment, job_status, f"cron job not scheduled? found {job_status}")
    _delete_workload()
  
    if not schedule:
        i = 0
        while job_status == "Pending" and i < 3:
            job_status = k8_util.k8_get_job_status(gpu_cluster, namespace, job_name)
            Logger.info(f"found {job_name} in {job_status}, waiting for this job state to change")
            time.sleep(5)
            i += 1
        if healthy:
            debug_on_failure(environment, (job_status in ["Running", "Pending", "Succeeded"]), f"job should be in Succeeded state")
        else:
            debug_on_failure(environment, (job_status in ["Running", "Pending"]), f"job should be in Running state")
    else:
        job_status = k8_util.k8_get_cron_job_status(gpu_cluster, namespace, job_name)
        debug_on_failure(environment, job_status, f"cron job not scheduled?")


    verify_events(gpu_cluster, namespace)

    if not gpu_cluster.k8_kube_config:
        gpu_cluster.k8_master.run_command("kubectl delete -f workspace/job.yaml")
    else:
        if not schedule:
            k8_util.k8_delete_job(gpu_cluster, namespace, job_name)
        else:
            k8_util.k8_delete_cron_job(gpu_cluster, namespace, job_name)

    if not healthy:
        k8_util.k8_metrics_error(gpu_cluster, [0] * sample_size, error_list, environment.gpu_operator_namespace)
