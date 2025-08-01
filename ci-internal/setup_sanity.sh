#!/bin/bash

#set -x

function usage() {
    echo ""
    echo "Usage: $0 [options]"
    echo "          --help print help/usage information"
    echo "          --registry <selection: local|master|global"
    echo "          --testbed /path/to/testbed.json, default /warmd.json"
    echo "          --image-manifest /path/to/images.yaml, default /tmp/images.yaml"
    echo ""
}

LOCAL_REGISTRY_PORT="5000"
REGISTRY_SELECTION="local"
TESTBED_JSON="/warmd.json"
IMAGE_MANIFEST="/tmp/images.yaml"
GLOBAL_REGISTRY="registry.test.pensando.io:5000"

REGISTRY=""

function start_registry() {
    # Maximum number of retries
    local MAX_RETRIES=20
    # Retry counter
    local RETRY_COUNT=0

    # Start Docker if START_DOCKER is set
    if [ ! -z "$START_DOCKER" ]; then
        echo "START_DOCKER is set. Attempting to start Docker..."
        dockerd -s vfs &
        sleep 2 # Give some time for the daemon to potentially start
    fi

    # Check if a `docker run` command succeeds
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        # start local docker registry for sanity ci test
        docker run -d -p $LOCAL_REGISTRY_PORT:$LOCAL_REGISTRY_PORT --name registry --restart always registry.test.pensando.io:5000/pensando/registry:2
        if [ $? -eq 0 ]; then
            echo "Registry is ready."
            return
        fi

        ((RETRY_COUNT++))
        echo "Registry is not ready. Retrying... ($RETRY_COUNT/$MAX_RETRIES)"
        sleep 2
    done

    echo "Docker is not ready after $MAX_RETRIES attempts."
    exit 1
}

function setup_registry() {
    if [[ ${REGISTRY_SELECTION} == "local" ]];
    then
        echo "Setting up local registry"
        start_registry
        REGISTRY="${HOST_IP}:${LOCAL_REGISTRY_PORT}"
    elif [[ ${REGISTRY_SELECTION} == "master" ]];
    then
        echo "Extract master node details, setup registry : TODO"
        exit 1
    elif [[ ${REGISTRY_SELECTION} == "global" ]];
    then
        REGISTRY=${GLOBAL_REGISTRY}
    else
        echo "FATAL ERROR: Invalid registry-selection - ABORT"
        exit 1
    fi
}

function load_images() {
    echo ""
    echo "Run k8_jobd_ctl to "
    echo "    (1) load images into registry : ${REGISTRY}"
    echo "    (2) generate image-manifest-yaml for test"
    /gpu-operator/ci-internal/k8_jobd_ctl.py image --load-images --registry $REGISTRY --image-manifest $IMAGE_MANIFEST --testbed $TESTBED_JSON --setup-insecure-registry
    RET=$?
    if [[ "$RET" != "0" ]]
    then
        echo "FATAL ERROR: Failed load images and generate image-manfiest-yaml "
        exit $RET
    fi
    echo ""

    echo ""
    echo "Run k8_jobd_ctl to "
    echo "    (1) update insecure-registry for each node in the cluster"
    /gpu-operator/ci-internal/k8_jobd_ctl.py image --registry $REGISTRY --testbed $TESTBED_JSON --setup-insecure-registry
    RET=$?
    if [[ "$RET" != "0" ]]
    then
        echo "FATAL ERROR: Failed to setup insecure-registry at each node in the k8 cluster"
        exit $RET
    fi
    echo ""
}

function prepare_cluster() {
    echo "Run k8_jobd_ctl to "
    echo "    (1) reboot worker-nodes"
    echo "    (2) fetch kube-config"
    /gpu-operator/ci-internal/k8_jobd_ctl.py testbed --testbed $TESTBED_JSON --reboot-workers --fetch-kube-config
    RET=$?
    if [[ "$RET" != "0" ]]
    then
        echo "FATAL ERROR: Failed to reboot-worker nodes and/or fetch kube-config from master"
        exit $RET
    fi
    echo ""
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --registry)
            REGISTRY_SELECTION="$2"
            shift
        ;;
        --testbed)
            TESTBED_JSON="$2"
            shift
        ;;
        --image-manifest)
            IMAGE_MANIFEST="$2"
            shift
        ;;
        --help)
            usage
            exit 0
        ;;
        --*)
            echo "Unknown option $1"
            exit 1
        ;;
    esac
    shift
done

function main() {
    echo "Running sanity-setup"
    setup_registry
    load_images
    prepare_cluster
    echo "Completed setting up environment for sanity-run"
}

main
