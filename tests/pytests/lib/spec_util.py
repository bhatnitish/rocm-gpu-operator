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

import sys
import os
import copy
import logging
import shutil
import json
import io
from ruamel.yaml import YAML
from ruamel.yaml import comments
from ruamel.yaml import scalarstring
from pathlib import Path
from collections import defaultdict

Logger = logging.getLogger("lib.specutil")
yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(sequence=4, offset=2)
DQ = scalarstring.DoubleQuotedScalarString

device_config_template_v1_0_0 = {
    'apiVersion'    : 'amd.com/v1alpha1',
    'kind'          : 'DeviceConfig',
    'metadata'      : {
        'name'      : 'test-deviceconfig',
        'namespace' : 'kube-amd-gpu',
    },
    'spec'          : {
        'driver'    : {
            'image' : '',
            'enable': False,
            'blacklist' : True,
            'imageRegistryTLS' : {
                'insecure'                  : True,
                'insecureSkipTLSVerify'     : True,
            },
        },
        'devicePlugin' : {
            'devicePluginImage': '',
            'nodeLabellerImage': '',
            'enableNodeLabeller' : False,
        },
        'metricsExporter' : {
            'image'             : '',
            'enable'            : False,
            'nodePort'          : 32500,
            'port'              : 5000,
            'serviceType'       : DQ('ClusterIP'),
            'rbacConfig' : {
                'enable'        : False,
                'disableHttps'  : True,
            },
        },
        'selector' : {
            'feature.node.kubernetes.io/amd-gpu' : DQ('true'),
        },
    },
}

device_config_template_v1_2_0 = {
    'apiVersion'    : 'amd.com/v1alpha1',
    'kind'          : 'DeviceConfig',
    'metadata'      : {
        'name'      : 'test-deviceconfig',
        'namespace' : 'kube-amd-gpu',
    },
    'spec'          : {
        'commonConfig' : {
            'initContainerImage': '',
        },
        'driver'    : {
            'image' : '',
            'enable': False,
            'blacklist' : True,
            'imageRegistryTLS' : {
                'insecure'                  : True,
                'insecureSkipTLSVerify'     : True,
            },
        },
        'devicePlugin' : {
            'devicePluginImage': '',
            'devicePluginImagePullPolicy' : 'Always',
            'nodeLabellerImage': '',
            'enableNodeLabeller' : False,
            'nodeLabellerImagePullPolicy' : 'Always',
        },
        'metricsExporter' : {
            'image'             : '',
            'imagePullPolicy'   : 'Always',
            'enable'            : False,
            'nodePort'          : 32500,
            'port'              : 5000,
            'serviceType'       : DQ('ClusterIP'),
            'rbacConfig' : {
                'enable'        : False,
                'disableHttps'  : True,
            },
        },
        'testRunner' : {
            'enable' : False,
            'config' : None,
            'image'  : '',
            'imagePullPolicy': 'Always',
        },
        'selector' : {
            'feature.node.kubernetes.io/amd-gpu' : DQ('true'),
        },
    },
}

device_config_templates = {
    'v1.0.0' : device_config_template_v1_0_0,
    'v1.1.0' : device_config_template_v1_0_0,
    'v1.2.0' : device_config_template_v1_2_0,
    'v1.2.1' : device_config_template_v1_2_0,
    'v1.2.2' : device_config_template_v1_2_0,
    'v1.3.0' : device_config_template_v1_2_0,
}

device_config_template_default = device_config_template_v1_2_0


