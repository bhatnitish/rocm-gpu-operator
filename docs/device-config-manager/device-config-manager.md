# Device Config Manager

Device config manager(DCM) is a component of the GPU Operator which is used to handle AMD Devices' configuration. To begin with, we will be handling the GPU partitioning configurations, but it will be flexible to support any kind of GPU configurations (or AINIC configurations) in the future. Users will provide the GPU configurations using a K8s config-map. The config-map will be associated with the DCM daemonset.

## Configure device config manager

To start the Device Config Manager along with the GPU Operator configure fields under the ``` spec/configManager ``` field in deviceconfig Custom Resource(CR)

```yaml
  configManager:
    # To enable/disable the metrics exporter, enable to partition
    enable: True

    # image for the device-config-manager container
    image: "rocm/device-config-manager:v1.3.0"

    # image pull policy for config manager set to always to pull image of latest version
    imagePullPolicy: Always

    # specify configmap name which stores profile config info
    config: 
      name: "config-manager-config"

    # DCM pod deployed either as a standalone pod or through the GPU operator will have 
    # a toleration attached to it. User can specify additional tolerations if required
    # key: amd-dcm , value: up , Operator: Equal, effect: NoExecute 

    # OPTIONAL
    # toleration field for dcm pod to bypass nodes with specific taints
    configManagerTolerations:
      - key: "key1"
        operator: "Equal" 
        value: "value1"
        effect: "NoExecute"

```

The **device-config-manager** pod start after updating the **DeviceConfig** CR

```bash
#kubectl get pods -n kube-amd-gpu
NAME                                                              READY   STATUS    RESTARTS       AGE
kube-amd-gpu   amd-gpu-operator-gpu-operator-charts-controller-manager-6drmvl7   1/1     Running   0              3h14m
kube-amd-gpu   amd-gpu-operator-kmm-controller-6d459dffcf-ltf5h                  1/1     Running   0              3h14m
kube-amd-gpu   amd-gpu-operator-kmm-webhook-server-5fdc8b995-c8crh               1/1     Running   0              3h14m
kube-amd-gpu   amd-gpu-operator-node-feature-discovery-gc-78989c896-2zmnl        1/1     Running   0              3h14m
kube-amd-gpu   amd-gpu-operator-node-feature-discovery-master-b8bffc48b-xkqkx    1/1     Running   0              3h14m
kube-amd-gpu   amd-gpu-operator-node-feature-discovery-worker-kb5tk              1/1     Running   0              3h14m
kube-amd-gpu   test-deviceconfig-device-config-manager-hn9rb                     1/1     Running   0              3h14m
kube-amd-gpu   test-deviceconfig-device-plugin-zft6k                             1/1     Running   0              3h14m
```

<div style="background-color: #d0e7f; border-left: 6px solid #2196F3; padding: 10px;">
<strong>Note:</strong> The Device Config Manager name will be prefixed with the name of your DeviceConfig custom resource
</div></br>

## Device Config Manager DeviceConfig
| Field Name                        | Details                                      |
|-----------------------------------|----------------------------------------------|
| **ConfigManagerImage**            | Device Config Manager image                  |
| **ConfigManagerImagePullPolicy**  | One of Always, Never, IfNotPresent.          |
| **EnableConfigManager**           | Enable/Disable node labeller with True/False |
| **ConfigMap**                     | Field to specify configmap name              |
| **ConfigManagerTolerations**      | Field to add configmanager tolerations       |
</br>

1. The `ImagePullPolicy` field default to `Always` if `:latest` tag is specified on the respective Image, or defaults to `IfNotPresent` otherwise. This is default k8s behaviour for `ImagePullPolicy`

2. `ConfigMap` is of type `string`. Device-Config-Manager pod needs a configmap to be mounted, else pod does not come up

## Steps for partitioning using config map

_Kubernetes Node labels for GPU partitioning_
```bash
dcm.amd.com/gpu-config-profile=<profile_name>
```

-  Create a config map and apply it on the node.
-  Once applied, user has to add the label amd.com/gpu-config-profile to specify the profile name to be used from the config map.
-  This will trigger the partition using that profile's config.

```bash
amd.com/gpu-config-profile=profile-1
profile-1 : name of profile created in the configmap
```

-  To change the profile, user can re-apply the amd.com/gpu-config-profile node label with --overwrite=true option

## ConfigMap

