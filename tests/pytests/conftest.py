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
import pdb
import os
import re
import json
import shutil
import requests
import logging
from datetime import datetime
from lib import common
from lib import k8_util
from pathlib import Path
from urllib.parse import urlparse
import getpass

Logger = logging.getLogger("root.conftest")
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger('invoke').setLevel(logging.WARNING)
logging.getLogger('kubernetes').setLevel(logging.WARNING)

def pytest_addoption(parser):
    parser.addoption(
            "--global-registry",
            action = "store",
            default = "registry.test.pensando.io:5000",
            help = "Docker registry to use while setting up exporter image",
    )

    parser.addoption(
            "--testbed",
            action="store",
            default=None,
            help="Testbed YAML file with details about platform/cluster",
    )

    parser.addoption(
            "--deployment",
            action = "store",
            default = "k8",
            choices = ["k8", "openshift", "standalone"],
            help = "Deployment model to test against",
    )

    parser.addoption(
            "--image-manifest",
            action = "store",
            default = None,
            required = True,
            help = "Image manifest listing images to use for testing"
    )

    parser.addoption(
            "--skip-kube-config",
            action = "store",
            default = False,
            help = "Skip K8 kube config to connect to cluster"
    )

    parser.addoption(
            "--secrets-json",
            action = "store",
            default = None,
            help = "K8 secrets json file"
    )

    parser.addoption(
            "--amdgpu-driver-spec",
            action = "store",
            default = "lib/files/amd-deviceconfig-driver-spec.json",
            required = False,
            help = "AMDGPU Driver to use"
    )

    parser.addoption(
            "--pause-on-failure",
            action = "store_true",
            default = False,
            help = "Pause on failure - calls pytest.set_trace() during assert"
    )


def pytest_html_report_title(report):
    # Add a custom title to the report
    report.title = f"GPU-Operator/DeviceConfig K8 Test Results"

def pytest_html_results_summary(prefix, summary, postfix):
    # Insert custom HTML into the summary section of the report
    '''
    prefix.extend([html.h3("Testbed Information")])
    summary.extend([html.h3("Additional Summary Information")])
    postfix.extend([html.h3("Post Run Information")])
    '''

def pytest_configure(config):
    if 'junit_suite_name' not in config.inicfg:
        config.inicfg['junit_suite_name'] = 'GPU Operator TestSuite'


@pytest.hookimpl(optionalhook=True)
def pytest_metadata(metadata):
    metadata.clear()

@pytest.fixture(scope="session")
def release_name():
    return "gpu-operator"

@pytest.fixture(scope="session")
def environment(request):
    global Logger
    class Env(object):
        pass

    tenv = Env()
    setattr(tenv, 'deployment_mode', request.config.option.deployment)
    setattr(tenv, 'gpu_operator_namespace', 'kube-amd-gpu')
    setattr(tenv, 'download_folder', 'downloads')
    setattr(tenv, 'global_registry', request.config.option.global_registry)
    setattr(tenv, 'sandbox_dir', "logs")
    if request.config.option.amdgpu_driver_spec:
        with open(request.config.option.amdgpu_driver_spec, "r") as fp:
            driver_spec = json.load(fp)
            setattr(tenv, 'amdgpu_driver_spec', driver_spec)
    setattr(tenv, 'pause_on_failure', request.config.option.pause_on_failure)
    kube_config_file = kube_config = os.path.join(Path.home(), ".kube", "config")
    if os.path.exists(kube_config_file):
        setattr(tenv, 'kube_config_file', kube_config_file)
    else:
        pytest.fail("Failed to find kube_config_file for cluster operator - Aborting")

    secrets_json_file = os.path.join(Path.home(), ".kube", "secrets.json")
    if request.config.option.secrets_json:
        secrets_json_file = request.config.option.secrets_json
    if os.path.exists(secrets_json_file):
        setattr(tenv, 'k8_secrets_file', secrets_json_file)
    '''
    request.config._metadata['Helm-Chart Version'] = request.config.option.gpu_operator_version
    request.config._metadata['Metrics Exporter Version'] = request.config.option.metrics_exporter_version
    request.config._metadata['Deployment'] = request.config.option.deployment.upper()
    '''
    return tenv