wl_template = {
    'apiVersion': 'v1', 
    'kind': 'Pod', 
    'metadata': {
         'name': 'pytorch-gpu-pod-1', 
         'namespace': 'kube-amd-gpu', 
         'labels': {
             'purpose': 'demo-wl'
         }
    }, 
    'spec': {
        'containers': [
            {
                'name': 'pytorch-gpu-container',
                'image': 'docker.io/rocm/pytorch:latest',
                'workingDir': '/root',
                'command': [
                    '/bin/bash',
                    '-c',
                    '--'
                ],
                'args': [
                    'rocm-smi > /tmp/rocm-smi-output; git clone https://github.com/ROCm/pytorch-micro-benchmarking.git; cd pytorch-micro-benchmarking;  python micro_benchmarking_pytorch.py --network resnet50 --compile > /tmp/benchmark-output; sleep infinity & wait'
                ],
                'resources': {
                    'limits': {
                        'amd.com/gpu': 0
                    }
                }
            }
        ],
        'nodeSelector': {
            'kubernetes.io/hostname': 'node'
        },
        'imagePullSecrets': [
            {
                'name': 'docker-amdpsdo-auth',
            }
        ]
    }
}

helm_deployment_template_0 = {
    'node-feature-discovery' : {
        'enabled': DQ('true'),
    },
    'installdefaultNFDRule': DQ('true'),
    'upgradeCRD': DQ('true'),
    'kmm' : {
        'enabled' : DQ('true'),
        'controller': {
            'manager': {
                'env': {
                    'relatedImageSign': 'rocm/kernel-module-management-signimage',
                    'relatedImageWorker': 'rocm/kernel-module-management-worker',
                },
                'image': {
                    'repository': 'rocm/kernel-module-management-operator',
                },
            }
        },
        'webhookServer': {
            'webhookServer': {
                'image': {
                    'repository': 'rocm/kernel-module-management-webhook-server',
                },
            }
        }
    },
    # AMD GPU operator controller related configs
    'controllerManager': {
        'manager': {
            'args': [
                '--config=controller_manager_config.yaml',
            ],
            'containerSecurityContext': {
                'allowPrivilegeEscalation': False,
            },
            'image': {
              # -- AMD GPU operator controller manager image repository
                'repository': 'rocm/gpu-operator',
              # -- AMD GPU operator controller manager image tag
                #'tag': '',
            },
            # -- Image pull policy for AMD GPU operator controller manager pod
            'imagePullPolicy': 'Always',
            # -- Image pull secret name for pulling AMD GPU operator controller manager image if registry needs credential to pull image
            #'imagePullSecrets': '',
            'tolerations': [
                {
                    'key': "node-role.kubernetes.io/master",
                    'operator': "Equal", 
                    'value': "",
                    'effect': "NoSchedule",
                },
                {
                    'key': "node-role.kubernetes.io/control-plane",
                    'operator': "Equal",
                    'value' : "",
                    'effect': "NoSchedule",
                }
            ],
        },
        # -- Node selector for AMD GPU operator controller manager deployment
        'nodeSelector': {},
        # -- Deployment affinity configs for controller manager
        'affinity': {
            'nodeAffinity': {
                'preferredDuringSchedulingIgnoredDuringExecution': [
                    {
                        'weight': 1,
                        'preference': {
                            'matchExpressions': [
                                {
                                    'key': 'node-role.kubernetes.io/control-plane',
                                    'operator': 'Exists',
                                }
                            ]
                        }
                    }
                ]
            }
        },
        'replicas': 1,
    }
}

def dump_yaml(file_name, data):
    with open(file_name, 'w') as fp:
        yaml.dump(data, fp)
    return data

def get_yaml(data):
    str_stream = io.StringIO()
    yaml.dump(data, str_stream)
    yaml_data = str_stream.getvalue()
    return yaml_data

