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
import os
import sys
import time
import json
import glob
import logging
import pytest
import subprocess
import base64
import pprint
import datetime
from functools import wraps
from collections import defaultdict
from typing import List, Dict
from kubernetes import client, config, stream
from kubernetes.client.rest import ApiException
import lib.common as common

Logger = logging.getLogger("lib.k8util")
LogPrettyPrinter = pprint.PrettyPrinter(indent = 2)

def log_arguments(func):
    global Logger
    global LogPrettyPrinter

    @wraps(func)
    def wrapper(*args, **kwargs):
        Logger.debug(f"Function::'{func.__name__}' with args: {args} kwargs: {kwargs}")
        return func(*args, **kwargs)
    return wrapper

K8Items = List[dict]

def k8_lib_init(k8_cluster : common.k8_cluster) -> None:
    global Logger
    if k8_cluster.k8_kube_config:
        # Load Kubernetes configuration
        try:
            config.load_kube_config(config_file = k8_cluster.k8_kube_config)
        except config.ConfigException as e:
            pytest.fail(f"failed to load kube-config, error : {e}")

        # Build k8_cluster with worker-node information
        ret_code, k8_nodes = k8_get_nodes(k8_cluster)
        assert ret_code == 0, f"Failed to collect worker nodes from k8/cluster"
        for node in k8_nodes:
            if 'node-role.kubernetes.io/control-plane' in node['metadata']['labels']:
                if 'node-role.kubernetes.io/worker' in node['metadata']['labels']:
                    Logger.info(f"control-plane node is also a worker-node")
                else:
                    Logger.warn(f"control-plane node is not a worker-node - skipping it")
                    continue # skip control-plane node

            node_ip = k8_get_node_address(node)
            Logger.debug(f"Adding {node_ip} worker-node to the cluster")
            k8_cluster.add_worker_node(node_ip)
        assert len(k8_cluster.worker_nodes) > 0, f"Failed to collect worker nodes from k8/cluster"
    else:
        k8_cluster.k8_master.run_command(f"rm -rf workspace")

    if k8_cluster.k8_secrets:
        # create secrets, but first create the non-default namespace(s) listed in each entry
        namespaces = list(filter(lambda x: x != 'default', map(lambda entry: entry.get('namespace', 'default'), k8_cluster.k8_secrets['secrets'])))
        for namespace in namespaces:
            ret_code, ret_stdout, ret_stderr = k8_create_namespace(k8_cluster, namespace)
            if ret_code != 0:
                Logger.debug(f"Failed to create namespace {namespace}, error: {ret_stderr}")

        for entry in k8_cluster.k8_secrets["secrets"]:
            ret_code, ret_stdout, ret_stderr = k8_delete_secret(k8_cluster,
                                                                entry.get("name"),
                                                                entry.get("type"),
                                                                entry.get("namespace", "default"))
            if ret_code != 0:
                Logger.warn(f"secret deletion failed, code: {ret_code}, stdout: {ret_stdout}, stderr: {ret_stderr}")
            ret_code, ret_stdout, ret_stderr = k8_create_secret(k8_cluster,
                                                                entry.get("name"),
                                                                entry.get("type"),
                                                                username = entry.get("username"),
                                                                password = entry.get("password"),
                                                                namespace = entry.get("namespace", "default"))
            if ret_code != 0:
                Logger.error(f"secret create failed, code: {ret_code}, stdout: {ret_stdout}, stderr: {ret_stderr}")
                pytest.fail(f"failed to create secret type {entry.get('name')} - Abort")
    return

@log_arguments
def helm_list(k8_cluster : common.k8_cluster, namespace : str) -> (int, str, str):
    """
    API to list installed helm-charts in a given namespace
    
    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    namespace : The name of namespace

    Returns:
    int: return-code, 0 for success else failure
    stdout : stdout from command execution
    stderr : stderr from command execution
    """
    global Logger
    cmd = ["helm", "list", "-a", "--namespace", namespace, "-o", "json"]
    if k8_cluster.k8_kube_config:
        cmd.extend(["--kubeconfig", k8_cluster.k8_kube_config])
        cmd_resp = subprocess.run(cmd, check=False,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  encoding='utf-8')
        return cmd_resp.returncode, cmd_resp.stdout, cmd_resp.stderr
    else:
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def helm_add_repo(k8_cluster : common.k8_cluster, repo_name : str, repo_url : str) -> None:
    """
    API to add helm repo

    For example, following commands will be run:
    helm repo add rocm <repo>
    helm repo update

    Parameters:
    k8_cluster : intance of lib.common.k8_cluster
    repo_name  : Name of the repo
    repo_url   : repo url
    """
    cmd = ["helm", "repo", "add", repo_name, repo_url]
    if k8_cluster.k8_kube_config:
        cmd.extend(["--kubeconfig", k8_cluster.k8_kube_config])
        cmd_resp = subprocess.run(cmd, check=False,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    encoding='utf-8')
        ret_code = cmd_resp.returncode
    else:
        ret_code, _, _ = k8_cluster.k8_master.run_command(" ".join(cmd))
    assert ret_code == 0, f"Failed to add helm repo {repo}, stdout : {ret_stdout} stderr: {ret_stderr}"

    cmd = ["helm", "repo", "update"]
    if k8_cluster.k8_kube_config:
        cmd.extend(["--kubeconfig", k8_cluster.k8_kube_config])
        cmd_resp = subprocess.run(cmd, check=False,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    encoding='utf-8')
        ret_code = cmd_resp.returncode
    else:
        ret_code, _, _ = k8_cluster.k8_master.run_command(" ".join(cmd))
    assert ret_code == 0, f"Failed to update helm repo {repo}, stdout : {ret_stdout} stderr: {ret_stderr}"
    return

@log_arguments
def helm_install(k8_cluster : common.k8_cluster, release_name : str, namespace : str, helm_chart_path : str, version : str, values_yaml : str, **kwargs) -> (int, str, str):
    """
    API to install helm-chart

    For example, following command will be run:
    helm install <release-name> <path-to-helm-chart>
        -n kube-amd-gpu --create-namespace --version=<version>
        --set controllerManager.manager.image.repository=registry.test.pensando.io:5000/amd-gpu-operator
        --set controllerManager.manager.image.tag=latest 

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    release_name : release-name to use for helm-chart installation
    namespace : namespace in which to install helm-chart
    helm_chart_path : path to helm chart (file or repo path)
    version : version of the helm-chart to install
    values_yaml : values.yaml file

    Returns:
    ret_code   : Return code for command execution. 0 for success else failure
    ret_stdout : Stdout from command execution
    ret_stderr : Stderr from command execution
    """

    global Logger
    cmd = ["helm", "install", "--debug", f"{release_name}", f"{helm_chart_path}"]
    cmd.extend(["-n", f"{namespace}", "--create-namespace"])
    if version:
        cmd.extend([f"--version={version}"])

    for key, value in kwargs:
        cmd.extend(["--set", f"{key}={value}"])

    if k8_cluster.k8_kube_config:
        cmd.extend(["--kubeconfig", k8_cluster.k8_kube_config])
        if values_yaml:
            if not os.path.exists(values_yaml):
                return -1, "", f"Missing values.yaml : {values_yaml}"
            if k8_cluster.k8_master.is_local():
                    cmd.extend(["-f", values_yaml])
        Logger.debug(f"helm-install command: {' '.join(cmd)}")
        cmd_resp = subprocess.run(cmd, check=False,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  encoding='utf-8')
        return cmd_resp.returncode, cmd_resp.stdout, cmd_resp.stderr
    else:
        if values_yaml:
            if not os.path.exists(values_yaml):
                return -1, "", f"Missing values.yaml : {values_yaml}"
            if k8_cluster.k8_master.is_local():
                cmd.extend(["-f", values_yaml])
            else:
                k8_cluster.k8_master.run_command(f"mkdir -p workspace")
                remote_file = os.path.join("workspace", os.path.basename(values_yaml))
                k8_cluster.k8_master.put(values_yaml, remote_file)
                cmd.extend(["-f", remote_file])
        Logger.debug(f"helm-install command: {' '.join(cmd)}")
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def helm_uninstall(k8_cluster : common.k8_cluster, release_name : str, namespace : str) -> (int, str, str):
    """
    API to uninstall helm-chart

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    release_name : Release-name of the helm-chart
    namespace : name-space in which helm-chart was installed

    Returns:
    int: return-code, 0 for success else failure
    stdout: stdout of command execution
    stderr: stderr of command execution
    """

    global Logger
    cmd = ["helm", "uninstall", "--debug", f"{release_name}", "--namespace", f"{namespace}"]
    if k8_cluster.k8_kube_config:
        cmd.extend(["--kubeconfig", k8_cluster.k8_kube_config])
        cmd_resp = subprocess.run(cmd, check=False,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    encoding='utf-8')
        return cmd_resp.returncode, cmd_resp.stdout, cmd_resp.stderr
    else:
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def helm_cleanup(k8_cluster : common.k8_cluster, release_name : str, namespace : str) -> (int, str, str):
    """
    API to do forceful cleanup, if helm-uninstall resulted in failure

    Following command will be run: "helm uninstall <release-name> --namespace <namespace> --no-hooks"

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    release_name : helm-chart release name
    namespace : namespace to use

    Returns:
    int: return-code, 0 for success else failure
    stdout: stdout of command execution
    stderr: stderr of command execution
    """
    global Logger
    cmd = ["helm", "uninstall", f"{release_name}", "--namespace", f"{namespace}", "--no-hooks"]
    if k8_cluster.k8_kube_config:
        cmd.extend(["--kubeconfig", k8_cluster.k8_kube_config])
        cmd_resp = subprocess.run(cmd, check=False,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    encoding='utf-8')
        return cmd_resp.returncode, cmd_resp.stdout, cmd_resp.stderr
    else:
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def is_helm_chart_deployed(k8_cluster : common.k8_cluster, release_name : str, namespace : str) -> bool:
    """
    API to check if helm-chart is deployed. 

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    release-name: release-name used for helm-chart
    namespace : namespace in which helm-chart is installed

    Returns:
    bool : True if chart is deployed else False
    """
    ret_code, ret_stdout, ret_stderr = helm_list(k8_cluster, namespace)

    """
    Sample output
    vm@master-node:~/sandbox$ helm list -n kube-amd-gpu -o json | jq .
    [
      {
        "name": "gpu-operator",
        "namespace": "kube-amd-gpu",
        "revision": "1",
        "updated": "2024-12-11 10:04:56.122288711 +0000 UTC",
        "status": "failed", or "deployed",
        "chart": "gpu-operator-v1.0.0",
        "app_version": "v1.0.0"
      }
    ]
    """
    for chart in json.loads(ret_stdout):
        if chart['name'] == release_name and chart['status'] != 'uninstalling':
            return True
    return False

@log_arguments
def is_helm_chart_healthy(k8_cluster : common.k8_cluster, release_name : str, namespace : str) -> bool:
    """
    API to check if installed helm-chart is healthy

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    release-name: release-name used for helm-chart
    namespace : namespace in which helm-chart is installed

    Returns:
    bool : True if chart is deployed and healthy else False
    """
    """
    Sample output
    vm@master-node:~/sandbox$ helm list -n kube-amd-gpu -o json | jq .
    [
      {
        "name": "gpu-operator",
        "namespace": "kube-amd-gpu",
        "revision": "1",
        "updated": "2024-12-11 10:04:56.122288711 +0000 UTC",
        "status": "failed", or "deployed",
        "chart": "gpu-operator-v1.0.0",
        "app_version": "v1.0.0"
      }
    ]
    """
    ret_code, ret_stdout, ret_stderr = helm_list(k8_cluster, namespace)
    for chart in json.loads(ret_stdout):
        if chart['name'] == release_name and chart['status'] == 'deployed':
            return True
    return False