@pytest.fixture(scope="session")
def gpu_cluster(request, release_name, environment):
    global Logger
    if environment.deployment_mode in ["k8", "openshift"]:
        localhost = common.Node("localhost", None, None, None, "master", None)
        k8_cluster_inst = common.k8_cluster(master_node = localhost)
        k8_cluster_inst.k8_kube_config = environment.kube_config_file
        if hasattr(environment, "k8_secrets_file"):
            with open(environment.k8_secrets_file) as fp:
                k8_cluster_inst.k8_secrets = json.load(fp)
        cleanup_cluster(k8_cluster_inst, release_name, environment)
        return k8_cluster_inst
    else:
        # Build testbed_info from testbed-yaml file
        from ruamel.yaml import YAML
        from ruamel.yaml import comments
        from ruamel.yaml import scalarstring
        import shutil

        yaml = YAML()
        yaml.preserve_quotes = True

        file_obj = Path(request.config.option.testbed)
        testbed_info = yaml.load(file_obj)
        gpu_node_list = list()
        k8_master_node_list = list()
        k8_master_docker_regsitry = False
        for inst in testbed_info["instances"]:
            node_types = inst.get("type", "worker").split(",")
            if 'master' in node_types:
                node = common.Node(inst["ip"], inst.get("username"),
                                   inst.get("password", None), inst.get("identity", None),
                                   "master", None)
                k8_master_node_list.append(node)
                k8_master_docker_regsitry = inst.get("registry", "no") == "yes"
            if 'worker' in node_types:
                node = common.Node(inst["ip"], inst.get("username"),
                                   inst.get("password", None), inst.get("identity", None),
                                   "worker", inst.get("gpu_series", "MI210"))
                gpu_node_list.append(node)

        assert len(k8_master_node_list) > 0
        assert len(gpu_node_list) > 0
        request.config._metadata['Testbed'] = request.config.option.testbed
        return common.standalone_gpu_nodes(gpu_node_list)

@pytest.fixture(scope="session")
def images(request, environment, gpu_cluster):
    image_info = None
    from ruamel.yaml import YAML
    from ruamel.yaml import comments
    from ruamel.yaml import scalarstring
    import shutil

    yaml = YAML()
    yaml.preserve_quotes = True

    file_obj = Path(request.config.option.image_manifest)
    image_manifest = dict(yaml.load(file_obj))

    # Process metadata section of image-manifest
    image_metadata = image_manifest['images'].get('meta', {})
    registry = 'docker.io'
    if 'registry' in image_metadata:
        registry = image_metadata['registry'].get('default', 'docker.io')
        if 'mirror' in image_metadata['registry']:
            if image_metadata['registry']['mirror'].get('enable', 'no') == 'yes':
                registry = image_metadata['registry']['mirror']['url']
    setattr(environment, 'default_registry', registry)
    if 'packaging' in image_metadata:
        if image_metadata['packaging'].get('gpuctl', 'enabled') == 'disabled':
            setattr(environment, "builtin_gpuctl_support", False)
        else:
            setattr(environment, "builtin_gpuctl_support", True)
    else:
        setattr(environment, "builtin_gpuctl_support", True)
    gpu_cluster.k8_registry = environment.default_registry
    assert environment.deployment_mode in image_manifest['images'], f"Missing images for {environment.deployment_mode}"
    if environment.deployment_mode == "standalone":
        image_info = images_standalone(request, environment, image_manifest['images'])

    if environment.deployment_mode == "k8":
        image_info = images_k8(request, environment, gpu_cluster, image_manifest['images'])

    if environment.deployment_mode == "openshift":
        image_info = images_openshift(request, environment, gpu_cluster, image_manifest['images'])

    assert image_info != None, f"Failed to build images for {environment.deployment_mode}"
    return image_info

def images_standalone(request, environment, image_manifest):
    images = image_manifest['standalone']
    file_name = 'amdgpu-exporter_1.0.0_amd64.deb'
    exp_image_folder = os.path.join(environment.download_folder, environment.metrics_exporter_version)
    os.makedirs(exp_image_folder, exist_ok=True)

    Logger.info(f"Downloading device-metric-exporter images for version {environment.metrics_exporter_version}")
    url = f'http://assets-hq.pensando.io/builds/hourly-device-metrics-exporter/{environment.metrics_exporter_version}/{file_name}'
    local_file = os.path.join(exp_image_folder, file_name)
    if not os.path.exists(local_file):
        try:
            resp = requests.get(url)
            if resp.status_code == 200:
                with open(local_file, 'wb') as fp:
                    fp.write(resp.content)
            else:
                raise Exception(f"Failed to download file {file_name}, error: {resp.status_code}")
        except Exception as e:
            Logger.error(f"Failed to download {file_name} from {url}, error : {e}")
            pytest.fail("Could not download images - abort")

    return local_file

