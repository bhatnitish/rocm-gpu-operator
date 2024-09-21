#!/bin/bash

if [ -z $RELEASE ]
then
  echo "RELEASE is not set, return"
  exit 0
fi

echo "Copying gpu-operator artifacts..."

setup_dir () {
    ls -al /gpu-operator/
    BUNDLE_DIR=/gpu-operator/output/
    mkdir -p $BUNDLE_DIR
}

copy_artifacts () {
    # copy gpu-opertar container image
    cp /gpu-operator/amd-gpu-operator-latest.tar.gz $BUNDLE_DIR/
    # copy k8s helm package
    cp /gpu-operator/helm-charts-k8s/gpu-operator-helm-k8s-0.0.1.tgz  $BUNDLE_DIR/
    # copy openshift helm package
    cp /gpu-operator/helm-charts-openshift/gpu-operator-helm-openshift-0.0.1.tgz  $BUNDLE_DIR/
    # copy gpuuperator bundle package
    cp /gpu-operator/amd-gpu-operator-olm-bundle.tar.gz  $BUNDLE_DIR/
    # list the artifacts copied out
    ls -la $BUNDLE_DIR
}

docker_build_push () {
    docker load -i /gpu-operator/amd-gpu-operator-latest.tar.gz
    echo "FROM registry.test.pensando.io:5000/amd-gpu-operator:latest" | docker build --label HOURLY_TAG=$RELEASE -t "registry.test.pensando.io:5000/amd-gpu-operator:latest" -
    docker push registry.test.pensando.io:5000/amd-gpu-operator:latest
}

setup () {
    setup_dir
    docker_build_push
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
}

main
exit 0
