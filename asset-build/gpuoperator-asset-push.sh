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
    cp /gpu-operator/helm-charts-k8s/gpu-operator-0.0.1.tgz  $BUNDLE_DIR/gpu-operator-k8s-0.0.1.tgz
    # copy openshift helm package
    cp /gpu-operator/helm-charts-openshift/gpu-operator-0.0.1.tgz  $BUNDLE_DIR/gpu-operator-openshift-0.0.1.tgz
    # copy gpuuperator bundle package
    cp /gpu-operator/amd-gpu-operator-bundle.tar.gz  $BUNDLE_DIR/
    # list the artifacts copied out
    ls -la $BUNDLE_DIR
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
}

main
exit 0
