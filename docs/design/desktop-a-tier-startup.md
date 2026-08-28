# Desktop A-tier startup

## Goal

Make the desktop shell interactive without waiting for the complete Python
runtime, then prioritize the default chat agent while optional capabilities
start independently in the background.

This branch keeps one Python sidecar. A worker is a supervised asynchronous
lifecycle unit inside that process, not a separate operating-system process.
The public `qwenpaw` CLI and its complete skill and plugin behavior remain part
of the product contract.

## Readiness contract

Startup exposes separate monotonic phases instead of one global ready flag:

| Phase | Contract |
| --- | --- |
| `api_ready` | The server can answer lightweight API requests. |
| `chat_core_ready` | The default agent can accept a chat request. |
| `browser_ready` | Browser housekeeping and optional downloads are active. |
| `memory_ready` | Deferred memory indexing and capture workers are active. |
| `channels_ready` | Configured channel connections have started. |
| `plugins_ready` | Installed non-channel plugins and hooks have loaded. |

Failures in an optional worker are reported in startup status and logs. They do
not change API or chat-core readiness. Chat requests received before
`chat_core_ready` may wait for the existing agent readiness primitive; they
must not observe a partially initialized agent.

## Critical path

The synchronous FastAPI lifespan keeps only state required for safe request
handling. Restore cleanup and migrations that protect persisted data remain
blocking. The default chat agent is the first background workload.

These operations must leave the API critical path where dependencies allow:

- descriptor cache warming;
- browser watchdog, bridge-token priming, and managed Chromium download;
- provider catalog synchronization and local-model resume;
- plugin discovery, loading, commands, and startup hooks;
- channel connection startup;
- memory history migration, indexing, and capture-worker warm-up;
- skill-pool automation.

## Desktop shell

The Tauri-hosted bootstrap renders the local desktop shell immediately. It
must not show a full-window Python loading gate. Until an API URL exists, data
surfaces use their normal unavailable/loading states and chat input may queue a
single first submission. Once the backend URL is announced, the shell binds to
it without discarding the queued submission.

## Targets

- desktop shell interactive in less than 1 second on the reference machine;
- Windows packaged `api_ready` P50 at or below 3 seconds;
- Windows packaged `chat_core_ready` P50 at or below 4 seconds;
- optional worker failure does not block chat-core readiness;
- no CLI, plugin, channel, browser, or memory capability is removed.

Formal packaged measurements run in GitHub Actions on Windows and macOS. Local
work is limited to source validation and tests.

## Checklist

- [x] Create `perf/desktop-startup-a-tier` from current `upstream/main`.
- [x] Apply the independently validated provider import deferrals.
- [x] Add a startup coordinator and status API.
- [x] Move the complete desktop app import behind a lightweight ASGI shell.
- [x] Publish API, chat, browser, memory, channel, and plugin readiness.
- [ ] Reduce the remaining synchronous full-app lifespan to its safe minimum.
- [ ] Prioritize default chat-core startup.
- [ ] Move optional capabilities into supervised background workers.
- [ ] Render the local desktop shell without the blocking backend gate.
- [ ] Queue and replay the first chat submission while chat core starts.
- [ ] Add Python, frontend, and Rust tests.
- [x] Add packaged startup milestones and CI comparisons.
- [ ] Run Windows and macOS GitHub Actions builds.