def k8_get_nodes(k8_cluster : common.k8_cluster) -> (int, str, K8Items):
    """
    API to get nodes from k8 cluster

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster

    Returns:
    list of dict. For example refer to output of 'kubectl get nodes -o json | jq .items'
    """
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        try:
            nodes = api.list_node().to_dict()
            return 0, nodes.get('items', None)
        except ApiException as e:
            Logger.error(f"Failed to collect nodes, error : {e}")
            return -1, None
    else:
        cmd = ["kubectl", "get", "nodes", "-ojson"]
        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join(cmd))
        if ret_code != 0:
            return ret_code, None
        k8_nodes_info = json.loads(resp_stdout)
        return ret_code, k8_nodes_info.get("items", None)

def k8_get_gpu_nodes(k8_cluster : common.k8_cluster, skip_not_ready : bool = True) -> (int, K8Items):
    """
    API to get nodes from k8 cluster which have 'feature.node.kubernetes.io/amd-gpu : true'

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster

    Returns:
    list of dict. For example refer to output of 'kubectl get nodes -o json | jq .items'
    """
    global Logger
    global LogPrettyPrinter
    ret_code, k8_nodes = k8_get_nodes(k8_cluster)
    if ret_code != 0:
        return ret_code, None
    #Logger.debug(f"Nodes : \n{LogPrettyPrinter.pformat(k8_nodes)}")

    k8_gpu_nodes = list()
    for node in k8_nodes:
        if node['metadata']['labels'].get('feature.node.kubernetes.io/amd-gpu', 'false') != 'true':
            continue

        if skip_not_ready:
            ready_condition = list(filter(lambda x: x.get('type', 'NotReady') == 'Ready', node['status']['conditions']))
            assert len(ready_condition) == 1, 'Failed to find Ready condition for node'

            if ready_condition[0]['status'] != 'True':
                continue
        k8_gpu_nodes.append(node)

    return ret_code, k8_gpu_nodes

@log_arguments
def k8_get_node_gpu_capacity(k8_cluster : common.k8_cluster, node_name : str) -> (int, int):
    """
    API to get the node's status.capacity and status.allocatable values of gpu

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    node_name  : name of the node

    Returns:
    gpu_capacity
    gpu_allocatable
    """
    ret_code, gpu_nodes = k8_get_gpu_nodes(k8_cluster)
    filtered_list = list(filter(lambda x: x['metadata']['name'] == node_name, gpu_nodes))
    assert len(filtered_list) == 1, f"No such cluster-node exists : {node_name}"
    node = filtered_list[0]
    gpu_capacity = node['status']['capacity'].get("amd.com/gpu", -1)
    gpu_allocatable = node['status']['allocatable'].get("amd.com/gpu", -1)
    return(int(gpu_capacity), int(gpu_allocatable))

@log_arguments
def k8_get_node_gpu_alloc_requests(k8_cluster, node_name):
    ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(f"kubectl describe node {node_name} | \
                                             awk '/Allocated resources/,/gpu/'")
    assert ret_code == 0, "Failed to get kubectl describe node output for node {node_name}"
    output = resp_stdout.strip().splitlines()
    requests = -1
    limit = -1
    for entry in output:
        if 'amd.com/gpu' in entry:
            entry = entry.split()
            requests = entry[1]
            limit = entry[2]

    return(requests, limit)
    

def k8_get_node_gpu_allocatable(k8_cluster: common.k8_cluster, node_name: str) -> str:
    ret_code, gpu_nodes = k8_get_gpu_nodes(k8_cluster)
    filtered_list = list(filter(lambda x: x['metadata']['name'] == node_name, gpu_nodes))
    assert len(filtered_list) == 1, f"No such cluster-node exists: {node_name}"

    node = filtered_list[0]

    for gpu_type in node['status']['allocatable'].keys():
        if node['status']['allocatable'][gpu_type] != '0':
            return gpu_type
    return "amd.com/gpu"


@log_arguments
def k8_get_pods(k8_cluster, namespace, node_name = None):
    """
    API to get all pods for a given namespace from a k8 cluster
    """
    global Logger
    if k8_cluster.k8_kube_config:
        try:
            api = client.CoreV1Api()
            if namespace:
                pod_info = api.list_namespaced_pod(namespace = namespace).to_dict()
            else:
                pod_info = api.list_pod_for_all_namespaces().to_dict()
            if node_name:
                return 0, list(filter(lambda x: x['spec']['node_name'] == node_name, pod_info['items']))
            return 0, pod_info['items']
        except ApiException as e:
            Logger.error(f"Failed to list all pods for give namespace {namespace} error : {e}")
            return -1, None
    else:
        cmd = ["kubectl", "get", "pods"]
        if namespace:
            cmd.extend(["--namespace", f"{namespace}"])
        else:
            cmd.append("-A")

        cmd.append("-ojson")
        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join(cmd))
        if ret_code != 0:
            return ret_code, None
        k8_pod_info = json.loads(resp_stdout)
        return ret_code, k8_pod_info.get("items", None)

@log_arguments
def k8_get_endpoints(k8_cluster, namespace):
    """
    API to get endpoints from a k8 cluster for a given namespace and filtered by service-name
    """
    global Logger
    global LogPrettyPrinter
    ret_values = defaultdict(list)
    ret_code = -1
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        try:
            k8_endpoint_info = api.list_endpoints_for_all_namespaces().to_dict()
            Logger.debug(f"List Endpoints, resp:\n{LogPrettyPrinter.pformat(k8_endpoint_info)}")
            endpoints = list(filter(lambda x: x['metadata']['namespace'] == namespace, k8_endpoint_info.get("items", list())))
            ret_code = 0
        except ApiException as e:
            Logger.error(f"Failed to collect endpoints, error: {e}")
            return -1, None
        for item in endpoints:
            service_name = item["metadata"]["name"]
            subset_infos = item.get("subsets", [])
            if subset_infos:
                for subset in subset_infos:
                    port = subset['ports'][0]['port']
                    for address in subset['addresses']:
                        ip_address = address['ip']
                        host = address['node_name']
                        ret_values[service_name].append((host, ip_address, port))
    else:
        cmd = ["kubectl", "get", "endpoints"]
        if namespace:
            cmd.extend(["--namespace", f"{namespace}"])
        else:
            cmd.append("-A")

        cmd.append("-ojson")

        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join(cmd))
        if ret_code != 0:
            return ret_code, None
        k8_endpoint_info = json.loads(resp_stdout)

        for item in k8_endpoint_info.get("items", []):
            service_name = item["metadata"]["name"]
            subset_infos = item.get("subsets", [])
            for subset in subset_infos:
                port = subset['ports'][0]['port']
                for address in subset['addresses']:
                    ip_address = address['ip']
                    host = address['node_name']
                    ret_values[service_name].append((host, ip_address, port))
    return ret_code, ret_values

@log_arguments
def k8_create_deviceconfig_cr(k8_cluster : common.k8_cluster, cr_spec : dict) -> (int, str, str):
    """
    API to create custom-resource on a K8 cluster.
    """
    global Logger

    if k8_cluster.k8_kube_config:
        custom_objects_api = client.CustomObjectsApi()
        # Read cr_file and derive: group, version, plural and name
        group, version = cr_spec['apiVersion'].split('/')
        plural = cr_spec['kind'].lower() + 's'
        namespace = cr_spec['metadata']['namespace']
        try:
            _ = custom_objects_api.create_namespaced_custom_object(group, version, namespace, plural, cr_spec)
        except ApiException as e:
            Logger.error(f"Failed to create deviceconfig-cr, error: {e}")
            return -1, "", str(e)
        return 0, "", ""
    else:
        cr_file = os.path.join("logs", "deviceconfig_cr.yaml")
        spec_util.dump_yaml(cr_file, cr_spec)

        if not os.path.exists(cr_file):
            return -1, "", f"Missing cr_file : {cr_file}"

        cmd = ["kubectl", "apply", "-f"]
        if k8_cluster.k8_master.is_local():
            cmd.append(f"{cr_file}")
        else:
            k8_cluster.k8_master.run_command(f"mkdir -p workspace")
            remote_file = os.path.join("workspace", os.path.basename(cr_file))
            k8_cluster.k8_master.put(cr_file, remote_file)
            cmd.append(remote_file)
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_modify_deviceconfig_cr(k8_cluster : common.k8_cluster, cr_spec : dict) -> (int, str, str):
    """
    API to modify custom-resource on a K8 cluster.
    """
    global Logger

    if k8_cluster.k8_kube_config:
        custom_objects_api = client.CustomObjectsApi()
        # Read cr_file and derive: group, version, plural and name
        group, version = cr_spec['apiVersion'].split('/')
        plural = cr_spec['kind'].lower() + 's'
        namespace = cr_spec['metadata']['namespace']
        devcfg_name = cr_spec['metadata']['name']
        try:
            devcfg_obj = custom_objects_api.get_namespaced_custom_object(group = group, version = version, namespace = namespace, 
                                                                         plural = plural, name = devcfg_name)
            # Modify devcfg_obj['spec']
            devcfg_obj['spec'] = cr_spec['spec']
            custom_objects_api.replace_namespaced_custom_object(group = group, version = version, namespace = namespace, 
                                                                plural = plural, name = devcfg_name, body=devcfg_obj)
        except ApiException as e:
            Logger.error(f"Failed to modify deviceconfig {devcfg_name}\n{devcfg_obj}\n Exception: {e}")
            return -1, "", str(e)
        return 0, "", ""
    else:
        return k8_create_deviceconfig_cr(k8_cluster, cr_spec)

@log_arguments
def k8_apply_cr(k8_cluster : common.k8_cluster, cr_spec : dict, cr_file : str) -> (int, str, str):
    """
    API to create custom-resource on a K8 cluster.
    """
    global Logger

    if k8_cluster.k8_kube_config:
        namespace = cr_spec.get('metadata').get('namespace')
        api = client.CoreV1Api()
        try:
            result = api.create_namespaced_pod(namespace, body=cr_spec)
        except ApiException as e:
            assert True, f"Failed to start pod\n{cr_spec}\n{str(e)}\n{result}"
            return -1, "", str(e)
        return 0, "", ""

    else:
        if not os.path.exists(cr_file):
            return -1, "", f"Missing cr_file : {cr_file}"

        cmd = ["kubectl", "apply", "-f"]
        if k8_cluster.k8_master.is_local():
            cmd.append(f"{cr_file}")
        else:
            k8_cluster.k8_master.run_command(f"mkdir -p workspace")
            remote_file = os.path.join("workspace", os.path.basename(cr_file))
            k8_cluster.k8_master.put(cr_file, remote_file)
            cmd.append(remote_file)
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_delete_deviceconfig_cr(k8_cluster : common.k8_cluster, namespace : str, name : str) -> (int, str, str):
    """
    API to delete deviceconfig CR with given name and namespace
    """
    global Logger
    if k8_cluster.k8_kube_config:
        custom_objects_api = client.CustomObjectsApi()
        group = 'amd.com'
        version = 'v1alpha1'
        plural = 'deviceconfigs'
        # check if it exists:
        found = False
        try:
            cr_list = custom_objects_api.list_namespaced_custom_object(group = group, version = version,
                                                                       namespace = namespace, plural = plural)
            for item in cr_list["items"]:
                if name == item["metadata"]["name"]:
                    found = True
        except ApiException as e:
            Logger.error(f"Failed to query deviceconfig CR, error: {e}")

        if not found:
            Logger.error(f"DeviceConfig {name} does not exists")
            return 0, "", ""
        try:
            custom_objects_api.delete_namespaced_custom_object(group=group,
                                                               version=version,
                                                               namespace=namespace,
                                                               plural=plural,
                                                               name=name,
                                                               body=client.V1DeleteOptions())
        except ApiException as e:
            Logger.error(f"Failed to delete deviceconfig CR, error: {e}")
            return -1, "", str(e)

        # Wait till resources are removed
        for _ in range(10):
            found = False
            try:
                cr_list = custom_objects_api.list_namespaced_custom_object(group = group, version = version,
                                                                           namespace = namespace, plural = plural)
                for item in cr_list["items"]:
                    if name == item["metadata"]["name"]:
                        found = True
            except ApiException as e:
                Logger.error(f"Failed to query deviceconfig CR, error: {e}")

            if not found:
                break
            time.sleep(5)
        return 0, "", ""
    else:
        cmd = ["kubectl", "delete", "deviceconfig", name, "-n", namespace]
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_delete_cr(k8_cluster, cr_spec, cr_file):
    """
    API to delete CR with given spec (dict)
    """
    global Logger

    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        try:
            api.delete_namespaced_pod(name=cr_spec.get('metadata').get('name'),
                                      namespace=cr_spec.get('metadata').get('namespace'))
        except ApiException as e:
            return -1, "", str(e)
        return 0, "", ""
    else:
        if not os.path.exists(cr_file):
            return  -1, "", f"Missing cr_file : {cr_file}"

        cmd = ["kubectl", "delete", "-f"]
        if k8_cluster.k8_master.is_local():
            cmd.append(f"{cr_file}")
        else:
            k8_cluster.k8_master.run_command(f"mkdir -p workspace")
            remote_file = os.path.join("workspace", os.path.basename(cr_file))
            k8_cluster.k8_master.put(cr_file, remote_file)
            cmd.append(remote_file)
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_create_rules_from_endpoint_list(endpoint_verbs : List):
    rules = []
    for url_verb in endpoint_verbs:
        url, verb = url_verb
        rules.append(client.V1PolicyRule(non_resource_ur_ls = [url], verbs=[verb]))
    return rules

