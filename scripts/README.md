# Scripts

Run from **repo root**.

## Desktop packaging (macOS / Windows)

- **Shared:** `scripts/pack/` — PyInstaller deps helper (`pyi_project_deps.py`) and desktop launchers (`gui_launcher.py`, `dev_gui_launcher.py`) used by macOS and future Windows builds.
- **macOS:** `scripts/macos/` — build `.app` and DMG. See [scripts/macos/README.md](macos/README.md).
  `bash scripts/macos/build_dmg.sh [VERSION] [--dev]`
- **Windows:** `scripts/windows/` — placeholder for future Windows build (exe/installer).

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
