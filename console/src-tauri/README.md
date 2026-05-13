# QwenPaw Desktop — Tauri shell

This directory contains the Tauri 2.x wrapper that turns the QwenPaw Console
frontend into a self-contained desktop application.

## Architecture

```
Tauri webview  (QwenPaw Console frontend, built from console/src)
    ↕ Tauri IPC (invoke "backend_port")
Rust host      (console/src-tauri/src/lib.rs)
    ↓ spawns
Python backend (src/qwenpaw/desktop_entry.py  –OR–  binaries/qwenpaw-backend)
    ↑ binds 127.0.0.1:<selected-port>
```

The backend port is chosen at runtime by `pick_backend_port()` (tries 8088–8187,
then falls back to a random OS-assigned port). The selected port is passed to
the backend via `QWENPAW_DESKTOP_PORT` and retrieved by the frontend through the
`backend_port` Tauri command.

## CSP note

`tauri.conf.json` allows `connect-src http://127.0.0.1:* ws://127.0.0.1:*`
because the backend port is not known at build time. The wildcard is limited to
the loopback address only, so no remote origin is reachable.

## Supported platforms

| Platform                      | Build target | Status                                           |
| ----------------------------- | ------------ | ------------------------------------------------ |
| macOS (Apple Silicon / Intel) | `dmg`, `app` | Supported                                        |
| Windows 10/11 (x64)           | `nsis`       | Supported                                        |
| Linux                         | —            | Not packaged (dev mode only via `npm run dev:tauri`) |

Windows installers use Tauri's WebView2 download bootstrapper in silent mode.
Machines without the Evergreen WebView2 Runtime need network access during
installation so the runtime can be installed automatically.

## Code signing

Release binaries are currently **unsigned**. macOS users may need to run
`xattr -d com.apple.quarantine "QwenPaw Desktop.app"` after download.
Windows users may see a SmartScreen warning on first launch.

## Version file

`tauri.conf.json` is updated automatically by
`scripts/pack-tauri/sync_tauri_version.mjs` before each build or `dev` run.
The script converts Python PEP 440 versions into Tauri-compatible SemVer.

## Single-window assumption

The application currently has exactly one window (`main`). The backend process
is killed when that window closes, and `RunEvent::ExitRequested` repeats the
cleanup as a process-exit fallback. If a menu-bar or multi-window mode is added
in the future, the window-close handler must become window-count aware while the
exit-event fallback remains in place.
