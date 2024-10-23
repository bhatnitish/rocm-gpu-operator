# AMD GPU Driver Installation Guide

This guide explains how to install AMD GPU drivers using the AMD GPU Operator on Kubernetes clusters.

## Prerequisites

Before installing the AMD GPU driver:

1. Ensure the AMD GPU Operator and its dependencies are successfully deployed
2. Have cluster admin permissions
3. Have access to an image registry for driver images

## Installation Steps

### 1. Blacklist Inbox Driver

Before installing the out-of-tree AMD GPU driver, you must blacklist the inbox AMD GPU driver:

- Create blacklist configuration file on worker nodes:

```bash
echo "blacklist amdgpu" > /etc/modprobe.d/blacklist-amdgpu.conf
```

- Reboot the worker node to apply the blacklist
- Verify the blacklisting:

```bash
lsmod | grep amdgpu
```

This command should return no results, indicating the module is not loaded.

> **Note**: If `amdgpu` remains loaded after reboot, run `sudo update-initramfs -u` to update the initial ramdisk with the new modprobe configuration.

### 2. Create DeviceConfig Resource

Create a DeviceConfig custom resource to trigger the driver installation:

```yaml
apiVersion: amd.com/v1alpha1
kind: DeviceConfig
metadata:
  name: test-deviceconfig
  namespace: kube-amd-gpu  # Use AMD GPU Operator's namespace
spec:
  driver:
    # Specify driver image here without tag
    # AMD GPU Operator will automatically manage the image tag
    driversImage: registry.example.com/amdgpu:6.2.2-5.15.0-generic
    
    # Registry credentials secret (if required)
    imageRepoSecret:
      name: docker-auth
      
    # Specify the driver version
    driversVersion: "6.2.2"
    
  devicePlugin:
    # Device plugin image configuration
    devicePluginImage: rocm/k8s-device-plugin:latest
    nodeLabellerImage: rocm/k8s-device-plugin:labeller-latest
  
  metricsExporter:
    # Enable/disable metrics exporter (disabled by default)
    enable: false
    # Service type: ClusterIP (default) or NodePort
    serviceType: "ClusterIP"
    # Node port for metrics endpoint if using NodePort
    nodePort: 9400
    
  selector:
    feature.node.kubernetes.io/amd-gpu: "true"
```

#### Configuration Reference

To verify existing DeviceConfig resources run `kubectl get deviceconfigs -A`

#### Metadata Parameters

| Parameter | Description |
|-----------|-------------|
| `name` | Unique identifier for the resource |
| `namespace` | Namespace where the operator is running |

#### Driver Parameters

| Parameter | Description |
|-----------|-------------|
| `driversImage` | Registry URL and repository (without tag) <br>*Note: Operator manages tags automatically* |
| `imageRepoSecret.name` | Name of registry credentials secret |
| `driversVersion` | ROCM driver version (e.g., "6.2.2")<br>[See ROCM Versions](https://rocm.docs.amd.com/en/latest/release/versions.html) |

#### Device Plugin Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `devicePluginImage` | AMD GPU device plugin image | `rocm/k8s-device-plugin:latest` |
| `nodeLabellerImage` | Node labeller image | `rocm/k8s-device-plugin:labeller-latest` |

#### Metrics Exporter Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `enable` | Enable/disable metrics exporter | `false` |
| `serviceType` | Service type for metrics endpoint <br>Options: "ClusterIP" or "NodePort" | `ClusterIP` |
| `nodePort` | Port number when using NodePort service type | - |

#### Node Selection Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `selector` | Labels to identify nodes for driver installation | `feature.node.kubernetes.io/amd-gpu: "true"` |

### Registry Secret Configuration

If you're using a private registry, create a docker registry secret before deploying:

```bash
kubectl create secret docker-registry mySecret \
  -n KMM-NameSpace \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=xxx \
  --docker-password=xxx
```

### 3. Monitor Installation Status

Check the deployment status:

```bash
kubectl get deviceconfigs test-deviceconfig -n kube-amd-gpu -o yaml
```

Example status output:

```yaml
status:
  devicePlugin:
    availableNumber: 1             # Nodes with device plugin running
    desiredNumber: 1               # Target number of nodes
    nodesMatchingSelectorNumber: 1 # Nodes matching selector
  driver:
    availableNumber: 1             # Nodes with driver installed
    desiredNumber: 1               # Target number of nodes
    nodesMatchingSelectorNumber: 1 # Nodes matching selector
  nodeModuleStatus:
    worker-1:                      # Node name
      containerImage: registry.example.com/amdgpu:6.2.2-5.15.0-generic
      kernelVersion: 5.15.0-generic
      lastTransitionTime: "2024-08-12T12:37:03Z"
```

## Driver and Module Management

### Driver Uninstallation Requirements

- Keep all resources available when uninstalling drivers by deleting DeviceConfig:
  - Image registry access
  - Driver images
  - Registry credential secrets
- Removing any of these resources may prevent proper driver uninstallation

### Module Management

- The AMD GPU Operator must exclusively manage the `amdgpu` kernel module
- Do not manually load/unload the module
- All changes must be made through the operator
