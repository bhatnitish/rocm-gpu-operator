# Driver Upgrade

After the installation of AMD GPU driver on worker nodes, users could choose to upgrade the driver to a new version by following these steps:

### 1. Check existing Node resource labels

After installing the drivers on selected worker nodes, the operator would automatically setup the driver version label on selected Node resource, it will be ```kmm.node.kubernetes.io/version-module.<deviceconfig-namespace>.<deviceconfig-name>=driverVersion``` and the Node resource labels could be queried by the commands like ```kubectl get node worker1 -o yaml```. For example, if users deployed the driver version 6.1.3 by using a DeviceConfig named test-device-config under kube-amd-gpu namespace, the label would be ```kmm.node.kubernetes.io/version-module.kube-amd-gpu.test-device-config=6.1.3```.

### 2. Update driver version on DeviceConfig

After verifying that all selected worker nodes have the version label configured properly, users could directly update the ```driversVersion``` field of the DeviceConfig custom resource. One example method to update the resource is to use command like ```kubectl edit deviceconfigs myDeviceConfig -n kube-amd-gpu``` then directly modify the YAML file and save it.

After modifying the ```driversVersion``` field, the operator will start to look for new version driver image within the image registry and determine the image exists or not based on image tag. The image tag name was determined by the worker nodes OS spec:

Example 1: Users select worker node with Ubuntu 22.04 + linux kernel ```6.8.0-40-generic``` and want to install driver with ROCM version 6.1.3, KMM would look for tag ```ubuntu-22.04-6.8.0-40-generic-6.1.3```

Example 2: Users select worker node with RedHat CoreOS 416.94 + linux kernel ```5.14.0-427.28.1.el9_4.x86_64``` and want to install driver with ROCM version 6.1.1, KMM would look for tag ```coreos-416.94-5.14.0-427.28.1.el9_4.x86_64-el9-6.1.1```

* If the new version driver image doesn't exist, the KMM operator would start to build the driver image within the cluster and once finished push the newly built image to user specified registry.

* If the new version driver image already exists, the image building will be skipped.

!!! warning
    After step 2 the DeviceConfig custom resource has been upgraded to new driver version. 
    During the driver upgrade of the cluster, if any worker node's ready status got reloaded (Ready -> NotReady -> Ready) unexpectedly (e.g. node reboot / networking issue) and that worker node's driver version label hasn't been updated to new version. 
    The old version driver won't be installed on the reloaded worker node. Users need to finish the upgrade steps on the reloaded worker node to install the new version driver.

### 3. Stop the workload on worker node

For each worker node that users want to upgrade the driver, users are responsible for stopping the workloads that are accessing the AMD GPU driver kernel module before unloading the old version driver.

### 4. Remove old driver version label from Node resource

After stopping all the AMD GPU driver related workloads, users could remove the label ```kmm.node.kubernetes.io/version-module.<deviceconfig-namespace>.<deviceconfig-name>=oldDriverVersion``` from Node resource. This step will trigger the uninstallation of the old version driver from the worker node.

### 5. Perform maintaince on the worker node

After uninstalling the old version driver kernel module from worker node, users could perform any additional maintainance of the worker node for the driver upgrade if it is required.

### 6. Add new driver version label to Node resource

Add the new driver version label ```kmm.node.kubernetes.io/version-module.<deviceconfig-namespace>.<deviceconfig-name>=newDriverVersion``` to the Node resource, where the ```newDriverVersion``` should be equal to the field ```driversVersion``` that has been updated in step 2. This step will trigger the installation of new version driver to the worker node.

!!! note
    If users don't need to perform any additional maintainance in step 5, step 5 can be skipped and step 4 and 6 can be merged, which means users could directly update the driver version label of the Node resource, instead of removing and recreating the label.

### 7. Bring up workload on worker node

After successfully installing the new version driver on worker node, users could bring up the AMD GPU related workload again on the worker node.

