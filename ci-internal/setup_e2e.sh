#!/bin/bash

# Label worker nodes with amdgpu true for testcases to pick up with the node selector
kubectl label node dind-cluster-1c2w-worker feature.node.kubernetes.io/amd-gpu=true
kubectl label node dind-cluster-1c2w-worker2 feature.node.kubernetes.io/amd-gpu=true

HOST_IP=$(hostname -I | awk '{print $1}')
REGISTRY_PORT="5000"

# Edit Makefile to use custom local registry paths for e2e
MAKEFILE_PATH="/go/src/github.com/pensando/gpu-operator/Makefile"
sudo sed -i "s#^DOCKER_REGISTRY ?= registry.test.pensando.io:5000#DOCKER_REGISTRY ?= $HOST_IP:$REGISTRY_PORT#" "$MAKEFILE_PATH"
sudo sed -i 's/^IMAGE_NAME ?= amd-gpu-operator/IMAGE_NAME ?= root-e2e/' "$MAKEFILE_PATH"

# # Edit e2e testcase config to use local registry IP
TESTSUITE_PATH="/go/src/github.com/pensando/gpu-operator/tests/e2e/cluster_tests.go"
sed -i "s#registry.test.pensando.io:5000/e2e#$HOST_IP:$REGISTRY_PORT/root-e2e#g" "$TESTSUITE_PATH"
cat /go/src/github.com/pensando/gpu-operator/tests/e2e/cluster_tests.go

# Add insecure registry to Docker daemon.json on the host
sudo apt-get update
sudo apt-get install jq -y
jq --version
DOCKER_CONFIG_FILE="/etc/docker/daemon.json"
sudo jq --arg host_ip "$HOST_IP" --arg reg_port "$REGISTRY_PORT"   '.["insecure-registries"] += ["\($host_ip):\($reg_port)"]'   "$DOCKER_CONFIG_FILE" > /tmp/daemon.json.tmp && sudo mv /tmp/daemon.json.tmp "$DOCKER_CONFIG_FILE"
sudo pkill -HUP dockerd
cat /etc/docker/daemon.json

# Configure containerd for setting local registry as insecure in all the nodes
kind_nodes=$(docker ps --filter "name=dind-cluster-1c2w-" --format "{{.Names}}")
for node in $kind_nodes; do
  echo "Configuring node: $node"
  docker exec $node bash -c "cat >> /etc/containerd/config.toml <<EOF
[plugins.\"io.containerd.grpc.v1.cri\".registry.configs.\"$HOST_IP:$REGISTRY_PORT\".tls]
  insecure_skip_verify = true
[plugins.\"io.containerd.grpc.v1.cri\".registry.mirrors.\"$HOST_IP:$REGISTRY_PORT\"]
  endpoint = [\"http://$HOST_IP:$REGISTRY_PORT\"]
EOF"
  docker exec $node pkill -SIGHUP containerd
  docker exec $node cat /etc/containerd/config.toml
done
