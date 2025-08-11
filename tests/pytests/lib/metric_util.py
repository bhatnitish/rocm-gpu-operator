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
from prometheus_client.parser import text_string_to_metric_families

Logger = logging.getLogger("lib.metricutil")

METRICS = [
    "gpu_average_package_power",
    "pcie_max_speed",
    "gpu_clock",
    "gpu_used_gtt",
    "gpu_used_vram",
    "gpu_vcn_activity",
    "gpu_umc_activity",
    "gpu_ecc_correct_athub",
    "gpu_edge_temperature",
    "gpu_energy_consumed",
    "gpu_free_gtt",
    "gpu_free_visible_vram",
    "gpu_free_vram",
    "gpu_gfx_activity",
    "gpu_gfx_voltage",
    "gpu_hbm_temperature",
    "gpu_jpeg_activity",
    "gpu_junction_temperature",
    "gpu_memory_temperature",
    "gpu_memory_voltage",
    "gpu_mma_activity",
    "gpu_nodes_total",
    "gpu_package_power",
    "gpu_power_usage",
    "gpu_total_gtt",
    "gpu_total_visible_vram",
    "gpu_total_vram",
    "gpu_ecc_correct_bif",
    "gpu_ecc_correct_gfx",
    "gpu_ecc_correct_hdp",
    "gpu_ecc_uncorrect_hdp",
    "gpu_ecc_uncorrect_sdma",
]

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

def parse_metric_data(http_response):
    global Logger
    metrics_content = http_response.decode('utf-8')
    metrics = {}
    for metrics_family in text_string_to_metric_families(metrics_content):
        for entry in metrics_family.samples:
            metrics[entry.name] = {
                'type' : metrics_family.type,
                'value' : entry.value,
                'labels' : entry.labels
            }
    return metrics

def health(port, node):
    ret_code, _, _ = node.http_get(port, "metrics")
    assert ret_code == 0, f"Failed to get metrics for {node.ip_address}"

def service_start(node):
    node.run_command("sudo systemctl start amd-metrics-exporter")
    
def service_stop(node):
    node.run_command("sudo systemctl stop amd-metrics-exporter")

def cleanup_cfg(node):
    node.run_command("sudo rm -rf /etc/metrics/")
