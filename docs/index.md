# AMD GPU Operator Documentation

The AMD GPU Operator simplifies the deployment and management of AMD Instinct GPU accelerators within Kubernetes clusters. This project enables seamless configuration and operation of GPU-accelerated workloads, including machine learning, Generative AI, and other GPU-intensive applications.

## Features

- Automated driver installation and management
- Easy deployment of the AMD GPU device plugin
- Metrics collection and export
- Support for both vanilla Kubernetes and OpenShift environments
- Simplified GPU resource allocation for containers
- Automatic worker node labeling for GPU-enabled nodes

## Compatibility

- **Kubernetes**: 1.29.0+ or **OpenShift**: 4.16+
- Please refer to the [ROCM documentaiton](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) for the compatability matrix for the AMD GPU DKMS driver.

## Prerequisites

- Helm v3.2.0+
- `kubectl` or `oc` CLI tool configured to access your cluster

## Support

For bugs and feature requests, please file an issue on our [GitHub Issues](https://github.com/ROCm/gpu-operator/issues) page.
