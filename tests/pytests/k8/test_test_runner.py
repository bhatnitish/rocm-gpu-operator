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
import time
import json
import logging
import random
import lib.common as common
import lib.k8_util as k8_util
import lib.spec_util as spec_util
import lib.metric_util as metric_util

#pytestmark = pytest.mark.skip("debugging")
Logger = logging.getLogger("k8.test_k8_test_runner")


@pytest.fixture(autouse=True, scope="module")
def skip_module(request, environment):
    if environment.gpu_operator_version in ["v1.0.0", "v1.1.0"]:
        pytest.skip(f"Skipping test-runner for current version {environment.gpu_operator_version}")
    return

@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment, k8_helper):
    global Logger
    if k8_util.is_helm_chart_healthy(gpu_cluster,
                                     environment.gpu_operator_namespace,
                                     release_name):
        Logger.info("gpu-operator helm-chart is already installed/running - skip rest of setup/fixture")
        yield
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
        Logger.error(f"Stdout: {ret_stdout.strip()}")
        Logger.error(f"Stderr: {ret_stderr.strip()}")
    k8_helper.assert_or_debug(ret_code == 0, f"Failed to install helm-chart for {release_name}", False)
    time.sleep(30)
    yield
    time.sleep(20)
    ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name, environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Failed to uninstall {release_name} helm-chart, error: {ret_stderr}", False)
    return

@pytest.fixture(scope="module")
def deviceconfig_deploy(gpu_cluster, images, gpu_operator_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0, "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : True,
            'metricsExporter.enable' : True,
            'testRunner.enable' : True,
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, 'test_runner_deviceconfig')

    devicecfg_list = []
    for spec_name, tcfg in test_cfg_map.items():
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr : {ret_stderr}", environment.pause_on_failure)
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
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
        common.PodInfo('node-labeller', len(gpu_nodes), 1),
        common.PodInfo('test-runner', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods, sleep_time = 20)
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

def test_deviceconfig_test_runner_deploy(request, gpu_cluster, images, gpu_operator_install, deviceconfig_deploy, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0, "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    '''
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
    '''
