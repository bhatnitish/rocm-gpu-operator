.DEFAULT: all
.PHONY: all lint

all:
	if [ -z ${OPENSHIFT} ]; then \
		go test -v; \
	else \
		go test -v -test.timeout=30m -openshift; \
	fi
lint:
	@go fmt ./...
	@goimports -w ./
	@go vet ./...
