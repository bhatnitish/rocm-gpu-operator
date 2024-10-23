# AMD GPU Operator Configuration Guide

The AMD GPU Operator is configured through a DeviceConfig custom resource that controls driver installation, GPU device plugin settings, metrics collection, and worker node selection. This guide provides detailed configuration options and examples.

## Checking Current Configuration

View existing DeviceConfig resources:

```bash
kubectl get deviceconfigs -A
```

View detailed configuration:

```bash
kubectl get deviceconfig <name> -n <namespace> -o yaml
```

## Configuration Parameters Reference

### Metadata Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `name` | Unique identifier for the resource | - |
| `namespace` | Namespace where the operator is running | - |

Example:

```yaml
apiVersion: amd.com/v1alpha1
kind: DeviceConfig
metadata:
  name: amd-gpu-config
  namespace: kube-amd-gpu
```

### Driver Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `driversImage` | Registry URL and repository (without tag) <br>*Note: Operator manages tags automatically* | - |
| `imageRepoSecret.name` | Name of registry credentials secret | - |
| `driversVersion` | ROCM driver version <br>*(e.g., "6.2.2")* <br>[See ROCM Versions](https://rocm.docs.amd.com/en/latest/release/versions.html) | - |

Example with private registry:

```yaml
spec:
  driver:
    driversImage: registry.example.com/amdgpu
    imageRepoSecret:
      name: registry-credentials
    driversVersion: "6.2.2"
```

Example with public registry:

```yaml
spec:
  driver:
    driversImage: docker.io/rocm/amdgpu
    driversVersion: "6.2.2"
```

### Device Plugin Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `devicePluginImage` | AMD GPU device plugin image | `rocm/k8s-device-plugin:latest` |
| `nodeLabellerImage` | Node labeller image | `rocm/k8s-device-plugin:labeller-latest` |

Example with custom images:

```yaml
spec:
  devicePlugin:
    devicePluginImage: custom-registry.com/device-plugin:v1.0.0
    nodeLabellerImage: custom-registry.com/node-labeller:v1.0.0
```

Example with defaults:

```yaml
spec:
  devicePlugin:
    devicePluginImage: rocm/k8s-device-plugin:latest
    nodeLabellerImage: rocm/k8s-device-plugin:labeller-latest
```

### Metrics Exporter Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `enable` | Enable/disable metrics exporter | `false` |
| `serviceType` | Service type for metrics endpoint <br>Options: "ClusterIP" or "NodePort" | `ClusterIP` |
| `nodePort` | Port number when using NodePort service type | - |

Example with ClusterIP:

```yaml
spec:
  metricsExporter:
    enable: true
    serviceType: "ClusterIP"
```

Example with NodePort:

```yaml
spec:
  metricsExporter:
    enable: true
    serviceType: "NodePort"
    nodePort: 31234
```

### Node Selection Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `selector` | Labels to identify nodes for driver installation | `feature.node.kubernetes.io/amd-gpu: "true"` |

Example with default selector:

```yaml
spec:
  selector:
    feature.node.kubernetes.io/amd-gpu: "true"
```

Example with custom selectors:

```yaml
spec:
  selector:
    feature.node.kubernetes.io/amd-gpu: "true"
    kubernetes.io/hostname: "gpu-node-1"
```

## Registry Authentication

### Creating Registry Secrets

If using a private registry, create a docker registry secret:

```bash
kubectl create secret docker-registry mySecret \
  -n KMM-NameSpace \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=xxx \
  --docker-password=xxx
```

Then reference it in the DeviceConfig:

```yaml
spec:
  driver:
    imageRepoSecret:
      name: mySecret
```

## Complete Configuration Example

Here's a complete DeviceConfig example combining all parameters:

```yaml
apiVersion: amd.com/v1alpha1
kind: DeviceConfig
metadata:
  name: amd-gpu-config
  namespace: kube-amd-gpu
spec:
  driver:
    driversImage: registry.example.com/amdgpu
    imageRepoSecret:
      name: registry-credentials
    driversVersion: "6.2.2"
    
  devicePlugin:
    devicePluginImage: custom-registry.com/device-plugin:v1.0.0
    nodeLabellerImage: custom-registry.com/node-labeller:v1.0.0
  
  metricsExporter:
    enable: true
    serviceType: "NodePort"
    nodePort: 31234
    
  selector:
    feature.node.kubernetes.io/amd-gpu: "true"
    kubernetes.io/hostname: "gpu-node-1"
```

## Configuration Validation

After applying configuration:

- Check DeviceConfig status:

```bash
kubectl get deviceconfig amd-gpu-config -n kube-amd-gpu -o yaml
```

- Verify driver deployment:

```bash
kubectl get pods -n kube-amd-gpu -l app=kmm-worker
```

- Check metrics endpoint (if enabled):

```bash
# For ClusterIP
kubectl port-forward svc/gpu-metrics -n kube-amd-gpu 9400:9400

# For NodePort
curl http://<node-ip>:<nodePort>/metrics
```

- Verify worker node labels:

```bash
kubectl get nodes -l feature.node.kubernetes.io/amd-gpu=true
```
