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
Logger = logging.getLogger("k8.test_metric_exporter")


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

@pytest.fixture(scope="module")
def deviceconfig_install(gpu_cluster, images, gpu_operator_install, environment, k8_helper):
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
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster",
                              environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0,
                              "No nodes with AMD/GPU found in the cluster",
                              environment.pause_on_failure)

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : False,
            'metricsExporter.enable' : True,
            'metricsExporter.serviceType' : 'NodePort',
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, 'exporter', environment.amdgpu_driver_spec)
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
    yield devcfg_info

    device_cfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, None)
    for devcfg_name, _ in device_cfg_info.items():
        k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
    return

def test_deviceconfig_exporter_nodeport_deploy(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster",
                              environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0,
                              "No nodes with AMD/GPU found in the cluster",
                              environment.pause_on_failure)

    # Watch for all pod creation
    '''
    test-deviceconfig-device-plugin-8f7px                        1/1     Running       0                 12d
    test-deviceconfig-metrics-exporter-27gq9                     2/2     Running       0                 12d
    test-deviceconfig-node-labeller-54vpd                        1/1     Running       0                 12d
    '''
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods, f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    time.sleep(30) # Wait for exporter to start working

    failed_endpoints = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_hostname = k8_util.k8_get_node_hostname(node)
        node_port = deviceconfig_install.exporter_port_map[node_hostname]
        ret_code, ret_stdout, ret_stderr = cluster_node.http_get(node_port, "metrics")
        #if ret_code != 0:
        #    # try from node itself
        #    ret_code, ret_stdout, ret_stderr = cluster_node.proxy_http_get(node_ip, node_port, "metrics")

        if ret_code != 0:
            failed_endpoints.add(node_ip)
            Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")
    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)

def test_deviceconfig_exporter_disable_nodeport_exporter(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes), "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    # disable exporter and check for metrics
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, "Failed to modify deviceconfig CR", environment.pause_on_failure)

    export_pods = [
        common.PodInfo('metrics-exporter', 1, 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(gpu_cluster, environment.gpu_operator_namespace, export_pods)
    k8_helper.assert_or_debug(not running_pods,
                              f"Some of the pods are still running post uninstallation - {running_pods}",
                              environment.pause_on_failure)
    devplugin_pods = [
        common.PodInfo('device-plugin', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devplugin_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}",
                              environment.pause_on_failure)
    failed_endpoints = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        node_hostname = k8_util.k8_get_node_hostname(node)
        node_port = deviceconfig_install.exporter_port_map[node_hostname]
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        ret_code, ret_stdout, ret_stderr = cluster_node.http_get(node_port, "metrics")
        # Commenting out following as this rely on ssh access to each node
        #if ret_code != 0:
        #    ret_code, ret_stdout, ret_stderr = cluster_node.proxy_http_get(node_ip, node_port, "metrics")

        if ret_code != 0:
            failed_endpoints.add(node_ip)
            Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == len(gpu_nodes),
                              f"GET :{node_port}/metrics expected to fail for {failed_endpoints}",
                              environment.pause_on_failure)

    # Re enable exporter and check for metrics
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, "Failed to modify deviceconfig CR", environment.pause_on_failure)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}",
                              environment.pause_on_failure)
    time.sleep(30) # For the pod to initialize so that HTTP GET work
    failed_endpoints = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_hostname = k8_util.k8_get_node_hostname(node)
        node_port = deviceconfig_install.exporter_port_map[node_hostname]
        ret_code, ret_stdout, ret_stderr = cluster_node.http_get(node_port, "metrics")
        # Commenting out following as this rely on ssh access to each node
        #if ret_code != 0:
        #    # try from node itself
        #    ret_code, ret_stdout, ret_stderr = cluster_node.proxy_http_get(node_ip, node_port, "metrics")

        if ret_code != 0:
            failed_endpoints.add(node_ip)
            Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")
    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)

