# GPU Validation Cluster

A containerized, one-click deployment solution for validating AMD GPU and AINIC in a cluster.

## Overview

This project provides an automated, reproducible testing environment for GPU operator functionality. It deploys a complete Kubernetes cluster with AMD GPU and Network operators pre-configured, enabling rapid validation of operator features and performance.

## Features

- **Automated Deployment**: Single-command cluster initialization with all operators ready
- **GPU Operator**: Full AMD GPU device plugin with resource management and scheduling
- **Network Operator**: AMD network operator for advanced networking and performance optimization
- **Cluster Validation Framework**: Comprehensive automated tests for both GPU validation and RCCL tests.
- **Containerized**: Entire stack runs in containers for portability and consistency

## Quick Start

### Prerequisites

- Docker engine installed and daemon is running (validated on Docker 29.1.5 or newer)
- `jq` CLI for JSON parsing
- Ubuntu 22.04 or 24.04 host

### Deployment

1. **Build the container image**

   ```bash
   ./gpu-cluster.sh build
   ```

2. **Start the validation cluster**

   ```bash
   # Bring up control plane
   ./gpu-cluster.sh run server

   # Fetch control plane token to join the cluster
   ./gpu-cluster.sh get-token

   # On other nodes, bring up worker to join the cluster
   ./gpu-cluster.sh run agent <server-ip> <token>
   ```

3. **Tear down the cluster**

   ```bash
   ./gpu-cluster.sh teardown
   ```

## Usage

```text
Usage: ./gpu-cluster.sh <command> [args...]

Commands:
  build                          Build the Docker image
  run <server|agent> [args...]   Run the node as server or agent
  teardown                       Tear down the cluster and clean up
  get-token                      Run on server node to print agent join token
  status                         Show cluster validation framework status and recent runs
  node-status                    Show validation status per node
  help                           Show this help message

Run arguments:
  run server
  run agent  <server-ip> <token>
```

## Environment Variables

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `IMAGE_NAME` | `gpu-validation-cluster` | Docker image name |
| `IMAGE_TAG` | `latest` | Docker image tag |
| `BUILD_DIR` | `$SCRIPT_DIR/build` | Path to directory containing Dockerfile and entrypoint.sh |
| `CONFIG_DIR` | `$SCRIPT_DIR/configs` | Path to directory containing config.json and other config files |
| `CLEANUP_TEST_LOGS` | `false` | Clean up cluster validation test logs in `/var/log/cluster-validation` during teardown |

### Examples

```bash
# Build using a custom build directory
BUILD_DIR=/path/to/custom/build ./gpu-cluster.sh build

# Run server node with custom config directory
CONFIG_DIR=/path/to/custom/configs ./gpu-cluster.sh run server

# Run agent node with custom config directory to join a cluster
CONFIG_DIR=/path/to/custom/configs ./gpu-cluster.sh run agent <server-ip> <token>

# Teardown with cluster validation logs cleanup enabled
CLEANUP_TEST_LOGS=true ./gpu-cluster.sh teardown

# Show cluster validation framework CronJob status and recent pod runs
./gpu-cluster.sh status

# Show per-node validation test status (last run time and result)
./gpu-cluster.sh node-status
```

## Directory Structure

```text
gpu-validation-cluster/
├── README.md            # Project documentation
├── gpu-cluster.sh       # Unified script for build, run, teardown, and get-token
├── build/               # Build context
│   ├── Dockerfile       # Dockerfile to build the image
│   └── entrypoint.sh    # Container entrypoint script
└── configs/             # Configuration files
    ├── config.json                      # Main configuration settings
    ├── cluster-validation-config.yaml   # Cluster validation framework config
    └── cluster-validation-job.yaml      # Cluster validation framework cronjob
```

## Configuration

Customize operator behavior by editing files in the `configs/` directory:

- `config.json`: Main configuration settings
- `cluster-validation-config.yaml`: cluster validation framework config
- `cluster-validation-job.yaml`: cluster validation framework cronjob definition

## Cleanup Behavior

By default, the teardown command preserves cluster validation logs in `/var/log/cluster-validation` for troubleshooting and analysis. To remove these logs during teardown, set the `CLEANUP_TEST_LOGS` environment variable to `true`:

```bash
CLEANUP_TEST_LOGS=true ./gpu-cluster.sh teardown
```

## Monitoring Validation Tests

### Cluster-Wide Status

To view the overall cluster validation framework status including CronJob configuration and recent pod runs:

```bash
./gpu-cluster.sh status
```

This command displays:
- **CronJob Status**: Configuration and schedule of validation CronJobs
- **Recent Pod Runs**: Last 5 pod executions with timestamps, phases, and assigned nodes
- **Pod Details**: Detailed information about recent validation test pods

### Per-Node Validation Status

To view validation test results broken down by individual node:

```bash
./gpu-cluster.sh node-status
```

This command displays:
- **Node Summary Table**: Shows each node with its last run timestamp and validation result (Passed/Failed/Pending)
- **Detailed Node Information**: Per-node breakdown including:
  - Last run timestamp (from node annotation)
  - Validation result status
  - Most recent pod name that executed on the node

**Result Status Legend:**
- `Passed`: All validation tests on the node passed
  - Label: `amd.com/cluster-validation-status=passed`
- `Failed`: One or more validation tests on the node failed
  - Label: `amd.com/cluster-validation-status=failed`
- `Pending`: Validation tests are running or have not yet executed
  - Label: not set (no label present)

### Understanding the Output

The per-node view uses Kubernetes node labels and annotations to track validation test execution:
- **Annotation `amd.com/cluster-validation-last-run-timestamp`**: Timestamp of the last validation test execution on this node
- **Label `amd.com/cluster-validation-status`**: Current validation result status:
  - Set to `passed` if all tests passed
  - Set to `failed` if any tests failed
  - Not set (empty) if tests are pending or have not yet run

## FAQ

1. What if I hit the DockerHub rate limit to pull images from public repository?

Users could configure a DockerHub account secrets in `configs/config.json` so that the system will globally use a registered account to pull images from DockerHub, for example:

```json
  "global": {
    "image-pull-secrets": [
      {
        "registry-url": "docker.io",
        "username": "my username",
        "token": "my password / access token",
        "isBaseImageSecret": true
      }
    ]
  }
```
