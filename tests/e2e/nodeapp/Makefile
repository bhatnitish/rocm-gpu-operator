DOCKER_REGISTRY ?= registry.test.pensando.io:5000
IMAGE_NAME ?= nodeapp
IMAGE_TAG ?= dev
IMAGE_TAG_BASE ?= $(DOCKER_REGISTRY)/$(IMAGE_NAME)
IMG ?= $(IMAGE_TAG_BASE):$(IMAGE_TAG)

checks:
	gofmt -l -s -w .
	golint ./...
	go vet ./...
	goimports -local "github.com/pensando/sw" -l -w -d `find . -name "*.go"`

build:
	go build -o nodeapp cmd/main.go

docker-build: build
	rm -f id_rsa*
	ssh-keygen -t rsa -b 4096 -C "" -N "" -f id_rsa
	chmod +x docker-entrypoint.sh
	docker build -t $(IMG) .

docker-push:
	docker push $(IMG)

clean:
	rm -f id_rsa* nodeapp
