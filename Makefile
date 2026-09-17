# CoPaw Test & Coverage Makefile

.PHONY: test test-unit test-contract test-integration test-channel test-channel-contract coverage-full clean gen-browser-manual install-dev install-mail-mcp

# Cross-platform default (override with: make PYTHON=python3.12 <target>)
PYTHON ?= python
PYTEST := $(PYTHON) -m pytest

# Default: run all tests
test:
	$(PYTEST) tests/ -v --tb=short -q

# Unit tests only
test-unit:
	$(PYTEST) tests/unit/ -v --tb=short

# Contract tests (interface compliance)
test-contract:
	$(PYTEST) tests/contract/ -v --tb=short

# Integration tests
test-integration:
	$(PYTEST) tests/integration/ -v --tb=short

# Full coverage (all modules)
coverage-full:
	$(PYTEST) tests/unit/ tests/integration/ -v \
		--cov=src/qwenpaw \
		--cov-report=term-missing \
		--cov-report=html

# Check contract coverage for all channels
check-contracts:
	$(PYTHON) scripts/check_channel_contracts.py

# Clean generated files
clean:
	rm -rf htmlcov/ .pytest_cache/
	rm -f coverage.xml coverage-sa.xml .coverage

# Quick check (fast feedback)
quick:
	@qp_test_workdir=$$(mktemp -d); \
	trap 'rm -rf "$$qp_test_workdir"' EXIT; \
	QWENPAW_WORKING_DIR="$$qp_test_workdir" \
	$(PYTEST) tests/unit/ -x -q --tb=line

gen-browser-manual:
	$(PYTHON) scripts/gen_browser_manual.py

# Channel-specific tests
test-channel:
	@echo "Running Channel unit tests..."
	$(PYTEST) tests/unit/channels/ -v --tb=short

test-channel-contract:
	@echo "Running Channel contract tests..."
	$(PYTEST) tests/contract/channels/ -v --tb=short

# BaseChannel core unit tests (optional, not enforced)
test-base-core:
	$(PYTEST) tests/unit/channels/test_base_core.py -v

## Install the project and bundled mail MCP for development.
install-dev:
	$(PYTHON) -m pip install -e .

## Install only the standalone mail MCP package.
install-mail-mcp:
	$(PYTHON) -m pip install -e packages/qwenpawmail-mcp