@log_arguments
def k8_create_rules_from_verbs(resources, verbs, api_groups=[""]):
    return client.V1PolicyRule(
        api_groups=api_groups,
        resources=resources,
        verbs=verbs
    )

@log_arguments
def k8_create_cluster_role(k8_cluster : common.k8_cluster, cluster_role_name : str, rules : List) -> (int, str, str):
    """
    API to create a cluster-role with specific endpoint and corresponding verb

    Parameters:
    k8_cluster : instance of common.k8_cluster
    cluster_role_name : name of cluster-role
    endpoint_verbs : list of tuple of (endpoint, verb)

    Returns:
    ret_code (int) : 0 for success else failure
    stdout (str) : stdout
    stderr (str) : stderr
    """
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.RbacAuthorizationV1Api()

        cluster_role = client.V1ClusterRole(
                api_version="rbac.authorization.k8s.io/v1",
                kind = "ClusterRole",
                metadata = client.V1ObjectMeta(name=cluster_role_name),
                rules=rules)
        try:
            api_response = api.create_cluster_role(cluster_role)
            return 0, "", ""
        except ApiException as e:
            return -1, "", str(e)
    else:
        # Build yaml file
        cr_file = os.path.join("logs", f"cluster_role_{cluster_role_name}.yaml")
        spec_util.generate_cluster_role_spec(cr_file, cluster_role_name, endpoint_verbs)
        cmd = ["kubectl", "apply", "-f"]
        if k8_cluster.k8_master.is_local():
            cmd.append(f"{cr_file}")
        else:
            k8_cluster.k8_master.run_command(f"mkdir -p workspace")
            remote_file = os.path.join("workspace", os.path.basename(cr_file))
            k8_cluster.k8_master.put(cr_file, remote_file)
            cmd.append(remote_file)
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_create_role_binding(k8_cluster : common.k8_cluster, crb_name : str,  namespace : str, cluster_role_name : str, sa_name : str) -> (int, str, str):
    """
    API to create cluster-role-binding

    Parameters:
    k8_cluster : instance of common.k8_cluster
    crb_name : cluster-role-binding name
    namespace : reader namespace
    cluster_role_name : cluster-role name
    sa_name : service-account name

    Returns:
    int : 0 on success else failure
    str : stdout
    str : stderr
    """
    global Logger
    if k8_cluster.k8_kube_config:
        cluster_role_binding = client.V1ClusterRoleBinding(
                api_version = "rbac.authorization.k8s.io/v1",
                kind = "ClusterRoleBinding",
                metadata=client.V1ObjectMeta(name=crb_name),
                subjects=[
                    client.RbacV1Subject(
                        kind="ServiceAccount",
                        name=sa_name,
                        namespace=namespace)
                ],
                role_ref=client.V1RoleRef(
                    kind="ClusterRole",
                    name=cluster_role_name,
                    api_group="rbac.authorization.k8s.io")
        )
        api = client.RbacAuthorizationV1Api()
        try:
            # Create the ClusterRoleBinding
            api_response = api.create_cluster_role_binding(cluster_role_binding)
            return 0, "", ""
        except ApiException as e:
            return -1, "", str(e)
    else:
        cr_file = os.path.join("logs", "metrics-reader-get-crb.yaml")
        spec_util.generate_clusterrolebinding_yaml(cr_file, crb_name, namespace, cluster_role_name, sa_name)
        cmd = ["kubectl", "apply", "-f"]
        if k8_cluster.k8_master.is_local():
            cmd.append(f"{cr_file}")
        else:
            k8_cluster.k8_master.run_command(f"mkdir -p workspace")
            remote_file = os.path.join("workspace", os.path.basename(cr_file))
            k8_cluster.k8_master.put(cr_file, remote_file)
            cmd.append(remote_file)
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_delete_pod(k8_cluster : common.k8_cluster, pod_name : str, namespace : str, force : bool = False):
    """
    API to delete a pod
    """
    global Logger
    global LogPrettyPrinter
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        try:
            resp = api.delete_namespaced_pod(pod_name, namespace)
            #Logger.debug(f"Successfully delete pod, resp:\n{LogPrettyPrinter.pformat(resp)}")
            return 0, "", ""
        except ApiException as e:
            Logger.error(f"Failed to delete pod, error: {e}")
            return -1, "", str(e)
    else:
        cmd = f"kubectl delete pod {pod_name} -n {namespace}"
        return k8_cluster.k8_master.run_command(cmd)

@log_arguments
def k8_delete_all_pods(k8_cluster : common.k8_cluster, namespace : str):
    """
    API to delete all pods in a given namespace
    """
    global Logger
    if k8_cluster.k8_kube_config:
        ret_code, pods = k8_get_pods(k8_cluster, namespace)
        if ret_code != 0:
            return ret_code, "", f"Failed to get all pods for given namespace {namespace}"
        for pod in pods:
            k8_delete_pod(k8_cluster, pod['metadata']['name'], namespace)
        return 0, "", ""
    else:
        cmd = f"kubectl delete pods --all -n {namespace}"
        return k8_cluster.k8_master.run_command(cmd)

@log_arguments
def k8_delete_all_pods_with_prefix(k8_cluster : common.k8_cluster, namespace : str, pod_name_prefix: str) -> int:
    """
    API to delete all pods with given name prefix
    """
    global Logger
    global LogPrettyPrinter
    ret_code = 0
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()

        delete_list = []
        try:
            pods = api.list_namespaced_pod(namespace = namespace)
            for pod in pods.items:
                if pod.metadata.name.startswith(pod_name_prefix):
                    delete_list.append(pod.metadata.name)
        except ApiException as e:
            Logger.error(f"Failed to get all pods from namespace {namespace}, error: {e}")
            return -1

        Logger.info(f"Deleting following pods from the cluster : {delete_list}")
        for pod_name in delete_list:
            ret_code, ret_stdout, ret_stderr = k8_delete_pod(k8_cluster, pod_name, namespace, force = True)
            if ret_code != 0:
                Logger.error(f"Failed to delete pod {pod_name}, error {ret_stderr}")
    return ret_code

@log_arguments
def k8_get_namespaces(k8_cluster : common.k8_cluster):
    """
    API to get all namespaces in a given k8 cluster
    """
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        try:
            k8_namespace_info = api.list_namespace().to_dict()
        except ApiException as e:
            Logger.error(f"Failed to collect namespaces, error : {e}")
            return -1, None
    else:
        cmd = f"kubectl get namespaces -ojson"
        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(cmd)
        if ret_code != 0:
            return ret_code, None
        k8_namespace_info = json.loads(resp_stdout)
    return 0, k8_namespace_info.get("items", list())

@log_arguments
def k8_delete_namespace(k8_cluster : common.k8_cluster, namespace : str):
    """
    API to delete namespace in a given k8 cluster
    """
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        try:
            api_response = api.delete_namespace(name = namespace, body=client.V1DeleteOptions())
            Logger.debug("k8_delete_namespace::api_response : {api_response}")
            return 0, "", ""
        except ApiException as e:
            Logger.error(f"Failed to delete namespace, error : {e}")
            return -1, "", str(e)
    else:
        cmd = f"kubectl delete namespace {namespace}"
        return k8_cluster.k8_master.run_command(cmd)

@log_arguments
def k8_create_namespace(k8_cluster : common.k8_cluster, namespace : str):
    """
    API to create a namespace
    """
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        msg_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        try:
            api_response = api.create_namespace(body = msg_body)
            Logger.debug("k8_create_namespace::api_response : {api_response}")
            return 0, "", ""
        except ApiException as e:
            Logger.error(f"Failed to create namespace, error : {e}")
            return -1, "", str(e)
    else:
        cmd = f"kubectl create namespace {namespace}"
        return k8_cluster.k8_master.run_command(cmd)


@log_arguments
def k8_create_pre_test_runner_job(k8_cluster: common.k8_cluster, namespace: str, images: dict, sa_name: str, deployment_name: str, worker: str):
    global Logger
    apps_v1 = client.AppsV1Api()
    core_v1 = client.CoreV1Api()
    gpu_type = k8_get_node_gpu_allocatable(k8_cluster, worker)
    init_cap, alloc = k8_get_node_gpu_capacity(k8_cluster, worker)

    # Define deployment metadata
    labels = {"purpose": "demo-pytorch-amdgpu"}

    # Define the volume mounts for the init container
    init_container_volume_mounts = [
        client.V1VolumeMount(
            name="config-volume",
            mount_path="/etc/test-runner/"
        ),
        client.V1VolumeMount(
            name="rvs-logs",
            mount_path="/var/log"
        )
    ]

    # Define initContainer for the test runner
    init_container = client.V1Container(
        name="init-test-runner",
        image=f"{images.get('testRunner.image.repository')}:{images.get('testRunner.image.version')}",
        image_pull_policy="IfNotPresent",
        volume_mounts=init_container_volume_mounts,
        resources=client.V1ResourceRequirements(
            requests={gpu_type: init_cap},
            limits={gpu_type: init_cap}
        ),
        env=[
            client.V1EnvVar(name="TEST_TRIGGER", value="PRE_START_JOB_CHECK"),
            client.V1EnvVar(
                name="POD_NAME",
                value_from=client.V1EnvVarSource(
                    field_ref=client.V1ObjectFieldSelector(field_path="metadata.name")
                )
            ),
            client.V1EnvVar(
                name="POD_NAMESPACE",
                value_from=client.V1EnvVarSource(
                    field_ref=client.V1ObjectFieldSelector(field_path="metadata.namespace")
                )
            ),
            client.V1EnvVar(
                name="NODE_NAME",
                value_from=client.V1EnvVarSource(
                    field_ref=client.V1ObjectFieldSelector(field_path="spec.nodeName")
                )
            )
        ]
    )

    # Define the copy-rvs-logs container
    copy_logs_container = client.V1Container(
        name="copy-rvs-logs",
        image="busybox",
        command=["sh", "-c", "echo 'Copying RVS logs...'; cp -rv /var/log/* /host-logs/ && sleep 3600"],
        volume_mounts=[
            client.V1VolumeMount(name="rvs-logs", mount_path="/var/log"),
            client.V1VolumeMount(name="host-logs", mount_path="/host-logs"),
        ]
    )

    # Define the main container for the PyTorch workload
    main_container = client.V1Container(
        name="pytorch-gpu-workload",
        image="docker.io/rocm/pytorch:latest",
        command=["/bin/bash", "-c", "--"],
        args=["sleep 6000"],
        resources=client.V1ResourceRequirements(
            requests={gpu_type: "1"},
            limits={gpu_type: "1"}
        ),
    )

    # Define the volumes
    volumes = [
        client.V1Volume(
            name="rvs-logs",
            empty_dir=client.V1EmptyDirVolumeSource()
        ),
        client.V1Volume(
            name="host-logs",
            host_path=client.V1HostPathVolumeSource(
                path="/var/log/amd-test-runner",
                type="DirectoryOrCreate"
            )
        ),
        client.V1Volume(
            name="config-volume",
            config_map=client.V1ConfigMapVolumeSource(name="config-test-runner")
        ),
    ]

    # Define the Pod template spec
    pod_template_spec = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels=labels),
        spec=client.V1PodSpec(
            service_account_name=sa_name,
            init_containers=[init_container],
            containers=[copy_logs_container, main_container],
            volumes=volumes
        )
    )

    # Define the Deployment spec
    deployment_spec = client.V1DeploymentSpec(
        replicas=1,
        selector=client.V1LabelSelector(match_labels=labels),
        template=pod_template_spec
    )

    # Combine everything into the final Deployment body
    deployment_body = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(name=deployment_name, namespace=namespace, labels=labels),
        spec=deployment_spec
    )

    # Call the function to create the Deployment
    try:
        # Create the Deployment using the create_namespaced_deployment method
        deployment = apps_v1.create_namespaced_deployment(
            namespace=namespace,
            body=deployment_body
        )
        Logger.info(f"Deployment '{deployment_body.metadata.name}' created successfully in namespace '{namespace}'.")
        Logger.info(f"Status : {deployment.status.ready_replicas}")
    except ApiException as e:
        assert True, f"Error creating Deployment: {e}"

