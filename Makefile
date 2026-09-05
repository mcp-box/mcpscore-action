.DEFAULT_GOAL := help

.PHONY: install
install: ## Install for development
	uv sync --all-groups

.PHONY: format
format: ## Auto-format code
	uv run ruff check --fix
	uv run ruff format

.PHONY: lint
lint: ## Lint code (no auto-fix)
	uv run ruff check
	uv run ruff format --check

.PHONY: typecheck
typecheck: ## Type check with pyright
	uv run pyright

.PHONY: test
test: ## Run unit tests
	uv run pytest -q

.PHONY: workflows
workflows: ## Audit the GitHub workflows with zizmor (pinned, as CI does)
	uvx zizmor==1.27.0 --no-progress .github/workflows/

.PHONY: all
all: lint typecheck test workflows ## Run all checks (mirrors CI's check job)

.PHONY: release
release: ## Cut a release: create the GitHub Release; publish.yml then moves the major tag
	uv run python scripts/release.py

.PHONY: release-dry-run
release-dry-run: ## Run all release checks without creating anything
	uv run python scripts/release.py --dry-run

.PHONY: help
help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'