def generate_k8_deviceconfig_cr(gpu_operator_version, spec = {}, skip_sections = {}):
    global Logger
    device_config = copy.deepcopy(device_config_templates.get(gpu_operator_version, device_config_template_default))
    device_config['metadata']['name'] = spec.get('metadata.name', 'deviceconfig')
    device_config['metadata']['namespace'] = spec.get('metadata.namespace', 'kube-amd-gpu')

    # commonConfig
    if not skip_sections.get('commonConfig', False):
        if spec.get('commonConfig.initContainerImage', None):
            device_config['spec']['commonConfig']['initContainerImage'] = spec.get('commonConfig.initContainerImage')
    else:
        del device_config['spec']['commonConfig']

    # driver
    if not skip_sections.get('driver', False):
        if spec.get('driver.image.repository', None):
            device_config['spec']['driver']['image'] = spec.get('driver.image.repository')
        device_config['spec']['driver']['version'] = DQ(spec.get('driver.version', '6.2.2'))
        device_config['spec']['driver']['enable'] = spec.get('driver.enable', False)
        device_config['spec']['driver']['blacklist'] = spec.get('driver.blacklist', True)
    else:
        del device_config['spec']['driver']

    # device-plugin
    if not skip_sections.get('devicePlugin', False):
        if spec.get('devicePlugin.devicePluginImage.repository', None):
            img = f"{spec.get('devicePlugin.devicePluginImage.repository')}:{spec.get('devicePlugin.devicePluginImage.version')}"
            device_config['spec']['devicePlugin']['devicePluginImage'] = img

        # node-labeller
        if spec.get('devicePlugin.nodeLabellerImage.repository', None):
            img = f"{spec.get('devicePlugin.nodeLabellerImage.repository')}:{spec.get('devicePlugin.nodeLabellerImage.version')}"
            device_config['spec']['devicePlugin']['nodeLabellerImage'] = img
        device_config['spec']['devicePlugin']['enableNodeLabeller'] = spec.get('devicePlugin.enableNodeLabeller', False)
    else:
        del device_config['spec']['devicePlugin']

    # metrics-exporter
    if not skip_sections.get('metricsExporter', False):
        if spec.get('metricsExporter.image.repository', None):
            img = f"{spec['metricsExporter.image.repository']}:{spec['metricsExporter.image.version']}"
            device_config['spec']['metricsExporter']['image'] = img
        if spec.get('metricsExporter.enable', False):
            device_config['spec']['metricsExporter']['enable'] = spec.get('metricsExporter.enable', False)
        if spec.get('metricsExporter.serviceType', None):
            device_config['spec']['metricsExporter']['serviceType'] = DQ(spec.get('metricsExporter.serviceType'))
            device_config['spec']['metricsExporter']['nodePort'] = spec.get('metricsExporter.nodePort', 32500)
            device_config['spec']['metricsExporter']['port'] = spec.get('metricsExporter.port', 5000)
        if spec.get('metricsExporter.config', None):
            device_config['spec']['metricsExporter']['config'] = {
                    'name' : spec.get('metricsExporter.config')
            }
        else:
            if 'config' in device_config['spec']['metricsExporter']:
                del device_config['spec']['metricsExporter']['config']
        device_config['spec']['metricsExporter']['rbacConfig']['enable'] = spec.get('metricsExporter.rbacConfig.enable', False)
        device_config['spec']['metricsExporter']['rbacConfig']['disableHttps'] = spec.get('metricsExporter.rbacConfig.disableHttps', True)
        if spec.get('metricsExporter.image.secret', None):
            device_config['spec']['metricsExporter']['imageRegistrySecret'] = {
                    'name' : spec.get('metricsExporter.image.secret')
            }
    else:
        del device_config['spec']['metricsExporter']

    # test-runner 
    if 'testRunner' in device_config['spec']:
        if not skip_sections.get('testRunner', False):
            if spec.get('testRunner.image.repository', None):
                img = f"{spec.get('testRunner.image.repository')}:{spec.get('testRunner.image.version')}"
                device_config['spec']['testRunner']['image'] = img
            device_config['spec']['testRunner']['enable'] = spec.get('testRunner.enable', False)
            device_config['spec']['testRunner']['imagePullPolicy'] = spec.get('testRunner.imagePullPolicy', 'IfNotPresent')
            if spec.get('testRunner.config', None):
                device_config['spec']['testRunner']['config'] = {
                        'name' : spec.get('testRunner.config'),
                }
            if spec.get('testRunner.image.secret', None):
                device_config['spec']['testRunner']['imageRegistrySecret'] = {
                        'name' : spec.get('testRunner.image.secret')
                }
        else:
            del device_config['spec']['testRunner']

    # selector
    if spec.get('selector.field', None) and spec.get('selector.value', None):
        device_config['spec']['selector'] = {
            spec.get('selector.field', 'feature.node.kubernetes.io/amd-gpu') : spec.get('selector.value', DQ('true')),
        }
    return device_config

