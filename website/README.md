# QwenPaw Website

Static site (Vite + React) for the QwenPaw product. Built output is served with a minimal Node server that supports SPA fallback (e.g. direct access to `/docs/channels`).

## Prerequisites

- Node.js 18+
- pnpm (recommended) or npm

## Install

```bash
pnpm install
# or
npm install
```

## Development

```bash
pnpm run dev
# or
npm run dev
```

Dev server runs at `http://localhost:5173` (or the next free port).

## Build

```bash
pnpm run build
# or
npm run build
```

Output is in `dist/`.

## Preview (local only)

- **Vite preview** (quick local check):
  `pnpm run preview`

- **Production-style server** (same as prod, no PM2):
  `pnpm run preview:prod`
  Serves `dist/` at `http://localhost:8088` with SPA fallback.

## Production with PM2

Use PM2 to run the preview server in production: auto-restart on crash, logs, and easy start/stop.

### 1. Install PM2 globally (one-time)

```bash
npm install -g pm2
```

If the script runs without global PM2, it will try to install it automatically.

### 2. Build and start

```bash
cd website
pnpm run build
pm2 start ecosystem.config.cjs
```

Or from repo root (install + build + PM2 start/reload):

```bash
bash scripts/website_build.sh
```

Or use the helper script (installs PM2 if missing, then starts):

```bash
bash scripts/start.sh
```

Default port: **8088**. Override with `PORT=3000 pm2 start ecosystem.config.cjs` or by editing `ecosystem.config.cjs`.

### 3. PM2 commands

| Command                                        | Description                               |
| ---------------------------------------------- | ----------------------------------------- |
| `pm2 status`                                   | List apps and status                      |
| `pm2 logs qwenpaw-website`                     | Stream stdout/stderr logs                 |
| `pm2 restart qwenpaw-website`                  | Restart the app                           |
| `pm2 reload ecosystem.config.cjs --update-env` | Reload with latest config (zero-downtime) |
| `pm2 stop qwenpaw-website`                     | Stop the app                              |
| `pm2 delete qwenpaw-website`                   | Remove from PM2 (stop + delete)           |

### 4. After code/build changes

Rebuild then reload so PM2 serves the new `dist/`:

```bash
pnpm run build
pm2 reload ecosystem.config.cjs --update-env
```

Or from repo root:

```bash
bash scripts/website_build.sh
```

## Config

- **Port**: Set in `ecosystem.config.cjs` (`env.PORT` / `args`) or env `PORT`. Default `8088`.
- **App name**: `qwenpaw-website` in `ecosystem.config.cjs` (used in `pm2 logs/restart`).
