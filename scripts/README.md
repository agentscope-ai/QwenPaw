# Scripts

Run from **repo root**.

## Bootstrap local dev environment

```bash
bash scripts/bootstrap_dev.sh
```

- Creates or repairs `.venv` in the repo root using a supported Python version.
- Installs the project in editable mode with `.[dev]` by default.
- Pass `--extras dev,full` to include the full optional dependency set.
- Pass `--recreate` to force rebuilding `.venv` from scratch.

## Build wheel (with latest console)

```bash
bash scripts/wheel_build.sh
```

- Builds the console frontend (`console/`), copies `console/dist` to `src/copaw/console/dist`, then builds the wheel. Output: `dist/*.whl`.

## Build website

```bash
bash scripts/website_build.sh
```

- Installs dependencies (pnpm or npm) and runs the Vite build. Output: `website/dist/`.

## Build Docker image

```bash
bash scripts/docker_build.sh [IMAGE_TAG] [EXTRA_ARGS...]
```

- Default tag: `copaw:latest`. Uses `deploy/Dockerfile` (multi-stage: builds console then Python app).
- Example: `bash scripts/docker_build.sh myreg/copaw:v1 --no-cache`.

## Local merge gate

```bash
bash scripts/local-gate.sh
```

- Runs a minimal local quality gate for merge-risk regressions.
- Includes: sync status check, console build, backend smoke checks, knowledge route check, and i18n missing-key audit.
- Exits with non-zero status on first failure.
- Run full backend unit tests in strict mode:

```bash
LOCAL_GATE_STRICT=1 bash scripts/local-gate.sh
```

## Run Test

```bash
# Run all tests
python scripts/run_tests.py

# Run all unit tests
python scripts/run_tests.py -u

# Run unit tests for a specific module
python scripts/run_tests.py -u providers

# Run integration tests
python scripts/run_tests.py -i

# Run all tests and generate a coverage report
python scripts/run_tests.py -a -c

# Run tests in parallel (requires pytest-xdist)
python scripts/run_tests.py -p

# Show help
python scripts/run_tests.py -h
```