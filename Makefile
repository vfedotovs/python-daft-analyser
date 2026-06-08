# Makefile for python-daft-analyser
#
# Common developer and deployment tasks. The Python environment is managed
# with uv; the container is driven through deploy/docker-compose.yml.

COMPOSE := docker compose -f deploy/docker-compose.yml

.DEFAULT_GOAL := help

.PHONY: help setup test docker-build docker-run docker-stop clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create the uv virtualenv, install dependencies, download Chromium
	uv sync --extra test --extra upload
	uv run playwright install chromium

test: ## Run the offline unit test suite
	uv run pytest -m "not integration"

docker-build: ## Build the scraper Docker image
	$(COMPOSE) build

docker-run: ## Start the scraper container (detached; needs a .env at repo root)
	$(COMPOSE) up -d

docker-stop: ## Stop and remove the scraper container
	$(COMPOSE) down

clean: ## Remove the virtualenv, caches, build artifacts, and scraper outputs
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache
	rm -rf build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} +
	rm -rf data
