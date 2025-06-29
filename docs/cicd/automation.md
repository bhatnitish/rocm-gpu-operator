# Functional Tests and CI/CD

## Functional Tests

Functional test cases are written in **Python**, using the **pytest** framework. These tests are located in the `tests/pytest` directory, accompanied by launcher scripts and a `requirements.txt` file for setting up the testing environment.

### Test Suite Modules

The test suite includes the following components:

- `metric-exporter`
- `test-runner`
- `gpu-operator`
- `amdgpu-driver`
- `node-labeller`

The test suite assumes a fully initialized and healthy **vanilla Kubernetes cluster**. Before executing the tests, ensure the following prerequisites are met:

### Prerequisites

1. A vanilla Kubernetes cluster with one or more nodes equipped with AMD GPUs.
2. An **image manifest** file specifying the container images to be used.  
   Example: `tests/pytest/release_v1.2.2_images.yaml`
3. A **secret** file (e.g., `secret.json`) to provide access credentials for any private/public image registries referenced in the manifest.

---

### Secrets

Access credentials required for pulling images from registries must be specified in a JSON-formatted secrets file.

```
{
    "secrets" : [
        {
            "name" : "my-secret",
            "server": "https://index.docker.io/v1/",
            "type" : "docker-registry",
            "namespace" : "kube-amd-gpu",
            "username" : "myusername",
            "password" : "mysecretpassword"
        }
    ]
}

This file will be used to create Kubernetes secrets, enabling the cluster to authenticate with image registries during test execution.

### Image Manifest

The target image is specified in a yaml file called image manifest file.

Example:
```
images:
    k8:
        driver:
            key         : driver.image
            location    : container://internal.registry:5000/amdgpu_drivers
            kind        : container

        gpu-operator:
            location    : repo://rocm.github.io/gpu-operator:gpu-operator-charts
            version     : v1.2.0
            kind        : helm-chart

        gpu-controller-manager:
            key         : controllerManager.manager.image
            location    : container://docker.io/rocm/gpu-operator
            version     : v1.2.0
            kind        : container
            secret      : my-secret

        device-metrics-exporter:
            key         : metricsExporter.image
            location    : container://docker.io/rocm/device-metrics-exporter
            version     : v1.2.0
            kind        : container
            secret      : my-secret

        test-runner:
            key         : testRunner.image
            location    : container://docker.io/rocm/test-runner
            version     : v1.2.0-beta.0
            kind        : container
            secret      : my-secret
        
        device-plugin:
            key         : devicePlugin.devicePluginImage
            location    : container://docker.io/rocm/k8s-device-plugin
            version     : latest
            kind        : container
            secret      : my-secret

        node-labeller:
            key         : devicePlugin.nodeLabellerImage
            location    : container://docker.io/rocm/k8s-device-plugin
            version     : labeller-latest
            kind        : container
            secret      : my-secret

        kmm-controller-manager-image-sign:
            key         : kmm.controller.manager.env.relatedImageSign
            location    : container://docker.io/rocm/kernel-module-management-signimage
            version     : v1.2.0
            kind        : container
            secret      : my-secret

        kmm-controller-manager-worker:
            key         : kmm.controller.manager.env.relatedImageWorker
            location    : container://docker.io/rocm/kernel-module-management-worker
            version     : v1.2.0
            kind        : container
            secret      : my-secret

        kmm-controller-manager:
            key         : kmm.controller.manager.image
            location    : container://docker.io/rocm/kernel-module-management-operator
            version     : v1.2.0
            kind        : container
            secret      : my-secret

        kmm-webhook-server:
            key         : kmm.webhookServer.webhookServer.image
            location    : container://docker.io/rocm/kernel-module-management-webhook-server
            version     : v1.2.0
            kind        : container
            secret      : my-secret
```

---
## Running Tests

Use the provided launcher script `k8_test_launcher.sh` to execute one or more test cases. The script supports various command-line options to customize the test run.

### Usage

```bash
./k8_test_launcher.sh [options]

Options:
  --help                      Display usage information
  --skip-kube-config          Skip Kubernetes config setup
  --secrets <file>            Path to secrets JSON file
  --image-manifest <file>     Path to image manifest YAML
  --module <module-name>      Specific test module to run (e.g., test_gpu_operator.py)
  --testcase <test-name>      Specific test case function to run (e.g., test_driver_installation)
  --testbed <file>            Path to testbed configuration YAML
  --debug                     Enable debug output
```

### Examples

```bash
./k8_test_launcher.sh \
  --secrets /path/to/secret.json \
  --image-manifest /path/to/image/manifest.yaml
```
