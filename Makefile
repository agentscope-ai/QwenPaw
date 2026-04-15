# CoPaw Test & Coverage Makefile

.PHONY: test test-unit test-contract test-integration test-channel test-channel-contract coverage-sa coverage-html clean

# Python path
PYTHON := ./venv/bin/python
PYTEST := ./venv/bin/pytest

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

# S-A modules coverage (Critical + Core)
coverage-sa:
	@echo "Running coverage for S级/A级 modules..."
	$(PYTEST) tests/unit/ -v \
		--cov-config=.coveragerc-s-a-only \
		--cov-report=term-missing \
		--cov-report=html
	@echo "HTML report: htmlcov-sa/index.html"

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
	rm -rf htmlcov/ htmlcov-sa/ .pytest_cache/
	rm -f coverage.xml coverage-sa.xml .coverage

# Quick check (fast feedback)
quick:
	$(PYTEST) tests/unit/ -x -q --tb=line

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
