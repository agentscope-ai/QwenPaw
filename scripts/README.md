# Scripts

Run from **repo root**.

## Build wheel (with latest console)

```bash
bash scripts/wheel_build.sh
```

- Builds the console frontend (`console/`), copies `console/dist` to `src/qwenpaw/console/dist`, then builds the wheel. Output: `dist/*.whl`.

## Build website

```bash
bash scripts/website_build.sh
```

- Installs dependencies (pnpm or npm) and runs the Vite build. Output: `website/dist/`.

## Build Docker image

```bash
bash scripts/docker_build.sh [IMAGE_TAG] [EXTRA_ARGS...]
```

- Default tag: `qwenpaw:latest`. Uses `deploy/Dockerfile` (multi-stage: builds console then Python app).
- Example: `bash scripts/docker_build.sh myreg/qwenpaw:v1 --no-cache`.

### Build the offline-ready image (Office/PDF toolchain)

The default image does not preinstall the Office/PDF toolchain; the `docx`,
`pptx`, `xlsx`, and `pdf` skills install what they need at task time. For
offline or air-gapped deployments, build the variant that bakes in
LibreOffice, pandoc, poppler, qpdf, tesseract, and the matching Python/npm
libraries:

```bash
DOCKERFILE=deploy/Dockerfile.offline bash scripts/docker_build.sh qwenpaw:offline
```

- The variant is much larger than the default image (~2 GB extra for the
  system packages).
- `deploy/Dockerfile` is left untouched; `deploy/Dockerfile.offline` is a copy
  that adds the toolchain, so keep the shared parts in sync when either file
  changes.

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