def generate_helmchart_deployment_config(gpu_operator_version, images, file_name):
    '''
    Generate values.yaml used to install gpu-operator helm-chart
    '''

    modifed = False
    helmchart_values = copy.deepcopy(helm_deployment_template_0)

    # kmm controller manager image-sign
    kmm_sign_prefix = 'kmm.controller.manager.env.relatedImageSign'
    if images.get(f'{kmm_sign_prefix}.repository', None):
        modifed = True
        img = images.get(f'{kmm_sign_prefix}.repository') + ":" + images.get(f'{kmm_sign_prefix}.version', 'latest')
        helmchart_values['kmm']['controller']['manager']['env']['relatedImageSign'] = img
    if images.get(f"{kmm_sign_prefix}.secret", None):
        helmchart_values['kmm']['controller']['manager']['env']['relatedImageSignPullSecret'] = images.get(f'{kmm_sign_prefix}.secret')

    # kmm controller manager image-worker
    kmm_worker_prefix = 'kmm.controller.manager.env.relatedImageWorker'
    if images.get(f"{kmm_worker_prefix}.repository", None):
        modifed = True
        img = images.get(f'{kmm_worker_prefix}.repository') + ":" + images.get(f'{kmm_worker_prefix}.version', 'latest')
        helmchart_values['kmm']['controller']['manager']['env']['relatedImageWorker'] = img
    if images.get(f"{kmm_worker_prefix}.secret", None):
        helmchart_values['kmm']['controller']['manager']['env']['relatedImageWorkerPullSecret'] = images.get(f'{kmm_worker_prefix}.secret')

    # kmm controller manager
    kmm_manager_prefix = 'kmm.controller.manager.image'
    if images.get(f'{kmm_manager_prefix}.repository', None):
        modifed = True
        helmchart_values['kmm']['controller']['manager']['image']['repository'] = images.get(f'{kmm_manager_prefix}.repository')
    if images.get(f'{kmm_manager_prefix}.version', None):
        modifed = True
        helmchart_values['kmm']['controller']['manager']['image']['tag'] = images.get(f'{kmm_manager_prefix}.version')
    if images.get(f'{kmm_manager_prefix}.secret', None):
        modifed = True
        helmchart_values['kmm']['controller']['manager']['imagePullSecrets'] = images.get(f'{kmm_manager_prefix}.secret')

    # kmm webhook-server
    kmm_webhook_prefix = 'kmm.webhookServer.webhookServer.image'
    if images.get(f'{kmm_webhook_prefix}.repository', None):
        modifed = True
        helmchart_values['kmm']['webhookServer']['webhookServer']['image']['repository'] = images.get(f'{kmm_webhook_prefix}.repository')
    if images.get(f'{kmm_webhook_prefix}.version', None):
        modifed = True
        helmchart_values['kmm']['webhookServer']['webhookServer']['image']['tag'] = images.get(f'{kmm_webhook_prefix}.version')
    if images.get(f'{kmm_webhook_prefix}.secret', None):
        modifed = True
        helmchart_values['kmm']['webhookServer']['webhookServer']['imagePullSecrets'] = images.get(f'{kmm_webhook_prefix}.secret')

    # AMD GPU operator controller related configs
    ctrl_manager_prefix = 'controllerManager.manager.image'
    if images.get(f'{ctrl_manager_prefix}.repository', None):
        modifed = True
        helmchart_values['controllerManager']['manager']['image']['repository'] = images.get(f'{ctrl_manager_prefix}.repository')
    if images.get(f'{ctrl_manager_prefix}.version', None):
        modifed = True
        helmchart_values['controllerManager']['manager']['image']['tag'] = images.get(f'{ctrl_manager_prefix}.version')
    if images.get(f'{ctrl_manager_prefix}.secret', None):
        modifed = True
        helmchart_values['controllerManager']['manager']['imagePullSecrets'] = images.get(f'{ctrl_manager_prefix}.secret')

    if modifed:
        return dump_yaml(file_name, helmchart_values)
    return modifed

