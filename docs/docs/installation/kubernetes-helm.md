# Installing AMD GPU Operator on Kubernetes

This guide walks through installing the AMD GPU Operator on a Kubernetes cluster using Helm.

## Prerequisites

### System Requirements

- Kubernetes cluster v1.30.0 or later
- Helm v3.2.0 or later
- `kubectl` command-line tool
- Cluster admin privileges

### Cluster Requirements

- A functioning Kubernetes cluster with:
  - All system pods running and ready
  - Properly configured Container Network Interface (CNI)
  - Worker nodes with AMD GPUs

### Required Access

- Access to pull images from:
  - AMD's container registry or your configured registry
  - Public container registries (Docker Hub, Quay.io)

## Pre-Installation Steps

### 1. Verify Cluster Status

Check that your cluster is healthy and running:

```bash
kubectl get nodes
kubectl get pods -A
```

Expected output should show:

- All nodes in `Ready` state
- System pods running (kube-system namespace)
- CNI pods running (e.g., Flannel, Calico)

Example of a healthy cluster:

```bash
NAMESPACE      NAME                                          READY   STATUS    RESTARTS   AGE
kube-flannel   kube-flannel-ds-7krtk                         1/1     Running   0          10d
kube-system    coredns-7db6d8ff4d-644fp                      1/1     Running   0          2d20h
kube-system    kube-apiserver-control-plane                  1/1     Running   0          64d
kube-system    kube-controller-manager-control-plane         1/1     Running   0          64d
kube-system    kube-scheduler-control-plane                  1/1     Running   0          64d
```

### 2. Install Cert-Manager

The AMD GPU Operator requires cert-manager for TLS certificate management.

!!! note "Skip if Installed"
    If cert-manager is already installed in your cluster, you can skip this step.

- Add the cert-manager repository:

```bash
helm repo add jetstack https://charts.jetstack.io --force-update
```

- Install cert-manager:

```bash
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.15.1 \
  --set crds.enabled=true
```

- Verify the installation:

```bash
kubectl get pods -n cert-manager
```

Expected output:

```bash
NAME                                       READY   STATUS    RESTARTS   AGE
cert-manager-84489bc478-qjwmw             1/1     Running   0          2m
cert-manager-cainjector-7477d56b47-v8nq8  1/1     Running   0          2m
cert-manager-webhook-6d5cb854fc-h6vbk     1/1     Running   0          2m
```

## Installing AMD GPU Operator

### 1. Add the AMD Helm Repository

```bash
helm repo add amd https://rocm.github.io/gpu-operator
helm repo update
```

### 2. Install the Operator

Basic installation:

```bash
helm install amd-gpu-operator amd/gpu-operator-helm \
  --namespace kube-amd-gpu \
  --create-namespace
```

Installation with custom options:

```bash
helm install amd-gpu-operator amd/gpu-operator-helm \
  --namespace kube-amd-gpu \
  --create-namespace \
  --set driver.version=6.2.2 \
  --set image.tag=latest
```

!!! tip "Installation Options"
    - Skip NFD installation: `--set node-feature-discovery.enabled=false`
    - Skip KMM installation: `--set kmm.enabled=false`
    - See [Configuration Guide](../configuration.md) for more options

!!! warning "KMM Images"
    It is strongly recommended to use AMD-optimized KMM images included in the operator release.

### 3. Verify the Installation

Check that all operator components are running:

```bash
kubectl get pods -n kube-amd-gpu
```

Expected output:

```bash
NAMESPACE      NAME                                                  READY   STATUS    RESTARTS   AGE
gpu-operator   amd-gpu-operator-controller-manager-6954b68958-ljthg  1/1     Running   0          2m
gpu-operator   amd-gpu-kmm-controller-59b85d48c4-f2hn4               1/1     Running   0          2m
gpu-operator   amd-gpu-kmm-webhook-server-685b9db458-t5qp6           1/1     Running   0          2m
gpu-operator   amd-gpu-nfd-gc-98776b45f-j2hvn                        1/1     Running   0          2m
gpu-operator   amd-gpu-nfd-master-9948b7b76-ncvnz                    1/1     Running   0          2m
gpu-operator   amd-gpu-nfd-worker-dhl7q                              1/1     Running   0          2m
```

## Post-Installation Verification

### 1. Check Node Labels

Verify that GPU nodes are properly labeled:

```bash
kubectl get nodes -L feature.node.kubernetes.io/amd-gpu
```

### 2. Check Driver Status

Verify driver installation status:

```bash
kubectl get deviceconfigs -n kube-amd-gpu
```

### 3. Test GPU Detection

Create a simple test pod:

```yaml
apiVersion: v1
kind: Pod
metadata:
 name: amd-smi
spec:
 containers:
 - image: docker.io/rocm/pytorch:latest
   name: amd-smi
   command: ["/bin/bash"]
   args: ["-c","amd-smi version && amd-smi monitor -ptum"]
   resources:
    limits:
      amd.com/gpu: 1
    requests:
      amd.com/gpu: 1
 restartPolicy: Never
```

- Create the pod:

```bash
kubectl create -f amd-smi.yaml
```

- Check the logs and verify the output `amd-smi` reflects the expected ROCm version and GPU presence:

```bash
kubectl logs amd-smi
AMDSMI Tool: 24.6.2+2b02a07 | AMDSMI Library version: 24.6.2.0 | ROCm version: 6.2.2
GPU  POWER  GPU_TEMP  MEM_TEMP  GFX_UTIL  GFX_CLOCK  MEM_UTIL  MEM_CLOCK
  0  126 W     40 °C     32 °C       1 %    182 MHz       0 %    900 MHz
```

## Troubleshooting

If you encounter issues during installation:

- Check operator logs:

```bash
kubectl logs -n kube-amd-gpu \
  deployment/amd-gpu-operator-controller-manager
```

- Check KMM status:

```bash
kubectl get modules -n kube-amd-gpu
```

- Check NFD status:

```bash
kubectl get nodefeatures -n kube-amd-gpu
```

For more detailed troubleshooting steps, see our [Troubleshooting Guide](../troubleshooting.md).

## Uninstallation

To remove the operator and its components:

```bash
helm uninstall amd-gpu-operator -n kube-amd-gpu
```

To also remove cert-manager:

```bash
helm uninstall cert-manager -n cert-manager
kubectl delete namespace cert-manager
```