@log_arguments
def k8_get_deployment(namespace, deployment_name):
    global Logger
    apps_v1 = client.AppsV1Api()
    try:
        deployment = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        Logger.info(f"Deployment '{deployment.metadata.name}' found. Status:")
        Logger.info(f"  Replicas: {deployment.status.replicas}")
        Logger.info(f"  Ready Replicas: {deployment.status.ready_replicas}")
        Logger.info(f"  Available Replicas: {deployment.status.available_replicas}")
        Logger.info(f"  Unavailable Replicas: {deployment.status.unavailable_replicas}")

        Logger.info("\n  Deployment Conditions:")
        if deployment.status.conditions:
            Logger.info(deployment.status.conditions)
        else:
            Logger.info("No conditions reported for the deployment.")
        return deployment
    except client.ApiException as e:
        if e.status == 404:
            Logger.error(f"Error: Deployment '{deployment_name}' not found in namespace '{namespace}'.")
        else:
            Logger.error(f"Error fetching deployment status: {e}")
        assert True, f"Error fetching Deployment: {e}"

@log_arguments
def k8_delete_deployment(namespace, deployment_name):
    global Logger
    apps_v1 = client.AppsV1Api()
    try:
        delete_options = client.V1DeleteOptions(
            propagation_policy="Foreground", # Options: "Foreground", "Background", "Orphan"
            grace_period_seconds=5 # Graceful shutdown period in seconds
        )

        # Delete the namespaced deployment
        api_response = apps_v1.delete_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            body=delete_options
        )

        Logger.info(f"Deployment '{deployment_name}' in namespace '{namespace}' deleted successfully.")
        # You might inspect api_response for further details, though it often returns a V1Status object on success.
        return

    except client.ApiException as e:
        if e.status == 404:
            assert True, f"Error: Deployment '{deployment_name}' not found in namespace '{namespace}'."
        else:
            assert True, f"Error deleting deployment: {e}"
    except Exception as e:
        assert True, f"An unexpected error occurred: {e}"

@log_arguments
def k8_create_test_runner_job(k8_cluster, namespace : str, images : dict, worker : str, sa_name: str, job_name : str, healthy : bool, schedule : bool, minute : str):
    global Logger

    # Pre loaded Load Kubernetes configuration
    # This will typically load from ~/.kube/config or from within a cluster
    # Create an instance of the BatchV1Api, which is used for Jobs

    batch_v1_api = client.BatchV1Api()
    gpu_type = k8_get_node_gpu_allocatable(k8_cluster, worker)
    init_cap, alloc = k8_get_node_gpu_capacity(k8_cluster, worker)

    # Define environment variables
    env_vars = [
        client.V1EnvVar(name="TEST_TRIGGER", value="MANUAL"),
        client.V1EnvVar(
            name="POD_NAME",
            value_from=client.V1EnvVarSource(
                field_ref=client.V1ObjectFieldSelector(field_path="metadata.name")
            ),
        ),
        client.V1EnvVar(
            name="POD_NAMESPACE",
            value_from=client.V1EnvVarSource(
                field_ref=client.V1ObjectFieldSelector(field_path="metadata.namespace")
            ),
        ),
        client.V1EnvVar(
            name="NODE_NAME",
            value_from=client.V1EnvVarSource(
                field_ref=client.V1ObjectFieldSelector(field_path="spec.nodeName")
            ),
        ),
    ]
    if schedule:
        container_name = "init-test-runner"
    else:
        container_name = "amd-test-runner"

    if healthy and not schedule:
        # Define resource limits for the container
        # Note: Custom resources like 'amd.com/gpu' are strings in the limits dictionary.
        resources = client.V1ResourceRequirements(
            limits={
                gpu_type: init_cap  # Requesting 8 GPUs
            }
        )
        # Define containers
        container = client.V1Container(
            name=container_name,
            image=f"{images.get('testRunner.image.repository')}:{images.get('testRunner.image.version')}",
            image_pull_policy="IfNotPresent",
            security_context=client.V1SecurityContext(privileged=True),
            env=env_vars,
            resources=resources
        )
        # Define pod template spec
        pod_template_spec = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": "test-runner"}), # Add a label for easier identification
            spec=client.V1PodSpec(
                service_account_name=sa_name,
                node_selector={"kubernetes.io/hostname": worker},
                containers=[container],
                restart_policy="Never",
            ),
        )
    else:    # Define volume mounts
        volume_mounts = [
            client.V1VolumeMount(mount_path="/dev/dri", name="dri"),
            client.V1VolumeMount(mount_path="/dev/kfd", name="kfd"),
            client.V1VolumeMount(mount_path="/var/log/amd-test-runner", name="host-logs")
        ]

        # Define volumes
        volumes = [
            client.V1Volume(
                name="kfd",
                host_path=client.V1HostPathVolumeSource(
                    path="/dev/kfd", type="CharDevice"
                ),
            ),
            client.V1Volume(
                name="dri",
                host_path=client.V1HostPathVolumeSource(
                    path="/dev/dri", type="Directory"
                ),
            ),
            client.V1Volume(
                name="host-logs",
                host_path=client.V1HostPathVolumeSource(
                    path="/var/log/amd-test-runner",
                    type="DirectoryOrCreate"
                )
            )
        ]
        # Define containers
        container = client.V1Container(
            name=container_name,
            image=f"{images.get('testRunner.image.repository')}:{images.get('testRunner.image.version')}",
            image_pull_policy="IfNotPresent",
            security_context=client.V1SecurityContext(privileged=True),
            volume_mounts=volume_mounts,
            env=env_vars,
        )

        # Define pod template spec
        pod_template_spec = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": "test-runner"}), # Add a label for easier identification
            spec=client.V1PodSpec(
                service_account_name=sa_name,
                node_selector={"kubernetes.io/hostname": worker},
                volumes=volumes,
                containers=[container],
                restart_policy="Never",
            ),
        )

    # Define job spec
    job_spec = client.V1JobSpec(
        template=pod_template_spec,
        backoff_limit=0,
        ttl_seconds_after_finished=120,
    )

    # Define job metadata
    job_metadata = client.V1ObjectMeta(
        name=job_name, namespace=namespace
    )

    if not schedule:
        # Create the V1Job object
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=job_metadata,
            spec=job_spec,
        )
        try:
            # Create the Job in the specified namespace
            api_response = batch_v1_api.create_namespaced_job(namespace=namespace, body=job)
            Logger.info(f"Job created successfully: {api_response.metadata.name}")
        except client.ApiException as e:
            assert True, f"Error creating Job: {e}"
    else:
            # Define the Job template spec for the CronJob
        job_template_spec = client.V1JobTemplateSpec(spec=job_spec)
        cronjob_spec = client.V1CronJobSpec(
            schedule=f"{minute} * * * *", # Daily at midnight
            job_template=job_template_spec
        )

        # Create the V1CronJob object
        cron_job = client.V1CronJob(
            api_version="batch/v1", # Changed apiVersion for CronJob
            kind="CronJob",        # Changed kind to CronJob
            metadata=job_metadata,
            spec=cronjob_spec,
        )
        try:
            # Create the Job in the specified namespace
            api_response = batch_v1_api.create_namespaced_cron_job(namespace=namespace, body=cron_job)
            Logger.info(f"Job created successfully: {api_response.metadata.name}")
        except client.ApiException as e:
            assert True, f"Error creating Job: {e}"


@log_arguments
def k8_get_job_status(k8_cluster : common.k8_cluster, namespace : str, job_name):
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.BatchV1Api()
        v1 = client.CoreV1Api()
        try:
            time.sleep(2)
            api_response = api.list_namespaced_job(namespace=namespace)
            Logger.debug(f"k8_get_job::api_response : {api_response}")
            result = ""
            if len(api_response.items) != 0:
                item = api_response.items[-1]
                if item.status.succeeded == None:
                    result = "Unknown"
                elif item.status.active == None and item.status.succeeded == "1":
                    result = "Succeeded"
                elif item.status.active == "1":
                    result = "Active"
            else:
                return "Incomplete"
            Logger.debug(f"Status of job is {result} and full status is {item.status}")
            label_selector = f"job-name={job_name}"
            pods = v1.list_pod_for_all_namespaces(label_selector=label_selector)
            Logger.debug("k8_get_job::list of pods assoc with job: {job_name}:\n{pods}")
                #Pending, Running, Succeeded
            if len(pods.items) == 0:
                return "Completed"
            if pods.items[-1].status.phase:
                return pods.items[-1].status.phase
            return result
        except ApiException as e:
            Logger.error(f"Failed to get job, error : {e}")
            return "Completed"
    else:
        cmd = f"kubectl get job -n {namespace} | tail -1" + " | awk '{print $2}'"
        ret_code, stdout, stderr = k8_cluster.k8_master.run_command(cmd)
        Logger.info(f"running job:\n{stdout}")
        return stdout.split('/')[0]

@log_arguments
def k8_delete_job(k8_cluster : common.k8_cluster, namespace : str, job_name : str):
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.BatchV1Api()
        v1 = client.CoreV1Api()
        try:
            label_selector = f"job-name={job_name}"
            pods = v1.list_pod_for_all_namespaces(label_selector=label_selector)
            for pod in pods.items:
                k8_delete_pod(k8_cluster, pod.metadata.name, namespace, True)
            api_response = api.delete_namespaced_job(namespace=namespace, name=job_name)
            Logger.debug("k8_get_job::api_response : {api_response}")
            return True
        except ApiException as e:
            return -1, "", str(e)
    else:
        cmd = f"kubectl delete job -n {namespace} {job_name} | tail -1" + " | awk '{print $2}'"
        ret_code, stdout, stderr = k8_cluster.k8_master.run_command(cmd)
        Logger.info(f"Deleting job:\n{stdout}")
        return stdout.split('/')[0]

