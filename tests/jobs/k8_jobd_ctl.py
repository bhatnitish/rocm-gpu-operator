#!/usr/bin/python3

import os
import sys
import pdb
import json
import argparse
import shutil
import time


def _init_cmdline_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--testbed", required=True, default = "/warmd.json", help = "jobd testbed json file")
    parser.add_argument("--fetch-kube-config", action='store_true', default=False, help = "Optionally download /etc/kubernetes/config file from master")
    parser.add_argument("--reboot-workers", action='store_true', default=False, help = "Reboot worker nodes")
    parser.add_argument("--generate-testbed-yaml", action='store_true', default=False, help = "Generate testbed yaml")
    args = parser.parse_args()
    return args

def _load_testbed_json(testbed_json):

    with open(testbed_json, "r") as fp:
        data = json.load(fp)

    if "Instances" in data:
        testbed_info = data["Instances"][0]["RawJSON"]
        return testbed_info
    return None

def run_command(node, cmd, timeout = 90):
    from fabric import Connection
    from invoke.exceptions import UnexpectedExit
    from invoke.exceptions import CommandTimedOut

    conn_kwargs = {
        "password" : node["password"],
    }
    with Connection(node["ip"], user = node["username"], connect_kwargs = conn_kwargs) as conn:
        try:
            result = conn.run(cmd, hide = True, in_stream=False, timeout = timeout)
            return result.return_code, result.stdout, result.stderr
        except UnexpectedExit as ue:
            return ue.result.exited, ue.result.stdout, ue.result.stderr
        except CommandTimedOut as to:
            return to.result.exited, to.result.stdout, to.result.stderr
    return -1, "", ""

def get(node, remote_file, local_file):
    from fabric import Connection
    from invoke.exceptions import UnexpectedExit
    from invoke.exceptions import CommandTimedOut

    conn_kwargs = {
        "password" : node["password"],
    }

    if not os.path.exists(os.path.dirname(local_file)):
        os.makedirs(os.path.dirname(local_file))
    
    with Connection(node["ip"], user = node["username"], connect_kwargs = conn_kwargs) as conn:
        try:
            conn.get(remote_file, local_file)
            return True
        except:
            print(f"Failed to download file {remote_file}")
    return False

def k8_get_node_info(master, node_name = None):
    if node_name:
        cmd = ["kubectl", "get", "node", node_name, "-ojson"]
        ret_code, resp_stdout, resp_stderr = run_command(master, " ".join(cmd))
        if ret_code != 0:
            return ret_code, None
        k8_node_info = json.loads(resp_stdout)
        return ret_code, k8_node_info
    else:
        cmd = ["kubectl", "get", "nodes", "-ojson"]
        ret_code, resp_stdout, resp_stderr = run_command(master, " ".join(cmd))
        if ret_code != 0:
            return ret_code, None
        k8_nodes_info = json.loads(resp_stdout)
        return ret_code, k8_nodes_info.get("items", None)

def k8_get_worker_nodename(master, worker_ip):
    ret_code, items = k8_get_node_info(master)
    if ret_code != 0:
        print("Failed to retrieve node information from k8 cluster")
        return None
    for node_info in items:
        addresses = node_info["status"]["addresses"]
        for entry in addresses:
            if entry["address"] == worker_ip:
                return node_info["metadata"]["name"]
    return None

def _get_master_nodes(testbed_info):
    """
    {
        "name": "mi200-testbed",
        "deployment": "k8",
        "instances": [
            {
                "ip": "10.11.78.80",
                "type": "master",
                "username": "vm",
                "password": "vm",
                "registry": "yes"
            },
            {
                "ip": "10.11.130.28",
                "type": "worker",
                "username": "vm",
                "password": "vm",
                "gpu_series": "MI200",
                "gpu_count": 1
            }
        ]
    }
    """
    master_nodes = list(filter(lambda x: x["type"] == "master", testbed_info["instances"]))
    return master_nodes

def _get_worker_nodes(testbed_info):
    """
    {
        "name": "mi200-testbed",
        "deployment": "k8",
        "instances": [
            {
                "ip": "10.11.78.80",
                "type": "master",
                "username": "vm",
                "password": "vm",
                "registry": "yes"
            },
            {
                "ip": "10.11.130.28",
                "type": "worker",
                "username": "vm",
                "password": "vm",
                "gpu_series": "MI200",
                "gpu_count": 1
            }
        ]
    }
    """
    worker_nodes = list(filter(lambda x: x["type"] == "worker", testbed_info["instances"]))
    return worker_nodes

def _cordon_uncordon_node(master, worker_nodename : str, cordon : bool):
    if cordon:
        cmd = ["kubectl", "cordon", worker_nodename]
        msg = f"Cordoning node {worker_nodename}"
    else:
        cmd = ["kubectl", "uncordon", worker_nodename]
        msg = f"Uncordoning node {worker_nodename}"
    ret_code, resp_stdout, resp_stderr = run_command(master, " ".join(cmd))
    if ret_code == 0:
        print(f"{msg}, successful")
    else:
        print(f"{msg}, failed")
    return ret_code

