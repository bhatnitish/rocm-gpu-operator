# HTTP Proxy
 
AMD GPU Operator supports usage within a Kubernetes cluster behind the HTTP Proxy. Generally, the AMD GPU Operator requires Internet access for 2 things:

1. Pulling the component container images from the registry during the installation.
    
2. Downloading the AMD GPU driver installer from ROCM repository.

!!! note
    If users choose to use pre-compiled driver image, the 2nd Internet access requirement of downloading driver installer can be waived.

When users setting up a Kubernetes cluster with traffic redirected to a proxy server, ensure the Kubernetes nodes, container runtime, and GPU Operator pods are properly configured to apply the proxy network settings.

This document won't cover all the detailed steps about how to setup proxy network, configure OS level proxy configurationa and update the container runtime level networking settings, since those steps are not specific to the AMD GPU Operator. The rest of the document will show users the methods to inject the proxy configuration to AMD GPU Operator so that all the components images and driver installer can be downloaded successfully behind a HTTP proxy.

### Prerequisites

A Kubernetes cluster with configured with HTTP Proxy settings (container runtime should also be configured with HTTP proxy)


### Deploy with proxy configuration

#### Declarative configuration

In the helm chart config file ```values.yaml```, the proxy configuration is empty by default:
```
global:
  proxy:
    env: {}
```
Users could prepare ```values.yaml``` and added the following content to the yaml, then run helm install command with specifying the values YAML file. ```helm install test ./hpu-operator-helm-k8s-0.0.1.tgz -n testNamespace --create-namespace -f values.yaml```:
```
global:
  proxy:
    env:
      HTTP_PROXY: "http://myproxy.com:123"
      HTTPS_PROXY: "http://myproxy.com:234"
      NO_PROXY: "10.1.2.3,localhost"
      http_proxy: "http://myproxy.com:123"
      https_proxy: "http://myproxy.com:234"
      no_proxy: "10.1.2.3,localhost"
```

#### Imperative configuration
Users could also directly specify the config in an imperative way, by running helm install with ```--set``` options, for example:

```
helm install test ./hpu-operator-helm-k8s-0.0.1.tgz -n testNamespace --create-namespace \
--set global.proxy.env.HTTP_PROXY=http://myproxy.com:123  \
--set global.proxy.env.HTTPS_PROXY=http://myproxy.com:234 \
--set global.proxy.env.NO_PROXY="10.1.2.3\,localhost"     \
--set global.proxy.env.http_proxy=http://myproxy.com:123  \
--set global.proxy.env.https_proxy=http://myproxy.com:234 \
--set global.proxy.env.no_proxy="10.1.2.3\,localhost"
```

!!! note
    The Kubernetes cluster internal networking traffic may not need to visit the Internet and won't need to be proxied, please add ```NO_PROXY``` and ```no_proxy``` settings for the Kubernetes internal services and communications if necessary.



