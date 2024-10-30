#!/bin/bash

if [ -z $DOCKERHUB_TOKEN ]
then
    echo "DOCKERHUB_TOKEN is not set, return"
      exit 0
fi

PUBLIC_TAG=${PUBLIC_TAG:-latest}
PRIVATE_TAG=${PRIVATE_TAG:-latest}

docker rmi registry.test.pensando.io:5000/amd-gpu-operator:$PRIVATE_TAG
docker pull registry.test.pensando.io:5000/amd-gpu-operator:$PRIVATE_TAG
docker tag registry.test.pensando.io:5000/amd-gpu-operator:$PRIVATE_TAG amdpsdo/gpu-operator:$PUBLIC_TAG

docker login --username=shreyajmeraamd --password-stdin <<< $DOCKERHUB_TOKEN
docker push amdpsdo/gpu-operator:$PUBLIC_TAG
