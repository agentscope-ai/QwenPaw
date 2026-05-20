# Integration Tests

[简体中文](README_zh.md)

HTTP smoke tests that exercise the QwenPaw FastAPI app end-to-end via a
real subprocess. Each test file owns its own QwenPaw app subprocess on a
random port, with isolated workspace directories — no real API keys or
external services required.

---

## Running

```bash
# Full suite (~3 minutes)
make test-integration
# or directly:
pytest tests/integration/ --no-cov

# By priority (PR / nightly / broad)
pytest tests/integration/ -m p0 --no-cov   # ~2 min, PR smoke gate
pytest tests/integration/ -m p1 --no-cov   # nightly / merge regression
pytest tests/integration/ -m p2 --no-cov   # error paths and contracts

# Single file
pytest tests/integration/test_agents.py -v --no-cov

# Single test
pytest tests/integration/test_agents.py::test_api_agents_list_create_get_delete -v --no-cov
```

Tests run sequentially (not validated under `pytest-xdist`). Use `--no-cov`
to skip parent-process coverage; see [Coverage](#coverage-optional) for
subprocess coverage.

---

## Priority markers

Tests are tagged by **user-facing impact**, not technical complexity. When
adding a test, ask:

> *"If this fails, can users still send a message and get a reply?"*
> Yes → `p1` or `p2`. No → `p0`.

### `p0` — Critical (PR smoke gate)

Failure means the product is essentially unusable. Every PR must pass
these. Covers:

- **Messaging main path** — `/api/messages/send` core flow, default-agent
  routing
- **Agent / Chat / Skills core CRUD** — list/create/get/delete, toggle
  enabled, system prompt files
- **Global config** — channels, heartbeat, MCP CRUD, workspace running
  config
- **Security guards (global)** — file guard, tool guard, skill scanner
- **Tools toggle** — affects agent capabilities at runtime
- **API version** — base health check

Run: `pytest -m p0` (~22 tests, ~2 min).

### `p1` — Supported (nightly / merge regression)

Failure causes degradation but defaults still let users get by. Covers:

- **Settings & scoped overrides** — language, audio mode, timezone,
  transcription provider, scoped versions of channel/heartbeat/guards
- **Workspace files** — working/memory file CRUD, zip up/down, scoped
  consistency
- **ACP / LLM routing** — developer-facing features
- **Plan / Cron** — assistive features
- **Statistics** — token usage, plugins/backups list, agent stats, auth
  status
- **Helper APIs** — files preview, agent ordering, batch operations

Run: `pytest -m p1` (~53 tests).

### `p2` — Contracts (broad coverage)

Boundary behavior with no main-flow impact. Covers:

- **Validation rejection** — `*_rejected` tests (duplicate names, invalid
  payload, non-zip uploads)
- **404 handling** — `*_returns_404`, `missing_*` tests
- **Partial-success branches** — batch operations with some failures
- **Isolation boundaries** — `*_isolated_*`, cross-agent edge cases
- **HEAD requests & contracts** — `*_minimal_contract`, file-preview HEAD
- **Version metadata** — package version, PEP 440 compliance

Run: `pytest -m p2` (~30 tests).

---

## Layout

| File | Coverage |
|---|---|
| `test_agents.py` | Agent CRUD, ordering, toggle |
| `test_chats_global.py` | Global `/api/chats` (CRUD, batch, isolation) |
| `test_chats_agent_scoped.py` | Agent-scoped chats |
| `test_workspace_files.py` | Working/memory files, zip up/down |
| `test_workspace_running_config.py` | Running config (global + scoped) |
| `test_workspace_agent_settings.py` | Agent-scoped workspace settings (language, audio, prompt, transcription, memory) |
| `test_heartbeat.py` | Heartbeat config (global + scoped) |
| `test_channels_config.py` | Channels config + health/restart |
| `test_security_config.py` | File guard, tool guard, skill scanner |
| `test_agent_routing_config.py` | ACP, LLM routing, allow-no-auth, timezone |
| `test_skills_global.py` | Global skills (CRUD, batch, validation) |
| `test_skills_agent_scoped.py` | Agent-scoped skills |
| `test_mcp.py` | MCP clients lifecycle |
| `test_messages_files.py` | Send messages + file preview |
| `test_plan.py` | Plan config |
| `test_cron.py` | Agent-scoped cron jobs |
| `test_console.py` | Console-specific endpoints (chat stop, upload) |
| `test_console_metadata.py` | Plugins / backups / token-usage / auth / agent-stats list |
| `test_settings_envs.py` | Settings + persisted env vars |
| `test_tools.py` | Tools toggle and async execution |
| `test_app_startup.py` | App readiness, console entry/fallback |
| `test_version.py` | Package version metadata (no app subprocess) |

---

## How `app_server` works

`tests/integration/conftest.py::app_server` is **module-scoped**: each
test file gets its own QwenPaw app subprocess on a random port, sharing
the subprocess across all tests within the file. Cross-module isolation
is achieved by re-launching with a fresh tmp dir.

**Tests must use unique resource ids within the module** (e.g.
`agent_id = "integ_<scope>_01"`) to avoid collisions inside the shared
subprocess. The existing convention already does this.

The fixture:

- Sanitizes 11 sensitive environment variables (`OPENAI_API_KEY`,
  `DASHSCOPE_API_KEY`, IM tokens, etc.) before launching
- Forces `QWENPAW_AUTH_ENABLED=false` and `NO_PROXY=*`
- Allocates a random free port via `socket.bind(0)`
- Polls `/api/version` for up to 60s as the readiness signal
- Uses **SIGINT** at teardown so uvicorn's atexit hooks flush state and
  subprocess coverage data writes correctly (SIGTERM often skips this)
- Uses a **15s HTTP timeout** to absorb cold-start delays (e.g. ACP
  getter on first hit takes 4-5s)

---

## Coverage (optional)

The default `pytest --cov` only sees the test process, which has near-zero
coverage of the actual app. To collect coverage from the **app
subprocess**:

```bash
QWENPAW_INTEGRATION_COVERAGE=1 pytest tests/integration/ --no-cov
```

This:

1. Writes a coverage rcfile under `.integration_coverage/` with absolute
   `source=…/src/qwenpaw`
2. Runs each subprocess with `COVERAGE_PROCESS_START` and `COVERAGE_FILE`
3. After the session, combines parallel data files and writes
   `htmlcov-integration/index.html`

> ⚠️ Always pass `--no-cov` when using this mode — `pytest-cov` on the
> parent process would otherwise enforce `fail_under=30` on near-zero
> host-process coverage and fail the run.

This flow is **not validated under `pytest-xdist`**.

---

## Adding a new test

1. **Pick the right file** by business subdomain (see [Layout](#layout))
   or create a new `test_<subdomain>.py`.
2. **Tag priority** with `@pytest.mark.integration` plus one of
   `@pytest.mark.p0` / `p1` / `p2` (see [Priority markers](#priority-markers)).
3. **Use unique resource ids** within the module (e.g.
   `integ_<feature>_<seq>`).
4. **Document the case** at the top of the function — purpose, flow,
   API endpoints touched. Use existing tests as template:

   ```python
   @pytest.mark.integration
   @pytest.mark.p1
   def test_my_feature_put_get_roundtrip(app_server) -> None:
       """Test purpose:
       - Verify ...

       Test flow:
       1. ...

       API endpoints:
       - PUT ...
       - GET ...
       """
   ```

5. **Always pass `app_server.logs_tail()`** to assertion messages so
   failures show backend logs:

   ```python
   assert resp.status_code == 200, app_server.logs_tail()
   ```

---

## Known constraints

- **Sequential only**: not validated under `pytest-xdist`.
- **Cold-start cost**: each module re-launches the app subprocess
  (~4s setup). Full suite ~3 min; P0 set ~2 min.
- **No real LLM calls**: messaging tests use the `console` channel and do
  not exercise model providers.
- **No real channel I/O**: only configuration-layer tests for channels;
  IM webhook/long-poll paths are not covered here.
- **Coverage mode is single-worker**: `QWENPAW_INTEGRATION_COVERAGE=1`
  cannot be combined with `pytest-xdist`.
