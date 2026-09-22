SHELL := /bin/bash

.PHONY: help backend frontend contract lint test build

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

backend: ## 启动后端 (dev)
	cd backend && go run ./cmd/server

frontend: ## 启动前端 (dev)
	cd frontend && npm run dev

contract: ## 校验接口契约
	python3 api/check_contract.py api/openapi.yaml

lint: ## 后端 vet + 前端 lint
	cd backend && go vet ./...
	cd frontend && npm run lint

test: ## 后端测试 + 契约校验
	cd backend && go test ./...
	python3 api/check_contract.py api/openapi.yaml

build: ## 构建后端与前端产物
	cd backend && go build -o bin/server ./cmd/server
	cd frontend && npm run build
