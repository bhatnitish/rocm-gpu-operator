"""
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
"""

import subprocess
import re
import time
import requests
import logging

logging.basicConfig(
    filename='../lib/amdgpuras_tests.log',  # Specify the log file name
    filemode='w',        # Use 'w' to overwrite the file each time, or 'a' to append
    level=logging.DEBUG, # Set the logging level
    format='%(asctime)s - %(levelname)s - %(message)s'  # Define the log message format
)

def is_amdgpuras_ready() -> bool:
    """
    Check if the amdgpuras tool is ready for injection commands.

    Returns:
        (bool): is amdgpuras Ready? False would indicate a driver issue and you ether need to wait for it to recover or reboot the system.
    """

    retval = subprocess.run("sudo amdgpuras -l".split(" "), capture_output=True)
    if retval.returncode == 0:
        return True
    else:
        return False

def decode_injection_type_string(type_string:str) -> int:
    """
    Converts the test type string from the amdgpuras list (-l) switch to the int that is compatible for the test type (-t) switch

    Parameters:
        type_string: The string from the amdgpuras -l command ue|ce|poison

    Returns:
        The -t integer for the test or None if the test type is not defined.
    """

    if type_string == "ce":
        return 2
    elif type_string == "ue":
        return 4
    elif type_string == "poison":
        return 8
    else:
        return None

def get_amdgpuras_valid_command_list() -> dict:
    """
    Analyzes the amdgpuras -l RAS device table and gives the full list of valid commands.

    Returns:
        Dictionary of valid commands as keys, and the list of parameters as the value.
    """

    def get_dict_depth(d:dict, level:int=1) -> int:
        if not isinstance(d, dict) or not d:
            return level
        return max(get_dict_depth(v, level + 1) for k, v in d.items())

    retval = subprocess.run("sudo amdgpuras -l".split(" "), capture_output=True)
    devices = re.split(r"\|-- Device\[(\d)]:", retval.stdout.decode("utf-8"))
    devices.pop(0) # Remove Header
    injection_table = dict()
    commands = dict()

    for device_index, device in enumerate(devices):
        if device_index % 2 == 0:
            blocks = re.split(r'\|\s{6}\|-- (\d{2}),', devices[device_index+1])
            blocks.pop(0) # Remove Header
            injection_table[int(device)] = dict()

            for block_index, block in enumerate(blocks):
                if block_index % 2 == 0:
                    subblocks = re.split(r'\|\s+\|\s+\|-- (\d{3}),', blocks[block_index+1])
                    subblocks.pop(0) # Remove Header
                    injection_table[int(device)][int(block)] = dict()

                    for subblock_index, subblock in enumerate(subblocks):
                        if subblock_index % 2 == 0:
                            # methods = re.split(r'\|\s+\|\s+\|\s+\|-- (\d{2}), (\w+)|(\w+)\((\w+)\)', subblocks[subblock_index+1])
                            methods = subblocks[subblock_index+1].split("\n")
                            if len(methods) > 2:
                                methods.pop(0) # Remove header
                                methods.pop(0) # Remove header
                                methods.pop(-1) # Remove Tail
                            else:
                                methods = []

                            injection_table[int(device)][int(block)][int(subblock)] = dict()

                            if int(block) == 7:
                                injection_table[int(device)][int(block)][int(subblock)] = [decode_injection_type_string('ue'), decode_injection_type_string('ce')]
                            elif int(block) == 3:
                                injection_table[int(device)][int(block)][int(subblock)] = [decode_injection_type_string('ue')]
                            else:
                                if len(methods) == 0:
                                    injection_table[int(device)][int(block)][int(subblock)] = [decode_injection_type_string('ue')]
                                else:
                                    for method in methods:
                                        items = re.findall(r'\|\s+\|\s+\|\s+\|-- (\d{2}), ([()\w]+)', method)
                                        for item in items:
                                            test_type = re.findall(r'\((\w+)\)', item[1])
                                            if len(test_type) > 0:
                                                injection_table[int(device)][int(block)][int(subblock)][int(item[0])] = [decode_injection_type_string(test_type[0])]
                                            else:
                                                injection_table[int(device)][int(block)][int(subblock)][int(item[0])] = [decode_injection_type_string('ue')]

    # Generate Commands from Injection Table
    for device in injection_table:
        for block in injection_table[device]:
            if block == 0:
                for subblock in injection_table[device][block]:
                    depth = get_dict_depth(injection_table[device][block][subblock])
                    if depth == 1:
                        for test_type in injection_table[device][block][subblock]:
                            commands[f"sudo /usr/bin/amdgpuras -d {device} -b {block} -s {subblock} -t {test_type} -a 0x800000000"] = [device, block, subblock, test_type]
                    else:
                        for method in injection_table[device][block][subblock]:
                            for test_type in injection_table[device][block][subblock][method]:
                                commands[f"sudo /usr/bin/amdgpuras -d {device} -b {block} -s {subblock} -m {method} -t {test_type} -a 0x800000000"] = [device, block, subblock, method, test_type]
            else:
                for subblock in injection_table[device][block]:
                    depth = get_dict_depth(injection_table[device][block][subblock])
                    if depth == 1:
                        for test_type in injection_table[device][block][subblock]:
                            commands[f"sudo /usr/bin/amdgpuras -d {device} -b {block} -s {subblock} -t {test_type}"] = [device, block, subblock, test_type]
                    else:
                        for method in injection_table[device][block][subblock]:
                            for test_type in injection_table[device][block][subblock][method]:
                                commands[f"sudo /usr/bin/amdgpuras -d {device} -b {block} -s {subblock} -m {method} -t {test_type}"] = [device, block, subblock, method, test_type]


    return commands

