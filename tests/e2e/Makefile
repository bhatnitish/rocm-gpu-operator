.DEFAULT: all
.PHONY: all lint

TEST_ARGS = ""
ifdef OPENSHIFT
	TEST_ARGS += "-openshift"
endif

ifdef SIM_ENABLE
	TEST_ARGS += "-simEnable"
endif

all:
	go test -test.timeout=360m -v $(TEST_ARGS);
lint:
	@go fmt ./...
	@goimports -w ./
	@go vet ./...
