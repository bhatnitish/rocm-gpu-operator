# Driver Installation

After deploying the AMD GPU Operator and all dependencies successfully, users are ready to install AMD GPU drivers on worker nodes via the operator by creating the custom resource ```DeviceConfig``` to the Kubernetes cluster. 

1. Before installing the out-of-tree AMD GPU driver, users need to blacklist the inbox AMD GPU driver, on the worker nodes users need to create a file under ```/etc/modprobe.d/``` named ```blacklist-amdgpu.conf```, and the file should contain the command to blacklist amdgpu:
```
blacklist amdgpu
```
Rebooting the worker node is needed to apply the blacklist, after which users would see the inbox ```amdgpu``` kernel module has been blacklisted.

2. Users could save the custom resource into a YAML file and use ```kubectl apply -f deviceconfig.yaml``` to create the resource and trigger the operator to install drivers on worker nodes.

* DeviceConfig Example:
```
apiVersion: amd.com/v1alpha1
kind: DeviceConfig
metadata:
  name: test-deviceconfig
  # it is highly recommended to use the namespace where AMD GPU Operator is running
  namespace: kube-amd-gpu
spec:
  driver:
    # Specify driver image here
    # DO NOT include the image tag as AMD GPU Operator will automatically manage the image tag for you
    # e.g. docker.io/myUserName/amdgpu-driver
    image: my.registry.io/myUserName/myRepo

    # Specify the credential for your private registry if it requires credential to get pull/push access
    # you can create the docker-registry type secret by running command like:
    # kubectl create secret docker-registry mySecret -n KMM-NameSpace --docker-server=https://index.docker.io/v1/ --docker-username=xxx --docker-password=xxx
    # Make sure you created the secret within the namespace that KMM operator is running
    imageRegistrySecret:
      name: docker-auth

    # Specify the driver version
    # when you need to upgrade the driver, just update this field
    # we will unload the old version driver and load the new version driver
    version: "6.2.2"

  devicePlugin:
    # Specify the device plugin image
    # default value is rocm/k8s-device-plugin:latest
    devicePluginImage: rocm/k8s-device-plugin:latest

    # Specify the node labeller image
    # default value is rocm/k8s-device-plugin:labeller-latest
    nodeLabellerImage: rocm/k8s-device-plugin:labeller-latest

  # Specifythe node to be managed by this DeviceConfig Custom Resource
  selector:
    feature.node.kubernetes.io/amd-gpu: "true"
```

* ```metadata```: users could specify the name and namespace of the resource by themselves. Before creating the resource or patching the resource, it is highly recommended to check the existing ```DeviceConfig``` custom resources names by running ```kubectl get deviceconfigs -A``` in order to avoid the conflict.

* ```spec```:

    * ```driversImage```: users could specify a URL that points to their image registry + repository name to manage their AMD GPU driver images. Users don't need to specify the image tag in this field, as the operator will automatically handle the image tag naming for users.

    * ```imageRepoSecret```: the image registry specified in ```driversImage``` may requires username and password to get access to pulling / pushing image. Users could create credentials in the ```docker-registry``` type of Kubernetes secret and put the secret name in ```imageRepoSecret``` field. The example command to create the secret is: ```kubectl create secret docker-registry mySecret -n KMM-NameSpace --docker-server=https://index.docker.io/v1/ --docker-username=xxx --docker-password=xxx```

    * ```devicePluginImage```: users could specify the AMD GPU device plugin image, it is highly recommended to use latest ROCM official device plugin image ```rocm/k8s-device-plugin:latest```.

    * ```nodeLabellerImage```: users could specify the AMD GPU node labeller image, it is highly recommended to use latest ROCM official node labeller image ```rocm/k8s-device-plugin:labeller-latest```.

    * ```driversVersion```: users could choose which version of driver to be installed on worker nodes, the version should be a valid ROCM release version, e.g. ```6.1.3```. Users could visit https://rocm.docs.amd.com/en/latest/release/versions.html to get the full list of released ROCM versions.

    * ```metricsExporter```: Users could specify the metrics exporter config in these fields.
        * ```enable```: True or False, users could configure this field to enable/disable the metrics exporter, which is disabled by default.

        * ```serviceType```: Users could specify the kubernetes service type for metrics exporter, clusterIP(default) or NodePort.

        * ```nodePort```: Users could specify the node port for metrics exporter service's metrics endpoint, the exposed endpoint address would be ```$node-ip:$nodePort```.
  
    * ```selector```: Users could use selectors to specify which nodes would be managed by this custom resource. In the documentation we prepared default rule for Node Feature Dsicovery operator to detect AMD GPU PCI device on worker nodes and the detected label would be ```feature.node.kubernetes.io/amd-gpu: "true"```, it is recommended to use that label to select worker nodes, users could add more conditions to the selector.

3. After creating the ```DeviceConfig``` custom resource, if everything works as expected:
    * The ```amdgpu`` driver kernel module would be installed on all selected worker nodes
    * device plugin and node labeller pods would be brought up on the worker nodes where the driver installation was successful.
    * The installation status could be found in the status field of DeviceConfig resource. Use commands like ```kubectl get deviceconfigs test-deviceconfig -n kube-amd-gpu -oyaml``` to get the current status of DeviceConfig resource. The example status would be:
```
status:
  devicePlugin:
    availableNumber: 1             # number of nodes that has ROCM device plugin brought up successfully
    desiredNumber: 1               # number of nodes that is expected to deploy new ROCM device plugin
    nodesMatchingSelectorNumber: 1 # number of nodes selected by node selector
  driver:
    availableNumber: 1             # number of nodes that has amdgpu dirver installed successfully and managed by operator
    desiredNumber: 1               # number of nodes that is expected to deploy new amdgpu driver
    nodesMatchingSelectorNumber: 1 # number of nodes selected by node selector
  nodeModuleStatus:                # per node status of installing driver
    leto:                          # Node resource name
      containerImage: registry.test.pensando.io:5000/ubuntu:amdgpu-6.1.3-6.5.0-44-generic
      kernelVersion: 6.5.0-44-generic
      lastTransitionTime: 2024-08-12 12:37:03 +0000 UTC
```

!!! warning
    
    Uninstalling the AMD GPU driver by deleting the DeviceConfig requires all the resources when the same DeviceConfig got created, including the image registry, driver images, secret for the registry access. In that way, after the creation of DeviceConfig and successful installation of drivers, users need to make sure don't remove any driver image within the image registry, or any registry credential secret within the Kubernetes cluster. Any unexpected deletion of the resource could result in the failure of uninstalling the driver on worker nodes.