@log_arguments
def k8_get_cron_job_status(k8_cluster : common.k8_cluster, namespace : str, job_name):
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.BatchV1Api()
        try:
            api_response = api.list_namespaced_cron_job(namespace=namespace)
            Logger.debug("k8_get_cron_job::api_response : {api_response}")
            return api_response.items[-1].metadata.name == job_name
        except ApiException as e:
            Logger.error(f"Failed to get cron job, error : {e}")
            return False
    else:
        cmd = f"kubectl get cronjob -n {namespace} | tail -1 | " + "awk '{print $NF}'"
        ret_code, stdout, stderr = k8_cluster.k8_master.run_command(cmd)
        Logger.info(f"was scheduled :\n{stdout}")
        return "No resources found in" not in stderr

@log_arguments
def k8_delete_cron_job(k8_cluster : common.k8_cluster, namespace : str, job_name : str):
    global Logger
    if k8_cluster.k8_kube_config:
        api = client.BatchV1Api()
        try:
            api_response = api.delete_namespaced_cron_job(namespace=namespace, name=job_name)
            Logger.debug("k8_get_job::api_response : {api_response}")
        except ApiException as e:
            return -1, "", str(e)
    else:
        cmd = f"kubectl delete cronjob -n {namespace} {job_name} | tail -1" + " | awk '{print $2}'"
        ret_code, stdout, stderr = k8_cluster.k8_master.run_command(cmd)
        Logger.info(f"Deleting job:\n{stdout}")
        return stdout.split('/')[0]


@log_arguments
def k8_check_pod_status(k8_cluster : common.k8_cluster, namespace : str, pod_list : List) -> Dict:
    pod_status = dict()
    ret_code, k8_pod_list = k8_get_pods(k8_cluster, namespace)
    assert ret_code == 0, "Error while getting all pods from k8-cluster"
    for pod_info in pod_list:
        sel_pods = list(filter(lambda x: pod_info.PodName in x['metadata'].get('name', None), k8_pod_list))
        for sel_pod_info in sel_pods:
            status_json = sel_pod_info.get('status', {})
            pod_status[sel_pod_info['metadata'].get('name')] = status_json.get('phase', 'Done')
    return pod_status


@log_arguments
def k8_check_pod_running(k8_cluster : common.k8_cluster, namespace : str, pod_list : List, sleep_time : int = 10, total_attempts : int = 10):
    """
    API to check if ALL of given list of PODs are running
    """
    global Logger
    global LogPrettyPrinter
    def _is_pod_present_and_match_status(k8_pod_list, pod_name, exp_pod_count, exp_cont_count, exp_status):
        sel_pods = list(filter(lambda x: pod_name in x['metadata'].get('name', None), k8_pod_list))
        if len(sel_pods) < exp_pod_count:
            Logger.warn(f"Found {len(sel_pods)} instances of pod_name: {pod_name}")
            return False

        match_status = True
        for sel_pod_info in sel_pods:
            status_json = sel_pod_info.get('status', None)
            if status_json and status_json.get('phase', None) != exp_status:
                match_status = False
                status = status_json.get('phase', None)
                Logger.warn(f"Pod: {pod_name} instance in {status} and not in {exp_status}")
                #Logger.debug(f"PodInfo:\n{LogPrettyPrinter.pformat(sel_pod_info)}")
        return match_status

    assert len(pod_list) > 0, "No pods specified to verify"
    if total_attempts == 0:
        total_attempts = 1

    failed_pods = list()
    for x in range(total_attempts):
        failed_pods.clear()
        ret_code, k8_pod_list = k8_get_pods(k8_cluster, namespace)
        assert ret_code == 0, "Error while getting all pods from k8-cluster"
        for pod_info in pod_list:
            if not _is_pod_present_and_match_status(k8_pod_list, pod_info.PodName, pod_info.NumInstances, pod_info.ContainerCount, 'Running'):
                failed_pods.append(pod_info.PodName)

        if failed_pods:
            time.sleep(sleep_time)
        else:
            break
    if failed_pods:
        Logger.debug(f"Status of the Pods {pod_list}\n{LogPrettyPrinter.pformat(k8_pod_list)}")
    return failed_pods

@log_arguments
def k8_check_pod_terminated(k8_cluster : common.k8_cluster, namespace : str, pod_list : List, sleep_time : int = 10, total_attempts : int = 10):
    """
    API to check if ALL of given list of PODs are terminated
    """
    global Logger
    global LogPrettyPrinter
    def _is_pod_terminated(k8_pod_list, pod_name):
        sel_pods = list(filter(lambda x: pod_name in x['metadata'].get('name', None), k8_pod_list))
        if len(sel_pods) == 0:
            return True
        return False

    assert len(pod_list) > 0, "No pods specified to verify"
    if total_attempts == 0:
        total_attempts = 1

    running_pods = list()
    for x in range(total_attempts):
        running_pods.clear()
        ret_code, k8_pod_list = k8_get_pods(k8_cluster, namespace)
        assert ret_code == 0, "Error while getting all pods from k8-cluster"

        for pod_info in pod_list:
            if not _is_pod_terminated(k8_pod_list, pod_info.PodName):
                running_pods.append(pod_info.PodName)

        if running_pods:
            time.sleep(sleep_time)
        else:
            break
    if running_pods:
        Logger.debug(f"Status of Pods {pod_list}\n{LogPrettyPrinter.pformat(k8_pod_list)}")
    return running_pods

@log_arguments
def k8_create_configmap(k8_cluster : common.k8_cluster, namespace : str, configmap_name : str, configmap_json_file : str):
    """
    API to create configmap in a k8-cluster

    Example: kubectl create configmap -n kube-amd-gpu exporter-config --from-file=config.json
    """
    global Logger
    if k8_cluster.k8_kube_config:
        with open(configmap_json_file) as fp:
            data = json.load(fp)
        api = client.CoreV1Api()
        config_map = client.V1ConfigMap(
                api_version = "v1",
                kind = "ConfigMap",
                metadata = client.V1ObjectMeta(name=configmap_name, namespace=namespace),
                data = {"config.json" : json.dumps(data)}
            )
        try:
            api_response = api.create_namespaced_config_map(namespace, config_map)
        except ApiException as e:
            Logger.error(f"Failed to create configmap, error : {e}")
            return -1, "", str(e)
        return 0, "", ""
    else:
        if not os.path.exists(configmap_json_file):
            return -1, "", f"Missing configmap_json_file : {configmap_json_file}"

        cmd = ["kubectl", "create", "configmap", "--namespace", namespace, configmap_name]
        if k8_cluster.k8_master.is_local():
            cmd.append(f"--from-file={configmap_json_file}")
        else:
            k8_cluster.k8_master.run_command(f"mkdir -p workspace")
            remote_file = os.path.join("workspace", os.path.basename(configmap_json_file))
            k8_cluster.k8_master.put(configmap_json_file, remote_file)
            cmd.append(f"--from-file={remote_file}")
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_delete_configmap(k8_cluster : common.k8_cluster, namespace : str, configmap_name : str):
    """
    API to create configmap in a k8-cluster

    Example: kubectl delete configmap --namespace kube-amd-gpu exporter-config
    """
    global Logger

    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        try:
            api_response = api.delete_namespaced_config_map(configmap_name, namespace)
        except ApiException as e:
            Logger.debug(f"Failed to delete config-map, error : {e}")
            return -1, "", str(e)
        return 0, "", ""
    else:
        cmd = ["kubectl", "delete", "configmap", "--namespace", namespace, configmap_name]
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_crictl_run_command(cluster_node, container_name, command):
    """
    API to run/inspect a container using crictl tool
    """
    pass

def k8_get_node_address(node_info, address_type = "InternalIP"):
    assert 'status' in node_info, f"k8 node missing status section, {node_info}"
    assert 'addresses' in node_info['status'], f"k8 node missing status.addresses, {node_info}"

    for addr in node_info['status']['addresses']:
        if addr.get("type", None) == address_type:
            return addr.get("address", None)
    assert f"Missing address-type : {address_type} in k8 node, {node_info}"

def k8_lookup_node_address(k8_cluster, node_name):
    global Logger
    ret_code, k8_nodes = k8_get_nodes(k8_cluster)
    if ret_code != 0:
        return ret_code, None

    for node in k8_nodes:
        if node['metadata']['name'] == node_name:
            return k8_get_node_address(node)

    assert f"Missing node k8-cluster, {node_name}"

def k8_get_node_hostname(node_info, address_type = "Hostname"):
    assert 'status' in node_info, f"k8 node missing status section, {node_info}"
    assert 'addresses' in node_info['status'], f"k8 node missing status.addresses, {node_info}"

    for addr in node_info['status']['addresses']:
        if addr.get("type", None) == address_type:
            return addr.get("address", None)
    assert f"Missing address-type : {address_type} in k8 node, {node_info}"

@log_arguments
def k8_cordon_node(k8_cluster, node_name : str):
    """
    API to cordon node
    """
    global Logger
    if k8_cluster.k8_kube_config:
        try:
            v1 = client.CoreV1Api()
            patch_body = {"spec": {"unschedulable": True}}
            api_response = v1.patch_node(name=node_name, body=patch_body)
            return 0, api_response
        except ApiException as e:
            Logger.error(f"Failed cordon node {node_name}: {e}")
            return -1, None
    return -1, None

@log_arguments
def k8_uncordon_node(k8_cluster, node_name):
    """
    API to uncodon node
    """
    global Logger
    if k8_cluster.k8_kube_config:
        try:
            v1 = client.CoreV1Api()
            patch_body = {"spec": {"unschedulable": False}}
            api_response = v1.patch_node(name=node_name, body=patch_body)
            return 0, api_response
        except ApiException as e:
            Logger.error(f"Failed cordon node {node_name}: {e}")
            return -1, None
    return -1, None

@log_arguments
def k8_delete_cluster_role(k8_cluster, cluster_role_name):
    """
    API to delete cluster-role

    Example: kubectl delete clusterrole metrics
    """
    if k8_cluster.k8_kube_config:
        rbac_api = client.RbacAuthorizationV1Api()
        try:
            api_response = rbac_api.delete_cluster_role(cluster_role_name)
        except ApiException as e:
            Logger.debug(f"Failed to delete cluster-role {cluster_role_name}, error {e}")
            return -1, "", str(e)
        return 0, "", ""
    else:
        cmd = ["kubectl", "delete", "clusterrole", cluster_role_name]
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_get_node_labels(k8_cluster, node_name):
    global Logger
    v1 = client.CoreV1Api()
    try:
        node = v1.read_node(name=node_name)
        return node.metadata.labels
    except ApiException as e:
        Logger.error(f"Error getting labels for node '{node_name}': {e}")
        return -1, "", str(e)

@log_arguments
def k8_label_node(node_name, labels_dict=None, overwrite=True):
    """Applies labels to a node."""
    global Logger
    v1 = client.CoreV1Api()
    POLL_INTERVAL_SECONDS = 5
    if labels_dict is None:
        labels_dict = {}
    body = {
        "metadata": {
            "labels": labels_dict
        }
    }
    try:
        v1.patch_node(name=node_name, body=body)
        Logger.info(f"Labels applied to node '{node_name}': {labels_dict}")
        time.sleep(POLL_INTERVAL_SECONDS) # Give system time to update
        return True
    except ApiException as e:
        Logger.erro(f"Error labeling node '{node_name}': {e}")
        return False

