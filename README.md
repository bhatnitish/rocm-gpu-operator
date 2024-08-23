# AMD GPU operator

  Explore the power of AMD Instinct GPU accelerators within your Kubernetes(k8s) cluster with the AMD GPU Operator. This documentation is your go-to resource to enable, configure, and run accelerated workloads with your AMD Instinct GPU accelerators. The AMD GPU Operator lets you seamlessly harness computing capabilities for machine learning, Generative AI, and GPU-accelerated applications.

## Developer Guidelines
Please follow these steps to prepare development environment:
1. Use golang v1.20 to develop this project, there are some [golang open issues](https://github.com/golang/go/issues/65637) when using golang v1.21 or v1.22
2. Install Helm (Use Helm official script to install Helm):
```
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh
./get_helm.sh
```
for other methods of installing Helm, please refer to [Helm Official Website](https://helm.sh/docs/intro/install/)

3. Install Helmify:
Download the relased binary from [Helmify GitHub repo release page](https://github.com/arttor/helmify/releases/tag/v0.4.13), unpack the binary and move it to your ```PATH```

4. Compile the project:
Run ```make``` to generate the basic yaml files for CRD and build controller images

5. Get an overview of the repository's [project layout](docs/project_layout.md)

(Optional) If you did any customized change on the AMD GPU Operator, use the following steps to apply your modification and prepare a new image + helm charts:
* Modify the registry related variables in ```Makefile```, use your own registry: 
    * ```DOCKER_REGISTRY```
    * ```IMAGE_NAME```
    * ```IMAGE_TAG```
* If your registry requires auth to push image, please use ```docker login``` on your dev environment to configure login credentials to your registry
*  Build and push AMD GPU operator's image:
    * ```make docker-build```
    * ```make docker-push```
* Prepare the helm charts:
    * For vanilla k8s cluster: Run ```make helm``` to generate new helm charts
    * For openshift cluster: Run ```OPENSHIFT=1 make helm``` to generate new helm charts

## Installation (for developers):
* Method 1 - Build and install from Helm Charts (Preferred):
  * Must have a k8s or openshift cluster up and running, if you're using OpenShift, please set ```OPENSHIFT=1```
  * Must build and install from a node that ```kubectl``` or ```oc``` has been configured properly for access to the cluster (control plane node preferred)
  * Modify the registry related variables in ```Makefile```, use your own registry: 
    * ```DOCKER_REGISTRY```
    * ```IMAGE_NAME```
    * ```IMAGE_TAG```
  * If your registry requires auth to push image, please use ```docker login``` on your dev environment to configure login credentials to your registry
  * (Optional) If you made any customized changes on AMD GPU Operator, recompile then build + push AMD GPU operator's image:
    * ```make```
    * ```make docker-build```
    * ```make docker-push```
  * For vanilla k8s cluster: Run ```make helm``` to generate helm charts, the helm charts will be packed into ```gpu-operator-x.x.x.tgz```
  * For openshift cluster: Run ```OPENSHIFT=1 make helm``` to generate helm charts, the helm charts will be packed into ```gpu-operator-x.x.x.tgz```
  * Run ```make cert-manager-install``` to install cert-manager if there is no cert-manager running within your cluster
  * Install helm chart:
    * Remember if you are installing on openshift cluster, pls run make commands with ```OPENSHIFT=1```
    * If your clsuter already have Node Feature Discovery running: ```SKIP_NFD=1 make helm-install```
    * If your clsuter already have Kernel Module Management running: ```SKIP_KMM=1 make helm-install```
    * If you want to install both NFD and KMM dependencies together with AMD GPU Operator: ```make helm-install```
  * Uninstallation (make sure to uninstall in the following order):
    * Delete all existing CRs: ```kubectl delete deviceconfigs.amd.com -n <CR's namespace> --all``` or ```oc delete deviceconfigs.amd.com -n <CR's namespace> --all```
    * Uninstall operator: ```make helm-uninstall``` 
    * Uninstall Cert Manager: ```make cert-manager-uninstall```
    * Uninstall all the CRDs: ```kubectl delete crd deviceconfigs.amd.com modules.kmm.sigs.x-k8s.io nodefeaturegroups.nfd.k8s-sigs.io nodefeaturerules.nfd.k8s-sigs.io nodefeatures.nfd.k8s-sigs.io nodemodulesconfigs.kmm.sigs.x-k8s.io preflightvalidations.kmm.sigs.x-k8s.io ``` 
    * ```kubectl delete crd issuers.cert-manager.io clusterissuers.cert-manager.io certificates.cert-manager.io certificaterequests.cert-manager.io orders.acme.cert-manager.io challenges.acme.cert-manager.io```

* Method 2 - Build and install from source code:
  
  * Must have a k8s or openshift cluster up and running, if you're using OpenShift, please set ```OPENSHIFT=1```
  * Must build and install from a node that ```kubectl``` or ```oc``` has been configured properly for access to the cluster (control plane node preferred)
  * Install dependencies:
    * Install Node Feature Discovery (NFD) Operator: 
    
    ``` kubectl apply -k https://github.com/kubernetes-sigs/node-feature-discovery/deployment/overlays/default?ref=v0.16.3```

    wait for NFD's master and worker pods ready 
    * Install Kernel Module Management Operator:
    
    ```
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.11.0/cert-manager.yaml
    kubectl -n cert-manager wait --for=condition=Available deployment \
    cert-manager \
    cert-manager-cainjector \
    cert-manager-webhook

    kubectl apply -k https://github.com/kubernetes-sigs/kernel-module-management/config/default
    ```

    wait for cert manager and kmm pods ready
  * (Optional) If you made any customized changes on AMD GPU Operator, recompile then build + push AMD GPU operator's image:
    * ```make```
    * ```make docker-build```
    * ```make docker-push```
  * Run ```make install``` to install the CRD
  * Run ```make deploy``` to deploy the AMD GPU Operator
  * Uninstallation (make sure to uninstall in the following order):
    * run ```make undeploy``` then ```make uninstall```, finally run ```kubectl delete``` on the dependencies resource URLs in the reverse order
    * Uninstall all the CRDs: ```kubectl delete crd deviceconfigs.amd.com modules.kmm.sigs.x-k8s.io nodefeaturegroups.nfd.k8s-sigs.io nodefeaturerules.nfd.k8s-sigs.io nodefeatures.nfd.k8s-sigs.io nodemodulesconfigs.kmm.sigs.x-k8s.io preflightvalidations.kmm.sigs.x-k8s.io ``` 
    * ```kubectl delete crd issuers.cert-manager.io clusterissuers.cert-manager.io certificates.cert-manager.io certificaterequests.cert-manager.io orders.acme.cert-manager.io challenges.acme.cert-manager.io```

### Adding insecure registries
Following are the instructions to set container image registries as insecure. This allows for faster dev environment setup avoiding the hassle of adding/creating secrets for registry access.  
* crio container runtime
  * Edit the `registries.conf` file:
    * Open the `/etc/containers/registries.conf` file.
    * Add your insecure registry under the `[[registry]]` section. For example:
      ```
      [[registry]]
      location = "registry.test.pensando.io:5000"
      insecure = true
      ```
  * After making the changes, restart the CRI-O service to apply the new configuration:
    ```
    sudo systemctl restart crio
    ```
* containerd 
  * Edit the `config.toml` file:
    * Locate the `config.toml` file, typically found at `/etc/containerd/config.toml`
    * Set `insecure_skip_verify` under config `[plugins."io.containerd.grpc.v1.cri".registry.configs]` section
      ```
      [plugins."io.containerd.grpc.v1.cri".registry.configs]
      [plugins."io.containerd.grpc.v1.cri".registry.configs."my.insecure.registry.com:8888".tls]
       insecure_skip_verify = true
      ```
    * Add your insecure registry under the `[plugins."io.containerd.grpc.v1.cri".registry.mirrors]` section. For example:
      ```
      [`plugins."io.containerd.grpc.v1.cri".registry.mirrors]
      [plugins`."io.containerd.grpc.v1.cri".registry.mirrors."my.insecure.registry.com:8888"]
      endpoint = ["http://my.insecure.registry.com:8888"]
      ```
  * Restart containerd:
    * After making the changes, restart the containerd service to apply the new configuration:
      ```
      sudo systemctl restart containerd
      ```

## Test the AMD GPU Operator

### Create an example Custom Resource (CR)
```
apiVersion: amd.com/v1alpha1
kind: DeviceConfig  # The CR is named as DeviceConfig
metadata:
  name: test-device-config
  namespace: kube-amd-gpu # the same namespace used for installation
spec:
  # driversImage must be a valid image URL, registry must be reachable and repo:tag should be valid
  # if the registry needs credential to login, please configure it by:
  # kubectl create secret docker-registry docker-auth -n kube-amd-gpu --docker-server=xxx --docker-username=xxx --docker-password=xxx
  # and specify the secret name at imageRepoSecret
  # if the tag exists, driver image will be directly pulled and directly used
  # if the tag doesn't exist, driver image will be built on the fly and pushed back to the given image URL
  driversImage: registry.test.pensando.io:5000/ubuntu:amdgpu-6.1.3
  # devicePluginImage is the ROCM official device plugin image
  devicePluginImage: rocm/k8s-device-plugin
  # driversVersion specifies the ROCM driver version that will be used during build on the fly
  driversVersion: 6.1.3
  # imageRepoSecret specifies the secret to get access to private registry
  # remove this if your registry doesn't require credential to pull/push images
  imageRepoSecret:
    name: docker-auth
  # selector specifies which node the CR will be applied
  # by default feature.node.kubernetes.io/amd-gpu: "true" will apply the CR to all worker nodes where AMD GPU was detected by AMD PCI vendor ID 1002
  selector:
    feature.node.kubernetes.io/amd-gpu: "true"
```

### Check Custom Resource status
Once the driver installation was successful, the status will be pushed back to CR status fields.
```
kubectl get deviceconfigs -n <CR's namespace> test-device-config -oyaml
```
For example: 
```
apiVersion: amd.com/v1alpha1
kind: DeviceConfig
metadata:
  creationTimestamp: "2024-08-12T12:36:39Z"
  finalizers:
  - amd.node.kubernetes.io/deviceconfig-finalizer
  generation: 1
  name: test-device-config
  namespace: kube-amd-gpu
  resourceVersion: "1851082"
  uid: 7b3100e5-4038-42fc-8077-b11e41451dcd
spec:
  devicePluginImage: rocm/k8s-device-plugin
  driversImage: registry.test.pensando.io:5000/ubuntu:amdgpu-6.1.3-6.5.0-44-generic
  driversVersion: 6.1.3
  imageRepoSecret:
    name: docker-auth
  selector:
    feature.node.kubernetes.io/amd-gpu: "true"
status:
  devicePlugin:
    availableNumber: 1             # number of nodes that has ROCM device plugin brought up successfully
    desiredNumber: 1               # number of nodes that is expected to deploy new ROCM device plugin
    nodesMatchingSelectorNumber: 1 # number of nodes selected by node selector
  driver:
    availableNumber: 1             # number of nodes that has amdgpu dirver installed successfully and managed by operator
    desiredNumber: 1               # number of nodes that is expected to deploy new amdgpu driver
    nodesMatchingSelectorNumber: 1 # number of nodes selected by node selector
  nodeModuleStatus:                # per node status of installing driver, once appeared here it means the driver kmod was successfully installed
    leto:                          # cluster's Node resource name
      containerImage: registry.test.pensando.io:5000/ubuntu:amdgpu-6.1.3-6.5.0-44-generic
      kernelVersion: 6.5.0-44-generic
      lastTransitionTime: 2024-08-12 12:37:03 +0000 UTC
```

### TroubleShooting
1. If the Custom Resource didn't went through the opeartor's controller and no worker pod was brought up. please try to get logs to check the error:

* list all the pods by ```kubectl get pods -A```
* describe the AMD GPU Operator controller pod ```kubectl describe pod -n <namespace> <gpu operator controller pod name>```
* check the logs of AMD GPU Operator controller pod ```kubectl logs -n <namespace> <gpu operator controller pod name>``` 
* describe the KMM webhook pod ```kubectl describe pod -n <kmm namespace> <kmm webhook pod name>```
* check the logs of KMM webhook pod ```kubectl logs -n <kmm namespace> <kmm webhook pod name>```
* describe the KMM controller pod ```kubectl describe pod -n <kmm namespace> <kmm controller pod name>```
* check the logs of KMM controller pod ```kubectl logs -n <kmm namespace> <kmm controller pod name>``` 

2. If the kaniko builder pod / kmm worker pod was up but it failed to install:
* list all the pods by ```kubectl get pods -A```
* describe the KMM kaniko builder pod ```kubectl describe pod -n <kmm namespace> <kmm kaniko builder pod name>```
* check the logs of kaniko builder pod ```kubectl logs -n <kmm namespace> <kmm kaniko builder pod name>``` 
* describe the KMM worker pod ```kubectl describe pod -n <kmm namespace> <kmm worker pod name>```
* check the logs of KMM worker pod ```kubectl logs -n <kmm namespace> <kmm worker pod name>``` 

### Test rocm-smi

Prepare the yaml file:
```
laptop % cat << EOF > rocm-smi.yaml
apiVersion: v1
kind: Pod
metadata:
 name: rocm-smi
spec:
 containers:
 - image: docker.io/rocm/pytorch:latest
   name: rocm-smi
   command: ["/bin/sh","-c"]
   args: ["rocm-smi"]
   resources:
    limits:
      amd.com/gpu: 1
    requests:
      amd.com/gpu: 1
 restartPolicy: Never
EOF
```

Create the rocm-smi pod:
```bash
laptop ~ % kubectl create -f rocm-smi.yaml
pod/rocm-smi created
```

Check rocm-smi log with one MI210 GPU:
```bash
laptop ~ % kubectl get pods
NAME        READY   STATUS      RESTARTS   AGE
rocm-smi   0/1     Completed   0           40s
```

Check the logs:
```bash
laptop ~ % kubectl logs pod/rocm-smi
====================================== ROCm System Management Interface ======================================
================================================ Concise Info ================================================
Device  [Model : Revision]    Temp    Power  Partitions      SCLK    MCLK     Fan  Perf  PwrCap  VRAM%  GPU%  
        Name (20 chars)       (Edge)  (Avg)  (Mem, Compute)                                                   
==============================================================================================================
0       [0x0c34 : 0x02]       32.0°C  38.0W  N/A, N/A        800Mhz  1600Mhz  0%   auto  300.0W    0%   0%    
        Instinct MI210                                                                                        
==============================================================================================================
============================================ End of ROCm SMI Log =============================================

laptop ~ % kubectl delete -f rocm-smi.yaml
pod "rocm-smi" deleted
```

## Test rocminfo

Prepare the yaml file:
```bash
laptop % cat << EOF > rocminfo.yaml
apiVersion: v1
kind: Pod
metadata:
 name: rocminfo
spec:
 containers:
 - image: docker.io/rocm/pytorch:latest
   name: rocminfo
   command: ["/bin/sh","-c"]
   args: ["rocminfo"]
   resources:
    limits:
      amd.com/gpu: 1
    requests:
      amd.com/gpu: 1
 restartPolicy: Never
EOF
```

Create the rocminfo pod:
```bash
laptop % kubectl create -f rocminfo.yaml
```

Check the rocminfo logs with one MI210 GPU:
```bash
laptop ~ % kubectl logs rocminfo | grep -A5 "Agent"
HSA Agents               
==========               
*******                  
Agent 1                  
*******                  
  Name:                    Intel(R) Xeon(R) Gold 6330 CPU @ 2.00GHz
  Uuid:                    CPU-XX                             
  Marketing Name:          Intel(R) Xeon(R) Gold 6330 CPU @ 2.00GHz
  Vendor Name:             CPU                                
--
Agent 2                  
*******                  
  Name:                    Intel(R) Xeon(R) Gold 6330 CPU @ 2.00GHz
  Uuid:                    CPU-XX                             
  Marketing Name:          Intel(R) Xeon(R) Gold 6330 CPU @ 2.00GHz
  Vendor Name:             CPU                                
--
Agent 3                  
*******                  
  Name:                    gfx90a                             
  Uuid:                    GPU-024b776f768a638b               
  Marketing Name:          AMD Instinct MI210                 
  Vendor Name:             AMD                     

laptop ~ % kubectl delete -f rocminfo.yaml
```
## Configurable parameters
|  Name           | Description     | Kubernetes Default | OpenShift Default |
|:----------------|:----------------|:-------------|:--------------------
|  devicePluginImage |  Device plugin image name| rocm/k8s-device-plugin | rocm/k8s-device-plugin |
|  driversImage | Defines image that includes drivers and firmware blobs | image-registry:5000/ <br> $MOD_NAMESPACE/amd_gpu_kmm_modules: <br> %s-$KERNEL_FULL_VERSION  | image-registry.openshift-image-registry.svc:5000 <br> /$MOD_NAMESPACE/amd_gpu_kmm_modules: <br> $KERNEL_FULL_VERSION  |
|  driversVersion | Version of the drivers source code, can be used as part of image of dockerfile source image | 6.1.3 | el9-6.1.1|
|  imageRepoSecret | Pull secrets used for pull/setting images used by operator | None | None |
|  blacklistDrivers | Blacklist amdgpu drivers on the host | False | False |
|  skipDrivers     |  Skip driver install/uninstall | False | False |
|  repoURL         |  Driver repo | repo.radeon.com/amdgpu-install | - | 

## e2e tests
Requires access to kubernetes setup (~/.kube/config configured)
```
make e2e # deploy gpu operator (default ./gpu-operator-0.0.1.tgz) and run tests
make e2e GPU_OPERATOR_CHART="path to helm chart" # deploy the given chart and run tests
make -C tests/e2e # run e2e tests only
```