def images_k8(request, environment, gpu_cluster, image_manifest):
    '''
    Download image from the asset-server/minio/hourly and load to local registry if needed
    '''
    global Logger
    image_info = dict()

    images = image_manifest['k8']
    # prepare to download gpu-operator
    setattr(environment, 'gpu_operator_version', images['gpu-operator']['version'].split("-", 1)[0])
    if 'build' in images['gpu-operator']:
        setattr(environment, 'gpu_operator_build', images['gpu-operator']['build'])
    setattr(environment, 'metrics_exporter_version', images['device-metrics-exporter']['version'])
    if 'build' in images['device-metrics-exporter']:
        setattr(environment, 'metrics_exporter_build', images['device-metrics-exporter']['build'])

    os.makedirs(environment.download_folder, exist_ok=True)
    gpu_cluster.k8_master.run_command(f"rm -r -f {environment.download_folder}")
    gpu_cluster.k8_master.run_command(f"mkdir -p {environment.download_folder}")
    image_info['image_folder'] = environment.download_folder

    for artifact, artifact_info in images.items():
        Logger.info(f"Downloading {artifact}")
        if 'repo://' in artifact_info['location']:
            pattern = r"repo://([a-zA-Z0-9.-]+/[^:]+):([^/]+)"
            match = re.search(pattern, artifact_info['location'])
            if match:
                image_info[f'{artifact}.repo-name'] = f"{artifact}-repo"
                image_info[f'{artifact}.repo'] = f"https://{match.group(1)}"
                image_info[f'{artifact}.helm-chart'] = f"{artifact}-repo/{match.group(2)}"
            else:
                pytest.fail(f"Failed to parse repo information from {artifact_info['location']}")
        elif 'file://' in artifact_info['location']:
            # Copy the files
            local_file = artifact_info['location'].split('file://')[-1]
            if not os.path.exists(local_file):
                pytest.fail(f"Invalid file name or path not found : {local_file}")
            # If not local, upload these files to the master node
            if not gpu_cluster.k8_master.is_local():
                # Upload the downloaded files to gpu_cluster.k8_master
                remote_file = os.path.join(environment.download_folder, os.path.basename(local_file))
                gpu_cluster.k8_master.put(local_file, remote_file)
                file_path = remote_file
            else:
                file_path = local_file

            if artifact_info['kind'] == 'container':
                if gpu_cluster.k8_master.is_local_registry_available():
                    setattr(environment, 'registry', f"{gpu_cluster.k8_master.ip_address}:5000")

                    # Setup k8-master docker registry
                    load_cmd = f"docker load -i {os.path.join(exp_image_folder, os.bath.basename(file_path))}"
                    result, cmd_stdout, _ = gpu_cluster.k8_master.run_command(load_cmd)
                    assert result == 0, f"Cmd failed: {load_cmd}, result:{result}, stdout:{cmd_stdout}"
                    loaded_img = cmd_stdout.split("Loaded image: ")[1].strip()

                    repository = f"{environment.registry}/{getpass.getuser()}/{artifact}"
                    version = artifact_info['version']
                    tag_cmd = f"docker tag {loaded_img} {repository}:{version}"
                    result, cmd_stdout, _ = gpu_cluster.k8_master.run_command(tag_cmd)
                    assert result == 0, f"Cmd failed: {tag_cmd}, result:{result}, stdout:{cmd_stdout}"

                    push_cmd = f"docker push {repository}:{version}"
                    result, cmd_stdout, _ = gpu_cluster.k8_master.run_command(push_cmd)
                    assert result == 0, f"Cmd failed: {push_cmd}, result:{result}, stdout:{cmd_stdout}"
                    image_info[f"{artifact_info['key']}.repository"] = repository
                    image_info[f"{artifact_info['key']}.version"] = version
                else:
                    pytest.fail("Use image-manifest.yaml with remote registry locations")
            elif artifact_info['kind'] == 'helm-chart':
                image_info[f'{artifact}.helm-chart'] = file_path
        elif 'http://' in artifact_info['location'] or 'https://' in artifact_info['location']:
            # Download the file
            url = artifact_info['location']
            local_file = os.path.join(environment.download_folder, os.path.basename(urlparse(url).path))
            if not os.path.exists(local_file):
                try:
                    resp = requests.get(url)
                    if resp.status_code == 200:
                        with open(local_file, 'wb') as fp:
                            fp.write(resp.content)
                    else:
                        raise Exception(f"Failed to download file {local_file}, error: {resp.status_code}")
                except Exception as e:
                    Logger.error(f"Failed to download {local_file} from {url}, error : {e}")
                    pytest.fail("Could not download images - abort")

            # If not local, upload these files to the master node
            if not gpu_cluster.k8_master.is_local():
                # Upload the downloaded files to gpu_cluster.k8_master
                gpu_cluster.k8_master.put(local_file, local_file)
            file_path = local_file

            if artifact_info['kind'] == 'container':
                if gpu_cluster.k8_master.is_local_registry_available():
                    setattr(environment, 'registry', f"{gpu_cluster.k8_master.ip_address}:5000")

                    # Setup k8-master docker registry
                    load_cmd = f"docker load -i {os.path.join(exp_image_folder, os.bath.basename(file_path))}"
                    result, cmd_stdout, _ = gpu_cluster.k8_master.run_command(load_cmd)
                    assert result == 0, f"Cmd failed: {load_cmd}, result:{result}, stdout:{cmd_stdout}"
                    loaded_img = cmd_stdout.split("Loaded image: ")[1].strip()

                    repository = f"{environment.registry}/{getpass.getuser()}/{artifact}"
                    version = artifact_info['version']
                    tag_cmd = f"docker tag {loaded_img} {repository}:{version}"
                    result, cmd_stdout, _ = gpu_cluster.k8_master.run_command(tag_cmd)
                    assert result == 0, f"Cmd failed: {tag_cmd}, result:{result}, stdout:{cmd_stdout}"

                    push_cmd = f"docker push {repository}:{version}"
                    result, cmd_stdout, _ = gpu_cluster.k8_master.run_command(push_cmd)
                    assert result == 0, f"Cmd failed: {push_cmd}, result:{result}, stdout:{cmd_stdout}"
                    image_info[f"{artifact_info['key']}.repository"] = repository
                    image_info[f"{artifact_info['key']}.version"] = version
                else:
                    pytest.fail("Use image-manifest.yaml with remote registry locations")
            elif artifact_info['kind'] == 'helm-chart':
                image_info[f'{artifact}.helm-chart'] = file_path
        elif 'container://' in artifact_info['location']:
            location = artifact_info['location']
            if '<registry>' in location and environment.default_registry:
                url = location.replace('<registry>', environment.default_registry)
            else:
                url = location
            parsed_data = urlparse(url)
            image_info[f"{artifact_info['key']}.repository"] = f"{parsed_data.netloc}{parsed_data.path}"
            if artifact_info.get('version'):
                image_info[f"{artifact_info['key']}.version"] = artifact_info['version']
            if 'secret' in artifact_info:
                image_info[f"{artifact_info['key']}.secret"] = artifact_info['secret']

    return image_info

