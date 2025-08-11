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
from enum import Enum
from datetime import datetime

import lib.common as common
import lib.k8_util as k8_util

Logger = logging.getLogger("k8.helper")

class PodStatus(Enum):
    NA          = 0
    PENDING     = 1
    RUNNING     = 2
    FAILED      = 3
    SUCCEEDED   = 4
    UNKNOWN     = 5


class K8Helper:

    @staticmethod
    def wait_kmm_worker_completion(gpu_cluster, environment, devcfgs):
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
        for devcfg_name in devcfgs:
            build_pods.append(common.PodInfo(f"{devcfg_name}-build", 1, 1))

        build_pod_status = set()
        time.sleep(20)
        for _ in range(5):
            build_pod_status.clear()
            status_info = k8_util.k8_check_pod_status(gpu_cluster, environment.gpu_operator_namespace, build_pods)
            Logger.debug(f"build pod status: {status_info}")

            for pod_name, status in status_info.items():
                if status == 'Running':
                    build_pod_status.add(PodStatus.RUNNING)
                elif status == 'Pending':
                    build_pod_status.add(PodStatus.PENDING)
                elif status == 'Failed':
                    build_pod_status.add(PodStatus.FAILED)
                else:
                    Logger.warn(f"build pod status unknown, pod-name: {pod_name}")
                    build_pod_status.add(PodStatus.UNKNOWN)

            if PodStatus.PENDING in build_pod_status or PodStatus.RUNNING in build_pod_status:
                Logger.debug("Wait for 120-sec as some of the build pods are in Running/Pending status")
                time.sleep(120)
            else:
                break

        K8Helper.assert_or_debug(PodStatus.PENDING not in build_pod_status, "build pod still pending", environment.pause_on_failure)
        K8Helper.assert_or_debug(PodStatus.RUNNING not in build_pod_status, "build pod still running", environment.pause_on_failure)
        K8Helper.assert_or_debug(PodStatus.FAILED not in build_pod_status, "build pod failed", environment.pause_on_failure)

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
                    kmm_pod_status.add(PodStatus.RUNNING)
                elif status == 'Pending':
                    kmm_pod_status.add(PodStatus.PENDING)
                elif status == 'Failed':
                    kmm_pod_status.add(PodStatus.FAILED)
                else:
                    Logger.warn(f"build pod status unknown, pod-name: {pod_name}")
                    kmm_pod_status.add(PodStatus.UNKNOWN)

            if PodStatus.PENDING in kmm_pod_status or PodStatus.RUNNING in kmm_pod_status:
                Logger.debug("Wait for 120-sec as some of the kmm-worker pods are in Running/Pending status")
                time.sleep(120)
            else:
                break

        K8Helper.assert_or_debug(PodStatus.PENDING not in kmm_pod_status, "kmm-worker pod still pending", environment.pause_on_failure)
        K8Helper.assert_or_debug(PodStatus.RUNNING not in kmm_pod_status, "kmm-worker pod still running", environment.pause_on_failure)
        K8Helper.assert_or_debug(PodStatus.FAILED not in kmm_pod_status, "kmm-worker pod failed", environment.pause_on_failure)

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

@pytest.fixture(scope="session")
def k8_helper():
    return K8Helper