@log_arguments
def k8_get_events(k8_cluster, namespace : str, pod_name=None):
    """
    API to

    Example: kubectl get events --namespace kube-amd-gpu
    """
    global Logger
    global LogPrettyPrinter
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        field_selector = None
        if pod_name:
            field_selector = f"involvedObject.kind=Pod,involvedObject.name={pod_name}"
        try:
            events = api.list_namespaced_event(namespace=namespace, field_selector=field_selector)
        except ApiException as e:
            Logger.error(f"Failed to get events from {namespace}, field_selector={field_selector}, error : {e}")
            return -1, "", str(e)
        return 0, events, ""
    else:
        cmd = f"kubectl events --namespace {namespace} --output json"
        if pod_name:
            cmd = cmd + f" --for pod/{pod_name}"
        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(cmd)
        assert ret_code == 0, f"Failed to get proper response with {cmd}, output : {resp_stdout}\ngot error : {resp_stderr}"
        try:
            events = json.loads(resp_stdout)
            return events
        except json.JSONDecodeError:
            Logger.error(f"Invalid JSON string:\n{resp_stdout}")
            assert True, f"got error {resp_stderr}"

@log_arguments
def k8_get_pod_name(k8_cluster, pod_str : str, namespace : str, node_name : str = None):
    ret_code, pods = k8_get_pods(k8_cluster, namespace, node_name = node_name)
    assert ret_code == 0, f"Failed to get pod names in namespace {namespace}"
    for pod in pods:
        if pod.get('metadata') != None and pod_str in pod.get('metadata').get('name'):
            return pod['metadata']['name']

@log_arguments
def k8_get_container_logs(k8_cluster, pod_str, namespace, container):
    global Logger
    pod_name = k8_get_pod_name(k8_cluster, pod_str, namespace)
    api = client.CoreV1Api()
    logs = ""

    try:
        logs = api.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container
        )
    except client.ApiException as e:
        Logger.error(f"Error getting container logs: {e}")
    return logs

@log_arguments
def k8_get_pod_logs(k8_cluster, pod_str : str, namespace : str, since="180s", container = None):
    if container != None:
        logs = k8_get_container_logs(k8_cluster, pod_str, namespace, container)
        return 0, logs, ""

    pod_name = k8_get_pod_name(k8_cluster, pod_str, namespace)
    if k8_cluster.k8_kube_config: 
        api = client.CoreV1Api()
        try:
            logs = api.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                since_seconds=int(since[:-1]),
                _return_http_data_only=True
            )
            return 0, logs, ""
        except client.ApiException as e:
            Logger.error(f"Error getting container logs: {e}")
            return 0, "", str(e)
    else:
        cmd = ["kubectl", "logs", pod_name, "--namespace", namespace, f"--since={since}"]
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_get_test_runner_worker_logs(k8_cluster):
    cmd = ["ls", "-lart", "/var/log/amd-test-runner"]

    worker_logs_dict = dict()
    for wn in k8_cluster.worker_nodes:
        ret_code, resp_stdout, resp_stderr = wn.run_command(" ".join(cmd), timeout = 60)
        worker_logs_dict[wn.hostname] = resp_stdout
    return worker_logs_dict

@log_arguments
def k8_taint_node(k8_cluster : common.k8_cluster, node_name : str, taint_add=True):
    """
    API to taint node

    Example: kubectl taint nodes node_name gpu=unhealthy:NoSchedule
    """
    global Logger
    taint_key = "amd-dcm"
    taint_value = "up"
    taint_effect = "NoExecute"

    if k8_cluster.k8_kube_config:
        v1 = client.CoreV1Api()
        node = v1.read_node(name=node_name)
        new_taint = client.V1Taint(key=taint_key, value=taint_value, effect=f"{taint_effect}")

        node.spec.taints = []
        if taint_add:
            node.spec.taints = [new_taint]

        # Update the node object with the modified taints
        try:
            v1.patch_node(name=node_name, body=node)
            Logger.info(f"Node '{node_name}' successfully tainted with {taint_key}={taint_value}:{taint_effect}, taint={taint_add}")
        except client.ApiException as e:
            Logger.error(f"Error tainting node: {e}")

    else:
        cmd = ["kubectl", "taint", "nodes", node_name, f"{taint_key}={taint_value}:{taint_effect}{taint_add}"]
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_untaint_node(k8_cluster : common.k8_cluster, node_name : str):
    """
    API to untaint node

    Example: kubectl untaint nodes node_name gpu=unhealthy:NoSchedule
    """
    global Logger
    k8_taint_node(k8_cluster, node_name, False)


@log_arguments
def k8_metrics_error(k8_cluster, counts, error_list, namespace : str):
    """
    API to artificially set health threshold
    kubectl exec -n kube-amd-gpu metrics-exporter -c metrics-exporter-container -- sh -c 'cat > /tmp/ecc.json <<EOF
    {
        "ID": "0",
        "Fields": [
            "GPU_ECC_UNCORRECT_SEM",
            "GPU_ECC_UNCORRECT_FUSE"
        ],
        "Counts" : [
            1, 2
        ]
    }
    EOF'
    """
    if k8_cluster.k8_kube_config: 
        pod_name = k8_get_pod_name(k8_cluster, "metrics-exporter", namespace)
        api = client.CoreV1Api()
        ecc = {
            "ID": "0",
            "Fields": error_list,
            "Counts": counts,
        }
        ecc_json = json.dumps(ecc)
        cmds = ["metricsclient",
                "rm -f /tmp/ecc.json",
                f"echo '{ecc_json}' > /tmp/ecc.json",
                "cat /tmp/ecc.json",
                "metricsclient -ecc-file-path /tmp/ecc.json"]
        try:
            for cmd in cmds:
                resp = stream.stream(
                    api.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=namespace,
                    container="metrics-exporter-container",
                    command=["sh", "-c", cmd],
                    stdin=False,
                    stdout=True,
                    stderr=True,
                    tty=False
                )
                Logger.info(f"executed on metrics-exporter:\n{cmd}\n\n")
                Logger.info(f"response from metrics-exporter:\n{resp}")
        except ApiException as e:
            assert True, f"Failed with str(e) while trying to exec {cmd} on {pod_name}"
    else:
        pod_name = k8_get_pod_name(k8_cluster, "metrics-exporter", namespace)
        exec_cmd = ["kubectl", "exec", "-n", namespace, pod_name, "-c", "metrics-exporter-container", "--", "sh", "-c"]
        exec_cmd = " ".join(exec_cmd)

        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join([exec_cmd, "metricsclient"]))
        errors = ",\n\t\t".join(error_list)
    
        cmd = [" ".join([exec_cmd, "'cat", ">", "/tmp/ecc.json", "<<EOF"]),
              '{',
              '\t"ID": "0",',
              '\t"Fields": [',
              f'\t\t{errors}',
              '\t],',
              '\t"Counts" : [',
              f'\t\t{", ".join([str(x) for x in counts])}',
              '\t]',
              '}',
              "EOF'"]
        cmd = "\n".join(cmd)
        Logger.info(f"executing the command=======\n{cmd}\n")
        ret_code, resp_stdout, resp_stderr= k8_cluster.k8_master.run_command(cmd)
        assert ret_code == 0, f"sent \n{cmd}\n and got output {resp_stdout} with error {resp_stderr}"
        cmd = [exec_cmd, '"metricsclient', '-ecc-file-path', '/tmp/ecc.json"']
        status = k8_cluster.k8_master.run_command(" ".join(cmd))
        Logger.info(f"Status of: {cmd}\nmetricsclient: {status}")

@log_arguments
def k8_get_node_health(k8_cluster, node_name : str, namespace : str):
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        node: client.V1Node = api.read_node(name=node_name)
        if node.metadata and node.metadata.annotations:
            gpu_state_annotation_key = "metricsexporter.amd.com/gpu.0.state" # Correct annotation key
            if gpu_state_annotation_key in node.metadata.annotations:
                state = node.metadata.annotations[gpu_state_annotation_key]
                Logger.info(f"Found GPU state for node '{node_name}': {state}")
                return state
            else:
                return "unhealthy"
                # You might want to inspect node.status.conditions here too for 'Unhealthy'
                # or related conditions that kubectl describe shows.
        else:
            return "unhealthy"

        if node.status and node.status.conditions:
            Logger.debug("Node conditions:")
            for condition in node.status.conditions:
                # Node condition types typically include "Ready", "MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"
                Logger.debug(f"  Type: {condition.type}, Status: {condition.status}, Reason: {condition.reason}, Message: {condition.message}")
                if condition.type == "Ready" and condition.status == "False":
                    Logger.debug(f"Node '{node_name}' is not Ready. Reason: {condition.reason}, Message: {condition.message}")

        return None
    else:
        cmd = ["kubectl", "describe", "node", node_name, "|", "grep", "unhealthy"]
        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join(cmd))
        state = resp_stdout.split('=')[-1].strip()
        assert "metricsexporter.amd.com.gpu.0.state=" in resp_stdout, f"expected response with GPU state, instead got {ret_code, resp_stdout, resp_stderr}"
        return state

@log_arguments
def k8_delete_cluster_role_binding(k8_cluster, cluster_role_name):
    """
    API to delete cluster-role

    Example: kubectl delete clusterrole metrics
    """
    if k8_cluster.k8_kube_config:
        rbac_api = client.RbacAuthorizationV1Api()
        try:
            api_response = rbac_api.delete_cluster_role_binding(cluster_role_name)
        except ApiException as e:
            Logger.debug(f"Failed to delete cluster-role-binding {cluster_role_name}, error {e}")
            return -1, "", str(e)
        return 0, "", ""
    else:
        cmd = ["kubectl", "delete", "clusterrolebinding", cluster_role_name]
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_create_service_account(k8_cluster : common.k8_cluster, sa_name : str, namespace : str) -> None:
    """
    API to create service-account

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    sa_name : name of service-account
    namespace : namespace to create SA
    """
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()

        sa = client.V1ServiceAccount(
                metadata = client.V1ObjectMeta(name = sa_name)
             )
        try:
            api_response = api.create_namespaced_service_account(namespace = namespace, body = sa)
        except ApiException as ae:
            return -1, "", str(ae)
        return 0, "", ""
    else: 
        sa_file = os.path.join("logs", f"{sa_name}.yaml")
        spec_util.generate_service_account_yaml(sa_file, namespace, sa_name)

        cmd = ["kubectl", "apply", "-f"]
        if k8_cluster.k8_master.is_local():
            cmd.append(f"{sa_file}")
        else:
            k8_cluster.k8_master.run_command(f"mkdir -p workspace")
            remote_file = os.path.join("workspace", os.path.basename(sa_file))
            k8_cluster.k8_master.put(sa_file, remote_file)
            cmd.append(remote_file)
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_delete_service_account(k8_cluster : common.k8_cluster, sa_name : str, namespace : str) -> (int, str, str):
    """
    API to delete service-account

    Example: kubectl delete serviceaccount exporter-client
    """
    if k8_cluster.k8_kube_config:
        api = client.CoreV1Api()
        try:
            api_response = api.delete_namespaced_service_account(sa_name, namespace)
        except ApiException as e:
            Logger.debug(f"Failed to delete service-account {sa_name} error : {e}")
            return -1, "", str(e)
        return 0, "", ""
    else:
        cmd = ["kubectl", "delete", "serviceaccount", sa_name, "--namespace", namespace]
        return k8_cluster.k8_master.run_command(" ".join(cmd))

