#!/bin/bash

set -xe

if [ ! -z "$START_DOCKER" ]; then
  echo "START_DOCKER is set. Attempting to start Docker..."
  dockerd -s vfs &
  sleep 2 # Give some time for the daemon to potentially start
fi

# Maximum number of retries
MAX_RETRIES=20

# Retry counter
RETRY_COUNT=0

# Check if Docker is running
while ! pgrep -x "dockerd" > /dev/null; do
    ((RETRY_COUNT++))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "Docker is not running after $MAX_RETRIES attempts."
        exit 1
    fi
    echo "Docker is not running. Retrying... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

echo "Docker is running."

make deploy-k8s-kind-1c2w
