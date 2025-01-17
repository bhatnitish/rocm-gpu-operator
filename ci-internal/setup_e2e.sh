#!/bin/bash

set -x

# print out host ip address for debugging purpose
hostname -I
hostname -i

HOST_IP=$(hostname -i | awk '{print $2}')
REGISTRY_PORT="5000"

sed -i "s/registry-replaceme/$HOST_IP/" deploy/kind-config-1c2w.yaml

./deploy_k8s_by_kind.sh;
ls -al ~/.kube; cat ~/.kube/config; kubectl cluster-info; kubectl get pods -A; kubectl get nodes -o wide;

# Label worker nodes with amdgpu true for testcases to pick up with the node selector
kubectl label node dind-cluster-1c2w-worker feature.node.kubernetes.io/amd-gpu=true
kubectl label node dind-cluster-1c2w-worker2 feature.node.kubernetes.io/amd-gpu=true

# Edit Makefile to use custom local registry paths for e2e
MAKEFILE_PATH="/gpu-operator/Makefile"
sudo sed -i "s#^DOCKER_REGISTRY ?= registry.test.pensando.io:5000#DOCKER_REGISTRY ?= $HOST_IP:$REGISTRY_PORT#" "$MAKEFILE_PATH"
sudo sed -i 's/^IMAGE_NAME ?= amd-gpu-operator/IMAGE_NAME ?= root-e2e/' "$MAKEFILE_PATH"

# # Edit e2e testcase config to use local registry IP
TESTSUITE_PATH="/gpu-operator/tests/e2e/cluster_tests.go"
sed -i "s#registry.test.pensando.io:5000/e2e#$HOST_IP:$REGISTRY_PORT/root-e2e#g" "$TESTSUITE_PATH"
#cat /gpu-operator/tests/e2e/cluster_tests.go

# Edit the helm charts to use the local registry IP, package it
TESTSUITE_CHART_PATH="/gpu-operator/tests/e2e/yamls/charts"
sudo find "$TESTSUITE_CHART_PATH" -type f -exec sed -i "s/test_host_ip/$HOST_IP/g" {} +
sudo tar -czvf "${TESTSUITE_CHART_PATH}/gpu-operator-helm-k8s-v1.0.0.tgz" -C "${TESTSUITE_CHART_PATH}" gpu-operator

# Load kmm images in docker registry
KMMOPERATOR_IMAGE_TAR="/gpu-operator/tests/e2e/yamls/container/kernel-module-management-operator-dev.tar"
KMMOPERATOR_IMAGE_TAR_XZ="/gpu-operator/tests/e2e/yamls/container/kernel-module-management-operator-dev.tar.xz"
WORKER_IMAGE_TAR="/gpu-operator/tests/e2e/yamls/container/kernel-module-management-worker-dev.tar"
WORKER_IMAGE_TAR_XZ="/gpu-operator/tests/e2e/yamls/container/kernel-module-management-worker-dev.tar.xz"
WEBHOOK_IMAGE_TAR="/gpu-operator/tests/e2e/yamls/container/kernel-module-management-webhook-server-dev.tar"
WEBHOOK_IMAGE_TAR_XZ="/gpu-operator/tests/e2e/yamls/container/kernel-module-management-webhook-server-dev.tar.xz"
sudo xz -d $KMMOPERATOR_IMAGE_TAR_XZ
sudo xz -d $WORKER_IMAGE_TAR_XZ
sudo xz -d $WEBHOOK_IMAGE_TAR_XZ
sudo docker load -i $KMMOPERATOR_IMAGE_TAR
sudo docker load -i $WORKER_IMAGE_TAR
sudo docker load -i $WEBHOOK_IMAGE_TAR
sudo docker tag registry.test.pensando.io:5000/kernel-module-management-operator:dev $HOST_IP:5000/kmm-e2e-operator:dev
sudo docker tag registry.test.pensando.io:5000/kernel-module-management-worker:dev $HOST_IP:5000/kmm-e2e-worker:dev
sudo docker tag registry.test.pensando.io:5000/kernel-module-management-webhook-server:dev $HOST_IP:5000/kmm-e2e-webhook-server:dev

# No need insecure daemon for local docker
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
  docker exec $node bash -c "echo $HOST_IP registry.local >> /etc/hosts"
  docker exec $node bash -c "curl -v $HOST_IP:$REGISTRY_PORT"
  docker exec $node bash -c "curl -v registry.local:$REGISTRY_PORT"
  docker exec $node cat /etc/containerd/config.toml
done

sudo docker push $HOST_IP:5000/kmm-e2e-operator:dev
sudo docker push $HOST_IP:5000/kmm-e2e-worker:dev
sudo docker push $HOST_IP:5000/kmm-e2e-webhook-server:dev
sudo docker rmi registry.test.pensando.io:5000/kernel-module-management-operator:dev
sudo docker rmi registry.test.pensando.io:5000/kernel-module-management-worker:dev
sudo docker rmi registry.test.pensando.io:5000/kernel-module-management-webhook-server:dev