@log_arguments
def k8_create_token(k8_cluster : common.k8_cluster, namespace : str, sa_name : str, duration : str) -> (int, str, str):
    """
    API to create token

    Example
    kubectl create token --namespace metrics-reader exporter-client --duration 1h
    """
    if k8_cluster.k8_kube_config:
        duration_in_seconds = 0
        if not duration[-1].isdigit():
            if duration[-1].lower() == 's':
                duration_in_seconds = int(duration[:-1])
            elif duration[-1].lower() == 'm':
                duration_in_seconds = int(duration[:-1]) * 60
            elif duration[-1].lower() == 'h':
                duration_in_seconds = int(duration[:-1]) * 60 * 60
            elif duration[-1].lower() == 'd':
                duration_in_seconds = int(duration[:-1]) * 60 * 60 * 24
        token_request = client.AuthenticationV1TokenRequest(
                spec=client.V1TokenRequestSpec(audiences = ['https://kubernetes.default.svc',
                                                            'https://kubernetes.default.svc.cluster.local'],
                                               expiration_seconds = duration_in_seconds))
        api = client.CoreV1Api()
        try:
            api_response = api.create_namespaced_service_account_token(name = sa_name, 
                                                                       namespace = namespace,
                                                                       body = token_request)
            Logger.debug(f"Created token: {api_response}")
            return api_response.status.token
        except ApiException as e:
            Logger.error(f"Failed to create token for sa-account : {sa_name}, error: {e}")
        return None
    else:
        cmd = ["kubectl", "create", "token", "--namespace", namespace, sa_name, "--duration", duration, "--output", "json"]
        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join(cmd))
        assert ret_code == 0, f"Failed to create token for service-account : {sa_name}, error : {resp_stderr}"
        k8_token_info = json.loads(resp_stdout)
        token_value = k8_token_info['status']['token']
        return token_value

@log_arguments
def k8_create_secret(k8_cluster : common.k8_cluster, secret_name : str,
                     secret_type : str, **kwargs) -> (int, str, str):
    """
    API to create a secret in kubernetes cluster
    """
    global Logger
    namespace = kwargs.get('namespace', 'default')
    server = kwargs.get('server', "https://index.docker.io/v1/")
    if k8_cluster.k8_kube_config:
        v1 = client.CoreV1Api()

        if secret_type == "docker-registry":
            # Prepare the Docker config JSON structure
            username = kwargs.get('username')
            password = kwargs.get('password')
            docker_config = {
                "auths": {
                    server: {
                        "username": username,
                        "password": password,
                        "email": "",
                        "auth": base64.b64encode(f"{username}:{password}".encode()).decode()
                    }
                }
            }

            docker_config_json = json.dumps(docker_config).encode()

            # Kubernetes expects this data base64 encoded in a secret under the key ".dockerconfigjson"
            secret_data = {
                ".dockerconfigjson": base64.b64encode(docker_config_json).decode()
            }

            secret = client.V1Secret(
                metadata=client.V1ObjectMeta(name=secret_name),
                data=secret_data,
                type="kubernetes.io/dockerconfigjson"
            )
        elif secret_type == "generic":
            data = {}
            for key, value in kwargs:
                if key == 'namespace':
                    continue
                data[key] = value
            secret = client.V1Secret(
                    metadata=client.V1ObjectMeta(name=secret_name),
                    string_data=data,
                    type="Opaque")
        errmsg = ""
        retval = 0
        try:
            v1.create_namespaced_secret(namespace=namespace, body=secret)
        except ApiException as e:
            retval = 1
            if e.status == 409:
                errmsg = f"Secret '{secret_name}' already exists in namespace '{namespace}'."
            else:
                errmsg = f"Exception when creating secret: {e}"
        return retval, "", errmsg
    else:
        create_cmd = ["kubectl", "create", "secret"]
        create_cmd.extend(["-n", namespace])
        if secret_type == "docker-registry":
            username = kwargs.get('username')
            password = kwargs.get('password')
            create_cmd.extend(["docker-registry", secret_name])
            create_cmd.extend([f"--docker-username={username}", f"--docker-password={password}"])
        elif secret_type == "generic":
            create_cmd.extend(["generic", secret_name])
            for key, value in kwargs:
                if key == 'namespace':
                    continue
                create_cmd.extend([f"--from-literal={key}={value}"])
        else:
            return 1, "", f"Unknown secret type {secret_type} - Abort"

        # Create
        ret_code, ret_stdout, ret_stderr = k8_cluster.k8_master.run_command(" ".join(create_cmd))
        return ret_code, ret_stdout, ret_stderr

@log_arguments
def k8_delete_secret(k8_cluster : common.k8_cluster, secret_name : str, secret_type : str, namespace : str = "default") -> (int, str, str):
    """
    API to delete a secret in kubernetes cluster
    """
    global Logger
    if k8_cluster.k8_kube_config:
        v1 = client.CoreV1Api()
        errmsg = ""
        retval = 0
        try:
            api_response = v1.delete_namespaced_secret(name = secret_name, 
                                                       namespace = namespace,
                                                       body=client.V1DeleteOptions())
        except ApiException as e:
            if e.status != 404:
                retval = 1
                errmsg = f"Exception when deleting secret {secret_name}, err: {e}"
        return retval, "", errmsg
    else:
        delete_cmd = ["kubectl", "delete", "secret"]
        delete_cmd.extend(["-n", namespace])
        delete_cmd.append(secret_name)

        # Delete first
        ret_code, ret_stdout, ret_stderr = k8_cluster.k8_master.run_command(" ".join(delete_cmd))
        if ret_code != 0:
            Logger.error(f"secret delete failed, code: {ret_code}, stdout: {ret_stdout}, stderr: {ret_stderr}")
        return ret_code, ret_stdout, ret_stderr

@log_arguments
def crictl_cleanup_images(k8_cluster):
    """
    API to prune images on all nodes
    Cmd: crictl rmi --prune
    """
    cmd = ["sudo", "crictl", "rmi", "--prune"]
    ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join(cmd))
    assert ret_code == 0, f"Failed prune images from master node, error: {resp_stderr}"
    for wn in k8_cluster.worker_nodes:
        ret_code, resp_stdout, resp_stderr = wn.run_command(" ".join(cmd), timeout = 60)
        assert ret_code == 0, f"Failed prune images from worker node {wn.ip_address}, error: {resp_stderr}"
    return

@log_arguments
def k8_get_deviceconfigs_info(k8_cluster : common.k8_cluster, namespace : str, deviceconfig_name : str = None) -> Dict:
    """
    API to get deviceconfig information

    Parameters:

    k8_cluster : instance of lib.common.k8_cluster
    namespace : name-space
    deviceconfig_name : name of the deviceconfigs

    Returns:
    map of deviceconfig-name => deviceconfig-info
        {
            "apiVersion": "amd.com/v1alpha1",
            "kind": "DeviceConfig",
            "metadata": {
                "annotations": {
                    "kubectl.kubernetes.io/last-applied-configuration": "{\"apiVersion\":\"amd.com/v1alpha1\",\"kind\":\"DeviceConfig\",\"metadata\":{\"annotations\":{},\"name\":\"gpu-operator\",\"namespace\":\"kube-amd-gpu\"},\"spec\":{\"devicePlugin\":{\"enableNodeLabeller\":true},\"driver\":{\"blacklist\":true,\"enable\":true,\"image\":\"docker.io/yan1996/ubuntu\",\"imageRegistrySecret\":{\"name\":\"driver-image-auth\"},\"version\":\"6.3\"},\"metricsExporter\":{\"config\":{\"name\":\"metric-configmap\"},\"enable\":true,\"nodePort\":32500,\"port\":5000,\"rbacConfig\":{\"disableHttps\":true,\"enable\":false},\"serviceType\":\"NodePort\"},\"selector\":{\"feature.node.kubernetes.io/amd-vgpu\":\"true\"},\"testRunner\":{\"config\":{\"name\":\"test-runner-config\"},\"enable\":true,\"logsLocation\":{\"hostPath\":\"/var/log/amd-test-runner\",\"mountPath\":\"/var/log/amd-test-runner\"}}}}\n"
                },
                "creationTimestamp": "2025-03-06T22:08:29Z",
                "finalizers": [
                    "amd.node.kubernetes.io/deviceconfig-finalizer"
                ],
                "generation": 14,
                "name": "gpu-operator",
                "namespace": "kube-amd-gpu",
                "resourceVersion": "8251885",
                "uid": "5edf3e5e-f268-4431-81e2-7c8ae2aa40ac"
            },
            "spec": {
                "devicePlugin": {
                    "enableNodeLabeller": true
                },
                "driver": {
                    "blacklist": true,
                    "enable": true,
                    "image": "docker.io/yan1996/ubuntu",
                    "imageRegistrySecret": {
                        "name": "driver-image-auth"
                    },
                    "version": "6.3"
                },
                "metricsExporter": {
                    "config": {
                        "name": "metric-configmap"
                    },
                    "enable": true,
                    "nodePort": 32500,
                    "port": 5000,
                    "rbacConfig": {
                        "disableHttps": true,
                        "enable": false
                    },
                    "serviceType": "NodePort"
                },
                "selector": {
                    "feature.node.kubernetes.io/amd-vgpu": "true"
                },
                "testRunner": {
                    "config": {
                        "name": "test-runner-config"
                    },
                    "enable": true,
                    "logsLocation": {
                        "hostPath": "/var/log/amd-test-runner",
                        "mountPath": "/var/log/amd-test-runner"
                    }
                }
            },
            "status": {
                "conditions": [
                    {
                        "lastTransitionTime": "2025-03-06T22:08:36Z",
                        "message": "",
                        "reason": "OperatorReady",
                        "status": "True",
                        "type": "Ready"
                    }
                ],
                "devicePlugin": {
                    "availableNumber": 1,
                    "desiredNumber": 1,
                    "nodesMatchingSelectorNumber": 1
                },
                "driver": {
                    "availableNumber": 1,
                    "desiredNumber": 1,
                    "nodesMatchingSelectorNumber": 1
                },
                "metricsExporter": {
                    "availableNumber": 1,
                    "desiredNumber": 1,
                    "nodesMatchingSelectorNumber": 1
                },
                "nodeModuleStatus": {
                    "aks-gpupool-12247365-vmss000004": {
                        "containerImage": "docker.io/yan1996/ubuntu:ubuntu-22.04-5.15.0-1079-azure-6.2.4",
                        "kernelVersion": "5.15.0-1079-azure",
                        "lastTransitionTime": "2025-03-19 17:00:16 +0000 UTC"
                    }
                },
                "observedGeneration": 14
            }
        }
    """

    global Logger
    global LogPrettyPrinter
    ret_values = {}
    if k8_cluster.k8_kube_config:
        api = client.CustomObjectsApi()
        try:
            k8_deviceconfig_info = api.list_custom_object_for_all_namespaces(version = "v1alpha1", group = "amd.com", resource_plural = "deviceconfigs")
        except ApiException as e:
            Logger.debug(f"Failed to list deviceconfigs for namespace {namespace}, error: {e}")
            return ret_values

        Logger.debug(f"Status of DeviceConfig CR\n{LogPrettyPrinter.pformat(k8_deviceconfig_info)}")
        for item in k8_deviceconfig_info.get('items', []):
            ret_values[item.get('metadata').get('name')] = item
    else:
        cmd = ["kubectl", "get", "deviceconfigs"]
        if deviceconfig_name:
            cmd.append(deviceconfig_name)
        if namespace:
            cmd.extend(["--namespace", namespace])
        else:
            cmd.extend([" -A"])
        cmd.append("-o json")

        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join(cmd))
        if ret_code != 0:
            Logger.error(f"Failed to list deviceconfigs for namespace {namespace} error : {ret_code}, {resp_stdout}, {resp_stderr}")
            return ret_values

        k8_deviceconfig_info = json.loads(resp_stdout)
        if deviceconfig_name:
            ret_values[k8_deviceconfig_info.get('metadata').get('name')] = k8_deviceconfig_info
        else:
            for item in k8_deviceconfig_info['items']:
                ret_values[item.get('metadata').get('name')] = item
    return ret_values

