# Prepare Pre-compiled AMD GPU Driver Kernel Module Image

## Background
* AMD GPU Operator is targeting for deploying AMD GPU driver kernel module on worker nodes within Kubernetes-based cluster and it is using Kernel Module Management (KMM) Operator as dependency to achieve its functionalities.

* Different worker node may have different Operating System installed, such as different Linux distro, OS release version and kernel version, etc. 

* For worker nodes with any specific combination of OS spec (e.g. Ubuntu 22.04 6.8.0-40-generic), it would require the incoming kernel module built by exactly the same environment, to make sure the kernel module could be loaded successfully.

* AMD GPU Operator will select the worker nodes based on user input selector, then read their OS info and get all combinations of these specs then submit the information to KMM.

```
Linux distros
OS release version
Kernel version 
```

* KMM will read through all the combinations of aforementioned system spec, plus user asked AMD GPU driver version, to check whether corresponding driver image exists or not in the registry based on image tag.

    * Example 1: Users select worker node with Ubuntu 22.04 + linux kernel ```6.8.0-40-generic``` and want to install driver with ROCM version 6.1.3, KMM would look for tag ```ubuntu-22.04-6.8.0-40-generic-6.1.3```
    * Example 2: Users select worker node with RedHat CoreOS 416.94 + linux kernel ```5.14.0-427.28.1.el9_4.x86_64``` and want to install driver with ROCM version 6.1.1, KMM would look for tag ```coreos-416.94-5.14.0-427.28.1.el9_4.x86_64-el9-6.1.1```

* There are 2 situations that the driver image could exist or doesn't exist when users push the custom resource to the Kubernetes cluster:
    * If the driver image tag doesn't exist, KMM would build the driver image within the cluster, by using AMD GPU Operator pre-defined Dockerfile. After the image build the image would be used to install the driver kernel module.
    * If the driver image tag already exists, KMM would directly pull the existing driver image within the worker pod and install the driver kernel module within the driver image.

* Users could prepare / download the pre-compiled AMD GPU driver image and tag them properly to let the operator directly pick up the existing driver image, then skip building the driver image.

## How to Prepare Pre-compiled image

Here is a Dockerfile example of building AMD GPU driver image, the eaxct steps may differ for other linux distros / release version:
```
FROM ubuntu:$$VERSION as builder

ARG KERNEL_FULL_VERSION

ARG DRIVERS_VERSION

ARG REPO_URL

RUN apt-get update && apt-get install -y bc \
    bison \
    flex \
    libelf-dev \
    gnupg \
    wget \
    git \
    make \
    gcc \
    linux-headers-${KERNEL_FULL_VERSION} \
    linux-modules-extra-${KERNEL_FULL_VERSION}

RUN mkdir --parents --mode=0755 /etc/apt/keyrings

RUN wget ${REPO_URL}/rocm/rocm.gpg.key -O - | \
    gpg --dearmor | tee /etc/apt/keyrings/rocm.gpg > /dev/null

RUN echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] ${REPO_URL}/amdgpu/${DRIVERS_VERSION}/ubuntu $$DRIVER_LABEL main" \
    | tee /etc/apt/sources.list.d/amdgpu.list
RUN apt-get update && apt-get install -y amdgpu-dkms

RUN depmod ${KERNEL_FULL_VERSION}

FROM ubuntu:$$VERSION

ARG KERNEL_FULL_VERSION

RUN apt-get update && apt-get install -y kmod
RUN mkdir -p /opt/lib/modules/${KERNEL_FULL_VERSION}/updates/dkms/
COPY --from=builder /lib/modules/${KERNEL_FULL_VERSION}/updates/dkms/amd* /opt/lib/modules/${KERNEL_FULL_VERSION}/updates/dkms/
COPY --from=builder /lib/modules/${KERNEL_FULL_VERSION}/modules.* /opt/lib/modules/${KERNEL_FULL_VERSION}/
RUN ln -s /lib/modules/${KERNEL_FULL_VERSION}/kernel /opt/lib/modules/${KERNEL_FULL_VERSION}/kernel
RUN mkdir -p /firmwareDir/updates/amdgpu
COPY --from=builder /lib/firmware/updates/amdgpu /firmwareDir/updates/amdgpu
```

#### 1. Select base image:

Users need to know the OS information of the worker nodes of their clusters, then pick up corresponding base image to build the driver image. For example, if the worker nodes are using Ubuntu 22.04, users need to pick up ubuntu:22.04 as the base image to prepare the driver image.
```
FROM ubuntu:22.04 as builder
```

#### 2. Install the driver kernel module

AMD GPU DKMS driver kernel module needs to be installed within the builder container during image preparation. In the above example, Ubuntu native package manager is used to install ```amdgpu-dkms``` package. Other linux distros may require other package manager / other installation method to install the AMD GPU dkms driver.

```
RUN wget ${REPO_URL}/rocm/rocm.gpg.key -O - | \
    gpg --dearmor | tee /etc/apt/keyrings/rocm.gpg > /dev/null

RUN echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] ${REPO_URL}/amdgpu/${DRIVERS_VERSION}/ubuntu $$DRIVER_LABEL main" \
    | tee /etc/apt/sources.list.d/amdgpu.list
RUN apt-get update && apt-get install -y amdgpu-dkms
```

#### 3. Update kernel module dependency map

After installing the new kernel module, updating the modules dependency map is required in order to record the new dependency mapping. 

```
RUN depmod ${KERNEL_FULL_VERSION}
```

#### 4. Pick up necessary files

After installing dkms driver in builder container, not all the system kernel modules are required to install ```amdgpu``` module and saving the whole builder container would cost large storage space of the image registry. Moving necessary files only to the final container and convert them to be the eventual image would be a better choice.

```
RUN apt-get update && apt-get install -y kmod
RUN mkdir -p /opt/lib/modules/${KERNEL_FULL_VERSION}/updates/dkms/
COPY --from=builder /lib/modules/${KERNEL_FULL_VERSION}/updates/dkms/amd* /opt/lib/modules/${KERNEL_FULL_VERSION}/updates/dkms/
COPY --from=builder /lib/modules/${KERNEL_FULL_VERSION}/modules.* /opt/lib/modules/${KERNEL_FULL_VERSION}/
RUN ln -s /lib/modules/${KERNEL_FULL_VERSION}/kernel /opt/lib/modules/${KERNEL_FULL_VERSION}/kernel
RUN mkdir -p /firmwareDir/updates/amdgpu
COPY --from=builder /lib/firmware/updates/amdgpu /firmwareDir/updates/amdgpu
```

Explanation:

* Installing kmod utility is required since KMM worker would use the utility later to do ```modprobe``` operations on ```amdgpu``` kernel module.

```
RUN apt-get update && apt-get install -y kmod
```

* AMD GPU operator asks KMM to look for the ```amdgpu``` at the path ```/opt```, so all ```amdgpu``` related kernel module files (for example: ```.ko``` and ```modules.*``` files) need to be copied to ```/opt/lib/modules/${KERNEL_FULL_VERSION}/``` folder, where ```${KERNEL_FULL_VERSION}``` is the linux kernel version full name of users worker nodes (e.g. ```6.8.0-40-generic```).

* Some firmware files could be required during loading the kernel module, by default the system would look for corresponding firmware from ```/lib/firmware```. AMD GPU operator asks KMM to add ```/firmwareDir/updates``` into the system's firmware search path, in that way all related ```amdgpu``` firmware files should be copied into ```/firmwareDir/udpates``` of the driver image

#### 5. Run ```docker build``` command to build the image based on prepare dockerfile

#### 6. Tag the prepared image properly

After building the driver image, the image tag should follow the following pattern:

```
<linux distro>-<OS version>-<kernel version>-<ROCM version>
```

For example, if the prepared image is for worker nodes with Ubuntu 22.04 + kernel 6.8.0-40-generic (can be queried on the worker node by running ```uname -r```) + ROCM 6.1.3, the image tag should be ```ubuntu-22.04-6.8.0-40-generic-6.1.3```

Use ```docker tag``` command to tag the newly built image

#### 7. Push the newly built image to users private registry

## Test prepared image

In the DeviceConfig custom resource, configure ```driver.image``` field to the registry that is storing the prepared pre-compile images.

For example, if users push the pre-compiled image to ```docker.io/username/amdgpu_driver_image:ubuntu-22.04-6.8.0-40-generic-6.1.3```, the DeviceConfig yaml should be:

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
    version: "6.1.3"

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

After creating the custom resource, cluster would skip building procedure and directly pick up the pre-compiled image.