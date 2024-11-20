#!/bin/bash

PROJECT_VERSION=${PROJECT_VERSION:-v1.0.0}

if [ -z $RELEASE ]
then
  echo "RELEASE is not set, return"

  if [ -z ${DOCKERHUB_TOKEN-} ]
  then
      echo "DOCKERHUB_TOKEN is not set"
  else
      echo "DOCKERHUB_TOKEN is set"
  fi
      
  exit 0
fi

tag_prefix="${RELEASE%-*}"

if [ "$tag_prefix" == "operator-0.0.1" ]; then
  tag="latest"
else
  tag="$tag_prefix"
fi

echo "Copying gpu-operator artifacts and pushing docker image with tag:$tag"

setup_dir () {
    ls -al /gpu-operator/
    BUNDLE_DIR=/gpu-operator/output/
    mkdir -p $BUNDLE_DIR
}

copy_artifacts () {
    # copy gpu-opertar container image
    cp /gpu-operator/amd-gpu-operator-latest.tar.gz $BUNDLE_DIR/
    # copy k8s helm package
    cp /gpu-operator/helm-charts-k8s/gpu-operator-helm-k8s-$PROJECT_VERSION.tgz  $BUNDLE_DIR/
    # copy openshift helm package
    cp /gpu-operator/helm-charts-openshift/gpu-operator-helm-openshift-$PROJECT_VERSION.tgz  $BUNDLE_DIR/
    # copy gpuuperator bundle package
    cp /gpu-operator/amd-gpu-operator-olm-bundle.tar.gz  $BUNDLE_DIR/
    # list the artifacts copied out
    ls -la $BUNDLE_DIR
}

docker_push () {
    # push operator controller image to internal registry
    docker load -i /gpu-operator/amd-gpu-operator-latest.tar.gz
    docker inspect registry.test.pensando.io:5000/amd-gpu-operator:latest | grep "HOURLY"
    docker tag registry.test.pensando.io:5000/amd-gpu-operator:latest registry.test.pensando.io:5000/amd-gpu-operator:$tag
    docker push registry.test.pensando.io:5000/amd-gpu-operator:$tag
    # push OLM bundle image to internal registry
    docker load -i /gpu-operator/amd-gpu-operator-olm-bundle.tar.gz
    docker inspect registry.test.pensando.io:5000/amd-gpu-operator-bundle:latest | grep "HOURLY"
    docker tag registry.test.pensando.io:5000/amd-gpu-operator-bundle:latest registry.test.pensando.io:5000/amd-gpu-operator-bundle:$tag
    docker push registry.test.pensando.io:5000/amd-gpu-operator-bundle:$tag
    # push final release to docker hub for public access
    if [ -z $DOCKERHUB_TOKEN ]
    then
      echo "DOCKERHUB_TOKEN is not set"
    else
      docker login --username=shreyajmeraamd --password-stdin <<< $DOCKERHUB_TOKEN
      docker tag registry.test.pensando.io:5000/amd-gpu-operator:$tag amdpsdo/gpu-operator:$tag
      docker push amdpsdo/gpu-operator:$tag
      docker tag registry.test.pensando.io:5000/amd-gpu-operator-bundle:$tag amdpsdo/gpu-operator-olm-bundle:$tag
      docker push amdpsdo/gpu-operator-olm-bundle:$tag
    fi
}

setup () {
    setup_dir
    copy_artifacts
}

upload () {
    cd $BUNDLE_DIR
    find . -type f -print0 | while IFS= read -r -d $'\0' file;
      do asset-push builds hourly-gpu-operator $RELEASE "$file" ;
      if [ $? -ne 0 ]; then
        exit 1
      fi
    done
}

main () {
  setup
  upload

  # docker push need happen after asset-push in case docker is not fully started yet
  docker_push
}

main

exit 0
