# Harness instance settings P1 repair

> **For agentic workers:** Use superpowers:subagent-driven-development. Production and tests have separate authors, as explicitly requested by the user.

**Goal:** Concurrent turns with different approvals/models and account status checks must not rebuild a shared backend; genuine busy failures must have explicit responses.

**Architecture:** Add `HarnessSpec.instance_settings_keys: tuple[str, ...] = ()`. The factory receives a deep-copied mapping containing only declared, present instance keys; instance reuse compares that mapping and registration identity. Each `HarnessCallContext.settings` retains a fresh deep copy of all effective request settings. Codex and Qoder declare `("binary",)`. Preserve workspace/generation separation, busy close protection, resource custody and native session mappings.

**Tech Stack:** Python asyncio, existing plugin SDK, pytest and actual ConsoleChannel/HTTP gateway.

**Spec:** User's confirmed P1 report and explicit repair instruction in this chat; the architecture above is the implementer's interface decision within that authorization.

## Global Constraints

- Work in current `refactor/plugin_harness`; preserve unrelated user edits; no merge/push/publish or changes to the user's 9099 server/accounts.
- Separate production author and test author. Production author never edits tests; test author never edits production code. Root coordinates and writes documentation only.
- Concise, colocated changes; no new dependencies or whole-module thread offloading.
- Factories, async clients, registry/lifecycle/task mutation remain on the event loop. Only bounded blocking filesystem work uses existing `run_sync_io()` boundaries.
- Canonical plugin ZIPs may only be updated under `/Users/luohh/Documents/Qwenpaw/harness插件化`.

## Review Focus

- Same workspace/backend, two held turns with different approvals/models: reuse one backend and preserve each request's parameters.
- Status HTTP request while a turn runs: succeeds with matching instance configuration despite omitted turn parameters.
- Nested settings mutation: neither another call nor a constructor snapshot can be changed by a different request.
- Real instance key change during a turn: reject without closing the active backend or creating a replacement, and return explicit `plugin_busy` failure.
- Idle instance-key change and different workspace/plugin generation: continue to replace or isolate instances correctly.

### Task 1: Independent regression tests and production repair

**Production files:** `src/qwenpaw/plugins/harnesses.py`, `src/qwenpaw/runtime/backends/execution.py`, `src/qwenpaw/app/channels/console/channel.py`, `src/qwenpaw/plugins/_harness_http.py`, `plugins/harness/{codex,qoder}/main.py`, and existing SDK documentation/typing declarations if needed.

**Test files:** Existing Harness SDK/bridge/lifecycle/author tests, their fixture, and focused ConsoleChannel/HTTP regressions. Prefer extending existing fixtures over a second host implementation.

- [x] Test author establishes RED evidence before production mutations, including existing-API concurrency/state behavior; records commands/results.
- [x] Production author adds and documents the key-selection contract, declares vendor keys, preserves per-call copies and adds explicit busy SSE/HTTP error handling.
- [x] Test author verifies concurrent differing approvals/models, HTTP status during a held turn, parameter isolation, declared-key busy and idle replacement, and concise public SDK coverage.
- [x] Run affected core Harness and Console regression tests, independent vendor suites and appropriate lint/type checks.
- [x] Fresh review of the scoped repair, spec compliance and code quality; route fixes back to original authors.
- [x] Build current plugin frontends/ZIPs as required, update only canonical ZIP paths, record hashes and distinguish implementation verification from remaining platform/account acceptance.
- [x] Record final evidence and leave a concrete reviewable result without pushing or merging.

Evidence: `docs/research/harness-instance-settings-p1-20261027.md` (local acceptance report), independent role reports under `.superpowers/sdd/2026-10-27-harness-instance-settings/`. Related tests: 131 core/Console + 66 Codex + 38 Qoder = 235 passed. Cached applicable pre-commit hooks and both plugin frontend builds passed; extra broad strict author-fixture analysis was interrupted and is not claimed as passed. Review has no findings. No real-account/platform acceptance or 9099 restart was performed.
