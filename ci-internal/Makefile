# CICD test image
TEST_CONTAINER_URL ?= registry.test.pensando.io:5000/pensando/gpu-op
TEST_CONTAINER_VERSION ?=1.2

# CHANNELS define the bundle channels used in the bundle.
docker/install_box:
	@if [ ! -x /usr/local/bin/box ]; then echo "Installing box, sudo is required"; curl -sSL pm.test.pensando.io/tools/box-builder/install.sh | sudo bash; fi

docker/build-test-container: docker/install_box
	BOX_INCLUDE_ENV="FLATTEN" FLATTEN=1 box -n -t '${TEST_CONTAINER_URL}:${TEST_CONTAINER_VERSION}' box-deps.rb

docker/release-test-container:
	docker push '${TEST_CONTAINER_URL}:${TEST_CONTAINER_VERSION}'

docker/build-shell-image: docker/install_box
	cd ../; BOX_INCLUDE_ENV="USER USER_UID USER_GID GROUP_NAME HOST_HOSTNAME HOST_WORKSPACE" USER_UID=$$(id -u) USER_GID=$$(id -g) GROUP_NAME=$$(id -gn) HOST_HOSTNAME=$$(hostname) box -t pensando/gpu-operator:test box.rb

docker/shell: docker/build-shell-image
	docker run --rm --privileged --cgroupns=host -v /lib/modules:/lib/modules:ro -v /sys/fs/cgroup:/sys/fs/cgroup --network host --name gpu-operator -v $(shell pwd):/gpu-operator -w /gpu-operator -it pensando/gpu-operator:test su -l $(shell whoami)

deploy-k8s-kind-1c:
	/usr/local/bin/kind create cluster --config=./deploy/kind-config.yaml --name dind-cluster

deploy-k8s-kind-1c2w:
	/usr/local/bin/kind create cluster --config=./deploy/kind-config-1c2w.yaml --name dind-cluster-1c2w
