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
import re
import pprint
from enum import Enum
from datetime import datetime

import lib.common as common
import lib.k8_util as k8_util
import lib.spec_util as spec_util

Logger = logging.getLogger("k8.helper")
LogPrettyPrinter = pprint.PrettyPrinter(indent = 2)

class K8Helper:

    class PodStatus(Enum):
        NA          = 0
        PENDING     = 1
        RUNNING     = 2
        FAILED      = 3
        SUCCEEDED   = 4
        UNKNOWN     = 5

    class WorkloadOp(Enum):
        UNKNOWN         = 0
        START_WORKLOAD  = 1
        STOP_WORKLOAD   = 2

    @staticmethod
    def wait_for_upgrade_completion(gpu_cluster, environment, devicecfg_list, gpu_nodes):
        # Check for kmm-worker-{gpu-node-name}-test-deviceconfig PODs to be started and completed
        global Logger
        if environment.amdgpu_driver_spec["driver-deployment"] == "inbox":
            Logger.info("Using inbox amdgpu driver - skip kmm verification")
            return

        time.sleep(20)
        upgrade_complete = False
        for _ in range(10):
            pending_nodes = set(map(lambda x: x['metadata']['name'], gpu_nodes))
            for devcfg in devicecfg_list:
                devcfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, devcfg)
                K8Helper.assert_or_debug(devcfg_info != None and devcfg in devcfg_info,
                                          f"Failed to collect status of deviceconfig {devcfg}", environment.pause_on_failure)

                nodeStatusMap = devcfg_info[devcfg]['status']['nodeModuleStatus']
                for node in gpu_nodes:
                    node_name = node['metadata']['name']
                    if node_name in nodeStatusMap:
                        if nodeStatusMap[node_name]['status'] == 'Upgrade-Complete':
                            if node_name in pending_nodes:
                                pending_nodes.remove(node_name)
                        else:
                            Logger.info(f"Node: {node_name} upgrade status pending : {nodeStatusMap[node_name]}")
            if len(pending_nodes) > 0:
                Logger.info(f"Waiting for {pending_nodes} to complete upgrade process")
                time.sleep(120)
            else:
                upgrade_complete = True

        if not upgrade_complete:
            Logger.error("Failed to complete upgrade-process for all nodes")
            for devcfg in devicecfg_list:
                devcfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, devcfg)
                K8Helper.assert_or_debug(devcfg_info != None and devcfg in devcfg_info,
                                          f"Failed to collect status of deviceconfig {devcfg}", environment.pause_on_failure)

                nodeStatus = devcfg_info[devcfg]['status']['nodeModuleStatus']
                Logger.debug(nodeStatus)
            K8Helper.assert_or_debug(upgrade_complete == True, "upgrade failed", environment.pause_on_failure)
            return
        Logger.info("Upgrade complete for all nodes")

    @staticmethod
    def wait_kmm_worker_completion(gpu_cluster, environment, devcfg_name):
        # Check for kmm-worker-{gpu-node-name}-test-deviceconfig PODs to be started and completed
        global Logger
        if environment.amdgpu_driver_spec["driver-deployment"] == "inbox":
            Logger.info("Using inbox amdgpu driver - skip kmm verification")
            return

        ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
        K8Helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
        K8Helper.assert_or_debug(len(gpu_nodes), "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

        # Check for build pods
        build_pods = []
        build_pods.append(common.PodInfo(f"{devcfg_name}-build", 1, 1))

        build_pod_status = set()
        time.sleep(20)
        for _ in range(5):
            build_pod_status.clear()
            status_info = k8_util.k8_check_pod_status(gpu_cluster, environment.gpu_operator_namespace, build_pods)
            Logger.debug(f"build pod status: {status_info}")

            for pod_name, status in status_info.items():
                if status == 'Running':
                    build_pod_status.add(K8Helper.PodStatus.RUNNING)
                elif status == 'Pending':
                    build_pod_status.add(K8Helper.PodStatus.PENDING)
                elif status == 'Failed':
                    build_pod_status.add(K8Helper.PodStatus.FAILED)
                else:
                    Logger.warn(f"build pod status unknown, pod-name: {pod_name}")
                    build_pod_status.add(K8Helper.PodStatus.UNKNOWN)

            if K8Helper.PodStatus.PENDING in build_pod_status or K8Helper.PodStatus.RUNNING in build_pod_status:
                Logger.debug("Wait for 120-sec as some of the build pods are in Running/Pending status")
                time.sleep(120)
            else:
                break

        K8Helper.assert_or_debug(K8Helper.PodStatus.PENDING not in build_pod_status, "build pod still pending", environment.pause_on_failure)
        K8Helper.assert_or_debug(K8Helper.PodStatus.RUNNING not in build_pod_status, "build pod still running", environment.pause_on_failure)
        K8Helper.assert_or_debug(K8Helper.PodStatus.FAILED not in build_pod_status, "build pod failed", environment.pause_on_failure)

        # Check for kmm pods
        kmm_worker_pods = []
        for node in gpu_nodes:
            node_name = node['metadata']['name']
            K8Helper.assert_or_debug(node_name != None, "Missing node-name for the gpu node in the node-info JSON", environment.pause_on_failure)
            kmm_worker_pods.append(common.PodInfo(f"kmm-worker-{node_name}-", 1, 1))

        kmm_pod_status = set()
        time.sleep(20)
        for _ in range(5):
            kmm_pod_status.clear()
            status_info = k8_util.k8_check_pod_status(gpu_cluster, environment.gpu_operator_namespace, kmm_worker_pods)
            Logger.debug(f"kmm-worker status: {status_info}")

            for pod_name, status in status_info.items():
                if status == 'Running':
                    kmm_pod_status.add(K8Helper.PodStatus.RUNNING)
                elif status == 'Pending':
                    kmm_pod_status.add(K8Helper.PodStatus.PENDING)
                elif status == 'Failed':
                    kmm_pod_status.add(K8Helper.PodStatus.FAILED)
                else:
                    Logger.warn(f"build pod status unknown, pod-name: {pod_name}")
                    kmm_pod_status.add(K8Helper.PodStatus.UNKNOWN)

            if K8Helper.PodStatus.PENDING in kmm_pod_status or K8Helper.PodStatus.RUNNING in kmm_pod_status:
                Logger.debug("Wait for 120-sec as some of the kmm-worker pods are in Running/Pending status")
                time.sleep(120)
            else:
                break

        K8Helper.assert_or_debug(K8Helper.PodStatus.PENDING not in kmm_pod_status, "kmm-worker pod still pending", environment.pause_on_failure)
        K8Helper.assert_or_debug(K8Helper.PodStatus.RUNNING not in kmm_pod_status, "kmm-worker pod still running", environment.pause_on_failure)
        K8Helper.assert_or_debug(K8Helper.PodStatus.FAILED not in kmm_pod_status, "kmm-worker pod failed", environment.pause_on_failure)

        # Finally check for labels
        label_missing = set()
        for _ in range(5):
            label_missing.clear()
            ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
            K8Helper.assert_or_debug(ret_code == 0, "Error while getting gpu-nodes from k8-cluster", environment.pause_on_failure)
            K8Helper.assert_or_debug(len(gpu_nodes), "No nodes with AMD/GPU found in the cluster", environment.pause_on_failure)

            pattern = r"kmm\.node\.kubernetes\.io/" + environment.gpu_operator_namespace + r"\.(.*?)\.ready"
            for node in gpu_nodes:
                label_found = False
                for label, _ in node['metadata']['labels'].items():
                    if re.match(pattern, label):
                        label_found = True
                        break
                if not label_found:
                    label_missing.add(node['metadata']['name'])
            if len(label_missing) > 0:
                Logger.warn(f"Missing kmm.ready label for {label_missing}")
                time.sleep(120)
        K8Helper.assert_or_debug(label_found, f"One or more nodes missing kmm.ready label : {label_missing}", environment.pause_on_failure)
        return

    # Check for corresponding deviceconfig created
    @staticmethod
    def check_deviceconfig_status(gpu_cluster, environment, devicecfg_list):
        for devcfg in devicecfg_list:
            devcfg_info = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace, devcfg)
            K8Helper.assert_or_debug(devcfg_info != None and devcfg in devcfg_info,
                                      f"Failed to collect status of deviceconfig {devcfg}", environment.pause_on_failure)
            #status_info = devcfg_info[devcfg].get('status')
            #if environment.gpu_operator_version > "v1.1.0":
            #    conditions = status_info.get('conditions', [])
            #    K8Helper.assert_or_debug(len(conditions) > 0, f"deviceconfig status.conditions is empty for {devcfg}", environment.pause_on_failure)
            #    K8Helper.assert_or_debug(conditions[0].get('status') == 'True', f"deviceconfig {devcfg} status is not True", environment.pause_on_failure)
            #    K8Helper.assert_or_debug(conditions[0].get('type') == 'Ready', f"deviceconfig {devcfg} type is not Ready", environment.pause_on_failure)
        return

    @staticmethod
    def check_node_driver_version(gpu_cluster, config_version, rocm_version, environment):
        global Logger
        global LogPrettyPrinter
        devcfg_map = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace)
        for devcfg_name, devcfg_info in devcfg_map.items():
            devcfg_driver_version = devcfg_info.get('spec').get('driver').get('version')
            Logger.info(f'Configured Version: {devcfg_driver_version}') 
            K8Helper.assert_or_debug(config_version == devcfg_driver_version,
                                     f"Expected config_version: {config_version}, device_config: {devcfg_driver_version}", environment.pause_on_failure)

        # check the worker node driver version
        ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
        for node in gpu_nodes:
            node_name = k8_util.k8_get_node_hostname(node)
            version_module_label = f"kmm.node.kubernetes.io/version-module.{environment.gpu_operator_namespace}.{devcfg_name}"
            node_driver_version = node['metadata']['labels'][version_module_label]
            K8Helper.assert_or_debug(config_version == node_driver_version,
                                      f"failed for node {node_name}: {node_driver_version}", environment.pause_on_failure)
            cmd = ["dmesg", "-T"]
            #cmd = ["sudo", "dmesg", "-T", "|", "grep", "'amdgpu version'", "|", "tail", "-1"]
            ret_code, resp_stdout = k8_util.run_command_on_node(gpu_cluster, node_name, cmd, skip_chroot = True)
            K8Helper.assert_or_debug(ret_code == 0, f"error getting dmesg from {node_name} {node_name}", environment.pause_on_failure)
            K8Helper.assert_or_debug(resp_stdout != None, f"Error: Command output is None", environment.pause_on_failure)
            Logger.debug(f"Cmd:{cmd}, Response:\n{LogPrettyPrinter.pformat(resp_stdout)}")
            amdgpu_lines = list(filter(lambda line: 'amdgpu version' in line, resp_stdout.split("\n")))
            K8Helper.assert_or_debug(len(amdgpu_lines) > 0, "No dmesg-lines with 'amdgpu version' information", environment.pause_on_failure)
            K8Helper.assert_or_debug(rocm_version in amdgpu_lines[0], f"can't find the right amdgpu version {resp_stdout}", environment.pause_on_failure)

    @staticmethod
    def assert_or_debug(condition, message, pause_on_failure = False, expected_to_fail = False):
        global Logger
        if not condition:
            if pause_on_failure:
                Logger.error(f"Pausing for failure : {message}")
                pytest.set_trace()
            if expected_to_fail:
                pytest.xfail(message)
            else:
                pytest.fail(message)

    @staticmethod
    def workload_operation(gpu_cluster, environment, op_code, **kwargs):
        global Logger
        """
        create the first workload pod requesting one gpu
        Assumption: no other workload pod with gpu has been instantiated
        """
        node_name = kwargs.get("node_name", None)
        num_gpu_reqd = kwargs.get("num_gpu_reqd", 1)
        workload_config = kwargs.get("workload_config", {})

        if node_name == None:
            # Take one node with gpu
            ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
            K8Helper.assert_or_debug(ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster", environment.pause_on_failure)
            gpu_node = gpu_nodes[0]
            node_name = k8_util.k8_get_node_hostname(gpu_node)

        # check gpu capacity
        init_cap, init_alloc = k8_util.k8_get_node_gpu_capacity(gpu_cluster, node_name)
        K8Helper.assert_or_debug(int(init_cap) != -1 or int(init_alloc) != -1,
                          f'Err getting gpu capacity and allocatable values: capacity: {init_cap} allocatable: {init_alloc}', environment.pause_on_failure)

        # check if the node has allocatable gpus; if not fail
        K8Helper.assert_or_debug(init_cap != 0 or init_alloc != 0, f'no gpu available', environment.pause_on_failure)

        # create a workload requesting one gpu
        pod_name = f"pytorch-gpu-pod-{common.generate_8byte_sha(node_name)}"

        #launch
        if op_code == K8Helper.WorkloadOp.START_WORKLOAD:
            Logger.info(f"Create the workload with gpu")
            workload_config = {
                    'pod_name' : pod_name,
                    'num_gpu' : num_gpu_reqd,
                    'nodeSelector' : node_name,
                    'podStatus' : K8Helper.PodStatus.NA,
                }
            wl_file = os.path.join(environment.sandbox_dir, f"{pod_name}.yaml")
            Logger.debug(f"New workload specification : {workload_config}")
            cr_spec = spec_util.generate_k8_workload_template(wl_file, workload_config)
            ret_code, ret_stdout, ret_stderr = k8_util.k8_apply_cr(gpu_cluster, cr_spec, wl_file)

            workload_pods = [
                common.PodInfo(pod_name, 1, 1),
            ]
            for _ in range(5):
                status_info = k8_util.k8_check_pod_status(gpu_cluster, cr_spec['metadata']['namespace'], workload_pods)
                Logger.debug(f"workload pod status: {status_info}")
                for pod_name, status in status_info.items():
                    if pod_name == workload_config['pod_name']:
                        if status == 'Running':
                            workload_config['podStatus'] = K8Helper.PodStatus.RUNNING
                            break
                        elif status == 'Pending':
                            workload_config['podStatus'] = K8Helper.PodStatus.PENDING
                        elif status == 'Failed':
                            workload_config['podStatus'] = K8Helper.PodStatus.FAILED
                            break
                        else:
                            Logger.warn(f"workload pod status unknown, pod-name: {pod_name}")
                            workload_config['podStatus'] = K8Helper.PodStatus.UNKNOWN
                    time.sleep(30) # give time for image download
            workload_config['spec'] = cr_spec
            return workload_config
        elif op_code == K8Helper.WorkloadOp.STOP_WORKLOAD:
            # delete the workload
            Logger.info(f"Delete the first workload with gpu")
            ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_cr(gpu_cluster, workload_config['spec'], None)
            if ret_code != 0:
                Logger.warn(f"Failed to delete workload : {workload_config}")
            workload_config['podStatus'] = K8Helper.PodStatus.UNKNOWN
            return workload_config
        return None