def test_deviceconfig_exporter_nodeport_rbac_support(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster",
                              environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes),
                              "No nodes with AMD/GPU found in the cluster",
                              environment.pause_on_failure)

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}",
                              environment.pause_on_failure)

    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while fetching namespaces from k8-cluster",
                              environment.pause_on_failure)

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(gpu_cluster, cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(gpu_cluster, cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(gpu_cluster, sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(gpu_cluster, metrics_reader_ns)
        k8_helper.assert_or_debug(ret_code == 0,
                                  f"Failed to create namespace:metrics-reader, error: {ret_stderr}",
                                  environment.pause_on_failure)

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(gpu_cluster, sa_name, metrics_reader_ns)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create service-account, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(gpu_cluster, cluster_role_name, [("/metrics", "get")])
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(gpu_cluster, crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(gpu_cluster, metrics_reader_ns, sa_name, "1h")
    k8_helper.assert_or_debug(token != None,
                              f"Failed to create token for the service-account : {sa_name}",
                              environment.pause_on_failure)
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)

    # Validate by connecting to exporter endpoint with token
    failed_endpoints = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_hostname = k8_util.k8_get_node_hostname(node)
        node_port = deviceconfig_install.exporter_port_map[node_hostname]
        ret_code, ret_stdout, ret_stderr = cluster_node.https_get(node_port, "metrics", token = token)
        if ret_code != 0:
            failed_endpoints.add(node_ip)
            Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")

    if len(failed_endpoints) > 0:
        Logger.warn(f"Failed to get metrics from some endpoints with direct access, {failed_endpoints}")

        failed_endpoints = set()
        for devcfg in deviceconfig_install.devicecfg_list:
            service_name = f"{devcfg}-metrics-exporter"
            k8_helper.assert_or_debug(service_name in endpoint_values,
                                      f"No endpoint address found for {service_name}", environment.pause_on_failure)
            k8_helper.assert_or_debug(len(endpoint_values[service_name]) > 0,
                                      f"No endpoint address found for {service_name}", environment.pause_on_failure)
            for host_ip_port in endpoint_values[service_name]:
                host, ip, port = host_ip_port
                ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"https://{ip}:{port}/metrics"])
                if ret_code != 0:
                    failed_endpoints.add(host_ip_port)
                    Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)

    # Restore/Revert back test configuration - Disable rbac (https)
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = False
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}",
                              environment.pause_on_failure)


def test_deviceconfig_exporter_nodeport_rbac_http(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes) > 0,
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = True

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while fetching namespaces from k8-cluster", environment.pause_on_failure)

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(gpu_cluster, cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(gpu_cluster, cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(gpu_cluster, sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(gpu_cluster, metrics_reader_ns)
        k8_helper.assert_or_debug(ret_code == 0,
                                  f"Failed to create namespace:metrics-reader, error: {ret_stderr}",
                                  environment.pause_on_failure)

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(gpu_cluster, sa_name, metrics_reader_ns)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create service-account, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(gpu_cluster, cluster_role_name, [("/metrics", "get")])
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(gpu_cluster, crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(gpu_cluster, metrics_reader_ns, sa_name, "1h")
    k8_helper.assert_or_debug(token != None,
                              f"Failed to create token for the service-account : {sa_name}",
                              environment.pause_on_failure)
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)
    # Validate by connecting to exporter endpoint with token
    failed_endpoints = set()
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_hostname = k8_util.k8_get_node_hostname(node)
        node_port = deviceconfig_install.exporter_port_map[node_hostname]
        ret_code, ret_stdout, ret_stderr = cluster_node.http_get(node_port, "metrics", token = token)
        # Commenting out following as this rely on ssh access to each node
        #if ret_code != 0:
        #    # try from node itself
        #    ret_code, ret_stdout, ret_stderr = cluster_node.proxy_http_get(node_ip, node_port, "metrics", token = token)

        if ret_code != 0:
            failed_endpoints.add(node_ip)
            Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")

    if len(failed_endpoints) > 0:
        Logger.warn(f"Failed to get metrics from some endpoints with direct access, {failed_endpoints}. Try via curl cmd")

        failed_endpoints = set()
        for devcfg in deviceconfig_install.devicecfg_list:
            service_name = f"{devcfg}-metrics-exporter"
            k8_helper.assert_or_debug(service_name in endpoint_values,
                                      f"No endpoint address found for {service_name}", environment.pause_on_failure)
            k8_helper.assert_or_debug(len(endpoint_values[service_name]) > 0,
                                      f"No endpoint address found for {service_name}", environment.pause_on_failure)
            for host_ip_port in endpoint_values[service_name]:
                host, ip, port = host_ip_port
                ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"http://{ip}:{port}/metrics"])
                if ret_code != 0:
                    failed_endpoints.add(host_ip_port)
                    Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)

    # Restore/Revert back test configuration - Disable rbac (http)
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = False
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}",
                              environment.pause_on_failure)


