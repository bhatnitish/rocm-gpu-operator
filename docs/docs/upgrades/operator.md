# AMD GPU Operator Upgrade Guide

## Overview

This guide describes the process for upgrading the AMD GPU Operator while minimizing workload disruption. The upgrade process includes updating the operator itself, associated components (NFD, KMM), and handling GPU driver updates.

## Prerequisites

Before upgrading the operator:

- Back up all `DeviceConfig` custom resources
- Ensure cluster admin access
- Verify current operator version
- Review the release notes for breaking changes
- Have access to the image registry

## Pre-upgrade Tasks

1. Check current operator version:
   ```bash
   helm list -n kube-amd-gpu
   ```

2. Verify current workload status:
   ```bash
   kubectl get pods -A -l amd.com/gpu=true
   ```

3. Back up existing configuration:
   ```bash
   kubectl get deviceconfigs.amd.com -A -o yaml > deviceconfigs-backup.yaml
   ```

## Upgrade Process

### Helm-based Upgrade

1. Update Helm repositories:
   ```bash
   helm repo update rocm
   ```

2. Check available versions:
   ```bash
   helm search repo rocm/gpu-operator-helm -l
   ```

3. Upgrade the operator:
   ```bash
   helm upgrade amd-gpu-operator rocm/gpu-operator-helm \
     --namespace kube-amd-gpu \
     --version <new-version>
   ```

### Verify Upgrade

1. Check operator pod status:
   ```bash
   kubectl get pods -n kube-amd-gpu
   ```

2. Verify operator version:
   ```bash
   kubectl get deployment -n kube-amd-gpu amd-gpu-operator-controller-manager -o jsonpath='{.spec.template.spec.containers[0].image}'
   ```

3. Check driver status:
   ```bash
   kubectl get deviceconfigs.amd.com -A
   ```

## Rollback Procedures

If issues occur during upgrade:

- Rollback Helm release:

```bash
helm rollback amd-gpu-operator -n kube-amd-gpu
```

- Verify rollback status:

```bash
kubectl get pods -n kube-amd-gpu
```

- Restore DeviceConfig backups if needed:

```bash
kubectl apply -f deviceconfigs-backup.yaml
```

## Version-specific Notes

!!! note "Version 1.x to 2.x"
    Include specific upgrade notes for major version changes when available.

## Troubleshooting

- Pod Stuck in Terminating State

```bash
kubectl delete pod <pod-name> -n kube-amd-gpu --force
```

- Image Pull Errors
  - Verify registry access
  - Check image tags
  - Validate pull secrets
