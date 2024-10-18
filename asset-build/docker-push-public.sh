#!/bin/bash

if [ -z $DOCKERHUB_TOKEN ]
then
    echo "DOCKERHUB_TOKEN is not set, return"
      exit 0
fi

docker rmi registry.test.pensando.io:5000/amd-gpu-operator:latest
docker pull registry.test.pensando.io:5000/amd-gpu-operator:latest
docker tag registry.test.pensando.io:5000/amd-gpu-operator:latest amdpsdo/gpu-operator:latest

docker login --username=shreyajmeraamd --password-stdin <<< $DOCKERHUB_TOKEN
docker push amdpsdo/gpu-operator:latest
