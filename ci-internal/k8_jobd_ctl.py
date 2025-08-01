#!/usr/bin/python3

import os
import sys
import pdb
import json
import argparse
import subprocess
import shutil
import time
import docker


GlobalOptions = argparse.Namespace()

DOCKER_DAEMON_CONFIG = {
    "exec-opts": ["native.cgroupdriver=cgroupfs"],
    "log-driver": "json-file",
    "insecure-registries": ["registry.test.pensando.io:5000"],
    "log-opts": {
        "max-size": "100m",
        "max-file": "3"
    },
    "storage-driver": "overlay2"
}

def _init_cmdline_args():
    global GlobalOptions
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", help="jobd ctl commands")

    testbed_cmd = subparsers.add_parser("testbed", help="Testbed commands")
    testbed_cmd.add_argument("--testbed", required = True, help = "jobd testbed json file")
    testbed_cmd.add_argument("--fetch-kube-config", action='store_true', default=False, help = "Optionally download /etc/kubernetes/config file from master")
    testbed_cmd.add_argument("--reboot-workers", action='store_true', default=False, help = "Reboot worker nodes")
    testbed_cmd.add_argument("--testbed-yaml", default=None, help = "path to testbed yaml to be generated")

    image_cmd = subparsers.add_parser("image", help="Image management commands")
    image_cmd.add_argument("--testbed", required = True, help = "jobd testbed json file")
    image_cmd.add_argument("--load-images", action='store_true', default=False, help = "Load images into the registry")
    image_cmd.add_argument("--setup-insecure-registry", action='store_true', default=False, help = "Load images into the registry")
    image_cmd.add_argument("--registry", default=None, help = "Destination Registry")
    image_cmd.add_argument("--image-manifest", default='/tmp/images.yaml', help = "output images yaml")
    cmd_opts = parser.parse_args()
    GlobalOptions.__dict__.update(cmd_opts.__dict__)
    return parser

def _load_testbed_json(testbed_json):
    if testbed_json:
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
            return result
        except UnexpectedExit as ue:
            return ue.result
        except CommandTimedOut as to:
            return to.result
    raise Exception(f"Failed to connect to node : {node}")

def put(node, src_file, dest_file, sudo = False, timeout = 90):
    from fabric import Connection
    from invoke.exceptions import UnexpectedExit
    from invoke.exceptions import CommandTimedOut

    conn_kwargs = {
        "password" : node["password"],
    }
    with Connection(node["ip"], user = node["username"], connect_kwargs = conn_kwargs) as conn:
        try:
            dest_tmp_file = os.path.join("/tmp", os.path.basename(dest_file))
            con.put(src_file, dest_tmp_file)
            cp_cmd = []
            if sudo:
                cp_cmd.append("sudo")
            cp_cmd.extend(["cp", dest_tmp_file, dest_file])
            result = conn.run(cp_cmd.join(" "), hide = True, in_stream=False, timeout = timeout)
            return result
        except UnexpectedExit as ue:
            return ue.result
        except CommandTimedOut as to:
            return to.result
    raise Exception(f"Failed to connect to node : {node}")

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
        result = run_command(master, " ".join(cmd))
        if result.return_code != 0:
            return result.return_code, None
        k8_node_info = json.loads(result.stdout)
        return 0, k8_node_info
    else:
        cmd = ["kubectl", "get", "nodes", "-ojson"]
        result = run_command(master, " ".join(cmd))
        if result.return_code != 0:
            return result.return_code, None
        k8_nodes_info = json.loads(result.stdout)
        return 0, k8_nodes_info.get("items", None)

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
    result = run_command(master, " ".join(cmd))
    if result.return_code == 0:
        print(f"{msg}, successful")
    else:
        print(f"{msg}, failed")
    return result.return_code

def _reboot_node(master, worker, worker_nodename):
    cmd = ["sudo", "reboot"]
    print(f"Rebooting worker node : {worker_nodename}")
    try:
        result = run_command(worker, " ".join(cmd))
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
    countdown = 100
    for _ in range(100):
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
                    return True
    print(f"Failed to connect to worker-node {worker_nodename} post reboot")
    return False
        
def _fetch_kube_config(master):
    cmd = ["sudo", "cp", "/etc/kubernetes/admin.conf", "/tmp/config"]
    result = run_command(master, " ".join(cmd))
    if result.return_code != 0:
        print("Failed to copy /etc/kubernetes/admin.conf to /tmp folder")
        return False

    cmd = ["sudo", "chmod", "755", "/tmp/config"]
    result = run_command(master, " ".join(cmd))
    if result.return_code != 0:
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
                ret = _wait_node_ready(master, worker_nodename)
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

