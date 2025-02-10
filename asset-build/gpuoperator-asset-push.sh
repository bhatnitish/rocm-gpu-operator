#!/bin/bash

PROJECT_VERSION=${PROJECT_VERSION:-v1.2.0}

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
    cp /gpu-operator/amd-gpu-operator-latest.tar.gz $BUNDLE_DIR/amd-gpu-operator-latest-$RELEASE.tar.gz
    # copy k8s helm package
    cp /gpu-operator/helm-charts-k8s/gpu-operator-helm-k8s-$PROJECT_VERSION.tgz  $BUNDLE_DIR/gpu-operator-helm-k8s-$PROJECT_VERSION-$RELEASE.tgz
    # copy openshift helm package
    cp /gpu-operator/helm-charts-openshift/gpu-operator-helm-openshift-$PROJECT_VERSION.tgz  $BUNDLE_DIR/gpu-operator-helm-openshift-$PROJECT_VERSION-$RELEASE.tgz
    # copy gpu operator OLM bundle package
    cp /gpu-operator/internal-gpu-operator-olm-bundle.tar.gz  $BUNDLE_DIR/internal-gpu-operator-olm-bundle-$RELEASE.tar.gz
    # copy gpu operator OLM bundle package for amdpsdo repository
    cp /gpu-operator/amdpsdo-gpu-operator-olm-bundle.tar.gz $BUNDLE_DIR/amdpsdo-gpu-operator-olm-bundle-$RELEASE.tar.gz
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
    docker load -i /gpu-operator/internal-gpu-operator-olm-bundle.tar.gz
    docker inspect registry.test.pensando.io:5000/amd-gpu-operator-bundle:$PROJECT_VERSION | grep "HOURLY"
    docker tag registry.test.pensando.io:5000/amd-gpu-operator-bundle:$PROJECT_VERSION registry.test.pensando.io:5000/amd-gpu-operator-bundle:$tag
    docker push registry.test.pensando.io:5000/amd-gpu-operator-bundle:$tag
    # load amdpsdo OLM bundle image
    docker load -i /gpu-operator/amdpsdo-gpu-operator-olm-bundle.tar.gz  
    # push final release to docker hub for public access
    if [ -z $DOCKERHUB_TOKEN ]
    then
      echo "DOCKERHUB_TOKEN is not set"
    else
      docker login --username=shreyajmeraamd --password-stdin <<< $DOCKERHUB_TOKEN
      docker tag registry.test.pensando.io:5000/amd-gpu-operator:$tag amdpsdo/gpu-operator:$RELEASE
      docker push amdpsdo/gpu-operator:$RELEASE
      # push OLM bundle images 
      docker tag amdpsdo/gpu-operator-bundle:$tag amdpsdo/gpu-operator-olm-bundle:$RELEASE
      docker push amdpsdo/gpu-operator-olm-bundle:$RELEASE
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
