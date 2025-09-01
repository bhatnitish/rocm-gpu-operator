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
import logging
import json
from collections import defaultdict
from prometheus_client.parser import text_string_to_metric_families

Logger = logging.getLogger("lib.metricutil")

def get_label_details(version_string):
    global Logger
    with open('lib/files/label-support-matrix.json', 'r') as fp:
        label_data = json.load(fp)

    version = version_string.split('-', 1)[0]
    label_support_info = {}
    for label, info in label_data.items():
        min_version = info['min-version']
        if min_version > version:
            Logger.debug(f"skipping label : {label} with info: {info} for current-version : {version}")
            continue
        if info.get("eos-version", None) != None:
            eos_version = info["eos-version"]
            if version > eos_version:
                Logger.debug(f"skipping label : {label} with info: {info} for current-version : {version}")
                continue

        label_support_info[label] = info["mandatory"].get(version, "no")
    return label_support_info

def dump_metrics(http_response, out_file):
    metric_data = str(http_response)
    with open(out_file, "w") as fp:
        for line in metric_data.split('\\n'):
            fp.write(line.strip())
            fp.write("\n")
    return

def dump_all_samples(all_metrics, file_prefix):
    for idx, sample in enumerate(all_metrics):
        out_file = f"{file_prefix}_{idx}.output"
        dump_metrics(sample, out_file)
    return

def dump_json_samples(all_json_samples, file_prefix):
    for idx, sample in enumerate(all_json_samples):
        out_file = f"{file_prefix}_{idx}.json"
        with open(out_file, "w") as fp:
            json.dump(json.loads(sample.replace("'", "\"")), fp, indent=4)
    return

def parse_metric_data(http_response):
    global Logger
    metrics_content = http_response.decode('utf-8')
    metrics = defaultdict(list)
    for metrics_family in text_string_to_metric_families(metrics_content):
        for entry in metrics_family.samples:
            metrics[entry.name].append({
                'type' : metrics_family.type,
                'value' : entry.value,
                'labels' : entry.labels
            })
    return metrics

def get_supported_metrics(gpu_series = None):
    global Logger
    with open('lib/files/metrics-support.json', 'r') as fp:
        metrics_data = json.load(fp)

    if gpu_series:
        supported_metrics = []
        for entry in metrics_data['metrics']:
            for support in entry['gpu-support']:
                if support['gpu'] == gpu_series:
                    supported_metrics.append(entry)
        return supported_metrics
    return metrics_data['metrics']

def is_metric_supported(metric_to_test, gpu_series):
    global Logger

    supported_metrics = get_supported_metrics(gpu_series)

    for entry in supported_metrics:
        if entry['name'].lower() == metric_to_test.lower():
            return True
    return False

def get_metric_metadata(metric_to_test):
    global Logger

    all_metrics = get_supported_metrics()
    for entry in all_metrics:
        if entry['name'].lower() == metric_to_test.lower():
            return entry
    return None

def get_metric_support_info(metric_metadata, gpu_series):
    global Logger

    for support in metric_metadata['gpu-support']:
        if support['gpu'] == gpu_series:
            return support
    return None

def health(port, node):
    ret_code, _, _ = node.http_get(port, "metrics")
    assert ret_code == 0, f"Failed to get metrics for {node.ip_address}"

def service_start(node):
    node.run_command("sudo systemctl start amd-metrics-exporter")
    
def service_stop(node):
    node.run_command("sudo systemctl stop amd-metrics-exporter")

def cleanup_cfg(node):
    node.run_command("sudo rm -rf /etc/metrics/")
