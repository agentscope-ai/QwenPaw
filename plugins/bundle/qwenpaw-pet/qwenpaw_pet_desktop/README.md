# `qwenpaw_pet_desktop` (package internals)

Importable Python package embedded inside the **QwenPaw Pet plugin**.
It ships the desktop runtime: a transparent always-on-top Qt pet
window + a local FastAPI bridge on `127.0.0.1:8765` that QwenPaw (via
the plugin) and other clients drive over HTTP.

Install / run / dependency notes live in the plugin's
[`../README.md`](../README.md). This file documents what is inside the
package itself, for people maintaining it.

The plugin's `plugin.py` puts this folder's parent on `sys.path`, so
the package is importable as `qwenpaw_pet_desktop` from QwenPaw's
interpreter without any `pip install`.

## Module map

| File | Responsibility |
| --- | --- |
| `__init__.py` | Package marker + `__version__`. |
| `__main__.py` | `python -m qwenpaw_pet_desktop` → delegates to `cli.main`. |
| `cli.py` | CLI subcommands (`python -m qwenpaw_pet_desktop ...`): `init`, `start`, `stop`, `status`, `install-pet`, `install-default-pet`, `token`, `switch`, `send`. |
| `app.py` | Qt event loop + uvicorn server in a background thread. Owns two thread-safe queues (`_PET_EVENT_QUEUE`, `_PET_SWITCH_QUEUE`) drained by a `QTimer` on the GUI thread. |
| `server.py` | FastAPI app factory (`build_app`). Defines `/health`, `/event`, `/state`, `/bubble`, `/pet`. Optional bearer-style token guard via `QWENPAW_PET_REQUIRE_TOKEN=1` + `X-QwenPaw-Pet-Token`. |
| `window.py` | `PetWindow(QWidget)`: frameless translucent always-on-top window, sprite animator, speech bubble, drag, right-click menu, `reload_pet()` for hot-switch. |
| `sprites.py` | Atlas constants (192×208 cells, 8×9 grid), per-state animation timing, and event→state mapping table. |
| `runtime.py` | Path resolution, atomic JSON writes, PID file, local update token, process status helpers. |
| `pet_package.py` | Pet package validation (`validate_pet_package`), installation (`install_pet`), default pet resolution, and hot-switch path resolution. |
| `assets/default-pet/snowpaw/` | The bundled default pet (`pet.json` + `spritesheet.webp`). Loaded via `importlib.resources.files("qwenpaw_pet_desktop")`, which resolves relative to this folder on disk (no setuptools install required). |

## Runtime layout

`runtime.home_dir()` defaults to `~/.qwenpaw-pet/` (override with
`QWENPAW_PET_HOME`) and contains:

```text
~/.qwenpaw-pet/runtime/
  state.json         # current pet state + last event (written by PetWindow)
  bubble.json        # latest bubble text + counter
  update-token       # 64-hex-char local token; chmod 0600
  pet-desktop.pid    # JSON: {pid, updatedAt}
  pet-desktop.log    # stdout/stderr of detached `qwenpaw-pet start`
```

Pet **packages** live in a separate location resolved by
`runtime.qwenpaw_working_dir()`, with this precedence:

1. `QWENPAW_WORKING_DIR`
2. `COPAW_WORKING_DIR`
3. `from qwenpaw.constant import WORKING_DIR` (if QwenPaw is installed)
4. `~/.copaw` if it already exists
5. `~/.qwenpaw`

Each installed pet ends up at `<WORKING_DIR>/pets/<pet-id>/`.

## HTTP bridge

Default bind: `127.0.0.1:8765`. All POSTs accept JSON.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness probe + process status. |
| GET | `/state` | Current `state.json` snapshot. |
| GET | `/bubble` | Current `bubble.json` snapshot. |
| GET | `/event` | Lists valid state names (helpful while iterating). |
| POST | `/event` | Drive the pet via a `PetEvent` payload (see `server.py`). Routed through `sprites.state_for_event()`. |
| POST | `/bubble` | Replace bubble text (`text` truncated to 200 chars). |
| POST | `/pet` | Hot-switch the running pet. Body: `{"pet_id": "..."}` **or** `{"pet_dir": "..."}` (exactly one). |