- Please find an example config map in [_example/configmap.yaml_](https://github.com/pensando/gpu-operator/blob/main/example/configManager/configmap.yaml#L1)
- Example config map and it's meaning

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-manager-config
  namespace: kube-amd-gpu
data:
  config.json: |
    {
      "gpu-config-profiles":
      {
          "default":
          {
              "skippedGPUs": {
                  "ids": []
              },
              "profiles": [
                  {
                      "computePartition": "CPX", 
                      "memoryPartition": "NPS1",
                      "numGPUsAssigned": 6
                  },
                  {
                      "computePartition": "SPX", 
                      "memoryPartition": "NPS1",
                      "numGPUsAssigned": 2
                  }
              ]
          },
          "profile-1":
          { 
              "skippedGPUs": {
                  "ids": [0, 1, 2]
              },
              "profiles": [
                  {
                      "computePartition": "CPX",
                      "memoryPartition": "NPS1",
                      "numGPUsAssigned": 5
                  }          
              ]
          }
      }
    }

```

- `gpu-config-profiles` defines a set of partitioning config profiles from which the user can choose the profile he wants to apply.
- `default` and `profile-1` are example profile names.
- `skippedGPUs` (Optional) list of GPU IDs to skip partitioning
- `computePartition` compute partition type
- `memoryPartition` memory partition type
- `numGPUsAssigned` number of GPUs to be partitioned on the node
- NOTE: User can also create a heterogenous partitioning config profile by mentioning different sets, each set having info about compute/memory types and the number of GPUs to have that partition (refer `default` profile example)

## Configmap Profile Checks

- Let's assume a node with 8 GPUs in it.
### List of profiles checks
- Total number of all `numGPUsAssigned` values of a single profile must be equal to the total number of GPUs on the node.
    - In `default` profile, you can observe that, we are requesting 6 GPUs of type CPX-NPS1 and 2 GPUs of SPX-NPS1 which is valid since it comes to a total of 8 GPUs
    - If `skippedGPUs` field is present, we need to account for those IDs as well.
    - Hence, `Sum of numGPUsAssigned + len(skippedGPUs) = TotalGPUCount`
- `skippedGPUs` field
    - GPU IDs in the list can range from `0` to `total number of GPUs - 1`
    - Length of list must be equal to `total number of GPUs` - `sum of numGPUsAssigned` in that profile
        - Example, in `profile-1`, we have 5 GPUs set to CPX-NPS1 and exactly 3 more GPU IDs mentioned in the skip list
- Compute types supported are SPX and CPX.
    - Beta stage: DPX, QPX
- Memory types supported are NPS1 and NPS4
    - NPS4 is supported only for CPX compute type
    - Combination of NPS1 and NPS4 memory types cannot be used in a single profile

### Partitioning GPUs using DCM
-  GPU on the node cannot be partitioned on the go, we need to bring down all daemonsets using the GPU resource before partitioning. Hence we need to taint the node and the partition.
- DCM pod comes with a toleration
    - `key: amd-dcm , value: up , Operator: Equal, effect: NoExecute `
    - User can specify additional tolerations if required

### Steps for deploying DCM pod
- Add tolerations to the required pods
- Taint the node
- Deploy the DCM pod using a custom resource file
- Once partition is done, untaint the node

#### Add toleration for the taint
-  Since tainting a node will bring down all pods/daemonsets, we need to add toleration to the pods to prevent it from getting evicted.
-  Add toleration to system level pods as well like flannel, proxy etc before tainting the node.
```bash
Example:
kubectl get ds -n kube-flannel kube-flannel-ds -o yaml > fnl.yaml

amd@asrock-126-b3-3b:~$ vi fnl.yaml

#Add this under the spec.template.spec.tolerations object
tolerations:
      - key: "amd-dcm"
        operator: "Equal"
        value: "up"
        effect: "NoExecute"
amd@asrock-126-b3-3b:~$ kubectl apply -f nfd.yaml
```

#### Taint
-  To TAINT a specific node for partitioning the GPU:
```bash
kubectl taint nodes asrock-126-b3-3b amd-dcm=up:NoExecute
```

#### Deploy DCM using a custom resource file
-  Create a CR to bring up the DCM daemonset.
-  Sample CR can be found in [_example/deviceConfigs_example.yaml_](https://github.com/pensando/gpu-operator/blob/main/example/configManager/deviceconfigs_example.yaml#L1)

#### Untaint
```bash
kubectl taint nodes asrock-126-b3-3b amd-dcm:NoExecute-
```