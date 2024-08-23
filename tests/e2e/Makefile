.DEFAULT: all
.PHONY: all lint

all:
	@go test -v
lint:
	@go fmt ./...
	@goimports -w ./
	@go vet ./...