Token check is **on** by default — any process running as the same user
can otherwise drive the floating pet on `127.0.0.1:8765`. Clients must
send `X-QwenPaw-Pet-Token: <token from runtime/update-token>` on
mutating endpoints (the bundled QwenPaw plugin reads the token file
automatically). To disable the check (e.g. for local development), set
`QWENPAW_PET_REQUIRE_TOKEN=0`.

## Event → state mapping

Defined in `sprites.EVENT_TO_STATE`. Callers may also pass an explicit
`state` field in the POST body; if it is one of `sprites.VALID_STATES`
it wins over the `event` mapping.

```text
qwenpaw.startup   -> waving
qwenpaw.shutdown  -> idle
query.received    -> jumping
query.running     -> running
query.first_token -> review
query.done        -> review
tool.detected     -> running
tool.result       -> review
query.cancelled   -> waiting
query.error       -> failed
approval.pending  -> waiting
approval.resolved -> idle
approval.bulk_cancel -> idle
idle              -> idle
```

`PetWindow.apply_event` adds an extra interlock: while
`approval.pending` is the latest lifecycle event, stray empty `idle`
or premature `query.done` events are dropped so the "Approval
required" bubble survives end-of-stream races.

## Pet package contract

A pet folder is valid when:

- `pet.json` exists and contains a non-empty string `"id"` (defaults
  to the folder name if missing) and a non-empty `"spritesheetPath"`.
- `<pet-dir>/<spritesheetPath>` is a real file.
- The spritesheet image is exactly `ATLAS_WIDTH x ATLAS_HEIGHT`
  (`1536 × 1872` = 8 cols × 9 rows of `192 × 208` cells).

The 9 rows are, in order:

```text
0 idle           6 frames
1 running-right  8 frames
2 running-left   8 frames
3 waving         4 frames
4 jumping        5 frames
5 failed         8 frames
6 waiting        6 frames
7 running        6 frames
8 review         6 frames
```

Per-row frame count, frame duration, and last-frame hold come from
`sprites.STATE_SPECS`.

## Threading model

```
┌──────────────────────────── main thread (Qt) ───────────────────────────┐
│ QApplication.exec()                                                     │
│   PetWindow (paints sprite, owns frame_timer)                           │
│   QTimer(40ms) ──drains──▶ _PET_SWITCH_QUEUE ─▶ window.reload_pet(path) │
│                  └─drains▶ _PET_EVENT_QUEUE  ─▶ window.apply_event(...) │
└─────────────────────────────────────────────────────────────────────────┘
                ▲                              ▲
                │ enqueue_switch_pet(path)     │ enqueue_pet_event(payload)
                │                              │
┌────────── uvicorn worker thread (daemon) ──┴──────────────────────────┐
│ FastAPI handlers in server.py                                          │
└────────────────────────────────────────────────────────────────────────┘
```

Background threads **never** touch `QWidget` state directly; they only
push to the queues. The 40 ms `QTimer` keeps reload + event drains on
the GUI thread.

## Running the package directly

These two are equivalent and bypass the `qwenpaw-pet start` daemon
wrapper (no PID file, no log redirection — useful while iterating):

```bash
python -m qwenpaw_pet_desktop.app --port 8765 --scale 0.58
python -m qwenpaw_pet_desktop                 # → cli.main, takes subcommands
```

Quick event smoke test once the window is up:

```bash
curl -X POST http://127.0.0.1:8765/event \
  -H 'Content-Type: application/json' \
  -d '{"event":"query.running","text":"Thinking"}'
```

## Adding a new bundled pet

1. Drop a Codex-compatible package under
   `assets/default-pet/<pet-id>/` (`pet.json` + `spritesheet.webp`).
2. To make it the **default**, update the path returned by
   `pet_package.bundled_default_pet_dir()`.

(No `pyproject.toml` step: this package is loaded straight off disk
through the plugin's `sys.path` injection, not installed via
setuptools.)

The current bundled default is **Snowpaw**
(`assets/default-pet/snowpaw/`).