def test_deviceconfig_exporter_nodeport_exp_config(request, gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    # Generate set of config-maps in the k8 cluster with different set of labels and metrics
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes),
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    # Restore default mode (non-rbac) for this testcase
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = False
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    exporter_config_defn = {}
    label_support_info = metric_util.get_label_details(environment.gpu_operator_version)
    non_mandatory_labels = list(filter(lambda x: label_support_info[x] == "no", label_support_info.keys()))
    mandatory_labels = list(filter(lambda x: label_support_info[x] == "yes", label_support_info.keys()))
    for idx in range(10):
        label_subset = random.sample(non_mandatory_labels, 5)
        metric_subset = random.sample(metric_util.METRICS, 5)
        config_map = {
            "GPUConfig" : {
                "Labels" : label_subset,
                "Fields" : metric_subset,
            },
        }
        exp_config_name = f"exporter-config-{idx}"
        configmap_file = os.path.join(environment.sandbox_dir, f"{exp_config_name}.json")
        with open(configmap_file, "w") as fp:
            fp.write(json.dumps(config_map, indent=4))

        configmap_file = os.path.join(environment.sandbox_dir, f"config.json")
        with open(configmap_file, "w") as fp:
            fp.write(json.dumps(config_map, indent=4))

        # Delete if there is any previous instance with same name
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_configmap(gpu_cluster, environment.gpu_operator_namespace, 
                                                                       exp_config_name)
        Logger.debug(f"Result of configmap delete operation, ret_code:{ret_code}, ret_stdout: {ret_stdout.strip()}, err: {ret_stderr.strip()}")
        # ignore ret_code
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_configmap(gpu_cluster, 
                                                                       environment.gpu_operator_namespace,
                                                                       exp_config_name,
                                                                       configmap_file)
        k8_helper.assert_or_debug(ret_code == 0,
                                  f"Failed to create configmap {exp_config_name} for {configmap_file}, err: {ret_stderr.strip()}",
                                  environment.pause_on_failure)
        exporter_config_defn[exp_config_name] = (label_subset, metric_subset)
        Logger.info(f"Created configmap {exp_config_name} with labels: {label_subset} and metrics: {metric_subset}")

    def _cleanup_configmap():
        # Restore/Revert back test configuration
        for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
            del tcfg['metricsExporter.config']
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
            if ret_code != 0:
                Logger.warn(f"Failed to create deviceconfig, stderr: {ret_stderr}")

            # Check for corresponding deviceconfig updated
            k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)

        for exp_config, _ in exporter_config_defn.items():
            # Delete
            ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_configmap(gpu_cluster, environment.gpu_operator_namespace, 
                                                                           exp_config)
            if ret_code != 0:
                Logger.warn(f"Failed to delete metrics-exporter configmap {exp_config}")
        return

    request.addfinalizer(_cleanup_configmap)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_exp_config_metrics = []
    failed_exp_config_labels = []
    failed_endpoints = set()
    for exp_config, label_metrics_tuple in exporter_config_defn.items():
        Logger.info(f"Testing with exporter-config {exp_config}")
        for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
            tcfg['metricsExporter.config'] = exp_config
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
            k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

            # Check for corresponding deviceconfig created
            k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)

            failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
            k8_helper.assert_or_debug(not failed_pods,
                                      f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)
            time.sleep(30) # Wait for config-map is read by exporter pod
            expected_metrics = set(label_metrics_tuple[1])
            expected_metrics.update(['promhttp_metric_handler_errors_total'])
            expected_labels = set(label_metrics_tuple[0])
            expected_labels.update(mandatory_labels)
            for node in gpu_nodes:
                node_ip = k8_util.k8_get_node_address(node)
                cluster_node = gpu_cluster.get_worker_node(node_ip)
                if not cluster_node:
                    pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
                node_hostname = k8_util.k8_get_node_hostname(node)
                node_port = deviceconfig_install.exporter_port_map[node_hostname]
                ret_code, resp, _ = cluster_node.http_get(node_port, "metrics")
                # Commenting out following as this rely on ssh access to each node
                #if ret_code != 0:
                #    # try from node itself
                #    ret_code, resp, _ = cluster_node.proxy_http_get(node_ip, node_port, "metrics", token = token)

                if ret_code != 0:
                    Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")
                    failed_endpoints.add(node_ip)
                    continue
                metric_util.dump_metrics(resp, os.path.join(environment.sandbox_dir, f"{node_ip}_{exp_config}_metrics.txt"))
                exported_metrics = metric_util.parse_metric_data(resp)

                # Check for metrics
                if set(exported_metrics.keys()) != expected_metrics:
                    Logger.error(f"Mismatch in metrics Expected : {expected_metrics} vs Observed : {set(exported_metrics.keys())} config-map:{exp_config}")
                    failed_exp_config_metrics.append(exp_config)

                # Check for labels associated with each exported metric
                for metric_name, metric_data in exported_metrics.items():
                    if metric_name in {'promhttp_metric_handler_errors_total', 'gpu_nodes_total'}:
                        continue
                    observed_labels = set(metric_data['labels'].keys())
                    if len(expected_labels - observed_labels) > 0:
                        Logger.error(f"Mismatch in labels Expected : {expected_labels} vs Observed {observed_labels}, config-map:{exp_config}, errror: {expected_labels - observed_labels}")
                        if exp_config not in failed_exp_config_labels:
                            failed_exp_config_labels.append(exp_config)

    # Do final verification
    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)
    k8_helper.assert_or_debug(len(failed_exp_config_metrics) == 0,
                              f"Export ConfigMap (Fields) failed for {failed_exp_config_metrics} cases",
                              environment.pause_on_failure)
    k8_helper.assert_or_debug(len(failed_exp_config_labels) == 0,
                              f"Export ConfigMap (Labels) failed for {failed_exp_config_labels} cases",
                              environment.pause_on_failure)

