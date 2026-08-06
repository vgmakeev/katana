.PHONY: install lint format-check typecheck test node-check check markdown-check build

install:
	uv sync --all-groups

lint:
	uv run ruff check katana tests examples

format-check:
	uv run ruff format --check katana tests examples

typecheck:
	uv run mypy katana

test:
	uv run pytest tests

node-check:
	node --check katana/ast_bridge.mjs

check: lint format-check typecheck test node-check

markdown-check:
	npm ci --ignore-scripts --no-audit --no-fund
	npm run test:markdown-bridge

build:
	uv build
