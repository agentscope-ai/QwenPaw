# Tauri Desktop App — CORS Fix (2026-04-19)

## Problem

The Tauri desktop app frontend is served via Tauri's custom protocol (`https://tauri.localhost`) while API requests go to `http://localhost:8088`. This is a cross-origin request, but the backend had **no CORS middleware** configured (`QWENPAW_CORS_ORIGINS` was empty), causing all API calls from the Tauri webview to fail silently.

## Changes

### 1. `console/.env.production` (new)

Set `VITE_API_BASE_URL=http://localhost:8088` for production builds (`bun build:prod` / `bun tauri build`). Without this, API requests default to same-origin, which doesn't work in the Tauri webview.

### 2. `console/.env.local` (edited)

Added `VITE_API_BASE_URL=http://localhost:8088` for Tauri dev mode (`bun tauri dev`). The frontend runs on Vite port 1420 and needs to reach the backend on 8088.

### 3. `src/qwenpaw/desktop_entry.py` (edited)

Added `QWENPAW_CORS_ORIGINS` env var default so the backend allows Tauri protocol origins:

```python
os.environ.setdefault(
    "QWENPAW_CORS_ORIGINS",
    "tauri://localhost,https://tauri.localhost",
)
```

The backend reads this at startup in `src/qwenpaw/app/_app.py` and adds `CORSMiddleware` when non-empty.

### 4. `scripts/pack-tauri/build_pyinstaller.sh` (bug fix)

Fixed the sidecar copy destination from `console/src-tauri/` to `console/src-tauri/binaries/`. Tauri looks for `externalBin` sidecars in the `binaries/` subdirectory. The old path caused the build to bundle a stale binary that predated the CORS change.

## Verification

- `https://tauri.localhost` origin — allowed, returns `access-control-allow-origin` header
- `tauri://localhost` origin — allowed
- OPTIONS preflight — returns correct `allow-methods`, `allow-headers`, `allow-origin`
- Unauthorized origins (e.g. `evil.com`) — no `allow-origin` header
- App launches, backend starts on port 8088, frontend can reach API
