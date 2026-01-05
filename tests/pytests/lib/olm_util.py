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
import json
import logging
import pytest
import subprocess
import pprint
import base64
import json
from functools import wraps
import lib.common as common
import lib.k8_util as k8_util

Logger = logging.getLogger("lib.olmutil")
LogPrettyPrinter = pprint.PrettyPrinter(indent = 2)

def log_arguments(func):
    global Logger
    global LogPrettyPrinter

    @wraps(func)
    def wrapper(*args, **kwargs):
        Logger.debug(f"Function::'{func.__name__}' with args: {args} kwargs: {kwargs}")
        return func(*args, **kwargs)
    return wrapper

@log_arguments
def olm_install(k8_cluster : common.k8_cluster, repo_url : str, namespace: str, **kwargs) -> (int, str, str):
    """
    API to install OLM Bundle

    For example, following commands will be run:
    $PATH/operator-sdk run bundle <registry>/amd-gpu-operator-bundle:v1.4.1 --namespace <namespace> <options>

    Following options:
     --skip-tls --skip-tls-verify --use-http --security-context-config restricted

    Parameters:
    k8_cluster : intance of lib.common.k8_cluster
    repo_url   : repo url
    namespace  : Namespace to use
    """
    cmd = ["operator-sdk", "run", "bundle", repo_url, "--namespace", namespace]
    if kwargs.get('skip-tls', True):
        cmd.append("--skip-tls")
    if kwargs.get('skip-tls-verify', True):
        cmd.append("--skip-tls-verify")
    if kwargs.get('use-http', True):
        cmd.append("--use-http")
    if kwargs.get("pull-secret-name", None):
        cmd.extend(["--pull-secret-name", kwargs.get("pull-secret-name")])
    cmd.extend(["--security-context-config", kwargs.get("security-context-config", "restricted")])
    if k8_cluster.k8_kube_config:
        cmd.extend(["--kubeconfig", k8_cluster.k8_kube_config])

    Logger.debug(f"olm-install command: {cmd}")
    cmd_resp = subprocess.run(cmd, check=False,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                encoding='utf-8')
    return cmd_resp.returncode, cmd_resp.stdout, cmd_resp.stderr

@log_arguments
def olm_cleanup(k8_cluster : common.k8_cluster, release_name : str, namespace : str) -> (int, str, str):
    """
    API to remove OLM Bundle

    For example, following commands will be run:
    $PATH/operator-sdk cleanup <release-name> -n <namespace> --delete-all

    Parameters:
    k8_cluster : intance of lib.common.k8_cluster
    release_name : Name of OLM Bundle
    namespace   : Namespace to use
    """

    cmd = ["operator-sdk", "cleanup", release_name, "--namespace", namespace]
    if k8_cluster.k8_kube_config:
        cmd.extend(["--kubeconfig", k8_cluster.k8_kube_config])

    Logger.debug(f"olm-cleanup command: {cmd}")
    cmd_resp = subprocess.run(cmd, check=False,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                encoding='utf-8')

    # cmd_resp.returncode, cmd_resp.stdout, cmd_resp.stderr
    # Delete catalogsources
    """
    oc delete catalogsources -n openshift-amd-gpu amd-gpu-operator-catalog
    """
    return k8_delete_custom_resource("operators.coreos.com", "v1alpha1", "catalogsources", namespace, f"{release_name}-catalog")

@log_arguments
def olm_manage_amdgpu_driver_blacklist(enable : bool, is_mini_kube_cluster : bool) -> (int, str, str):
    """
    API to manage amdgpu driver-blacklist on openshift cluster

    Parameters:
    enable : True to enable, False to disable
    """
    global Logger
    global LogPrettyPrinter

    # --- Resource Definition ---
    # The content "blacklist amdgpu\n" is base64 encoded as "YmxhY2tsaXN0IGFtZGdwdQo="
    # as shown in your YAML.

    GROUP = "machineconfiguration.openshift.io"
    VERSION = "v1"
    PLURAL = "machineconfigs" # The plural name for MachineConfig objects
    NAMESPACE = "openshift-machine-config-operator" # This is the standard namespace for MCO resources
    RESOURCE_NAME = "amdgpu-module-blacklist"
    ROLE_LABEL = "master" if is_mini_kube_cluster else "worker"
    CONFIG_PATH = "/etc/modprobe.d/amdgpu-blacklist.conf"
    CONFIG_CONTENT_BASE64 = "YmxhY2tsaXN0IGFtZGdwdQo="

    # Construct the MachineConfig body as a dictionary
    machine_config_body = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "MachineConfig",
        "metadata": {
            "name": RESOURCE_NAME,
            "labels": {
                "machineconfiguration.openshift.io/role": ROLE_LABEL
            }
        },
        "spec": {
            "config": {
                "ignition": {
                    "version": "3.5.0"
                },
                "storage": {
                    "files": [
                        {
                            "path": CONFIG_PATH,
                            "mode": 420,
                            "overwrite": True,
                            "contents": {
                                "source": f"data:text/plain;base64,{CONFIG_CONTENT_BASE64}"
                            }
                        }
                    ]
                }
            }
        }
    }

    if enable:
        ret_code, cr_list, err = k8_util.k8_get_custom_resource_objects(group = GROUP, version = VERSION, plural = PLURAL)
        if ret_code != 0:
            return ret_code, cr_list, err
        amdgpu_mod_blklist_crobjs = list(filter(lambda x: x['metadata']['name'] == RESOURCE_NAME, cr_list))
        if len(amdgpu_mod_blklist_crobjs) == 0:
            Logger.info(f"{PLURAL} CustomResource object not found, create to blacklist amdgpu driver")
            return k8_util.k8_create_custom_resource(machine_config_body)
        else:
            Logger.warning(f"Found {len(amdgpu_mod_blklist_crobjs)} {PLURAL} CustomResource objects - proceeding as-is. Check logs for any inconsistency")
            Logger.debug(LogPrettyPrinter.pformat(amdgpu_mod_blklist_crobjs))
        return 0, "", ""
    else:
        return k8_util.k8_delete_custom_resource(GROUP, VERSION, PLURAL, NAMESPACE, RESOURCE_NAME)


@log_arguments
def update_secrets(k8_cluster : common.k8_cluster, namespace : str) -> (int, str, str):
    """
    API to patch openshift serviceaccount with image pull secrets
    """
    patch = {
        "imagePullSecrets" : [],
    }
    for entry in k8_cluster.k8_secrets["secrets"]:
        patch["imagePullSecrets"].append({"name": entry.get("name")})

    Logger.debug(f"Applying following patch to Openshift default-namespace service-account, {patch}")
    ret_code, ret_stdout, ret_stderr = k8_util.k8_patch_serviceaccount(namespace, "default", patch)
    if ret_code != 0:
        Logger.error(f"failed to patch openshift serviceaccount with image pull-secret, stderr: {ret_stderr}")
        return ret_code, ret_stdout, ret_stderr
    return 0, "", ""