def is_amdgpuras_command_supported(cmd:str) -> bool:
    """
    Check if a command has as supported RAS device.

    Parameters:
        cmd: The command to check

    Returns:
        True if the command has as supported RAS device.
    """

    if cmd in get_amdgpuras_valid_command_list():
        return True
    else:
        return False

def get_afid_data(num_gpus:int=8) -> dict:
    """
    Queries amd-smi to get the currently reported AFID data

    Parameters:
        num_gpus: Total number of GPUs in system, assuming 8.

    Returns:
        AFID data structure.
    """

    afid_table = dict()

    for gpu in range(num_gpus):
        retval = subprocess.run(f"sudo amd-smi ras --cper --gpu={gpu} --folder .amdsmi_afid_temp", shell=True, stdout=subprocess.PIPE)
        afid_table[gpu] = re.findall(r'(\d{4}/\d{2}/\d{2}\s\d{2}:\d{2}:\d{2})\s+(\d{1,2})\s+([\w-]+)\s+([.\w-]+)\s+(\d{2})\n',retval.stdout.decode())

    return afid_table

def compute_afid_diff(initial_afid_data:dict) -> dict:
    """
    Returns only the AFIDs reported since the initial dataset was recorded.

    Parameters:
        initial_afid_data: An earlier AFID datastructure to compare against to compute changes since then.

    Returns:
        AFID data structure, excluding existing AFIDs from initial dataset.
    """
    final_afid_data = get_afid_data()

    afid_diff = dict()
    for gpu in range(8):
        afid_diff[gpu] = list(set(final_afid_data[gpu]) - set(initial_afid_data[gpu]))

    afid_table = dict()
    for gpu in afid_diff:
        afid_table[gpu] = list()
        for index, value in enumerate(afid_diff[gpu]):
            afid_table[gpu].append(value[-1])

    return afid_table

def get_dme_endpoint_address() -> str:
    """
    Gets the metrics exporter endpoints from the get kubectl get endpointsplce command

    Returns:
    metrics exporter endpoint IP:Port
    """
    if is_openshift():
        retval = subprocess.run("oc get endpointslice -n openshift-amd-gpu", shell=True, stdout=subprocess.PIPE)
    else:
        retval = subprocess.run("kubectl get endpointslice -n kube-amd-gpu", shell=True, stdout=subprocess.PIPE)

    dme_endpoints = re.findall(r'metrics-exporter-\w+\s+IPv4\s+(\d{4,6})\s+([\d.]+)\s+\w+\n', retval.stdout.decode())
    if len(dme_endpoints) > 1:
        print("More than one DME endpoint found")
        dme_endpoints = f"{dme_endpoints[0][1]}:{dme_endpoints[0][0]}"
    if len(dme_endpoints) == 1:
        dme_endpoints = f"{dme_endpoints[0][1]}:{dme_endpoints[0][0]}"
    if len(dme_endpoints) == 0:
        print("No DME endpoint found")
        return None
    return dme_endpoints

def get_afid_metrics_data() -> dict:
    """
    Gets the metrics AFID data from the metrics exporter Prometheus interface.

    Returns:
        metrics datastructure.
    """
    afid_metrics = dict()

    dme_address = get_dme_endpoint_address()

    if dme_address is not None:
        try:
            response = requests.get(f'http://{dme_address}/metrics')
            if response.status_code == 200:
                for line in response.text.splitlines():
                    if line[0] != "#":
                        results = re.findall(r'(\w+)\{(.+)}\s(\d+)',line)[0]
                        labels = dict()
                        value = results[2]
                        if results[0] == "gpu_afid_errors":
                            for label in results[1].split(','):
                                label = label.split('=')
                                labels[label[0]] = label[1].strip('"')
                            index = int(labels["gpu_id"])
                            afid_metrics[index] = dict()
                            afid_metrics[index]['labels'] = labels
                            afid_metrics[index]['value'] = value

        except requests.exceptions.RequestException as e:
            print(e)

    return afid_metrics

