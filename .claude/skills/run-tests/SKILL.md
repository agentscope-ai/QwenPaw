---
name: run-tests
description: Run the appropriate QwenPaw test suite based on changed files. Supports unit, integration, contract, and frontend tests.
---

Determine which tests to run based on the files changed in this session, then execute them using the project's venv.

## Rules

- Changed files under `src/qwenpaw/` → run **unit tests**
- Changed files under `src/qwenpaw/app/channels/` or `scripts/check_channel_contracts.py` → run **contract tests**
- Changed files under `tests/integration/` or multi-module changes → run **integration tests**
- Changed files under `console/` → run **frontend tests**
- If unsure, run unit + contract

## Commands

**Unit tests:**
```bash
.venv/Scripts/python -m pytest tests/unit/ -x -q
```

**Integration tests:**
```bash
.venv/Scripts/python -m pytest tests/integration/ -x -q
```

**Contract tests (channel contracts):**
```bash
.venv/Scripts/python scripts/check_channel_contracts.py
```

**Frontend tests:**
```bash
cd console && npm run test:run
```

**All Python tests with coverage:**
```bash
.venv/Scripts/python -m pytest tests/unit/ tests/integration/ --cov=src/qwenpaw --cov-report=term-missing -q
```

Run the appropriate command(s), show the output, and summarize pass/fail. If tests fail, identify the root cause before suggesting fixes.
