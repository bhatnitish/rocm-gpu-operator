.DEFAULT: all
.PHONY: all lint

TEST_ARGS = ""
ifdef OPENSHIFT
	TEST_ARGS += "-openshift"
endif

ifdef NOAMDGPU
	TEST_ARGS += "-noamdgpu"
endif

all:
	go test -test.timeout=30m -v $(TEST_ARGS);
lint:
	@go fmt ./...
	@goimports -w ./
	@go vet ./...
