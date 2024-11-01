- [HTTP Proxy](#http-proxy)
    - [Configuration Options](#configuration-options)
    - [Methods to Apply Proxy Settings](#methods-to-apply-proxy-settings)
    - [Method 1: Using `--set` with `helm install`](#method-1-using---set-with-helm-install)
    - [Method 2: Using a Custom `values.yaml` File](#method-2-using-a-custom-valuesyaml-file)
  - [Verifying Proxy Settings](#verifying-proxy-settings)

# HTTP Proxy

The AMD GPU Operator supports usage within a Kubernetes cluster behind an HTTP Proxy. Generally, the AMD GPU Operator requires Internet access for two reaons:

1. Pulling he container images from the registry during installation.
2. Downloading the AMD GPU driver installer.

!!! Note
    Downloading the driver installer (Step 2) can be skipped when using a [pre-compiled driver image](../drivers/precompiled-driver.md).

When users setting up a Kubernetes cluster with traffic redirected to a proxy server, ensure the Kubernetes nodes, container runtime, and GPU Operator pods are properly configured to apply the proxy network settings.

This document won't cover all the detailed steps about how to setup proxy network, configure OS level proxy configurationa and update the container runtime level networking settings, since those steps are not specific to the AMD GPU Operator. The rest of the document will show users the methods to inject the proxy configuration to AMD GPU Operator so that all the components images and driver installer can be downloaded successfully behind a HTTP proxy.

### Configuration Options

You can configure the following proxy settings:

- `HTTP_PROXY`: The HTTP proxy server URL
- `HTTPS_PROXY`: The HTTPS proxy server URL
- `NO_PROXY`: A comma-separated list of hostnames or IP addresses that should bypass the proxy

### Methods to Apply Proxy Settings

There are two ways to apply these proxy settings:

### Method 1: Using `--set` with `helm install`

You can specify the proxy settings directly in the `helm install` command using the `--set` flag.

```bash
helm install amd-gpu-operator rocm/gpu-operator-helm \
  --namespace kube-amd-gpu \
  --create-namespace \
  --set global.proxy.env.HTTP_PROXY=http://myproxy.com:123 \
  --set global.proxy.env.HTTPS_PROXY=http://myproxy2.com:234 \
  --set global.proxy.env.NO_PROXY="10.1.2.3\,localhost"
```

Note: When using `--set`, use `\,` to separate multiple values in the `NO_PROXY` setting.

### Method 2: Using a Custom `values.yaml` File

1. Create a Helm Charts values YAML file named `custom-values.yaml` with the following content included:

```yaml
global:
  proxy:
    env:
      HTTP_PROXY: "http://myproxy.com:123"
      HTTPS_PROXY: "http://myproxy2.com:234"
      NO_PROXY: "10.1.2.3,localhost"
```

1. Use this file when installing the Helm chart:

```bash
helm install amd-gpu-operator rocm/gpu-operator-helm \
  --namespace kube-amd-gpu \
  --create-namespace \
  -f custom-values.yaml
```

## Verifying Proxy Settings

After installation, you can verify the proxy settings by inspecting the environment variables of the deployed pods:

```bash
kubectl get pods -n kube-amd-gpu
kubectl exec -it <pod-name> -n kube-amd-gpu -- env | grep -i proxy
```

Replace `<pod-name>` with the name of one of the GPU Operator pods.