def _reboot_node(master, worker, worker_nodename):
    cmd = ["sudo", "reboot"]
    print(f"Rebooting worker node : {worker_nodename}")
    try:
        ret_code, _, _ = run_command(worker, " ".join(cmd))
    except:
        pass # Ignore timeout based errors
    while True:
        ret_code, node_info = k8_get_node_info(master, worker_nodename)
        if ret_code != 0:
            print("Failed to retrieve node information from k8 cluster")
            return
        conditions = node_info["status"]["conditions"]
        for entry in conditions:
            if entry["type"] == "Ready":
                """
                {
                    "lastHeartbeatTime": "2025-06-20T07:23:15Z",
                    "lastTransitionTime": "2025-06-20T07:26:48Z",
                    "message": "Kubelet stopped posting node status.",
                    "reason": "NodeStatusUnknown",
                    "status": "Unknown",
                    "type": "Ready"
                }
                """
                if entry["status"] == "Unknown":
                    print(f"Worker node : {worker_nodename} is offline")
                    return
                elif entry["status"] == "True":
                    time.sleep(10)
    return

def _wait_node_ready(master, worker_nodename):
    print(f"Waiting for worker-node {worker_nodename} to come online")
    while True:
        ret_code, node_info = k8_get_node_info(master, worker_nodename)
        if ret_code != 0:
            print("Failed to retrieve node information from k8 cluster")
            return
        conditions = node_info["status"]["conditions"]
        for entry in conditions:
            if entry["type"] == "Ready":
                """
                {
                    "lastHeartbeatTime": "2025-06-20T07:23:15Z",
                    "lastTransitionTime": "2025-06-20T07:26:48Z",
                    "message": "Kubelet stopped posting node status.",
                    "reason": "NodeStatusUnknown",
                    "status": "Unknown",
                    "type": "Ready"
                }
                """
                if entry["status"] == "Unknown":
                    time.sleep(20)
                elif entry["status"] == "True":
                    print(f"Worker-node {worker_nodename} is online")
                    return
    return
        
def _fetch_kube_config(master):
    cmd = ["sudo", "cp", "/etc/kubernetes/admin.conf", "/tmp/config"]
    ret_code, _, _ = run_command(master, " ".join(cmd))
    if ret_code != 0:
        print("Failed to copy /etc/kubernetes/admin.conf to /tmp folder")
        return False

    cmd = ["sudo", "chmod", "755", "/tmp/config"]
    ret_code, _, _ = run_command(master, " ".join(cmd))
    if ret_code != 0:
        print("Failed enable read/write permission to /tmp/config")
        return False

    dest_file = os.path.join(os.getenv("HOME"), ".kube", "config")
    get(master, "/tmp/config", dest_file)
    os.system(f"chmod 600 {dest_file}")
    return True

def _reboot_workers(master, workers):
    ret = True
    for worker in workers:
        node_ip = worker["ip"]
        worker_nodename = k8_get_worker_nodename(master, node_ip)
        if worker_nodename:
            if _cordon_uncordon_node(master, worker_nodename, True) == 0:
                _reboot_node(master, worker, worker_nodename)
                time.sleep(180)
                _wait_node_ready(master, worker_nodename)
            else:
                ret = False
            if _cordon_uncordon_node(master, worker_nodename, False) != 0:
                ret = False
        else:
            print(f"No such node found with ip-address {node_ip}")
            ret = False
    return ret

def _generate_testbed_yaml(testbed_info, file_name):
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(sequence=4, offset=2)

    with open(file_name, 'w') as fp:
        yaml.dump(testbed_info, fp)
    return True

def main():
    args = _init_cmdline_args()

    testbed_info = _load_testbed_json(args.testbed)
    if testbed_info:
        masters = _get_master_nodes(testbed_info)
        workers = _get_worker_nodes(testbed_info)
        print(f"Found {len(masters)} master(s) and {len(workers)} workers in the k8-cluster")
        if masters and args.fetch_kube_config:
            if _fetch_kube_config(masters[0]):
                print("Successfully downloaded /etc/kubernetes/admin.conf file")
            else:
                print("Failed to download /etc/kubernetes/admin.conf file - Abort")
                sys.exit(1)

        if workers and args.reboot_workers:
            if _reboot_workers(masters[0], workers):
                print("Successfully rebooted all worker nodes - cluster is ready to use")
            else:
                print("Failed to reboot all worker nodes - test-result could be unreliable")

        if args.generate_testbed_yaml:
            dest_file = _generate_testbed_yaml(testbed_info, "testbed.yaml")
            if dest_file:
                print(f"Successfully generated testbed-yaml : {dest_file}")
            else:
                print(f"Failed to genreate testbed-yaml file")
    else:
        print(f"Failed to parse/extract testbed information from input file {args.testbed}")
        sys.exit(1)
    return


if __name__ == '__main__':
    main()
    sys.exit(0)
