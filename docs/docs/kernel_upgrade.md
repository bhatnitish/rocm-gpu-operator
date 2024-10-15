# Kernel Upgrade

AMD GPU Operator has the handling to support the kernel upgrade on users cluster. 

### PreFlightValidate (Optional)

Users could use the Kernel Module Management (KMM) Operator's functionality to validate whether the AMD GPU driver module could be built successfully on the new version kernel or not. See more details about the PreFlightValidation at [KMM docs](https://kmm.sigs.k8s.io/documentation/preflight_validation/) (OpenShift users could refer to [OpenShift version PreflightValidate documentation](https://openshift-kmm.netlify.app/documentation/preflight_validation/)).

### Drain the node

Users need to drain the node to make sure no more AMD GPU related workload could be scheduled on the node. After draining the node, all AMD GPU related workloads would be scheduled to other available worker nodes and users would be able to start the kernel upgrade process.

### Upgrade the kernel

Users don't need to remove the node out of the cluster, they could directly perform the steps needed for upgrading the kernel. This document won't cover all the details of upgrading the kernel since it is not specific to the AMD GPU Operator and the steps would differ for different Linux distributions.

If the kernel upgrade was successful, after the reboot the worker node would connect back to the cluster with updated information.

### Uncordon the node

Once the kernel upgrade completed users could mark the worker node back to schedulable, then AMD GPU Operator could automatically trigger the driver installation against the new kernel.