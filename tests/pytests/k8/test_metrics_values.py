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
import threading
from collections import defaultdict
import lib.common as common
import lib.k8_util as k8_util
import lib.spec_util as spec_util
import lib.metric_util as metric_util
import lib.amdgpu as amdgpu_util
from k8.util import K8Helper

#pytestmark = pytest.mark.skip("debugging")
Logger = logging.getLogger("k8.test_metrics_values")
LogPrettyPrinter = pprint.PrettyPrinter(indent = 2)

@pytest.fixture(scope="function", autouse=True)
def setup_testcase_info(request, environment):
    setattr(environment, 'current_tc_name', request.node.name)
    yield
    delattr(environment, 'current_tc_name')

@pytest.fixture(scope="module")
def gpu_operator_install(gpu_cluster, release_name, images, environment):
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
    K8Helper.triage(environment, (ret_code == 0), f"Failed to install helm-chart for {release_name}")
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
    K8Helper.triage(environment, (ret_code == 0), f"Failed to uninstall {release_name} helm-chart, error: {ret_stderr}")
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
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")

    # Enable profile-metrics
    config_map_name = "prof-metrics-cfgmap"
    config_map = {
        "GPUConfig" : {
            "ProfilerMetrics": {
                "all": True,
            }
        },
    }
    configmap_file = os.path.join(environment.logdir, f"{config_map_name}.json")
    with open(configmap_file, "w") as fp:
        fp.write(json.dumps(config_map, indent=4))

    configmap_file = os.path.join(environment.logdir, f"config.json")
    with open(configmap_file, "w") as fp:
        fp.write(json.dumps(config_map, indent=4))

    # Delete if there is any previous instance with same name
    ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_configmap(gpu_cluster, environment.gpu_operator_namespace, config_map_name)
    Logger.debug(f"Configmap cleanup: ret_code:{ret_code}")
    # ignore ret_code
    ret_code, ret_stdout, ret_stderr = k8_util.k8_create_configmap(gpu_cluster, 
                                                                   environment.gpu_operator_namespace,
                                                                   config_map_name, configmap_file)
    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'devicePlugin.enableNodeLabeller' : False,
            'metricsExporter.enable' : True,
            'metricsExporter.serviceType' : 'NodePort',
            'metricsExporter.port' : 5000,
            'metricsExporter.rbacConfig.enable' : False,
            'metricsExporter.rbacConfig.disableHttps' : False,
            'metricsExporter.config' : config_map_name,
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
        K8Helper.triage(environment, (ret_code == 0), f"Failed to create deviceconfig, stderr: {ret_stderr}")
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

@pytest.fixture(scope="module")
def amd_smi_collect(gpu_cluster, gpu_operator_install, deviceconfig_install, environment):
    # Derive gpu information using amd-smi information
    global Logger
    Logger.info("Collecting amd-smi info collection for all nodes")
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
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
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    time.sleep(30) # Wait for exporter to start working
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_name = k8_util.k8_get_node_hostname(node)
        exporter_pod_name = k8_util.k8_get_pod_name(gpu_cluster, "metrics-exporter", environment.gpu_operator_namespace, node_name)
        # Collect gpu information from the node
        cmd = [K8Helper.get_amd_smi_path(environment), "static", "--json"]
        ret_code, amd_smi_info, resp_stderr = k8_util.exec_command_in_pod(gpu_cluster,
                                                                          environment.gpu_operator_namespace,
                                                                          cmd, exporter_pod_name, "metrics-exporter-container")
        K8Helper.triage(environment, (ret_code == 0 and len(amd_smi_info) > 0),
                        f"Unable to collect amd-smi static information from node {node_name}, error : {resp_stderr}")
        amdgpu_util.extract_amdgpu_info(cluster_node, node, amd_smi_info)

