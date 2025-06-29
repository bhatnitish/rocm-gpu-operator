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

import pytest
import os
import logging
import time
from datetime import datetime
from py.xml import html

import lib.common as common
import lib.k8_util as k8_util

Logger = logging.getLogger("k8.helper")

class K8Helper:

    @staticmethod
    def wait_kmm_worker_completion(gpu_cluster, environment, gpu_nodes):
        # Check for kmm-worker-{gpu-node-name}-test-deviceconfig PODs to be started and completed
        global Logger

        # Check for build pods
        build_pods = [common.PodInfo(f"build", len(gpu_nodes), 1)]
        build_job_done = False
        for _ in range(5):
            build_pod_status = k8_util.k8_check_pod_status(gpu_cluster, environment.gpu_operator_namespace, build_pods)
            Logger.debug(f"kmm-worker status: {build_pod_status}")

            build_job_done = True
            for pod_name, status in build_pod_status.items():
                if status in {'Running', 'Pending'}:
                    build_job_done  = False
            if build_job_done :
                break
            Logger.info(f"kmm-worker status: {build_pod_status}")
            time.sleep(120)

        assert build_job_done, "build pod still running, check cluster status"

        # Check for kmm pods
        kmm_worker_pods = []
        for node in gpu_nodes:
            node_name = node['metadata']['name']
            assert node_name, "Missing node-name for the gpu node in the node-info JSON"
            kmm_worker_pods.append(common.PodInfo(f"kmm-worker-{node_name}", 1, 1))

        kmm_worker_done = False
        for _ in range(5):
            kmm_worker_status = k8_util.k8_check_pod_status(gpu_cluster, environment.gpu_operator_namespace, kmm_worker_pods)
            Logger.debug(f"kmm-worker status: {kmm_worker_status}")

            kmm_worker_done = True
            for pod_name, status in kmm_worker_status.items():
                if status in {'Running', 'Pending'}:
                    kmm_worker_done = False
            if kmm_worker_done:
                break
            Logger.info(f"kmm-worker status: {kmm_worker_status}")
            time.sleep(120)

        assert kmm_worker_done, "kmm-worker still running, check cluster status"

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
    def assert_or_debug(condition, message, pause_on_failure = False):
        global Logger
        if not condition and pause_on_failure:
            Logger.error(f"Pausing for failure : {message}")
            pytest.set_trace()
        assert condition, message

@pytest.fixture(scope="session")
def k8_helper():
    return K8Helper
