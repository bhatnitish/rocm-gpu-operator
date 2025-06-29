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
import time
import logging
from lib import metric_util
from lib import deb_util

default_metric_port = 5000
deb_pkg_name = "amdgpu-exporter"

Logger = logging.getLogger("standalone.exporter")

def test_exporter_deploy(request, images, environment, gpu_cluster):
    for node in gpu_cluster.worker_nodes:
        metric_util.service_stop(node)
        deb_util.deb_uninstall(deb_pkg_name, node)
        metric_util.cleanup_cfg(node)
        deb_util.deb_install(images, node)
        metric_util.service_start(node)

    # sleep 10 second to ensure service is up
    time.sleep(10)
    for node in gpu_cluster.worker_nodes:
        Logger.info(f"Validate health on {node.ip_address}")
        metric_util.health(default_metric_port, node)

@pytest.mark.skip
def test_exporter_uninstall():
    pass