@pytest.fixture(scope="module")
def metrics_samples(gpu_cluster, images, deviceconfig_install, amd_smi_collect, environment):
    global Logger
    global LogPrettyPrinter
    Logger.info(f"Collecting metrics-exporter curl output, amd-smi metrics and gpuctl metrics snapshot")
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    K8Helper.delete_debug_pods(gpu_cluster, [environment.gpu_operator_namespace, "default"])

    # Watch for all pod creation
    '''
    test-deviceconfig-device-plugin-8f7px                        1/1     Running       0                 12d
    test-deviceconfig-metrics-exporter-27gq9                     2/2     Running       0                 12d
    '''
    devicecfg_pods = [
        common.PodInfo('device-plugin', len(gpu_nodes), 1),
        common.PodInfo('metrics-exporter', len(gpu_nodes), 1),
    ]
    failed_pods = k8_util.k8_check_pod_running(gpu_cluster, environment.gpu_operator_namespace, devicecfg_pods)
    K8Helper.triage(environment, not failed_pods, f"One or more pods are not ready - {failed_pods}")

    time.sleep(30) # Wait for exporter to start working
    def _collect_amd_smi_output(cmd_responses, exporter_pod_name, num_samples = 10):
        cmd = ["amd-smi", "metric", "--json"]
        for _ in range(num_samples):
            ret_code, resp_stdout, resp_stderr = k8_util.exec_command_in_pod(gpu_cluster,
                                                                             environment.gpu_operator_namespace,
                                                                             cmd, exporter_pod_name,
                                                                             "metrics-exporter-container")
            if ret_code != 0:
                Logger.error(f"Cmd {cmd} failed on {exporter_pod_name}, error : {resp_stderr}")
            else:
                cmd_responses.append(resp_stdout.replace("'", "\"").replace("True", "\"True\"").replace("False", "\"False\""))
            time.sleep(1)
        return

    def _collect_gpuctl_output(cmd_responses, exporter_pod_name, num_samples = 10):
        cmd = ["gpuctl", "show", "gpu", "--json"]
        for _ in range(num_samples):
            ret_code, resp_stdout, resp_stderr = k8_util.exec_command_in_pod(gpu_cluster,
                                                                             environment.gpu_operator_namespace,
                                                                             cmd, exporter_pod_name,
                                                                             "metrics-exporter-container")
            if ret_code != 0:
                Logger.error(f"Cmd {cmd} failed on {exporter_pod_name}, error : {resp_stderr}")
            else:
                cmd_responses.append(resp_stdout.replace("'", "\"").replace("True", "\"True\"").replace("False", "\"False\""))
            time.sleep(1)
        return

    def _collect_exporter_metrics(cmd_responses, cluster_node, num_samples = 10):
        for _ in range(num_samples):
            # Collect 10 exporter_metrics
            ret_code, ret_stdout, ret_stderr = cluster_node.http_get(node_port, "metrics")
            #if ret_code != 0:
            #    # try from node itself
            #    ret_code, ret_stdout, ret_stderr = cluster_node.proxy_http_get(node_ip, node_port, "metrics")

            if ret_code != 0:
                Logger.error(f"Failed to get metrics from nodeport endpoint for {node_ip}, stdout: {ret_stdout} stderr: {ret_stderr}")
            else:
                cmd_responses.append(ret_stdout)
            time.sleep(1)
        return

    num_samples = 10
    idle_metrics = {}
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_name = k8_util.k8_get_node_hostname(node)
        node_port = deviceconfig_install.exporter_port_map[node_name]
        exporter_pod_name = k8_util.k8_get_pod_name(gpu_cluster, "metrics-exporter", environment.gpu_operator_namespace, node_name)
        # Collect gpu information from the node
        cmd = ["amd-smi", "static", "--json"]
        ret_code, amd_smi_info, resp_stderr = k8_util.exec_command_in_pod(gpu_cluster,
                                                                         environment.gpu_operator_namespace,
                                                                         cmd, exporter_pod_name,
                                                                         "metrics-exporter-container")
        K8Helper.triage(environment, (ret_code == 0 and len(amd_smi_info) > 0),
                        f"Unable to collect amd-smi static information from node {node_name}, error : {resp_stderr}")

        threads = []
        exporter_metrics = []
        smi_metrics = []
        gpuctl_metrics = []

        threads.append(threading.Thread(target = _collect_amd_smi_output, args=(smi_metrics, exporter_pod_name, num_samples)))
        threads.append(threading.Thread(target = _collect_exporter_metrics, args=(exporter_metrics, cluster_node, num_samples)))
        if environment.builtin_gpuctl_support:
            threads.append(threading.Thread(target = _collect_gpuctl_output, args=(gpuctl_metrics, exporter_pod_name, num_samples)))

        # Start all the threads
        for thr in threads:
            thr.start()

        time.sleep(num_samples * 1)

        # Wait for all threads to complete
        for thr in threads:
            thr.join()

        idle_metrics[node_name] = {}
        idle_metrics[node_name]['title'] = f"Metrics for {node_name} under idle conditions"
        idle_metrics[node_name]['num-samples'] = num_samples
        idle_metrics[node_name]['gpu-series'] = cluster_node.gpu_series
        idle_metrics[node_name]['gpu-info'] = amd_smi_info
        idle_metrics[node_name]['exporter'] = exporter_metrics
        idle_metrics[node_name]['amd-smi'] = smi_metrics
        idle_metrics[node_name]['gpuctl'] = gpuctl_metrics
        metric_util.dump_json_samples(smi_metrics, os.path.join(environment.logdir, f"idle_{cluster_node.gpu_series}_smi_metrics"))
        metric_util.dump_json_samples([amd_smi_info], os.path.join(environment.logdir, f"idle_{cluster_node.gpu_series}_smi_info"))
        metric_util.dump_all_samples(exporter_metrics, os.path.join(environment.logdir, f"idle_{node_name}_curl"))
        metric_util.dump_json_samples(gpuctl_metrics, os.path.join(environment.logdir, f"idle_{cluster_node.gpu_series}_gpuctl"))
        K8Helper.triage(environment, (len(smi_metrics) == num_samples),
                        f"Failed to collect all required number of amd-smi-metrics samples for node {node_name}")
        K8Helper.triage(environment, (len(exporter_metrics) == num_samples),
                        f"Failed to collect all required number of metrics-exporter samples for node {node_name}")
        if environment.builtin_gpuctl_support:
            K8Helper.triage(environment, (len(gpuctl_metrics) == num_samples),
                            f"Failed to collect all required number of gpucltl-metrics samples for node {node_name}")

    # Deploy workload (pytorch application) and check for metrics
    local_workload_ctxts = []
    # Create a workload
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_name = k8_util.k8_get_node_hostname(node)
        gpu_cap, gpu_alloc = k8_util.k8_get_node_gpu_capacity(gpu_cluster, node_name)
        params = {
            "node_name" : node_name,
            "images" : images,
            "num_gpu_reqd" : gpu_cap,
        }
        workload_ctxt = K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.START_WORKLOAD, **params)
        K8Helper.triage(environment, (workload_ctxt['podStatus'] == K8Helper.PodStatus.RUNNING),
                        f"Job: workload failed to start : {workload_ctxt}")
        local_workload_ctxts.append(workload_ctxt)

    # Collect new sample of metrics
    workload_metrics = {}
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_name = k8_util.k8_get_node_hostname(node)
        node_port = deviceconfig_install.exporter_port_map[node_name]
        exporter_pod_name = k8_util.k8_get_pod_name(gpu_cluster, "metrics-exporter", environment.gpu_operator_namespace, node_name)

        # Collect gpu information from the node
        cmd = ["amd-smi", "static", "--json"]
        ret_code, amd_smi_info, resp_stderr = k8_util.exec_command_in_pod(gpu_cluster,
                                                                         environment.gpu_operator_namespace,
                                                                         cmd, exporter_pod_name,
                                                                         "metrics-exporter-container")
        K8Helper.triage(environment, (ret_code == 0 and len(amd_smi_info) > 0),
                        f"Unable to collect amd-smi static information from node {node_name}, error : {resp_stderr}")
        threads = []
        exporter_metrics = []
        smi_metrics = []
        gpuctl_metrics = []

        threads.append(threading.Thread(target = _collect_amd_smi_output, args=(smi_metrics, exporter_pod_name, num_samples)))
        threads.append(threading.Thread(target = _collect_exporter_metrics, args=(exporter_metrics, cluster_node, num_samples)))
        if environment.builtin_gpuctl_support:
            threads.append(threading.Thread(target = _collect_gpuctl_output, args=(gpuctl_metrics, exporter_pod_name, num_samples)))

        # Start all the threads
        for thr in threads:
            thr.start()

        time.sleep(num_samples * 1)

        # Wait for all threads to complete
        for thr in threads:
            thr.join()

        workload_metrics[node_name] = {}
        workload_metrics[node_name]['title'] = f"Metrics for {node_name} with workload"
        workload_metrics[node_name]['num-samples'] = num_samples
        workload_metrics[node_name]['gpu-series'] = cluster_node.gpu_series
        workload_metrics[node_name]['gpu-info'] = amd_smi_info
        workload_metrics[node_name]['exporter'] = exporter_metrics
        workload_metrics[node_name]['amd-smi'] = smi_metrics
        workload_metrics[node_name]['gpuctl'] = gpuctl_metrics
        metric_util.dump_json_samples(smi_metrics, os.path.join(environment.logdir, f"load_{cluster_node.gpu_series}_smi_metrics"))
        metric_util.dump_json_samples([amd_smi_info], os.path.join(environment.logdir, f"load_{cluster_node.gpu_series}_smi_info"))
        metric_util.dump_all_samples(exporter_metrics, os.path.join(environment.logdir, f"load_{node_name}_curl"))
        metric_util.dump_json_samples(gpuctl_metrics, os.path.join(environment.logdir, f"load_{cluster_node.gpu_series}_gpuctl"))

        K8Helper.triage(environment, (len(smi_metrics) == num_samples),
                        f"Failed to collect all required number of amd-smi-metrics samples for node {node_name}")
        K8Helper.triage(environment, (len(exporter_metrics) == num_samples),
                        f"Failed to collect all required number of metrics-exporter samples for node {node_name}")
        if environment.builtin_gpuctl_support:
            K8Helper.triage(environment, (len(gpuctl_metrics) == num_samples),
                            f"Failed to collect all required number of gpucltl-metrics samples for node {node_name}")
    for ctxt in local_workload_ctxts:
        K8Helper.workload_operation(gpu_cluster, environment, K8Helper.WorkloadOp.STOP_WORKLOAD, **ctxt)
    yield (idle_metrics, workload_metrics)
    return