def generate_k8_workload_template(file_name, spec = {}):
    """
    Generates a simple workload yaml file based on the wl_template
    """
    global Logger
    wl_config = copy.deepcopy(wl_template)
    wl_config['metadata']['namespace'] = spec.get('namespace', 'kube-amd-gpu')
    wl_config['metadata']['name'] = spec.get('pod_name', 'pytorch-gpu-pod-1')
    wl_config['spec']['containers'][0]['resources']['limits']['amd.com/gpu'] = spec.get('num_gpu', 1)
    wl_config['spec']['nodeSelector']['kubernetes.io/hostname'] = spec.get('nodeSelector')

    return dump_yaml(file_name, wl_config)

def generate_service_account_yaml(file_name, namespace, sa_name):
    """

    Example:
    service-account.yaml
    apiVersion: v1
    kind: ServiceAccount
    metadata:
      name: exporter-client
      namespace : kube-amd-gpu
    """

    global Logger
    sa_spec = {
        'apiVersion' : 'v1',
        'kind' : 'ServiceAccount',
        'metadata' : {
            'name' : sa_name,
            'namespace' : namespace,
        }
    }
    return dump_yaml(file_name, sa_spec)

def generate_cluster_role_spec(file_name, cluster_role_name, endpoint_verbs):
    global Logger

    rules = []
    for endpoint in endpoint_verbs:
        rules.append({
            'nonResourceURLs' : [endpoint[0]],
            'verbs' : [endpoint[1]],
        })
    cluster_role_spec = {
        'apiVersion' : 'rbac.authorization.k8s.io/v1',
        'kind' : 'ClusterRole',
        'metadata' : {
            'name' : cluster_role_name,
        },
        'rules' : rules,
    }

    return dump_yaml(file_name, cluster_role_spec)

def generate_clusterrolebinding_yaml(file_name, crb_name, namespace, cluster_role, sa_name):
    """
    Example:
        apiVersion: rbac.authorization.k8s.io/v1
        kind: ClusterRoleBinding
        metadata:
          name: metrics
        roleRef:
          apiGroup: rbac.authorization.k8s.io
          kind: ClusterRole
          name: metrics
        subjects:
        - kind: ServiceAccount
          name: exporter-client
          namespace: kube-amd-gpu   # Updated namespace to metrics-reader
    """

    global Logger
    crb_spec = {
        'apiVersion' : 'rbac.authorization.k8s.io/v1',
        'kind' : 'ClusterRoleBinding',
        'metadata' : {
            'name' : crb_name,
        },
        'roleRef' : {
            'apiGroup' : 'rbac.authorization.k8s.io',
            'kind' : 'ClusterRole',
            'name' : cluster_role,
        },
        'subjects' : [
            {
                'kind' : 'ServiceAccount',
                'name' : sa_name,
                'namespace' : namespace,
            }
        ]
    }
    return dump_yaml(file_name, crb_spec)

def get_compatible_driver_versions(worker_node):
    global Logger
    with open('lib/files/amdgpu-driver-config.json') as fp:
        gpuinfo = json.load(fp)
        driver_data  = list(filter(lambda x: x['gpu'] == worker_node.gpu_series, gpuinfo['gpu-driver-info']))
        if len(driver_data) == 1:
            return driver_data[0]['versions']
    return [ { "software-version" : "6.2.4", "display-version" : "6.8.5" } ]

def group_gpu_nodes_by_dev_series(worker_nodes):
    '''
    Classify gpu-nodes based on gpu device-series
    '''
    global Logger
    groups = defaultdict(list)
    for node in worker_nodes:
        groups[node.gpu_series].append(node)
    return groups