def get_ecc_metrics_data(num_gpus:int=8) -> dict:
    """
    Gets the metrics ECC data from the metrics exporter Prometheus interface.

    Returns:
        metrics datastructure.
    """
    ecc_metrics = dict()

    dme_address = get_dme_endpoint_address()

    if dme_address is not None:
        try:
            response = requests.get(f'http://{dme_address}/metrics')
            logging.info(f"[DME Curl Response] {response.status_code}")
            logging.info(f"\n{response.text}")
            logging.info("[Done]")

            if response.status_code == 200:
                for line in response.text.splitlines():
                    if line[0] != "#":
                        results = re.findall(r'(gpu_ecc\w+)\{(.+)}\s(\d+)',line)
                        if results:
                            label_table = dict()
                            labels = results[0][1].split(",")
                            for label in labels:
                                label = label.split('=')
                                label_table[label[0]] = label[1].strip('"')
                            if results[0][0] in ecc_metrics:
                                ecc_metrics[results[0][0]][int(label_table['gpu_id'])] = results[0][2]
                            else:
                                ecc_metrics[results[0][0]] = [None] * num_gpus
                                ecc_metrics[results[0][0]][int(label_table['gpu_id'])] = results[0][2]

        except requests.exceptions.RequestException as e:
            print(e)

    return ecc_metrics

def compute_ecc_metrics_diff(initial_metrics:dict) -> dict:
    diff = dict()
    current_metrics = get_ecc_metrics_data()

    for label in initial_metrics:
        if label in current_metrics:
            diff[label] = list(set(initial_metrics[label]).symmetric_difference(current_metrics[label]))

    return diff

def is_openshift() -> bool:
    oc_exists = subprocess.run('if command -v oc >/dev/null 2>&1; then echo "true"; fi', shell=True, stdout=subprocess.PIPE)
    if oc_exists.stdout.decode() == "true\n":
        return True
    else:
        return False

def get_metrics_exporter_pod() -> str:
    if is_openshift():
        pods = subprocess.run('oc get pods -n openshift-amd-gpu', shell=True, stdout=subprocess.PIPE)
    else:
        pods = subprocess.run('kubectl get pods -n kube-amd-gpu', shell=True, stdout=subprocess.PIPE)
    metrics_pod = re.findall(r'(.+-metrics-exporter-\w+)', pods.stdout.decode())
    if len(metrics_pod) == 1:
        return metrics_pod[0]
    elif len(metrics_pod) > 1:
        logging.info("Multiple metrics exporters detected, returned first.")
        return metrics_pod[0]
    else:
        return None

def get_amdsmi_table() -> str:
    if is_openshift():
        amd_smi_data = subprocess.run(f'oc exec {get_metrics_exporter_pod()} -n openshift-amd-gpu -- amd-smi metric --ecc-blocks', shell=True, stdout=subprocess.PIPE)
        ecc_table = amd_smi_data.stdout.decode()
    else:
        amd_smi_data = subprocess.run(f'kubectl exec {get_metrics_exporter_pod()} -n kube-amd-gpu -- amd-smi metric --ecc-blocks', shell=True, stdout=subprocess.PIPE)
        ecc_table = amd_smi_data.stdout.decode()

    gpus = re.split(r'GPU:\s\d\n\s+ECC_BLOCKS:\n', ecc_table)

    for gpu in gpus:
        blocks = re.split(r'(\w+):\n', gpu)

        for block in blocks[1:]:
            logging.info(f"GPU: {gpu}")
            logging.info(block)

    return ecc_table


if __name__ == "__main__":

    check_afids = False
    print_command_list = False

    if print_command_list:
        commands = get_amdgpuras_valid_command_list()

        for command in commands:
            print(command)

    if is_amdgpuras_ready() and check_afids:
        afid_start = get_afid_data()
        # TODO capture initial metrics exporter state for comparison post injection.

        # Run poison commands on each device, this should generate AFIDs and ECC counter increments
        print("Several 'Bus error' messages are expected as a result of error injection, please disregard.")
        for gpu in range(8):
            command = f"sudo amdgpuras -d {gpu} -b 2 -s 0 -m 0 -t 8"
            if is_amdgpuras_command_supported(command):
                subprocess.run(command, shell=True, stdout=subprocess.PIPE)
            else:
                print(f"'{command}' is not supported.")

        # Let system settle and gather new AFIDs since test start
        time.sleep(5)
        afid_table = compute_afid_diff(afid_start)
        # TODO capture metrics ECC counter changes.

        # Check if AFIDs reported by RAS match AFIDs from DME, if all are reported the test will pass.
        results = dict()
        test_passed = True
        afid_metrics_data = get_afid_metrics_data()
        for index, value in enumerate(afid_metrics_data):
            if afid_metrics_data[index]['value'] in afid_table[index]:
                results[index] = (afid_metrics_data[index]['value'], afid_table[index], "Match")
            else:
                results[index] = (afid_metrics_data[index]['value'], afid_table[index], "No Match")
                test_passed = False

        # Print results
        # TODO: use pytest logging capabilities to write results to disk.
        for result in results:
            print(results[result])
        print("AFID Test Passed" if test_passed else "AFID Test Failed")

    print(get_amdsmi_table())
    print(get_ecc_metrics_data())