#
# Following deploys deviceconfig metric.exporter in default mode (cluster endpoing ip)
#
def test_deviceconfig_exporter_servicetype_default_deploy(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes),
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.rbacConfig.enable'] = False
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    # Watch for all pod creation
    '''
    test-deviceconfig-device-plugin-8f7px                        1/1     Running       0                 12d
    test-deviceconfig-metrics-exporter-27gq9                     2/2     Running       0                 12d
    test-deviceconfig-node-labeller-54vpd                        1/1     Running       0                 12d
    '''
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        k8_helper.assert_or_debug(service_name in endpoint_values,
                                  f"No endpoint address found for {service_name}", environment.pause_on_failure)
        k8_helper.assert_or_debug(len(endpoint_values[service_name]) > 0,
                                  f"No endpoint address found for {service_name}", environment.pause_on_failure)
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)

    # Disable metrics-exporter
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False # Now disable exporter and check for metrics-exporter POD deleted
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    export_pods = [
        common.PodInfo('metrics-exporter', 1, 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(gpu_cluster, environment.gpu_operator_namespace, export_pods)
    k8_helper.assert_or_debug(not running_pods,
                              f"Some of the pods are still running post uninstallation - {running_pods}", environment.pause_on_failure)

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        k8_helper.assert_or_debug(service_name not in endpoint_values,
                                  f"Endpoint address found for {service_name} after disabling exporter", environment.pause_on_failure)

    # Reenable metrics-exporter
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}",
                              environment.pause_on_failure)

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        k8_helper.assert_or_debug(service_name in endpoint_values,
                                  f"No endpoint address found for {service_name}", environment.pause_on_failure)
        k8_helper.assert_or_debug(len(endpoint_values[service_name]) > 0,
                                  f"No endpoint address found for {service_name}", environment.pause_on_failure)
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)


