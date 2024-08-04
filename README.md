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

5. Prepare the helm charts:
Run ```make helm``` to generate helm charts

## Installation (for developers):
* Method 1 - Build and install from Helm Charts (Preferred):
  * Must have a k8s or openshift cluster up and running
  * Must build and install from a node that ```kubectl``` or ```oc``` has been configured properly for access to the cluster (control plane node preferred)
  * Run ```make helm``` to generate helm charts, the helm charts will be packed into ```gpu-operator-x.x.x.tgz``` 
  * Run ```make cert-manager-install``` to install cert-manager, one dependency operator
  * Configure helm-charts/values.yaml to change default config
              (node-feature-discovery, kmm, controller image version etc)
  * Run ```make helm-install``` to depoly the operator
  * When you need to uninstall, run ```make helm-uninstall``` then ```make cert-manager-uninstall```

* Method 2 - Build and install from source code:
  
  * Must have a k8s or openshift cluster up and running
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
  * Run ```make install``` to install the CRD
  * Run ```make deploy``` to deploy the AMD GPU Operator
  * When you need to uninstall, run ```make undeploy``` then ```make uninstall```, finally run ```kubectl delete``` on the dependencies resource URL in the reverse order

## Test the AMD GPU Operator

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