def get_common_amdgpu_driver(worker_nodes, gpu_nodes):
    global Logger
    driver_version_sets = []
    for node in worker_nodes:
        k8_node = get_k8_node_info(gpu_nodes, node.ip_address)
        if k8_node == None:
            Logger.error(f"No such k8 node for {node.ip_address}")
            continue
        driver_version_sets.append(set(map(lambda x:x['software-version'], get_compatible_driver_versions(node))))
    common_driver = set.intersection(*driver_version_sets)
    Logger.debug(f"Found common-driver version supported as {common_driver}")
    return common_driver

def get_k8_node_info(gpu_nodes, node_ip_address):
    '''
    Return K8 Node JSON Info for given ip-address
    '''
    global Logger
    def k8_get_node_address(node_info, address_type = "InternalIP"):
        assert 'status' in node_info, f"k8 node missing status section, {node_info}"
        assert 'addresses' in node_info['status'], f"k8 node missing status.addresses, {node_info}"

        for addr in node_info['status']['addresses']:
            if addr.get("type", None) == address_type:
                return addr.get("address", None)
        assert f"Missing address-type : {address_type} in k8 node, {node_info}"

    for k8_node in gpu_nodes:
        if node_ip_address == k8_get_node_address(k8_node):
            return k8_node
    return None

def build_deviceconfigs_by_hostname(init_test_config, gpu_cluster, gpu_nodes, ctxt_name, driver_version = None):
    global Logger
    test_configs = {}
    groups = group_gpu_nodes_by_dev_series(gpu_cluster.worker_nodes)
    for dev_series, nodes in groups.items():
        for node in nodes:
            k8_node = get_k8_node_info(gpu_nodes, node.ip_address)
            if k8_node == None:
                Logger.error(f"No such k8 node for {node.ip_address}")
                continue
            supported_driver_info = get_compatible_driver_versions(node)
            assert supported_driver_info, f"No compatible gpu information available for worker-node {node.ip_address}"
            if driver_version:
                filtered_drivers = list(filter(lambda x:x['software-version'] == driver_version, get_compatible_driver_versions(node)))
                if not filtered_drivers:
                    Logger.warn(f"Specified driver {driver_version} not compatible for {node.ip_address}")
                    continue
                selected_driver_info = filtered_drivers[0]
            else:
                selected_driver_info = supported_driver_info[0]
            local_test_config = copy.deepcopy(init_test_config)
            local_test_config['metadata.name'] = f'deviceconfig-{dev_series.lower()}'
            local_test_config['driver.version'] = selected_driver_info['software-version']
            local_test_config['selector.field'] = 'kubernetes.io/hostname'
            local_test_config['selector.value'] = k8_node['metadata']['labels'].get('kubernetes.io/hostname')
            test_configs[f"{ctxt_name}_{dev_series}"] = local_test_config
    return test_configs

def build_deviceconfig_cr_template(init_test_config, gpu_cluster, gpu_nodes, ctxt_name, amdgpu_driver_spec):
    global Logger

    test_configs = {}
    local_test_config = copy.deepcopy(init_test_config)
    if amdgpu_driver_spec["driver-deployment"] == "inbox":
        local_test_config['driver.enable'] = False
        local_test_config['driver.version'] = "0.0"
        local_test_config['driver.blacklist'] = False
    else:
        local_test_config['driver.version'] = amdgpu_driver_spec["default-version"]
    local_test_config['metadata.name'] = f'deviceconfig-clusterwide'
    test_configs[ctxt_name] = local_test_config

    # TODO: Reimplement workflow where we can create multiple deviceconfig CRs
    """
        common_driver_options = get_common_amdgpu_driver(gpu_cluster.worker_nodes, gpu_nodes)
        if len(common_driver_options) > 0:
            # Chose one from the common-options
            selected_driver_version = next(iter(common_driver_options))
            local_test_config = copy.deepcopy(init_test_config)
            local_test_config['driver.version'] = selected_driver_version
            local_test_config['metadata.name'] = f'deviceconfig-clusterwide'
            test_configs[ctxt_name] = local_test_config
        else:
            test_configs = build_deviceconfigs_by_hostname(init_test_config, gpu_cluster, gpu_nodes, ctxt_name, driver_version)
    """
    return test_configs