def test_deviceconfig_exporter_servicetype_default_rbac_support(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes),
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)
    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while fetching namespaces from k8-cluster", environment.pause_on_failure)

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(gpu_cluster, cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(gpu_cluster, cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(gpu_cluster, sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(gpu_cluster, metrics_reader_ns)
        k8_helper.assert_or_debug(ret_code == 0,
                                  f"Failed to create namespace:metrics-reader, error: {ret_stderr}", environment.pause_on_failure)

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(gpu_cluster, sa_name, metrics_reader_ns)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create service-account, error:{ret_stderr}", environment.pause_on_failure)

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(gpu_cluster, cluster_role_name, [("/metrics", "get")])
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}", environment.pause_on_failure)

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(gpu_cluster, crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}", environment.pause_on_failure)

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(gpu_cluster, metrics_reader_ns, sa_name, "1h")
    k8_helper.assert_or_debug(token != None,
                              f"Failed to create token for the service-account : {sa_name}", environment.pause_on_failure)
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        k8_helper.assert_or_debug(service_name in endpoint_values,
                                  f"No endpoint address found for {service_name}", environment.pause_on_failure)
        k8_helper.assert_or_debug(len(endpoint_values[service_name]) > 0,
                                  f"No endpoint address found for {service_name}", environment.pause_on_failure)
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"https://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTPS-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)
    # Check port 4999
    failed_endpoints = set()
    port = 4999
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        for host_ip_port in endpoint_values[service_name]:
            host, ip, _ = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"https://{ip}:{port}/metrics"])
            if ret_code == 0:
                failed_endpoints.add(f"{host}_{ip}_{port}")
                Logger.error(f"Able to get metrics from {service_name} endpoint for {host} {ip}:{port} with Bearer token")

            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"https://{ip}:{port}/metrics"])
            if ret_code == 0:
                failed_endpoints.add(f"{host}_{ip}_{port}")
                Logger.error(f"Able to get metrics from {service_name} endpoint for {host} {ip}:{port}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTPS-GET succeeded with port:{port}, nodes: {failed_endpoints}",
                              environment.pause_on_failure, expected_to_fail = (environment.gpu_operator_version < "v1.3.1"))


def test_deviceconfig_exporter_servicetype_default_rbac_http(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes),
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)
    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while fetching namespaces from k8-cluster", environment.pause_on_failure)

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(gpu_cluster, cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(gpu_cluster, cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(gpu_cluster, sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(gpu_cluster, metrics_reader_ns)
        k8_helper.assert_or_debug(ret_code == 0,
                                  f"Failed to create namespace:metrics-reader, error: {ret_stderr}",
                                  environment.pause_on_failure)

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(gpu_cluster, sa_name, metrics_reader_ns)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create service-account, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(gpu_cluster, cluster_role_name, [("/metrics", "get")])
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(gpu_cluster, crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(gpu_cluster, metrics_reader_ns, sa_name, "1h")
    k8_helper.assert_or_debug(token != None,
                              f"Failed to create token for the service-account : {sa_name}",
                              environment.pause_on_failure)
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        k8_helper.assert_or_debug(service_name in endpoint_values,
                                  f"No endpoint address found for {service_name} in {endpoint_values}", environment.pause_on_failure)
        k8_helper.assert_or_debug(len(endpoint_values[service_name]) > 0,
                                  f"No endpoint address found for {service_name} in {endpoint_values}", environment.pause_on_failure)
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, 
                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)

    # Check for port 4999
    failed_endpoints = set()
    port = 4999
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        for host_ip_port in endpoint_values[service_name]:
            host, ip, _ = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, 
                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"http://{ip}:{port}/metrics"])
            if ret_code == 0:
                failed_endpoints.add(f"{host}_{ip}_{port}")
                Logger.error(f"Able to get metrics from {service_name} endpoint for {host} {ip}:{port} with bearer-token")

            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"http://{ip}:{port}/metrics"])
            if ret_code == 0:
                failed_endpoints.add(f"{host}_{ip}_{port}")
                Logger.error(f"Able to get metrics from {service_name} endpoint for {host} {ip}:{port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET succeeded with port:{port}, nodes: {failed_endpoints}",
                              environment.pause_on_failure, expected_to_fail = (environment.gpu_operator_version < "v1.3.1"))