def cleanup_cluster(gpu_cluster, release_name, environment):
    global Logger
    Logger.info("Delete any deviceconfig CRs from the cluster")
    def _delete_deviceconfigs(k8_cluster : common.k8_cluster, namespace : str) -> None:
        device_cfg_info = k8_util.k8_get_deviceconfigs_info(k8_cluster, namespace, None)

        for devcfg_name, _ in device_cfg_info.items():
            k8_util.k8_delete_deviceconfig_cr(k8_cluster, namespace, devcfg_name)
        return

    def _delete_debug_pods(k8_cluster : common.k8_cluster, namespaces) -> None:
        for namespace in namespaces:
            k8_util.k8_delete_all_pods_with_prefix(k8_cluster, namespace, "node-debug-")
            k8_util.k8_delete_all_pods_with_prefix(k8_cluster, namespace, "curl-cmd-pod-")
            k8_util.k8_delete_all_pods_with_prefix(k8_cluster, namespace, "pytorch-")
            k8_util.k8_delete_all_pods_with_prefix(k8_cluster, namespace, "techsupport-")
            k8_util.k8_delete_all_pods_with_prefix(k8_cluster, namespace, "test-runner-manual-trigger-")

    # Init k8 config
    k8_util.k8_lib_init(gpu_cluster)
    # cleanup
    _delete_deviceconfigs(gpu_cluster, environment.gpu_operator_namespace)
    _delete_debug_pods(gpu_cluster, ["default", environment.gpu_operator_namespace])
    if k8_util.is_helm_chart_deployed(gpu_cluster, release_name, environment.gpu_operator_namespace):
        Logger.warn(f"helm {release_name} is already deployed - cleanup")
        ret_code, ret_stdout, ret_stderr = k8_util.helm_uninstall(gpu_cluster, release_name,
                                                                  environment.gpu_operator_namespace)
        if ret_code != 0:
            k8_util.helm_cleanup(gpu_cluster, release_name, environment.gpu_operator_namespace)
        #k8_util.k8_delete_namespace(gpu_cluster, environment.gpu_operator_namespace)
    return
