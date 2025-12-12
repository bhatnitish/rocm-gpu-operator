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
import time
import json
import logging
import random
import functools
import lib.common as common
import lib.helm_util as helm_util
import lib.k8_util as k8_util
import lib.spec_util as spec_util
import lib.metric_util as metric_util
import lib.amdgpu as amdgpu_util
from lib.util import K8Helper

#pytestmark = pytest.mark.skip("debugging")
Logger = logging.getLogger("k8.test_metrics_exporter")

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
            'devicePlugin.enableNodeLabeller' : False,
            'metricsExporter.enable' : True,
            'metricsExporter.serviceType' : 'NodePort',
        }
    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_nodes, 'exporter', environment.amdgpu_driver_spec)
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

def test_exporter_nodeport_deploy(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

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
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

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
    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

def test_exporter_disable_nodeport_exporter(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # disable exporter and check for metrics
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    export_pods = [
        common.PodInfo('metrics-exporter', 1, 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(environment.gpu_operator_namespace, export_pods)
    K8Helper.triage(environment, not running_pods, f"Some of the pods are still running post uninstallation - {running_pods}")
    devplugin_pods = [
        common.PodInfo('device-plugin', 1, 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devplugin_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
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

    K8Helper.triage(environment, (len(failed_endpoints) == len(gpu_nodes)),
                    f"GET :{node_port}/metrics expected to fail for {failed_endpoints}")

    # Re enable exporter and check for metrics
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to modify deviceconfig CR")

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
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
    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

def test_exporter_nodeport_rbac_support(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, ret_code == 0, "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, len(gpu_nodes) > 0, "No nodes with AMD/GPU found in the cluster")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces()
    K8Helper.triage(environment, (ret_code == 0), "Error while fetching namespaces from k8-cluster")

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(metrics_reader_ns)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create namespace:metrics-reader, error: {ret_stderr}")

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(sa_name, metrics_reader_ns)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create service-account, error:{ret_stderr}")

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(cluster_role_name,
                                                                      k8_util.k8_create_rules_from_endpoint_list([("/metrics", "get")]))
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    K8Helper.triage(environment, (ret_code == 0),
                    f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(metrics_reader_ns, sa_name, "1h")
    K8Helper.triage(environment, (token != None), f"Failed to create token for the service-account : {sa_name}")
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")

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
            K8Helper.triage(environment, (service_name in endpoint_values), f"No endpoint address found for {service_name}")
            K8Helper.triage(environment, (len(endpoint_values[service_name]) > 0),
                            f"No endpoint address found for {service_name}")
            for host_ip_port in endpoint_values[service_name]:
                host, ip, port = host_ip_port
                ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"https://{ip}:{port}/metrics"])
                if ret_code != 0:
                    failed_endpoints.add(host_ip_port)
                    Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, (len(failed_endpoints) == 0), f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

    # Restore/Revert back test configuration - Disable rbac (https)
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = False
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

def test_exporter_nodeport_rbac_http(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = True

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces()
    K8Helper.triage(environment, (ret_code == 0), "Error while fetching namespaces from k8-cluster")

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(metrics_reader_ns)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create namespace:metrics-reader, error: {ret_stderr}")

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(sa_name, metrics_reader_ns)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create service-account, error:{ret_stderr}")

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(cluster_role_name,
                                                                      k8_util.k8_create_rules_from_endpoint_list([("/metrics", "get")]))
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(metrics_reader_ns, sa_name, "1h")
    K8Helper.triage(environment, (token != None), f"Failed to create token for the service-account : {sa_name}")
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
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
            K8Helper.triage(environment, (service_name in endpoint_values), f"No endpoint address found for {service_name}")
            K8Helper.triage(environment, (len(endpoint_values[service_name]) > 0),
                            f"No endpoint address found for {service_name}")
            for host_ip_port in endpoint_values[service_name]:
                host, ip, port = host_ip_port
                ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"http://{ip}:{port}/metrics"])
                if ret_code != 0:
                    failed_endpoints.add(host_ip_port)
                    Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, (len(failed_endpoints) == 0), f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

    # Restore/Revert back test configuration - Disable rbac (http)
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = False
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, (not failed_pods), f"One or more pods are not ready - {failed_pods}")

def test_exporter_nodeport_exp_config(request, gpu_cluster, deviceconfig_install, amd_smi_collect, environment):
    global Logger
    # Generate set of config-maps in the k8 cluster with different set of labels and metrics
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # Restore default mode (non-rbac) for this testcase
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'NodePort'
        tcfg['metricsExporter.rbacConfig.enable'] = False
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False

        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    exporter_config_defn = {}
    label_support_info = metric_util.get_label_details(environment.gpu_operator_version)
    non_mandatory_labels = list(filter(lambda x: label_support_info[x] == "no", label_support_info.keys()))
    mandatory_labels = list(filter(lambda x: label_support_info[x] == "yes", label_support_info.keys()))

    # Build common list of metrics across all nodes in the cluster (if different gpu-series are part of cluster)
    list_of_metrics_set = []
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        metrics_data = metric_util.get_supported_metrics(gpu_series = cluster_node.gpu_series,
                                                         amdgpu_driver = cluster_node.amdgpu_driver_version)
        list_of_metrics_set.append(set(map(lambda x: x['name'].split(":")[0].lower(), metrics_data)))
    common_metrics = list(functools.reduce(lambda s1, s2: s1.intersection(s2), list_of_metrics_set))
    Logger.info(f"Using {common_metrics} for metrics-exporter configmap validation")

    for idx in range(10):
        label_subset = random.sample(non_mandatory_labels, 5)
        metric_subset = random.sample(common_metrics, 5)
        config_map = {
            "GPUConfig" : {
                "Labels" : label_subset,
                "Fields" : metric_subset,
            },
        }
        exp_config_name = f"exporter-config-{idx}"
        configmap_file = os.path.join(environment.logdir, f"{exp_config_name}.json")
        with open(configmap_file, "w") as fp:
            fp.write(json.dumps(config_map, indent=4))

        configmap_file = os.path.join(environment.logdir, f"config.json")
        with open(configmap_file, "w") as fp:
            fp.write(json.dumps(config_map, indent=4))

        # Delete if there is any previous instance with same name
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_configmap(environment.gpu_operator_namespace, 
                                                                       exp_config_name)
        Logger.debug(f"Result of configmap delete operation, ret_code:{ret_code}, ret_stdout: {ret_stdout.strip()}, err: {ret_stderr.strip()}")
        # ignore ret_code
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_configmap(environment.gpu_operator_namespace,
                                                                       exp_config_name,
                                                                       configmap_file)
        K8Helper.triage(environment, ret_code == 0,
                        f"Failed to create configmap {exp_config_name} for {configmap_file}, err: {ret_stderr.strip()}")
        exporter_config_defn[exp_config_name] = (label_subset, metric_subset)
        Logger.info(f"Created configmap {exp_config_name} with labels: {label_subset} and metrics: {metric_subset}")

    def _cleanup_configmap():
        # Restore/Revert back test configuration
        for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
            del tcfg['metricsExporter.config']
            cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
            ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
            if ret_code != 0:
                Logger.warn(f"Failed to create deviceconfig, stderr: {ret_stderr}")

            # Check for corresponding deviceconfig updated
            K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)

        for exp_config, _ in exporter_config_defn.items():
            # Delete
            ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_configmap(environment.gpu_operator_namespace, 
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
            ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
            K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

            # Check for corresponding deviceconfig created
            K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)

            failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
            K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
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
                metric_util.dump_metrics(resp, os.path.join(environment.logdir, f"{node_ip}_{exp_config}_metrics.txt"))
                obs_metric_info = metric_util.parse_metric_data(resp)
                obs_metrics = set(obs_metric_info.keys())

                # Check for metrics
                if obs_metrics != expected_metrics:
                    Logger.error(f"Mismatch in metrics Expected : {expected_metrics} vs Observed : {obs_metrics} config-map:{exp_config}")
                    if expected_metrics - obs_metrics:
                        Logger.error(f"Missing: {expected_metrics - obs_metrics}")
                    if obs_metrics - expected_metrics:
                        Logger.error(f"Unexpected: {obs_metrics - expected_metrics}")
                    failed_exp_config_metrics.append((exp_config, f"Expected:{expected_metrics}, Observed:{obs_metrics}"))

                # Check for labels associated with each exported metric
                for metric_name, metric_data_list in obs_metric_info.items():
                    if metric_name in {'promhttp_metric_handler_errors_total', 'gpu_nodes_total'}:
                        continue
                    label_check_failed = False
                    for metric_data in metric_data_list:
                        observed_labels = set(metric_data['labels'].keys())
                        if len(expected_labels - observed_labels) > 0:
                            Logger.error(f"Missing labels with config-map:{exp_config}, error: {expected_labels - observed_labels}")
                            label_check_failed = True
                    if label_check_failed and exp_config not in failed_exp_config_labels:
                        failed_exp_config_labels.append((exp_config, f"Expected:{expected_labels}, Observed:{observed_labels}"))

    # Do final verification
    K8Helper.triage(environment, len(failed_endpoints) == 0, f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")
    K8Helper.triage(environment, (len(failed_exp_config_metrics) == 0),
                    f"Export ConfigMap (Fields) failed for {failed_exp_config_metrics} cases")
    K8Helper.triage(environment, (len(failed_exp_config_labels) == 0),
                    f"Export ConfigMap (Labels) failed for {failed_exp_config_labels} cases")

#
# Following deploys deviceconfig metric.exporter in default mode (cluster endpoing ip)
#
def test_exporter_servicetype_default_deploy(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.rbacConfig.enable'] = False
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

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
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        K8Helper.triage(environment, (service_name in endpoint_values), f"No endpoint address found for {service_name}")
        K8Helper.triage(environment, (len(endpoint_values[service_name]) > 0),
                        f"No endpoint address found for {service_name}")
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, (len(failed_endpoints) == 0), f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

    # Disable metrics-exporter
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False # Now disable exporter and check for metrics-exporter POD deleted
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    export_pods = [
        common.PodInfo('metrics-exporter', 1, 1),
    ]
    running_pods = k8_util.k8_check_pod_terminated(environment.gpu_operator_namespace, export_pods)
    K8Helper.triage(environment, not running_pods, f"Some of the pods are still running post uninstallation - {running_pods}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        K8Helper.triage(environment, (service_name not in endpoint_values),
                        f"Endpoint address found for {service_name} after disabling exporter")

    # Reenable metrics-exporter
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        K8Helper.triage(environment, (service_name in endpoint_values), f"No endpoint address found for {service_name}")
        K8Helper.triage(environment, (len(endpoint_values[service_name]) > 0),
                        f"No endpoint address found for {service_name}")
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, ["-s", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, len(failed_endpoints) == 0, f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")


def test_exporter_servicetype_default_rbac_support(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces()
    K8Helper.triage(environment, (ret_code == 0), "Error while fetching namespaces from k8-cluster")

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(metrics_reader_ns)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create namespace:metrics-reader, error: {ret_stderr}")

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(sa_name, metrics_reader_ns)
    K8Helper.triage(environment, (ret_code == 0),
                    f"Failed to create service-account, error:{ret_stderr}")

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(cluster_role_name,
                                                                      k8_util.k8_create_rules_from_endpoint_list([("/metrics", "get")]))
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    K8Helper.triage(environment, (ret_code == 0),
                    f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(metrics_reader_ns, sa_name, "1h")
    K8Helper.triage(environment, (token != None), f"Failed to create token for the service-account : {sa_name}")
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        K8Helper.triage(environment, (service_name in endpoint_values), f"No endpoint address found for {service_name}")
        K8Helper.triage(environment, (len(endpoint_values[service_name]) > 0),
                        f"No endpoint address found for {service_name}")
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"https://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, (len(failed_endpoints) == 0), f"One or more metric endpoints HTTPS-GET failed, nodes: {failed_endpoints}")
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

    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTPS-GET succeeded with port:{port}, nodes: {failed_endpoints}",
                    expected_to_fail = (environment.gpu_operator_version < "v1.3.1"))


def test_exporter_servicetype_default_rbac_http(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces()
    K8Helper.triage(environment, (ret_code == 0), "Error while fetching namespaces from k8-cluster")

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(metrics_reader_ns)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create namespace:metrics-reader, error: {ret_stderr}")

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(sa_name, metrics_reader_ns)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create service-account, error:{ret_stderr}")

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(cluster_role_name,
                                                                      k8_util.k8_create_rules_from_endpoint_list([("/metrics", "get")]))
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(metrics_reader_ns, sa_name, "1h")
    K8Helper.triage(environment, (token != None), f"Failed to create token for the service-account : {sa_name}")
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        K8Helper.triage(environment, (service_name in endpoint_values),
                        f"No endpoint address found for {service_name} in {endpoint_values}")
        K8Helper.triage(environment, len(endpoint_values[service_name]) > 0,
                        f"No endpoint address found for {service_name} in {endpoint_values}")
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, 
                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

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

    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET succeeded with port:{port}, nodes: {failed_endpoints}",
                    expected_to_fail = (environment.gpu_operator_version < "v1.3.1"))

def test_exporter_clusterip_rbac_internal_port(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.port'] = 7000
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces()
    K8Helper.triage(environment, (ret_code == 0), "Error while fetching namespaces from k8-cluster")

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(metrics_reader_ns)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create namespace:metrics-reader, error: {ret_stderr}")

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(sa_name, metrics_reader_ns)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create service-account, error:{ret_stderr}")

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(cluster_role_name,
                                                                      k8_util.k8_create_rules_from_endpoint_list([("/metrics", "get")]))
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(metrics_reader_ns, sa_name, "1h")
    K8Helper.triage(environment, (token != None), f"Failed to create token for the service-account : {sa_name}")
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        K8Helper.triage(environment, (service_name in endpoint_values), f"No endpoint address found for {service_name}")
        K8Helper.triage(environment, (len(endpoint_values[service_name]) > 0), f"No endpoint address found for {service_name}")
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster,
                                                ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"https://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, (len(failed_endpoints) == 0), f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

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

    K8Helper.triage(environment, (len(failed_endpoints) == 0), 
                    f"One or more metric endpoints HTTPS-GET succeeded for stale/disabled port, nodes: {failed_endpoints}",
                    expected_to_fail = (environment.gpu_operator_version < "v1.3.1"))

def test_exporter_clusterip_rbac_http_default_port(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceType'] = 'ClusterIP'
        tcfg['metricsExporter.port'] = 8000
        tcfg['metricsExporter.rbacConfig.enable'] = True
        tcfg['metricsExporter.rbacConfig.disableHttps'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 2),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
    # Get all namespaces and check if metrics-reader is already created
    ret_code, namespace_info_list = k8_util.k8_get_namespaces()
    K8Helper.triage(environment, (ret_code == 0), "Error while fetching namespaces from k8-cluster")

    metrics_reader_ns = "metrics-reader"
    sa_name = "exporter-client"
    cluster_role_name = "metrics"
    # Delete ClusterRoleBinding if previous/stale version exists
    k8_util.k8_delete_cluster_role_binding(cluster_role_name)

    # Delete ClusterRole if previous/stale version exists
    k8_util.k8_delete_cluster_role(cluster_role_name)

    # Delete previous service-account
    k8_util.k8_delete_service_account(sa_name, metrics_reader_ns)

    # Check if metrics-reader namespace exists or not
    metrics_reader_ns_exists = False
    for ninfo in namespace_info_list:
        if ninfo['metadata']['name'] == metrics_reader_ns:
            metrics_reader_ns_exists = True

    if not metrics_reader_ns_exists:
        # Create metrics-reader namespace
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_namespace(metrics_reader_ns)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create namespace:metrics-reader, error: {ret_stderr}")

    # Create ServiceAccount
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_service_account(sa_name, metrics_reader_ns)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create service-account, error:{ret_stderr}")

    # Define ClusterRole: verb=get
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_cluster_role(cluster_role_name,
                                                                      k8_util.k8_create_rules_from_endpoint_list([("/metrics", "get")]))
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Define ClusterRoleBinding: verb=get
    crb_name = 'metrics'
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_role_binding(crb_name, metrics_reader_ns, cluster_role_name, sa_name)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to create metrics-reader clusterrole with GET, error:{ret_stderr}")

    # Create token for ServiceAccount
    token = k8_util.k8_create_token(metrics_reader_ns, sa_name, "1h")
    K8Helper.triage(environment, (token != None), f"Failed to create token for the service-account : {sa_name}")
    Logger.info(f"TOKEN={token}")

    time.sleep(30) # Wait for exporter to start working
    # Get endpoint for each node
    ret_code, endpoint_values = k8_util.k8_get_endpoints(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Error while collecting kubectl endpoints")
    failed_endpoints = set()
    for devcfg in deviceconfig_install.devicecfg_list:
        service_name = f"{devcfg}-metrics-exporter"
        K8Helper.triage(environment, (service_name in endpoint_values),
                        f"No endpoint address found for {service_name} in {endpoint_values}")
        K8Helper.triage(environment, (len(endpoint_values[service_name]) > 0),
                        f"No endpoint address found for {service_name} in {endpoint_values}")
        for host_ip_port in endpoint_values[service_name]:
            host, ip, port = host_ip_port
            ret_code, ret_stdout, ret_stderr = k8_util.k8_run_curl_cmd(gpu_cluster, 
                    ["-s", "-k", "-H", f"Authorization: Bearer {token}", f"http://{ip}:{port}/metrics"])
            if ret_code != 0:
                failed_endpoints.add(host_ip_port)
                Logger.error(f"Failed to get metrics from nodeport endpoint for {host_ip_port}, stdout: {ret_stdout} stderr: {ret_stderr}")

    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET failed, nodes: {failed_endpoints}")

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

    K8Helper.triage(environment, (len(failed_endpoints) == 0),
                    f"One or more metric endpoints HTTP-GET succeeded for stale/disabled port, nodes: {failed_endpoints}",
                    expected_to_fail = (environment.gpu_operator_version < "v1.3.1"))


def test_exporter_servicemonitor_enable_flag(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # enable exporter service-monitor
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['prometheus.serviceMonitor.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    time.sleep(30) 
    # Check if service-monitor object is created
    ret_code, resp, err = k8_util.k8_get_servicemonitor_cr(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0),
                    f"Failed to collect servicemonitors from namespace: {environment.gpu_operator_namespace}, error : {err}")
    K8Helper.triage(environment, (len(resp) > 0),
                    f"Found 0 entries of servicemonitors in namespace: {environment.gpu_operator_namespace}")

    # Disable exporter service-monitor
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False
        tcfg['prometheus.serviceMonitor.enable'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")
        
    time.sleep(30)
    # Check if service-monitor object is deleted
    ret_code, resp, err = k8_util.k8_get_servicemonitor_cr(environment.gpu_operator_namespace)
    
    K8Helper.triage(environment, (ret_code == 0),
                    f"Failed to collect servicemonitors from namespace: {environment.gpu_operator_namespace}, error : {err}")
    K8Helper.triage(environment, (len(resp) == 0),
                    f"Failed to delete servicemonitors in namespace: {environment.gpu_operator_namespace}")
    

def test_servicemonitor_spec_fields(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['prometheus.serviceMonitor.enable'] = True
        tcfg['prometheus.serviceMonitor.honorLabels'] = True
        tcfg['prometheus.serviceMonitor.honorTimestamps'] = True
        tcfg['prometheus.serviceMonitor.interval'] = '60s'
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    time.sleep(30)
    ret_code, resp, err  = k8_util.k8_get_servicemonitor_cr(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to get ServiceMonitors: {err}")
    K8Helper.triage(environment, (len(resp) > 0), "No ServiceMonitors found")
    
    service_monitor = resp[0] 
    ep = service_monitor['spec']['endpoints'][0]
    K8Helper.triage(environment, (ep['port'] == 'exporter-port'), f"Wrong port: {ep['port']}")
    K8Helper.triage(environment, (ep['scheme'] == 'http'), f"Wrong scheme: {ep['scheme']}")
    K8Helper.triage(environment, (ep['interval'] == '60s'), f"Wrong interval: {ep['interval']}")
    K8Helper.triage(environment, (ep['honorLabels'] is True), "honorLabels not True")
    K8Helper.triage(environment, (ep['honorTimestamps'] is True), "honorTimestamps not True")

    selector = service_monitor['spec']['selector']['matchLabels']
    K8Helper.triage(environment, (selector.get('app.kubernetes.io/service') == 'devcfg-clusterwide-gpu-metrics-exporter'),f"Selector mismatch: {selector}")
    ns_selector = service_monitor['spec']['namespaceSelector']['matchNames']
    K8Helper.triage(environment, (environment.gpu_operator_namespace in ns_selector), f"NamespaceSelector mismatch: {ns_selector}")
    
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False
        tcfg['prometheus.serviceMonitor.enable'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr  = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to modify deviceconfig CR")
        
    time.sleep(30)
    ret_code, resp, err = k8_util.k8_get_servicemonitor_cr(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0),f"Failed to collect servicemonitors from namespace: {environment.gpu_operator_namespace}, error : {err}")
    K8Helper.triage(environment, (len(resp) == 0),f"Failed to delete servicemonitors in namespace: {environment.gpu_operator_namespace}")

def test_servicemonitor_attachMetadata(gpu_cluster, deviceconfig_install, environment):
    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['prometheus.serviceMonitor.enable'] = True
        tcfg['prometheus.serviceMonitor.attachMetadata.node'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    time.sleep(30)
    ret_code, resp, err = k8_util.k8_get_servicemonitor_cr(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to get ServiceMonitors: {err}")
    K8Helper.triage(environment, (len(resp) > 0), "No ServiceMonitors found")

    service_monitor = resp[0]  
    attach_metadata = service_monitor.get('spec', {}).get('attachMetadata', {})
    K8Helper.triage(environment, ('node' in attach_metadata),f"attachMetadata not found in servicemonitor spec")
    K8Helper.triage(environment, (attach_metadata.get('node') == True),f"attachMetadata is not set to True, found: {attach_metadata.get('node')}")
    
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False
        tcfg['prometheus.serviceMonitor.enable'] = False
        tcfg['prometheus.serviceMonitor.attachMetadata.node'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to modify deviceconfig CR")
        
    time.sleep(30)
    ret_code, resp, err = k8_util.k8_get_servicemonitor_cr(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0),f"Failed to collect servicemonitors from namespace: {environment.gpu_operator_namespace}, error : {err}")
    K8Helper.triage(environment, (len(resp) == 0),f"Failed to delete servicemonitors in namespace: {environment.gpu_operator_namespace}")  

def test_servicemonitor_relabeling(gpu_cluster, deviceconfig_install, environment):

    global Logger
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['prometheus.serviceMonitor.enable'] = True
        tcfg['prometheus.serviceMonitor.honorLabels'] = False
        tcfg['prometheus.serviceMonitor.relabelings'] = [
            {
                'sourceLabels': ['pod'],
                'targetLabel': 'exporter_pod',
                'action': 'replace',
                'regex': '(.*)',
                'replacement': '$1'
            },
            {
                'action': 'labeldrop',
                'regex': 'pod'
            }
        ]
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR with honorLabels=False")
        
    time.sleep(30)
    ret_code, resp, err = k8_util.k8_get_servicemonitor_cr(environment.gpu_operator_namespace)
    K8Helper.triage(environment,(ret_code == 0),f"Failed to collect servicemonitors from namespace: {environment.gpu_operator_namespace}, error: {err}")
    K8Helper.triage(environment, (len(resp) > 0), f"Found 0 entries of servicemonitors in namespace: {environment.gpu_operator_namespace}")

    service_monitor = resp[0]
    spec = service_monitor.get('spec', {})
    K8Helper.triage(environment,('honorLabels' not in spec),f"ServiceMonitor should NOT have honorLabels, but spec contains: {spec.get('honorLabels')}")
    
    endpoints = spec.get('endpoints', [])
    relabelings = endpoints[0].get('relabelings', [])
    K8Helper.triage(environment,(len(relabelings) == 2), f"Expected 2 relabeling rules, got: {len(relabelings)}")

    K8Helper.triage(environment, (relabelings[0].get('sourceLabels') == ['pod']), f"First relabeling rule should have sourceLabels=['pod'], got: {relabelings[0].get('sourceLabels')}")
    K8Helper.triage(environment,(relabelings[0].get('targetLabel') == 'exporter_pod'),f"First relabeling rule should have targetLabel='exporter_pod', got: {relabelings[0].get('targetLabel')}" )
    K8Helper.triage(environment,(relabelings[0].get('action') == 'replace'),f"First relabeling rule should have action='replace', got: {relabelings[0].get('action')}")
    K8Helper.triage( environment, (relabelings[0].get('regex') == '(.*)'),f"First relabeling rule should have regex='(.*)', got: {relabelings[0].get('regex')}")

    K8Helper.triage( environment,(relabelings[1].get('action') == 'labeldrop'),f"Second relabeling rule should have action='labeldrop', got: {relabelings[1].get('action')}")
    K8Helper.triage( environment, (relabelings[1].get('regex') == 'pod'),f"Second relabeling rule should have regex='pod', got: {relabelings[1].get('regex')}")

    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = False
        tcfg['prometheus.serviceMonitor.enable'] = False
        tcfg['prometheus.serviceMonitor.honorLabels'] = True
        tcfg['prometheus.serviceMonitor.relabelings'] = []
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), f"Failed to modify deviceconfig CR")
        
    time.sleep(30)
    ret_code, resp, err = k8_util.k8_get_servicemonitor_cr(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0),f"Failed to collect servicemonitors from namespace: {environment.gpu_operator_namespace}, error : {err}")
    K8Helper.triage(environment, (len(resp) == 0),f"Failed to delete servicemonitors in namespace: {environment.gpu_operator_namespace}")  

def test_exporter_pod_annotations(gpu_cluster, deviceconfig_install, environment):
    global Logger
    # This feature was introduced in v1.4.1
    if environment.gpu_operator_version < "v1.4.1":
        pytest.skip(f"pod_annotations feature is not available in release before v1.4.1")

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # enable exporter pod annotation and check for metrics
    NUM_ANNOTATIONS = 10
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.podAnnotations'] = {
            f"pod-annotation-{i}" : f"pod-value-{i}" for i in range(NUM_ANNOTATIONS)
        }
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
    """
    {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "annotations": {
                "cni.projectcalico.org/containerID": "c59f3e17575ea8739d828bb4764de7398d5136474b45d39b1ae7a6cec895cbe7",
                "cni.projectcalico.org/podIP": "192.168.125.91/32",
                "cni.projectcalico.org/podIPs": "192.168.125.91/32",
                "label-1": "pod-1",
                "label-2": "pod-2"
             },
        }
    }
    """
    ret_code, pods = k8_util.k8_get_pods(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to collect pods from {environment.gpu_operator_namespace}")
    for pod in pods:
        pod_name = pod['metadata']['name']
        if "metrics-exporter" not in pod_name:
            continue

        # this is a metrics-exporter pod
        node_name = pod['spec']['node_name']
        K8Helper.triage(environment, pod["metadata"].get("annotations", None) != None,
                        f"pod : {pod_name} on node {node_name} missing annotations section")
        pod_annots = pod["metadata"]["annotations"]
        for i in range(NUM_ANNOTATIONS):
            lbl = f"pod-annotation-{i}"
            val = f"pod-value-{i}"
            K8Helper.triage(environment, lbl in pod_annots,
                            f"pod : {pod_name} on node {node_name} missing label : {lbl}")
            K8Helper.triage(environment, pod_annots[lbl] == val,
                            f"pod : {pod_name} on node {node_name} label-value mismatch, expected: {lbl}:{val}")

    # remove pod-annotations
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.podAnnotations'] = {}
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    # Check for corresponding deviceconfig created
    K8Helper.check_deviceconfig_status(environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(environment, devcfg)

    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")
    ret_code, pods = k8_util.k8_get_pods(environment.gpu_operator_namespace)
    K8Helper.triage(environment, (ret_code == 0), f"Failed to collect pods from {environment.gpu_operator_namespace}")
    for pod in pods:
        pod_name = pod['metadata']['name']
        if "metrics-exporter" not in pod_name:
            continue

        # this is a metrics-exporter pod
        node_name = pod['spec']['node_name']
        K8Helper.triage(environment, pod["metadata"].get("annotations", None) != None,
                        f"pod : {pod_name} on node {node_name} missing annotations section")
        pod_annots = pod["metadata"]["annotations"]
        for i in range(NUM_ANNOTATIONS):
            lbl = f"pod-annotation-{i}"
            val = f"pod-value-{i}"
            K8Helper.triage(environment, lbl not in pod_annots,
                            f"pod : {pod_name} on node {node_name} found label : {lbl}, annotations: {pod_annots}")


def test_exporter_service_annotations(gpu_cluster, deviceconfig_install, environment):
    global Logger
    # This feature was introduced in v1.4.1
    if environment.gpu_operator_version < "v1.4.1":
        pytest.skip(f"pod_annotations feature is not available in release before v1.4.1")

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes()
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # enable exporter serviceAnnotations
    NUM_ANNOTATIONS = 10
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceAnnotations'] = {
            f"svc-annotation-{i}" : f"svc-value-{i}" for i in range(NUM_ANNOTATIONS)
        }
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    """
    vm@k8-master-249:~$ kubectl get svc -n kube-amd-gpu devcfg-clusterwide-gpu-metrics-exporter   -o json
    {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "annotations": {
               "label-1": "svc-1",
               "label-2": "svc-2"
            },
    }
    """
    time.sleep(10)
    ret_code, services, ret_err = k8_util.k8_get_services(environment.gpu_operator_namespace)
    K8Helper.triage(environment, ret_code == 0,
                    f"Failed to get k8-services in {environment.gpu_operator_namespace}, error : {ret_err}")
    K8Helper.triage(environment, len(services) > 0,f"No services found in {environment.gpu_operator_namespace}")
    for svc in services:
        svc_name = svc["metadata"]["name"]
        if "metrics-exporter" in svc_name:
            K8Helper.triage(environment, (svc["metadata"].get("annotations", None) != None),
                            f"Missing annotations for svc : {svc_name}")
            svc_annots = svc["metadata"]["annotations"]
            for i in range(NUM_ANNOTATIONS):
                lbl = f"svc-annotation-{i}"
                val = f"svc-value-{i}"
                K8Helper.triage(environment, lbl in svc_annots, f"Missing annotation : {lbl}")
                K8Helper.triage(environment, svc_annots[lbl] == val, f"Mismatch in annotation, expected: {lbl}:{val}")

    # disable exporter serviceAnnotations
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['metricsExporter.enable'] = True
        tcfg['metricsExporter.serviceAnnotations'] = {}
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(cr_spec)
        K8Helper.triage(environment, (ret_code == 0), "Failed to modify deviceconfig CR")

    time.sleep(10)
    ret_code, services, ret_err = k8_util.k8_get_services(environment.gpu_operator_namespace)
    K8Helper.triage(environment, ret_code == 0,
                    f"Failed to get k8-services in {environment.gpu_operator_namespace}, error : {ret_err}")
    K8Helper.triage(environment, len(services) > 0, f"No services found in {environment.gpu_operator_namespace}")
    for svc in services:
        svc_name = svc["metadata"]["name"]
        if "metrics-exporter" in svc_name:
            svc_annots = svc["metadata"].get("annotations", None)
            if svc_annots:
                for i in range(NUM_ANNOTATIONS):
                    lbl = f"svc-annotation-{i}"
                    val = f"svc-value-{i}"
                    K8Helper.triage(environment, (lbl not in svc_annots), f"Persistent annotation after cleanup: {svc_annots}")