def test_deviceconfig_exporter_clusterip_rbac_internal_port(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes),
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.port'] = 7000
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)
    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while fetching namespaces from k8-cluster", environment.pause_on_failure)

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(gpu_cluster, cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(gpu_cluster, cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(gpu_cluster, sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(gpu_cluster, metrics_reader_ns)
        k8_helper.assert_or_debug(ret_code == 0,
                                  f"Failed to create namespace:metrics-reader, error: {ret_stderr}", environment.pause_on_failure)

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(gpu_cluster, sa_name, metrics_reader_ns)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create service-account, error:{ret_stderr}", environment.pause_on_failure)

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(gpu_cluster, cluster_role_name, [("/metrics", "get")])
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}", environment.pause_on_failure)

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(gpu_cluster, crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}", environment.pause_on_failure)

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(gpu_cluster, metrics_reader_ns, sa_name, "1h")
    k8_helper.assert_or_debug(token != None,
                              f"Failed to create token for the service-account : {sa_name}", environment.pause_on_failure)
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        k8_helper.assert_or_debug(service_name in endpoint_values,
                                  f"No endpoint address found for {service_name}", environment.pause_on_failure)
        k8_helper.assert_or_debug(len(endpoint_values[service_name]) > 0,
                                  f"No endpoint address found for {service_name}", environment.pause_on_failure)
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"https://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)

    # Check for default port=5000
    failed_endpoints = set()
    port = 5000
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        for host_ip_port in endpoint_values[service_name]:
            host, ip, _ = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"https://{ip}:{port}/metrics"])
            if ret_code == 0:
                failed_endpoints.add(f"{host}_{ip}_{port}")
                Logger.error(f"Able to connect to {service_name} endpoint for {host}, {ip} and {port} with bearer token")

            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"https://{ip}:{port}/metrics"])
            if ret_code == 0:
                failed_endpoints.add(f"{host}_{ip}_{port}")
                Logger.error(f"Able to connect to disbaled metrics-endpoint for {host}, {ip} and {port}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTPS-GET succeeded for stale/disabled port, nodes: {failed_endpoints}",
                              environment.pause_on_failure, expected_to_fail = (environment.gpu_operator_version < "v1.3.1"))

def test_deviceconfig_exporter_clusterip_rbac_http_default_port(gpu_cluster, images, gpu_operator_install, deviceconfig_install, environment, k8_helper):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
    k8_helper.assert_or_debug(len(gpu_nodes),
                              "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.port'] = 8000
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        k8_helper.assert_or_debug(ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}", environment.pause_on_failure)

    # Check for corresponding deviceconfig created
    k8_helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        k8_helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    k8_helper.assert_or_debug(not failed_pods,
                              f"One or more pods are not ready - {failed_pods}", environment.pause_on_failure)
    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces(gpu_cluster)
    k8_helper.assert_or_debug(ret_code == 0,
                              "Error while fetching namespaces from k8-cluster", environment.pause_on_failure)

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(gpu_cluster, cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(gpu_cluster, cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(gpu_cluster, sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(gpu_cluster, metrics_reader_ns)
        k8_helper.assert_or_debug(ret_code == 0,
                                  f"Failed to create namespace:metrics-reader, error: {ret_stderr}",
                                  environment.pause_on_failure)

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(gpu_cluster, sa_name, metrics_reader_ns)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create service-account, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(gpu_cluster, cluster_role_name, [("/metrics", "get")])
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(gpu_cluster, crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    k8_helper.assert_or_debug(ret_code == 0,
                              f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}",
                              environment.pause_on_failure)

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(gpu_cluster, metrics_reader_ns, sa_name, "1h")
    k8_helper.assert_or_debug(token != None,
                              f"Failed to create token for the service-account : {sa_name}",
                              environment.pause_on_failure)
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(gpu_cluster,
                                                         environment.gpu_operator_namespace)
    k8_helper.assert_or_debug(ret_code == 0, f"Error while collecting kubectl endpoints",
                              environment.pause_on_failure)
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        k8_helper.assert_or_debug(service_name in endpoint_values,
                                  f"No endpoint address found for {service_name} in {endpoint_values}", environment.pause_on_failure)
        k8_helper.assert_or_debug(len(endpoint_values[service_name]) > 0,
                                  f"No endpoint address found for {service_name} in {endpoint_values}", environment.pause_on_failure)
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, 
                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}",
                              environment.pause_on_failure)

    # Check default port=5000
    failed_endpoints = set()
    port = 5000
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        for host_ip_port in endpoint_values[service_name]:
            host, ip, _ = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, 
                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"http://{ip}:{port}/metrics"])
            if ret_code == 0:
                failed_endpoints.add(f"{host}_{ip}_{port}")
                Logger.error(f"Able to connect to disbaled metrics-endpoint for {host}, {ip} and {port} with bearer token")

            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"http://{ip}:{port}/metrics"])
            if ret_code == 0:
                failed_endpoints.add(f"{host}_{ip}_{port}")
                Logger.error(f"Able to connect to disbaled metrics-endpoint for {host}, {ip} and {port}")

    k8_helper.assert_or_debug(len(failed_endpoints) == 0,
                              f"One or more metric endpoints HTTP-GET succeeded for stale/disabled port, nodes: {failed_endpoints}",
                              environment.pause_on_failure, expected_to_fail = (environment.gpu_operator_version < "v1.3.1"))