def _load_images(registry, image_manifest):
    if not registry:
        return False

    result = True
    # Load /gpu-operator/ci-internal/sanity-images.yml
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(sequence=4, offset=2)

    template_file = f'/gpu-operator/ci-internal/sanity-images.yml'
    with open(template_file, 'r') as fp:
        image_manifest_templ = yaml.load(fp)

    client = docker.from_env(timeout=300)
    for artifact_name, artifact_info in image_manifest_templ['images']['k8'].items():
        print(f"Processing {artifact_name} section")
        if artifact_info.get('image', None) != None:
            image_file = artifact_info['image']
            if not os.path.exists(image_file):
                print(f"Fatal Error: Specified image-file {image_file} missing")
                result = False
                continue

            if artifact_info['kind'] == 'helm-chart':
                artifact_info['location'] = f"file://{image_file}"
                artifact_info['version'] = 'sanity' # TODO derive correct version for each artifact
            elif artifact_info['kind'] == 'container':
                try:
                    with open(image_file, 'rb') as fp:
                        loaded_images = client.images.load(fp)
                    if not loaded_images:
                        result = False
                        print(f"Fatal Error: Failed to collect loaded-images information, image-file : {image_file}")
                        continue
                except docker.errors.APIError as de:
                    print(f"Fatal Error: Unable to load image {image_file}, error : {de}")
                    result = False
                    continue
                except Exception as e:
                    print(f"Fatal Error: Unknown error while loading image {image_file}, error : {e}")
                    result = False
                    continue

                loaded_image = loaded_images[0]
                loaded_image_id = loaded_image.id
                loaded_image_tag = loaded_image.tags[0]
                _, image_ver = loaded_image_tag.split('/', 1)
                image_name, image_tag = image_ver.split(':')

                # Push tag to specified registry
                tag = "sanity"
                # TODO: Replace tag with metadata-derived version information, currently using common tag=sanity
                loaded_image.tag(repository = f"{registry}/rocm/{image_name}", tag = tag)
                new_image = f"{registry}/rocm/{image_name}"

                try:
                    resp = client.images.push(f"{new_image}:{tag}", stream=True, decode=True)
                except docker.errors.APIError as de:
                    print(f"Fatal Error: Unable to tag image {image_file}, error : {de}")
                    result = False
                    continue
                except Exception as e:
                    print(f"Fatal Error: Unknown error while tagging image {image_file}, error : {e}")
                    result = False
                    continue
                artifact_info['location'] = f"container://{new_image}"
                artifact_info['version'] = tag
    if result:
        with open(image_manifest, 'w') as fp:
            yaml.dump(image_manifest_templ, fp)
    return result

def _upload_docker_daemon_conf(registry, testbed_info):
    # Generate/Update /etc/docker/daemon.json file
    daemon_conf = DOCKER_DAEMON_CONFIG
    daemon_conf["insecure-registries"].append(registy)
    with open("docker_daemon.json", "w") as fp:
        json.dump(daemon_conf, indent=4)

    masters = _get_master_nodes(testbed_info)
    workers = _get_worker_nodes(testbed_info)
    cmd = ["sudo", "systemctl", "restart", "docker"]
    for node in masters + workers:
        result = put(node, "docker_daemon.json" "/etc/docker/daemon.json", sudo = True) 
        if result.return_code != 0:
            print(f"Failed to upload docker_daemon.json to /etc/docker/daemon.json for node {node}")
            return -1
        result = run_command(node, " ".join(cmd))
        if result.return_code != 0:
            print("Failed restart docker daemon")
            return -1
    return 0

def _run_testbed_commands():
    if GlobalOptions.fetch_kube_config:
        testbed_info = _load_testbed_json(GlobalOptions.testbed)
        if testbed_info:
            masters = _get_master_nodes(testbed_info)
            workers = _get_worker_nodes(testbed_info)
            print(f"Found {len(masters)} master(s) and {len(workers)} workers in the k8-cluster")
        else:
            print(f"Failed to load testbed.json file {GlobalOptions.testbed} - Abort")
            sys.exit(1)
        if masters and _fetch_kube_config(masters[0]):
            print("Successfully downloaded /etc/kubernetes/admin.conf file")
        else:
            print("Failed to download /etc/kubernetes/admin.conf file - Abort")
            sys.exit(1)

    if GlobalOptions.reboot_workers:
        testbed_info = _load_testbed_json(GlobalOptions.testbed)
        if testbed_info:
            masters = _get_master_nodes(testbed_info)
            workers = _get_worker_nodes(testbed_info)
            print(f"Found {len(masters)} master(s) and {len(workers)} workers in the k8-cluster")
        else:
            print(f"Failed to load testbed.json file {GlobalOptions.testbed} - Abort")
            sys.exit(1)
        if workers and _reboot_workers(masters[0], workers):
            print("Successfully rebooted all worker nodes - cluster is ready to use")
        else:
            print("Failed to reboot all worker nodes - test-result could be unreliable")
            sys.exit(1)

    if GlobalOptions.testbed_yaml:
        testbed_info = _load_testbed_json(GlobalOptions.testbed)
        if testbed_info:
            masters = _get_master_nodes(testbed_info)
            workers = _get_worker_nodes(testbed_info)
            print(f"Found {len(masters)} master(s) and {len(workers)} workers in the k8-cluster")
        else:
            print(f"Failed to load testbed.json file {GlobalOptions.testbed} - Abort")
            sys.exit(1)
        if _generate_testbed_yaml(testbed_info, GlobalOptions.testbed_yaml):
            print(f"Successfully generated testbed-yaml - {GlobalOptions.testbed_yaml}")
        else:
            print(f"Failed to genreate testbed-yaml file")
            sys.exit(1)

def _run_image_commands():
    if GlobalOptions.load_images:
        if _load_images(GlobalOptions.registry, GlobalOptions.image_manifest):
            print(f"Images loaded to specified registry, Successfully generated image-manifest - {GlobalOptions.image_manifest}")
        else:
            print(f"Failed to load images into the registry: {GlobalOptions.registry}")
            sys.exit(1)
    if GlobalOptions.setup_insecure_registry:
        testbed_info = _load_testbed_json(GlobalOptions.testbed)
        if _upload_docker_daemon_conf(GlobalOptions.registry, testbed_info):
            print("Successfully uploaded new /etc/docker/daemon.json to all nodes")
        else:
            print(f"Failed to upload /etc/docker/daemon.json to all nodes")
            sys.exit(1)

def main():
    parser = _init_cmdline_args()

    if GlobalOptions.command == 'testbed':
        _run_testbed_commands()
    elif GlobalOptions.command == 'image':
        _run_image_commands()
    else:
        parser.print_help()
    return


if __name__ == '__main__':
    main()
