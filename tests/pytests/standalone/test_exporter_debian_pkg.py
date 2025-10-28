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
import re
import time
import json
import logging
import lib.k8_util as k8_util
import lib.amdgpu as amdgpu
import lib.common as common
import lib.spec_util as spec_util
from k8.util import K8Helper

Logger = logging.getLogger("k8.test_driver_deviceplugin")

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
    K8Helper.triage(environment, ret_code == 0, f"Failed to install helm-chart for {release_name}")
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
    K8Helper.triage(environment, ret_code == 0, f"Failed to uninstall {release_name} helm-chart, error: {ret_stderr}")
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
    K8Helper.triage(environment, ret_code == 0, "Error while getting gpu-nodes from k8-cluster")
    K8Helper.triage(environment, len(gpu_nodes) > 0, "No nodes with AMD/GPU found in the cluster")

    test_config = {
            'metadata.namespace' : environment.gpu_operator_namespace,
            'driver.enable' : True,
            'driver.blacklist' : True,
            'devicePlugin.enableNodeLabeller' : False,
            'metricsExporter.enable' : False
        }

    test_config.update(images)

    test_cfg_map = spec_util.build_deviceconfig_cr_template(test_config, gpu_cluster, gpu_nodes, 'device-plugin', environment.amdgpu_driver_spec)
    exporter_port_map = {}
    devicecfg_list = []

    for spec_name, tcfg in test_cfg_map.items():
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_create_deviceconfig_cr(gpu_cluster, cr_spec)
        K8Helper.triage(environment, ret_code == 0, f"Failed to create deviceconfig, stderr: {ret_stderr}")
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

    # cleanup - remove any deviceconfigs and then gpu-operator helm-chart
    devcfg_map = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace)
    for devcfg_name, _ in devcfg_map.items():
        ret_code, ret_stdout, ret_stderr = k8_util.k8_delete_deviceconfig_cr(gpu_cluster, environment.gpu_operator_namespace, devcfg_name)
        if ret_code != 0:
            Logger.error(f"Failed to delete deviceconfig name: {devcfg_name}, error : {ret_stderr}")
    time.sleep(10)
    return

def test_deploy_exporter_debian_package(gpu_cluster, deviceconfig_install, environment):
    global Logger

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    K8Helper.triage(environment, ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster")

    # TODO: Deploy exporter debian package on the node and do verification
    for node in gpu_nodes:
        node_name = k8_util.k8_get_node_hostname(node)

        # For each node, upload debian package after starting a ubuntu pod in sysadmin profile
        # install debian package on the host

# Generate testcases for each supported driver-version
def pytest_generate_tests(metafunc):
    global Logger
    if 'upgrade_version' in metafunc.fixturenames:
        if metafunc.config.option.amdgpu_driver_spec:
            with open(metafunc.config.option.amdgpu_driver_spec, "r") as fp:
                driver_spec = json.load(fp)
        current_version = driver_spec["default-version"]
        driver_versions = []
        for ver in driver_spec.get('alternative-versions', []):
            if ver != current_version:
                driver_versions.append(ver)
        metafunc.parametrize('upgrade_version', driver_versions)

def test_debian_pkg_driver_compat(gpu_cluster, deviceconfig_install, environment, upgrade_version):
    global Logger
    if environment.gpu_operator_version in ["v1.0.0", "v1.1.0"]:
        pytest.skip(f"Skipping driver-upgrade testcase for current version {environment.gpu_operator_version}")
    if gpu_cluster.mini_kube_cluster:
        pytest.skip("Using mini-kube cluster - skip driver upgrade testcases")

    current_version = environment.amdgpu_driver_spec["default-version"]
    Logger.info(f"Upgrading cluster/gpu-nodes from {current_version} => {upgrade_version}")

    ret_code, gpu_nodes = k8_util.k8_get_gpu_nodes(gpu_cluster)
    K8Helper.triage(environment, ret_code == 0, "gpu-operator failed to find amd/gpu nodes in the cluster")
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['driver.blacklist'] = True
        tcfg['driver.version'] = upgrade_version
        tcfg['driver.upgradePolicy.enable'] = False
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        K8Helper.triage(environment, ret_code == 0, "Failed to modify deviceconfig CR")

    devcfg_map = k8_util.k8_get_deviceconfigs_info(gpu_cluster, environment.gpu_operator_namespace)
    for devcfg_name, devcfg_info in devcfg_map.items():
        devcfg_driver_version = devcfg_info.get('spec').get('driver').get('version')
        Logger.info(f'Configured Version: {devcfg_driver_version}') 
        K8Helper.triage(environment, upgrade_version == devcfg_driver_version,
                        f"Expected {upgrade_version}, found {devcfg_driver_version}")

    # Enable upgradePolicy
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['driver.upgradePolicy.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        K8Helper.triage(environment, ret_code == 0, "Failed to modify deviceconfig CR to enable upgradePolicy")

    K8Helper.wait_for_upgrade_completion_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list, gpu_nodes)
    if environment.gpu_operator_version in ["v1.2.0", "v1.2.1", "v1.2.2"]:
        # For v1.2.0 and v1.2.1, manual reboot is required
        Logger.info(f"For {environment.gpu_operator_version}, manual reboot of nodes required post driver upgrade")
        for node in gpu_nodes:
            node_name = k8_util.k8_get_node_hostname(node)
            ret_code = k8_util.reboot_node(gpu_cluster, node_name)
            K8Helper.triage(environment, ret_code == 0, f"Failed to reboot node {node_name}")

    rocm_version = amdgpu.get_rocm_version(upgrade_version)
    K8Helper.check_node_driver_version(gpu_cluster, upgrade_version, rocm_version, environment)

    # TODO: Deploy exporter debian package on the node and do verification

    # Restore
    Logger.info(f"Restoring cluster/gpu-nodes from {upgrade_version} => {current_version}")
    for spec_name, tcfg in deviceconfig_install.test_cfg_map.items():
        tcfg['driver.blacklist'] = True
        tcfg['driver.version'] = current_version
        tcfg['driver.upgradePolicy.enable'] = True
        cr_spec = spec_util.generate_k8_deviceconfig_cr(environment.gpu_operator_version, tcfg)
        ret_code, ret_stdout, ret_stderr = k8_util.k8_modify_deviceconfig_cr(gpu_cluster, cr_spec)
        K8Helper.triage(environment, ret_code == 0, "Failed to modify deviceconfig CR")

    # Check for reboot operation
    K8Helper.wait_for_upgrade_completion_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list, gpu_nodes)

    # Check for corresponding deviceconfig updated
    K8Helper.check_deviceconfig_status(gpu_cluster, environment, deviceconfig_install.devicecfg_list)
    for devcfg in deviceconfig_install.devicecfg_list:
        K8Helper.wait_kmm_worker_completion(gpu_cluster, environment, devcfg)

    rocm_version = amdgpu.get_rocm_version(current_version)
    K8Helper.check_node_driver_version(gpu_cluster, current_version, rocm_version, environment)

