# AMD GPU operator

<img src="docs/docs/imgs/amd_logo.jpg" alt="AMD" style="width:220px; height:auto;">
<img src="docs/docs/imgs/k8s_logo.png" alt="Kubernetes" style="width:100px; height:auto;">

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

5. Get an overview of the repository's [project layout](docs/docs/project_layout.md)

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
  * For vanilla k8s cluster: Run ```make helm``` to generate helm charts, the helm charts will be packed into ```helm-charts-k8s/gpu-operator-helm-k8s-x.x.x.tgz```
  * For openshift cluster: Run ```OPENSHIFT=1 make helm``` to generate helm charts, the helm charts will be packed into ```helm-charts-openshift/gpu-operator-helm-openshift-x.x.x.tgz```
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

* Method 2 - Build and install from Operator Lifecycle Manager (OLM):
  * Must have a k8s or openshift cluster up and running, and make sure OLM is running in the cluster
  * Must build and install from a node that ```kubectl``` or ```oc``` has been configured properly for access to the cluster (control plane node preferred), kubeconfig file should be saved at ```~/.kube/config```
  * Modify the registry related variables in ```Makefile```, use your own registry: 
    * ```DOCKER_REGISTRY```
    * ```IMAGE_NAME```
    * ```IMAGE_TAG```
  * If your registry requires auth to push image, please use ```docker login``` on your dev environment to configure login credentials to your registry
  * (Optional) If you made any customized changes on AMD GPU Operator controller, recompile then build + push AMD GPU operator's image:
    * ```make```
    * ```make docker-build```
    * ```make docker-push```
  * Build the OLM bundle by running ```make bundle-build```
  * Running the scorecard test of the bundle by running ```make bundle-scorecard-test```, you can modify ```bundle/tests/scorecard/config.yaml``` to configure the scorecard test cases. Remember to save kubeconfig file at ```~/.kube/config``` to run the test on your cluster. All test cases are expected to pass
  * After the validation, push the bundle image to registry by running ```make bundle-push```
  * Deploy the OLM bundle by running ```BUNDLE_NAMESPACE=test-olm-ns make bundle-deploy```
  * Uninstallation: run ```BUNDLE_NAMESPACE=test-olm-ns make bundle-cleanup``` to remove the bundle deployment from your cluster


* Method 3 - Build and install from source code:
  
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
| Name                       | Description                                                                                  | Kubernetes Default                                                                         | OpenShift Default                                                                                                    |
|:---------------------------|:---------------------------------------------------------------------------------------------|:-------------------------------------------------------------------------------------------|:---------------------------------------------------------------------------------------------------------------------
| devicePluginImage          | Device plugin image name                                                                     | rocm/k8s-device-plugin                                                                     | rocm/k8s-device-plugin                                                                                               |
| driversImage               | Defines image that includes drivers and firmware blobs                                       | image-registry:5000/ <br> $MOD_NAMESPACE/amd_gpu_kmm_modules: <br> %s-$KERNEL_FULL_VERSION | image-registry.openshift-image-registry.svc:5000 <br> /$MOD_NAMESPACE/amd_gpu_kmm_modules: <br> $KERNEL_FULL_VERSION |
| driversVersion             | Version of the drivers source code, can be used as part of image of dockerfile source image  | 6.1.3                                                                                      | el9-6.1.1                                                                                                            |
| imageRepoSecret            | Pull secrets used for pull/setting images used by operator                                   | None                                                                                       | None                                                                                                                 |
| blacklistDrivers           | Blacklist amdgpu drivers on the host                                                         | False                                                                                      | False                                                                                                                |
| skipDrivers                | Skip driver install/uninstall                                                                | False                                                                                      | False                                                                                                                |
| repoURL                    | Driver repo                                                                                  | repo.radeon.com/amdgpu-install                                                             | -                                                                                                                    | 
| redhatSubscriptionUsername | UserName for redhat subscription on RHEL machines                                            | None                                                                                       | None                                                                                                                 |
| redhatSubscriptionPassword | Password for redhat subscription on RHEL machines                                            | None                                                                                       | None                                                                                                                 |
|                            |                                                                                              |                                                                                            |                                                                                                                      |
| metricsExporter            | Metrics Exporter configurations                                                              |                                                                                            |                                                                                                                      |
|                            |                                                                                              |                                                                                            |                                                                                                                      | 
| Enable                     | Enable/Disable metrics exporter                                                             | disable                                                                                    | disable                                                                                                              | 
| Port                       | Service port exposed by metrics exporter                                                     | 5000                                                                                       | 5000                                                                                                                 |
| serviceType                | service type for metrics, clusterIP/Nodeport                                                 | clusterIP                                                                                  | clusterIP                                                                                                            | 
| nodePort                   | Node port for  metrics exporter service                                                        | global selector                                                                            | global selector                                                                                                      |
| selector                   | Node selector for metrics exporter daemonset                                                   | from k8s nodeport range                                                                    | from OpenShift nodeport range                                                                                        | 
| image                      | metrics exporter image                                                                       | registry.test.pensando.io:5000/gpu-operator/rdcd-export:0.3                                | registry.test.pensando.io:5000/gpu-operator/rdcd-export:0.3                                                          |
| config                     | metrics configurations (fields/labels)                                                       |                                                                                            |
|                            |                                                                                              |                                                                                            |
| name                       | configmap name to use     (kubectl create configmap <name> --from-file=examples/config.json) |                                                                                            |
## Techsupport-dump