# Generate testcases for each metrics supported for value 
def pytest_generate_tests(metafunc):
    global Logger
    if 'metric_to_test' in metafunc.fixturenames:
        metrics_to_test = []
        for entry in metric_util.get_supported_metrics():
            if entry.get('skip-validation', 'no') == 'yes':
                continue
            metrics_to_test.append(entry['name'])
        metafunc.parametrize('metric_to_test', metrics_to_test)

def test_exporter_all_supported_metrics(gpu_cluster, metrics_samples, environment):
    """
    Testcase to check if all metrics supported for each of gpu-series is observed in the curl output of exporter endpoint
    """
    global Logger
    global LogPrettyPrinter

    def _test_if_metrics_exported(metric_to_test, gpu_id, exporter_metrics):
        metric_metadata = metric_util.get_metric_metadata(metric_to_test)
        if ':' in metric_to_test:
            label_name = metric_metadata['label']
            metric_name, label_value = metric_to_test.split(":")
            m_info_list = []
            for _, entry in enumerate(exporter_metrics[metric_name.lower()]):
                if entry['labels']['gpu_id'] != str(gpu_id):
                    continue
                K8Helper.triage(environment, (label_name in entry['labels']),
                                f"Label {label_name} missing in exported metrics {entry}, {metric_metadata}")
                lval = entry['labels'][label_name]
                if lval != label_value:
                    continue
                m_info_list.append(entry)

            Logger.debug(f"Found total {len(m_info_list)} exported metrics for {metric_to_test}")
            if len(m_info_list) > 0:
                Logger.info(f"Found {len(m_info_list)} entries of {metric_to_test}")
                return True
        else:
            if metric_to_test.lower() in exporter_metrics:
                Logger.info(f"Found {metric_to_test}")
                return True
        Logger.error(f"Missing {metric_to_test}")
        return False

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    failed_metrics = defaultdict(set)
    all_idle_metrics, all_workload_metrics = metrics_samples
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_name = k8_util.k8_get_node_hostname(node)
        K8Helper.triage(environment, (cluster_node.num_gpus > 0), f"Node {node_name} has no GPUs present")

        # Pick up first sample of exporter metrics for given node
        idle_metrics = metric_util.parse_metric_data(all_idle_metrics[node_name]['exporter'][0])
        workload_metrics = metric_util.parse_metric_data(all_workload_metrics[node_name]['exporter'][0])

        supported_metrics = metric_util.get_supported_metrics(cluster_node.gpu_series)
        Logger.info(f"Node: {node_name} having {cluster_node.gpu_series} has {len(supported_metrics)} metrics")
        for entry in supported_metrics:
            metric_to_test = entry['name']
            Logger.info(f"Checking {metric_to_test} among exported metrics for node {node_name}")
            for gpu_id in range(cluster_node.num_gpus):
                if _test_if_metrics_exported(metric_to_test, gpu_id, idle_metrics) == False:
                    Logger.error(f"Idle Conditions Metrics: {metric_to_test} failed for {gpu_id}")
                    failed_metrics[metric_to_test].add(gpu_id)
                if _test_if_metrics_exported(metric_to_test, gpu_id, workload_metrics) == False:
                    Logger.error(f"Load Conditions Metrics: {metric_to_test} failed for {gpu_id}")
                    failed_metrics[metric_to_test].add(gpu_id)
    K8Helper.triage(environment, (len(failed_metrics) == 0),
                    f"Metics validation failed: {failed_metrics.keys()} from exported-metrics\n{LogPrettyPrinter.pformat(failed_metrics)}")