@log_arguments
def k8_lookup_crd(k8_cluster : common.k8_cluster, crd_name : str) -> Dict:
    """
    API to retrieve DeviceConfig CRD information post gpu-operator installation

    Parameters:
    k8_cluster : instance of lib.common.k8_cluster
    crd_name : The name of crd to lookup/filter

    Returns:
    Dict: dict of CRD information or None on error
    """

    global Logger
    global LogPrettyPrinter
    
    if k8_cluster.k8_kube_config:
        api = client.ApiextensionsV1Api()

        try:
            crd_list = api.list_custom_resource_definition().to_dict()
        except ApiException as e:
            Logger.error(f"Error retrieving CRDs from cluster, error: {e}")
            return None
    else:
        #  kubectl get crd deviceconfigs.amd.com -n kube-amd-gpu  -o json
        cmd = ["kubectl", "get" "crd"]
        cmd.append("-o json")

        ret_code, resp_stdout, resp_stderr = k8_cluster.k8_master.run_command(" ".join(cmd))
        if ret_code != 0:
            Logger.error(f"Failed to list CRDs error : {ret_code}, {resp_stdout}, {resp_stderr}")
            return None
        crd_list = json.loads(resp_stdout)

    for crd in crd_list.get('items', None):
        if crd['metadata']['name'] == crd_name:
            return crd
    Logger.debug(f"CRDs from the cluster\n{LogPrettyPrinter.pformat(crd_list)}")
    return None

@log_arguments
def k8_run_curl_cmd(k8_cluster : common.k8_cluster, args : List, retry = 10) -> (int, int, str):
    """
    API to run a curl command in the kubernetes cluster to collect information
    """

    global Logger
    global LogPrettyPrinter
    if k8_cluster.k8_kube_config:
        pod_name = f"curl-cmd-pod-{common.generate_8byte_sha('gpu-operator/metrics-exporter')}"
        namespace = "default"

        curl_pod_manifest = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(name=pod_name),
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    client.V1Container(
                        name="curl-container",
                        image=f"{k8_cluster.k8_registry}/curlimages/curl",
                        command=["curl"],
                        args=args
                    )
                ]
            )
        )

        v1 = client.CoreV1Api()
        for _ in range(retry):
            try:
                v1.create_namespaced_pod(body=curl_pod_manifest, namespace=namespace)
                Logger.debug(f"Pod : {pod_name} created. Waiting for completion...")

                cmd_complete = False
                pod_status = v1.read_namespaced_pod_status(name=pod_name, namespace=namespace)
                for _ in range(20):
                    Logger.debug(f"Pod : {pod_name} current status : {pod_status.status.phase}")
                    if pod_status.status.phase in ["Succeeded", "Failed"]:
                        cmd_complete = True
                        break
                    time.sleep(10)
                    pod_status = v1.read_namespaced_pod_status(name=pod_name, namespace=namespace)

                exit_code = -1
                if pod_status.status.container_statuses:
                    for container_status in pod_status.status.container_statuses:
                        if container_status.name == "curl-container" and container_status.state.terminated:
                            exit_code = container_status.state.terminated.exit_code
                            break
                else:
                    Logger.debug("No container statuses found in the pod_status.")

                if pod_status.status.phase in ["Succeeded", "Failed"]:
                    # Retrieve logs from the completed Pod
                    pod_logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace)
                    Logger.debug(f"Response of curl-command {args}\n{LogPrettyPrinter.pformat(pod_logs)}")
                    return exit_code, pod_logs, ""
                else:
                    Logger.warn(f"Unexpected curl-command POD Status\n{LogPrettyPrinter.pformat(pod_status)}")
            except ApiException as e:
                Logger.error(f"Failed to create pod: {pod_name}, error: {e}")
            finally:
                # Clean up: Delete the Pod
                try:
                    v1.delete_namespaced_pod(name=pod_name, namespace=namespace, body=client.V1DeleteOptions())
                except ApiException as e:
                    Logger.error(f"Failed to delete pod: {pod_name}, error: {e}")
            time.sleep(20)
    return -1, "", ""

@log_arguments
def run_command_on_node(k8_cluster : common.k8_cluster, node_name : str, cmd : List, skip_chroot : bool = False, retry : int = 10, timeout_seconds = 300):
    """
    Runs a command on a specific Kubernetes worker node using an ephemeral debug pod.

    Args:
        k8_cluster (common.k8_cluster): k8_cluster object.
        node_name (str): The name of the worker node.
        cmd (list): The shell command to execute on the node.
        skip_chroot : Flag to skip/include chrooot /host
        retry : Number of retries, default 10

    Returns:
        tuple: A tuple containing (exit_code, logs)
    """
    global Logger
    global LogPrettyPrinter
    if k8_cluster.k8_kube_config:
        v1 = client.CoreV1Api()
        pod_name = f"node-debug-{node_name}-{common.generate_8byte_sha('gpu-operator/metrics-exporter')}"
        namespace = "default"

        full_cmd = []
        if not skip_chroot:
            chroot_cmd = ["chroot", "/host"]
            full_cmd.extend(chroot_cmd)
        full_cmd.extend(cmd)

        # Define the debug pod
        debug_pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": namespace,
                "labels": {
                    "app": "node-debugger",
                    "node": node_name
                }
            },
            "spec": {
                "nodeName": node_name,  # Target the specific node
                "restartPolicy": "Never", # Ensure it doesn't restart after command completes
                "hostPID": True,         # Allows access to host process IDs
                "hostNetwork": True,     # Allows access to host network namespace
                "hostIPC": True,         # Allows access to host IPC namespace
                "containers": [
                    {
                        "name": "debugger",
                        "image": f"{k8_cluster.k8_registry}/ubuntu",
                        "command": full_cmd,
                        "securityContext": {
                            "privileged": True # Essential for full host access
                        },
                        "volumeMounts": [
                            {
                                "name": "host-root",
                                "mountPath": "/host",
                                "mountPropagation": "Bidirectional"
                            }
                        ]
                    }
                ],
                "volumes": [
                    {
                        "name": "host-root",
                        "hostPath": {
                            "path": "/",
                            "type": "Directory"
                        }
                    }
                ]
            }
        }

        for _ in range(retry):
            try:
                v1.create_namespaced_pod(body=debug_pod_manifest, namespace=namespace)
                Logger.debug(f"Creating debug pod {pod_name} on node '{node_name}'...")

                # Wait for the pod to complete
                start_time = time.time()
                while True:
                    pod_status = v1.read_namespaced_pod_status(name=pod_name, namespace=namespace)
                    if pod_status.status.phase in ["Succeeded", "Failed"]:
                        Logger.info(f"Pod {pod_name} finished with status: {pod_status.status.phase}")
                        break
                    if time.time() - start_time > timeout_seconds:
                        Logger.error(f"Pod {pod_name} timed out after {timeout_seconds} seconds.")
                        return -1, f"Pod {pod_name} timed out after {timeout_seconds} seconds."
                    time.sleep(5)

                # Get container status to check exit code
                exit_code = -1
                if pod_status.status.container_statuses:
                    for container_status in pod_status.status.container_statuses:
                        if container_status.name == "debugger" and container_status.state.terminated:
                            exit_code = container_status.state.terminated.exit_code
                            break
                else:
                    Logger.debug("No container statuses found in the pod.")

                # Get logs
                logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace)
                Logger.debug(f"Logs from {pod_name}:\n{LogPrettyPrinter.pformat(logs)}")
                return exit_code, logs
            except client.ApiException as e:
                Logger.error(f"Kubernetes API Error: {e}")
                # Attempt to get logs if pod was created but failed
                try:
                    logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace)
                    Logger.info(f"Logs (before error): {logs}")
                except Exception as log_e:
                    Logger.error(f"Could not retrieve logs after API error: {log_e}")
                return -1, f"Kubernetes API Error: {e}"
            except Exception as e:
                Logger.error(f"An unexpected error occurred: {e}")
                return -1, f"An unexpected error occurred: {e}"
            finally:
                # Delete the pod
                Logger.debug(f"Deleting pod {pod_name}...")
                v1.delete_namespaced_pod(name=pod_name, namespace=namespace,
                                         body=client.V1DeleteOptions(propagation_policy='Foreground',
                                                                     grace_period_seconds=0))
    return

@log_arguments
def exec_command_in_pod(k8_cluster : common.k8_cluster, namespace : str, cmds : List, pod_name : str, container_name : str = None):
    """
    Exec a command inside a specific container within a Kubernetes pod.

    Args:
        k8_cluster (common.k8_cluster): k8 Cluster
        namespace (str): The namespace of the pod.
        cmds (list): A list of strings representing the command and its arguments.
                        For example: ["ls", "-l", "/tmp"]
        pod_name (str): The name of the pod.
        container_name (str, optional): The name of the container within the pod
                                        to execute the command in. If None, it
                                        defaults to the first container if only one
                                        exists.
    Returns:
        tuple: A tuple containing (stdout, stderr) of the executed command.
    """
    try:
        # Create a CoreV1Api client
        v1 = client.CoreV1Api()

        # Execute the command
        # _preload_content=False is crucial for interactive sessions or streaming output
        # For simple command execution, you might set it to True to get all output at once.
        resp = stream.stream(
                v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=cmds,
                container=container_name,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=True)  # Set to True to get all content at once

        # The 'resp' object contains the combined stdout and stderr if _preload_content is True
        # Otherwise, you would read from the stream interactively.
        return 0, resp, None
    except client.ApiException as e:
        print(f"Error executing command: {e}")
        return -1, None, f"Error: {e}"
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return -1, None, f"Unexpected error: {e}"


@log_arguments
def reboot_node(k8_cluster : common.k8_cluster, node_name : str):
    """
    Reboot node using run_command_on_node API and check for node status.conditions to declare as ready
    Args:
        k8_cluster (common.k8_cluster): k8 Cluster
        node_name (str): name of the node.
    """
    ret_code, _ = k8_cordon_node(k8_cluster, node_name)
    if ret_code != 0:
        return ret_code
    ret_code, _ = run_command_on_node(k8_cluster, node_name, ["systemctl", "reboot"], timeout_seconds = 30)
    # For now ignore ret_code
    # Check for status to be declared as NotReady
    for _ in range(10):
        ret_code, k8_nodes = k8_get_nodes(k8_cluster)
        if ret_code != 0:
            return ret_code

        reboot_success = False
        for node in k8_nodes:
            if node['metadata']['labels'].get('feature.node.kubernetes.io/amd-gpu', 'false') != 'true':
                continue

            if node['metadata']['name'] != node_name:
                continue

            for entry in node['status']['conditions']:
                if entry.get('type', 'NotReady') == 'Ready':
                    if entry['status'] != 'True':
                        reboot_success = True
                    break
            break
        if reboot_success:
            break
        time.sleep(20)

    if not reboot_success:
        Logger.error(f"Failed to reboot node {node_name}")
        return -1
    Logger.info(f"Node {node_name} successfully rebooted, sleep for 240s")
    time.sleep(240)

    # Check for status to be declared as Ready
    for _ in range(10):
        ret_code, k8_nodes = k8_get_nodes(k8_cluster)
        if ret_code != 0:
            return ret_code

        node_online = False
        for node in k8_nodes:
            if node['metadata']['labels'].get('feature.node.kubernetes.io/amd-gpu', 'false') != 'true':
                continue

            if node['metadata']['name'] != node_name:
                continue

            for entry in node['status']['conditions']:
                if entry.get('type', 'NotReady') == 'Ready':
                    if entry['status'] == 'True':
                        node_online = True
                    break
            break

        if node_online:
            break
        time.sleep(20)
    if not node_online:
        Logger.error(f"Node {node_name} failed to come online - fatal error")
        return -1
    Logger.info(f"Node {node_name} is up")
    ret_code, _ = k8_uncordon_node(k8_cluster, node_name)
    if ret_code != 0:
        Logger.error(f"Failed to uncordon node - {node_name}")
        return ret_code
    return 0

