# Deploy AMD GPU Operator on Kubernetes Cluster

## 1. PreCheck

The vanilla Kubernetes cluster should be up and running:
  * All the Kubernetes system component pods should be running and in ready state
  * The cluster CNI should also be configured properly.

For example, in the following cluster, all default components are up and running and flannel is also installed to manage the Kubernetes network.

```
kube-flannel   kube-flannel-ds-7krtk                          1/1     Running   0              10d
kube-flannel   kube-flannel-ds-hmrb7                          1/1     Running   24 (35h ago)   10d
kube-system    coredns-7db6d8ff4d-644fp                       1/1     Running   0              2d20h
kube-system    coredns-7db6d8ff4d-6mb9t                       1/1     Running   5 (35h ago)    2d20h
kube-system    etcd-localhost.localdomain                     1/1     Running   2 (14d ago)    64d
kube-system    kube-apiserver-localhost.localdomain           1/1     Running   2 (14d ago)    64d
kube-system    kube-controller-manager-localhost.localdomain  1/1     Running   1 (14d ago)    64d
kube-system    kube-proxy-cmqj7                               1/1     Running   0              64d
kube-system    kube-proxy-xw87j                               1/1     Running   24 (35h ago)   10d
kube-system    kube-scheduler-localhost.localdomain           1/1     Running   2 (14d ago)    64d
```

## 2. Install

### 2.1 Install Cert-Manager

[Cert-Manager](https://cert-manager.io/docs/) is an operator that helps manage the TLS certificate within the Kubernetes or OpenShift cluster. AMD GPU Operator is using it to generate certificate for securing the communication between the controller and webhook server.

!!! note
    Users could skip this step if the cluster already has Cert-Manager installed

Run the kubectl command to install the cert-manager operator into Kubernetes cluster:
```
helm repo add jetstack https://charts.jetstack.io --force-update 

helm install cert-manager jetstack/cert-manager --namespace cert-manager --create-namespace --version v1.15.1 --set crds.enabled=true 
```

After the installation, the cert-manager related resources should be deployed:
```
-bash-4.2$ kubectl get pods -n cert-manager
NAME                                       READY   STATUS    RESTARTS      AGE
cert-manager-84489bc478-qjwmw              1/1     Running   5 (36h ago)   2d21h
cert-manager-cainjector-7477d56b47-v8nq8   1/1     Running   5 (36h ago)   2d21h
cert-manager-webhook-6d5cb854fc-h6vbk      1/1     Running   5 (36h ago)   2d21h
```

### 2.2 Install AMD GPU Operator

Download the helm chart of AMD GPU Operator (e.g. From GitHub), then run the ```helm install``` to install AMD GPU Operator:

```
helm install demo ./gpu-operator-0.0.1-k8s.tgz -n kube-amd-gpu --create-namespace 
```

The output of helm install would be:

```
NAME: demo
LAST DEPLOYED: Mon Oct  7 23:09:48 2024
NAMESPACE: kube-amd-gpu
STATUS: deployed
REVISION: 1
TEST SUITE: None
```

!!! note
    If users already have Node Feature Discovery (NFD) or Kernel Module Management (KMM) deployed in cluster, users can use these 2 options with helm install commands to skip the installation of those 2 dependency operators:<br>
    ```--set node-feature-discovery.enabled=false ```<br>
    ```--set kmm.enabled=false ```

!!! warning
    It is highly recommended to use the Kernel Module Management (KMM) images optimized and released by AMD, which is included in AMD GPU Operator release. If users don't skip installing KMM when doing helm install, the KMM with recommended image will be installed.

After the installation all the related pods should be running and in ready status:
```
kube-amd-gpu   demo-gpu-operator-controller-manager-6954b68958-ljthg   1/1     Running   0              62s
kube-amd-gpu   demo-kmm-controller-59b85d48c4-f2hn4                    1/1     Running   0              62s
kube-amd-gpu   demo-kmm-webhook-server-685b9db458-t5qp6                1/1     Running   0              62s
kube-amd-gpu   demo-node-feature-discovery-gc-98776b45f-j2hvn          1/1     Running   0              62s
kube-amd-gpu   demo-node-feature-discovery-master-9948b7b76-ncvnz      1/1     Running   0              62s
kube-amd-gpu   demo-node-feature-discovery-worker-dhl7q                1/1     Running   0              62s
```