def test_exporter_metrics_value_accuracy(gpu_cluster, metrics_samples, metric_to_test, environment):
    """
    Parameterized testcase to test metric_to_test metric as set by pytest_generate_tests
    """

    global Logger
    metric_metadata = metric_util.get_metric_metadata(metric_to_test)
    def _extract_amd_smi_value(amd_smi_metrics, path_to_metric):
        if len(path_to_metric) == 0:
            return None
        elif len(path_to_metric) == 1:
            return amd_smi_metrics.get(path_to_metric[0], None)
        else:
            return _extract_amd_smi_value(amd_smi_metrics.get(path_to_metric[0], {}), path_to_metric[1:])

    def _analyze_metrics_collection(metric_to_test, gpu_id, metric_data):
        num_samples = metric_data['num-samples']
        Logger.info(f"Processing {metric_data['title']} - total samples {num_samples}")
        hit_count = 0
        miss_count = 0
        all_amd_smi_metrics = metric_data['amd-smi']
        all_exporter_metrics = metric_data['exporter']
        for sample_id in range(num_samples):
            # Extract exporter metrics for current sample_id
            exporter_metrics = metric_util.parse_metric_data(all_exporter_metrics[sample_id])

            # Extract amd-smi metrics for current sample_id
            amd_smi_metrics = json.loads(all_amd_smi_metrics[sample_id])
            gpu_support_info = metric_util.get_metric_support_info(metric_metadata, metric_data["gpu-series"])
            K8Helper.triage(environment, (gpu_support_info != None),
                            f"Missing gpu-support-info for {metric_to_test}, {metric_metadata}, {metric_data['gpu-series']}")
            amd_smi_source = gpu_support_info.get('amd-smi', None)
            K8Helper.triage(environment, (amd_smi_source != None),
                            f"Missing amd-smi source information for {metric_to_test}, {gpu_support_info}")

            if ':' in metric_to_test:
                label_name = metric_metadata['label']
                metric_name, label_value = metric_to_test.split(":")
                m_info_list = []
                for _, entry in enumerate(exporter_metrics[metric_name.lower()]):
                    if entry['labels']['gpu_id'] != str(gpu_id):
                        continue
                    K8Helper.triage(environment, (label_name in entry['labels']),
                                    f"Label {label_name} missing in exported metrics {entry}, {metric_metadata}")
                    lval = entry['labels'][label_name]
                    if lval != label_value:
                        continue
                    m_info_list.append(entry)

                Logger.debug(f"Found total {len(m_info_list)} exported metrics for {metric_to_test}")
                K8Helper.triage(environment, (len(m_info_list) > 0),
                                f"Unable to get {metric_to_test} from exporter-metrics for gpu:{gpu_id}")
                idx = 0
                amd_smi_values = []
                while True:
                    path_to_metric = amd_smi_source.format(idx = idx).split(".")
                    if isinstance(amd_smi_metrics, list):
                        amd_smi_val = _extract_amd_smi_value(amd_smi_metrics[gpu_id], path_to_metric)
                    elif isinstance(amd_smi_metrics, dict) and 'gpu_data' in amd_smi_metrics.keys():
                        amd_smi_val = _extract_amd_smi_value(amd_smi_metrics['gpu_data'][gpu_id], path_to_metric)
                    if amd_smi_val != None:
                        amd_smi_values.append(amd_smi_val)
                    else:
                        break
                    idx = idx + 1
                Logger.debug(f"Found total {len(amd_smi_values)} from amd-smi output for {metric_to_test}")
                for idx, entry in enumerate(list(zip(m_info_list, amd_smi_values))):
                    metric_info, amd_smi_val = entry
                    if amd_smi_val["value"] == "N/A":
                        Logger.warn(f"No amd-smi metric information for idx {idx} {metric_to_test}, got {amd_smi_val}")
                        continue
                    lower_limit = int(0.95 * float(amd_smi_val["value"]))
                    upper_limit = int(1.05 * float(amd_smi_val["value"]))
                    Logger.debug(f"{metric_to_test} Sample:{sample_id} AMD-SMI: {amd_smi_val}, exporter : {metric_info}")
                    if lower_limit <= int(metric_info["value"]) <= upper_limit:
                        hit_count = hit_count + 1
                    else:
                        miss_count = miss_count + 1
            else:
                path_to_metric = amd_smi_source.split(".")
                K8Helper.triage(environment, (metric_to_test.lower() in exporter_metrics),
                                f"Missing {metric_to_test} in collected metrics from exporter endpoint, {metric_metadata}")
                m_info_list = list(filter(lambda x: x['labels']['gpu_id'] == str(gpu_id), exporter_metrics[metric_to_test.lower()]))
                Logger.debug(f"Found total {len(m_info_list)} exported metrics for {metric_to_test}")

                metric_info = m_info_list[0]
                if isinstance(amd_smi_metrics, list):
                    amd_smi_val = _extract_amd_smi_value(amd_smi_metrics[gpu_id], path_to_metric)
                elif isinstance(amd_smi_metrics, dict) and 'gpu_data' in amd_smi_metrics.keys():
                    amd_smi_val = _extract_amd_smi_value(amd_smi_metrics['gpu_data'][gpu_id], path_to_metric)
                K8Helper.triage(environment, (amd_smi_val != None),
                                f"Failed to extract amd-smi metric value for {metric_to_test}, {gpu_support_info}")
                if amd_smi_val["value"] == 'N/A':
                    pytest.skip(f"No amd-smi metric information for {metric_to_test}, got {amd_smi_val}")

                Logger.debug(f"{metric_to_test} Sample:{sample_id} AMD-SMI: {amd_smi_val}, exporter : {metric_info}")
                lower_limit = int(0.95 * float(amd_smi_val["value"]))
                upper_limit = int(1.05 * float(amd_smi_val["value"]))
                Logger.debug(f"{metric_to_test} Sample:{sample_id} AMD-SMI: {amd_smi_val}, exporter : {metric_info}")
                if lower_limit <= int(metric_info["value"]) <= upper_limit:
                    hit_count = hit_count + 1
                else:
                    miss_count = miss_count + 1
        return hit_count, miss_count

    metric_validated = False
    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    K8Helper.triage(environment, (ret_code == 0), "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, (len(gpu_nodes) > 0), "No nodes with AMD/GPU found in the cluster")
    all_idle_metrics, all_workload_metrics = metrics_samples
    for node in gpu_nodes:
        node_ip = k8_util.k8_get_node_address(node)
        cluster_node = gpu_cluster.get_worker_node(node_ip)
        if not cluster_node:
            pytest.fail(f"Unable to get worker node from cluster for ip: {node_ip}")
        node_name = k8_util.k8_get_node_hostname(node)

        if not metric_util.is_metric_supported(metric_to_test, cluster_node.gpu_series):
            continue
        metric_validated = True

        """
        for idle-state metrics, access metrics values as below:

        idle_metrics['exporter'] = exporter_metrics
        idle_metrics['amd-smi'] = smi_metrics

        for workload-state metrics, access metrics values as below:

        workload_metrics['exporter'] = exporter_metrics
        workload_metrics['amd-smi'] = smi_metrics
        """
        idle_metrics = all_idle_metrics[node_name]
        workload_metrics = all_workload_metrics[node_name]

        for gpu_id in range(cluster_node.num_gpus):
            num_samples = idle_metrics['num-samples']
            idle_hit_count, idle_miss_count = _analyze_metrics_collection(metric_to_test, gpu_id, idle_metrics)
            Logger.info(f"Worker: {node_name} GPU: {gpu_id} - Idle Hit/Miss: {idle_hit_count}/{idle_miss_count}")

            load_hit_count, load_miss_count = _analyze_metrics_collection(metric_to_test, gpu_id, workload_metrics)
            Logger.info(f"Worker: {node_name} GPU: {gpu_id} - Loaded Hit/Miss: {load_hit_count}/{load_miss_count}")

            K8Helper.triage(environment, (idle_hit_count > int(0.65 * num_samples)),
                            f"IDLE Metric: {metric_to_test} GPU: {gpu_id} not in sync, hit: {idle_hit_count}, miss {idle_miss_count}")

            K8Helper.triage(environment, (load_hit_count > int(0.65 * num_samples)),
                            f"LOAD Metric: {metric_to_test} GPU: {gpu_id} not in sync, hit: {load_hit_count}, miss {load_miss_count}")

    if not metric_validated:
        pytest.skip(f"Metric {metric_to_test} cannot be validated in this setup - skip")

