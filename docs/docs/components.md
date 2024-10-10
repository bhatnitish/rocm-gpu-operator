# AMD GPU Operator Components

AMD GPU Operator and its dependencies consist of multiple components to achieve their functionalities.

### AMD GPU Operator Controller Manager
AMD GPU Operator controller manager is the controller for the operator's custom resource ```DeviceConfig```. It is responsible to run the reconcile loop for watching ```DeviceConfig``` resource event and perform corresponding action to adjust the cluster to the desired state of the custom resource.

From the ```DeviceConfig``` the controller would read the configuration and perform proper actions to trigger the AMD GPU driver kernel module installation / upgrade / uninstallation. When the driver was installed, the operator is also responsible for bringing up device plugin, node labeller and metrics exporter on the worker node so that the Kubernetes cluster could collect the system information from the driver-ready nodes.

### Node Feature Discovery Operator

[Node Feature Discovery Operator](https://github.com/kubernetes-sigs/node-feature-discovery) (NFD) is an operator for detecting hardware and system configurations for Kubernetes cluster. AMD GPU Operator is using it to detect the AMD GPU hardware by the PCI vendor ID and device ID. Once detected the worker node will be labeled with ```"feature.node.kubernetes.io/amd-gpu": "true``` so that the label could be utilized to select all the worker nodes with AMD GPU hardware.

!!! note
    For OpenShift cluster, AMD GPU Operator is using [OpenShift version NFD Operator](https://github.com/openshift/cluster-nfd-operator) which includes some optimization for OpenShift cluster from Red Hat to manipulate the Kubernetes-Sigs version NFD.

### Kernel Module Management Operator
[Kernel Module Management Operator](https://github.com/kubernetes-sigs/kernel-module-management) (KMM) is an operator for managing out-of-tree kernel module of Kubernetes cluster, providing the functionality of loading / upgrading / unloading host kernel module by the containerized working process. AMD GPU Operator is using the KMM Operator by preparing all the necessary Kubernetes resources (e.g. secrets, configmaps, service accounts, etc.) then manipulate the KMM Operator to do corresponding driver kernel module operations (load / upgrade / unload).

!!! note
    For vanilla Kubernetes cluster, AMD GPU Operator is using AMD optimized version KMM Operator. It is highly recommended to install KMM Operator from AMD GPU Operator helm chart instead of installing orignal Kubernetes-Sigs KMM Operator separately.
!!! note
    For OpenShift cluster, AMD GPU Operator is using [OpenShift version KMM Operator](https://github.com/rh-ecosystem-edge/kernel-module-management) which includes some optimization from Red Hat to provide better user experience on OpenShift cluster.

### AMD GPU Device Plugin
[AMD GPU Device Plugin](https://github.com/ROCm/k8s-device-plugin) is a [Kubernetes device plugin](https://kubernetes.io/docs/concepts/cluster-administration/device-plugins/) implementation that enables the registration of AMD GPU in a container cluster for compute workload. With the appropriate hardware and the plugin deployed in Kubernetes cluster, users will be able to run jobs that require AMD GPU.

### AMD GPU Node Labeller
[AMD GPU Node Labeller](https://github.com/ROCm/k8s-device-plugin/blob/master/cmd/k8s-node-labeller/README.md) is a tool that automatically labels nodes with GPU properties if a node has one or more AMD GPU installed. This tool leverage controller-runtime in the spirit of Custom Resource Definition (CRD) controller even though we do not define a Custom Resource.

### AMD GPU Deivce Metrics Exporter
[AMD GPU Device Metrics Exporter](https://github.com/pensando/device-metrics-exporter) is a tool that exports metrics from AMD GPUs to collectors like Prometheus.
