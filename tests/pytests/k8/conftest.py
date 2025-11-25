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
import os
import logging
import time
from lib import common
import lib.helm_util as helm_util
import lib.k8_util as k8_util
import lib.spec_util as spec_util
import lib.amdgpu as amdgpu_util
from lib.util import K8Helper

Logger = logging.getLogger("k8.conftest")

@pytest.fixture(scope="session")
def inbox_driver_skip(environment):
    if environment.amdgpu_driver_spec["driver-deployment"] == "inbox":
        pytest.skip("Using inbox amdgpu driver - skip")
    return

@pytest.fixture(scope="session", autouse=True)
def init_testbed(request, gpu_cluster, release_name, environment):
    global Logger
    all_namespaces = []
    if hasattr(environment, "gpu_operator_namespace"):
        all_namespaces.append(environment.gpu_operator_namespace)
    if hasattr(environment, "exporter_namespace"):
        all_namespaces.append(environment.exporter_namespace)

    def _cleanup_steps():
        # cleanup
        K8Helper.delete_debug_pods(all_namespaces + ["default"])

        # remove gpu-operator helm-chart
        if hasattr(environment, "gpu_operator_namespace"):
            # remove any deviceconfig instances
            device_cfg_info = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace, None)
            for devcfg_name, _ in device_cfg_info.items():
                k8_util.k8_delete_deviceconfig_cr(environment.gpu_operator_namespace, devcfg_name)

            if helm_util.is_helm_chart_deployed(gpu_cluster, release_name, environment.gpu_operator_namespace):
                Logger.warn(f"helm {release_name} is already deployed - cleanup")
                ret_code, ret_stdout, ret_stderr = helm_util.helm_uninstall(gpu_cluster, release_name,
                                                                          environment.gpu_operator_namespace)
                if ret_code != 0:
                    helm_util.helm_cleanup(gpu_cluster, release_name, environment.gpu_operator_namespace)

        if hasattr(environment, "exporter_namespace"):
            if helm_util.is_helm_chart_deployed(gpu_cluster, release_name, environment.exporter_namespace):
                Logger.warn(f"helm {release_name} is already deployed - cleanup")
                ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name,
                                                                          environment.exporter_namespace)
                if ret_code != 0:
                    helm_util.helm_cleanup(gpu_cluster, release_name, environment.exporter_namespace)

    Logger.info("Cleanup before starting test session")
    _cleanup_steps()

    # Init k8 cluster
    k8_util.k8_init_cluster(gpu_cluster, all_namespaces)
    yield
    Logger.info("Cleanup after starting test session")
    _cleanup_steps()
    return

@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment):
    global Logger

    # cleanup
    devcfg_map = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    if helm_util.is_helm_chart_deployed(gpu_cluster, release_name, environment.gpu_operator_namespace):
        Logger.warn(f"helm {release_name} is already deployed - cleanup")
        ret_code, ret_stdout, ret_stderr = helm_util.helm_uninstall(gpu_cluster, release_name,
                                                                    environment.gpu_operator_namespace)
        if ret_code != 0:
            helm_util.helm_cleanup(gpu_cluster, release_name, environment.gpu_operator_namespace)
        #k8_util.k8_delete_namespace(environment.gpu_operator_namespace)

    if images.get("gpu-operator.repo", None):
        helm_util.helm_add_repo(gpu_cluster, images.get("gpu-operator.repo-name"), images.get("gpu-operator.repo"))

    values_yaml = os.path.join(environment.logdir, f"values_{environment.gpu_operator_version}.yaml")
    if spec_util.generate_helmchart_deployment_config(environment.gpu_operator_version, images, values_yaml):
        Logger.debug(f"Generated values.yaml for helm-chart install command, {values_yaml}")
    else:
        values_yaml = None

    ret_code, ret_stdout, ret_stderr = helm_util.helm_install(gpu_cluster, release_name,
                                                              environment.gpu_operator_namespace,
                                                              images.get('gpu-operator.helm-chart', None),
                                                              environment.gpu_operator_version, values_yaml)
    if ret_code != 0:
        Logger.error(f"Failed to install helm chart for {release_name}")
        Logger.error(f"Stdout: {ret_stdout}")
        Logger.error(f"Stderr: {ret_stderr}")
    K8Helper.triage(environment, (ret_code == 0), f"Failed to install {release_name}")
    time.sleep(30)
    yield
    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)

    ret_code, ret_stdout, ret_stderr = helm_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to uninstall {release_name} helm-chart, error: {ret_stderr}")
    return

@pytest.fixture(scope="module")
def amd_smi_collect(gpu_cluster, gpu_operator_install, deviceconfig_install, environment):
    if environment.amd_smi_collection_complete:
        Logger.debug("amd-smi information already collection, skip now")
        return

    # Derive gpu information using amd-smi information
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # Enable metricsExporter in gpu-operator deviceconfig CR, if not already enabled
    revert = False
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        if tcfg['metricsExporter.enable'] == False:
            revert = True
            tcfg['metricsExporter.enable'] = True
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
            K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

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
        cluster_node.host_name = node_name

    if revert:
        # Disable metricsExporter in gpu-operator deviceconfig CR, if previously not enabled
        for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
            tcfg['metricsExporter.enable'] = False
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
            K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")
    environment.amd_smi_collection_complete = True
    Logger.info("Collected amd-smi information for all cluster nodes")