Use techsupport-dump tool to collect system state/logs to debug.
* Can run from external machines or from nodes in the cluster
* Requires ```kubectl``` and access to kubernetes cluster (~/.kube/config configured)
```
gpu-operator$ ./tools/techsupport_dump.sh -h
./tools/techsupport_dump.sh [-w] [-o yaml/json] [-k kubeconfig] <node-name/all>
   [-w] wide option
   [-o yaml/json] output format, yaml/json(default)
   [-k kubeconfig] path to kubeconfig(default ~/.kube/config)
```
```
gpu-operator$ ./tools/techsupport_dump.sh all
....
[2024-09-03_18:52:53 techsupport]techsupport-2024-09-03_18-52-43.tgz is ready
```

## e2e tests
Requires access to kubernetes cluster (~/.kube/config configured)
```
make e2e # deploy gpu operator (default ./helm-charts-k8s/gpu-operator-helm-k8s-0.0.1.tgz) and run tests
make e2e GPU_OPERATOR_CHART="path to helm chart" # deploy the given chart and run tests
make -C tests/e2e # run e2e tests only
```

## Debug driver build
if the amdgpu driver build fails, the build pod will be in error state
```
gpu-operator$ kubectl get pods -n kube-amd-gpu
NAME                                                             READY   STATUS    RESTARTS   AGE
amd-gpu-operator-controller-manager-7d99f945fd-jcclc             1/1     Running   0          11h
test-device-config-build-8jqdm                                   0/1     Error     0          3m11s

```
pod logs contain more details
```
gpu-operator$ kubectl logs -n kube-amd-gpu test-device-config-build-8jqdm
INFO[0000] Resolved base name ubuntu:22.04 to builder
INFO[0000] Retrieving image manifest ubuntu:22.04
INFO[0000] Retrieving image ubuntu:22.04 from registry index.docker.io
error building image: unable to complete operation after 0 attempts, last error: GET https://index.docker.io/v2/library/ubuntu/manifests/22.04: TOOMANYREQUESTS: You have reached your pull rate limit. You may increase the limit by authenticating and upgrading: https://www.docker.com/increase-rate-limit

```
build error will be in events also
```
gpu-operator$ kubectl events -n kube-amd-gpu
LAST SEEN   TYPE      REASON         OBJECT                                             MESSAGE
7m33s       Normal    Pulled         Pod/kmm-worker-genoa4-test-device-config           Container image "gcr.io/k8s-staging-kmm/kernel-module-management-worker:v20240618-v2.1.1" already present on machine
7m33s       Normal    Created        Pod/kmm-worker-genoa4-test-device-config           Created container worker
7m33s       Normal    Started        Pod/kmm-worker-genoa4-test-device-config           Started container worker
7m33s       Normal    Killing        Pod/test-device-config-device-plugin-rgfsj-jqblb   Stopping container device-plugin
7m33s       Normal    Killing        Pod/test-device-config-node-labeller-4bs8f         Stopping container node-labeller-container
6m53s       Normal    Scheduled      Pod/test-device-config-build-8jqdm                 Successfully assigned kube-amd-gpu/test-device-config-build-8jqdm to genoa4
6m53s       Normal    BuildCreated   Module/test-device-config                          Build created for kernel 6.8.0-40-generic
6m52s       Normal    Pulled         Pod/test-device-config-build-8jqdm                 Container image "gcr.io/kaniko-project/executor:v1.23.2" already present on machine
6m52s       Normal    Created        Pod/test-device-config-build-8jqdm                 Created container kaniko
6m52s       Normal    Started        Pod/test-device-config-build-8jqdm                 Started container kaniko
6m50s       Warning   BuildFailed    Module/test-device-config                          Build job failed for kernel 6.8.0-40-generic
```

## Setup HTTP Proxy

In the Helm Chart, there is a section for users to specify the HTTP proxy configurations:

```
global:
  proxy:
    env: {}
```
the configuration could be applied in 2 ways:

* Running ```helm install``` with ```--set``` options, for example:
```
--set global.proxy.env.HTTP_PROXY=http://myproxy.com:123  \
--set global.proxy.env.HTTPS_PROXY=http://myproxy2.com:234 \
--set global.proxy.env.NO_PROXY="10.1.2.3\,localhost"
```

* Prepare the values.yaml and added the following content to the yaml, then run helm install testRelease ./test.tgz -n testNamespace -f values.yaml:
```
global:
  proxy:
    env:
      HTTP_PROXY: "http://myproxy.com:123"
      HTTPS_PROXY: "http://myproxy2.com:234"
      NO_PROXY: "10.1.2.3,localhost"
```

## Deploy and Modify Documentation Website

* Download mkdocs utilities

```
python3 -m pip install mkdocs
```

* Build the website

```
cd docs
python3 -m mkdocs build
```

* Deploy the website 

```
python3 -m mkdocs serve --dev-addr localhost:2345
```

* Modify the markdown document, the website will be lively refreshed with latest change.
