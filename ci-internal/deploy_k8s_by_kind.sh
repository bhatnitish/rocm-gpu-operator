#!/bin/bash

set -x

start_registry() {
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
        docker run -d -p 5000:5000 --name registry --restart always registry.test.pensando.io:5000/pensando/registry:2
        if [ $? -eq 0 ]; then
            echo "Registry is ready."
            return 0
        fi

        ((RETRY_COUNT++))
        echo "Registry is not ready. Retrying... ($RETRY_COUNT/$MAX_RETRIES)"
        sleep 2
    done

    echo "Docker is not ready after $MAX_RETRIES attempts."
    return 1
}

# Call the function
start_registry

# Handle the return value
if [ $? -eq 0 ]; then
    echo "Registry is ready, continuing with the script..."
else
    echo "Failed to start registry. Exiting or taking alternative action."
    # You can add other logic here for failure cases
fi

make deploy-k8s-kind-1c2w
