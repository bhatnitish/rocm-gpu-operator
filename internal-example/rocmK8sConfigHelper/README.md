# Usage

This folder contains simple and straightforward examples for how to push configs to AMD GPU worker nodes within Kubernetes cluster, by executing SMI commands within a `Daemonset` or `Job`. You can customize these examples for your specific GPU configs / use case. 

Some SMI commands may return warning regarding the system warranty, please double check before executing the configuration commands, e.g.:

```
        ******WARNING******

        Operating your AMD GPU outside of official AMD specifications or outside of
        factory settings, including but not limited to the conducting of overclocking,
        over-volting or under-volting (including use of this interface software,
        even if such software has been directly or indirectly provided by AMD or otherwise
        affiliated in any way with AMD), may cause damage to your AMD GPU, system components
        and/or result in system failure, as well as cause other problems.
        DAMAGES CAUSED BY USE OF YOUR AMD GPU OUTSIDE OF OFFICIAL AMD SPECIFICATIONS OR
        OUTSIDE OF FACTORY SETTINGS ARE NOT COVERED UNDER ANY AMD PRODUCT WARRANTY AND
        MAY NOT BE COVERED BY YOUR BOARD OR SYSTEM MANUFACTURER'S WARRANTY.
        Please use this utility with caution.
```

## Usage of amdsmi-config-daemonset.yml

This `Daemonset` can help you execute SMI commands in selected nodes in a batch.

1. Modify the commands you want to execute inside the `ConfigMap` and main container, optionally add nodeSelector to the daemonset for selecting nodes across cluster.
2. Apply the YAML file `kubectl apply -f amdsmi-config-daemonset.yml -n <namespace>`
3. Check the logs to verify the configs were applied successfully: `kubectl logs -l name=amd-smi-daemon --tail=-1 -n <namespace>` and `kubectl logs -l name=amd-smi-daemon --tail=-1 -c amd-smi-init -n <namespace>`.
4. Remove the resources: `kubectl delete -f amdsmi-config-daemonset.yml -n <namespace>`

## Usage of amdsmi-config-job.yml

This `Job` can help you execute SMI commands in one target node.

1. Modify the commands you want to execute inside the `ConfigMap` and main container
2. Modify the `nodeSelector` to specify which node you want to execute the job
3. Apply the YAML file `kubectl apply -f amdsmi-config-job.yml -n <namespace>`
4. Check the logs to verify the configs were applied successfully: `kubectl logs -l name=amd-smi-job --tail=-1 -n <namespace>` and `kubectl logs -l name=amd-smi-job --tail=-1 -c amd-smi-init -n <namespace>`
5. Remove the resources: `kubectl delete -f amdsmi-config-job.yml -n <namespace>`
