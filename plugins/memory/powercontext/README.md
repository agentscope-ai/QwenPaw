# PowerContext Memory Backend

[中文文档](README_ZH.md)

The PowerContext Memory plugin connects QwenPaw to a separately deployed
[PowerContext](https://github.com/oceanbase/powercontext) server. It provides a
remote memory scope for durable task state, explicit remembering, and retrieval
across conversations.

## Capabilities

- Saves a bounded task-state snapshot through QwenPaw's automatic memory workflow.
- Automatically retrieves relevant memories before normal user turns.
- Exposes governed `memory_search` and `memory_remember` tools to the Agent.
- Supports current Atomic Memory search results and preserves their exact
  Artifact references and state versions. Legacy v0.2 search-result citations
  remain supported.
- Supports optional bearer-token authentication, configurable timeouts, result
  limits, and a total UTF-8 byte budget for automatically injected context.
- Creates or reuses an installation- and Agent-specific default Scope when no
  explicit Scope is configured; Agents can share an existing Scope intentionally.

Automatic recall and post-turn persistence are configuration-driven network
operations. The Agent-visible tools are governed network operations. Use only
a server and scope suitable for the data being stored.

## Quick Start

### 1. Start a PowerContext server

Install the pinned PowerContext v1.4.0 release for a local server:

```bash
uv tool install "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@powercontext-v1.4.0"
powercontext server run
```

The default local endpoint is `http://127.0.0.1:8000`. QwenPaw does not install
or start the PowerContext server automatically.

### 2. Build the configuration UI

From the QwenPaw source checkout:

```bash
cd plugins/memory/powercontext/frontend
npm ci
npm run build
cd ../../../../
```

### 3. Install the plugin

```bash
qwenpaw plugin install plugins/memory/powercontext
```

When QwenPaw is stopped, start it after installation. When it is running, the
CLI uses the hot-install API. Add `--force` when reinstalling an existing copy.

### 4. Configure an Agent

In the Console, open the Agent's running configuration, select
**PowerContext**, and set:

- **Server URL**: the PowerContext endpoint.
- **Access token**: an optional bearer token.
- **Memory scope**: leave empty to create or reuse this Agent's default Scope,
  or enter the ID of an existing Scope that the token can access. Use the same
  explicit Scope ID only when Agents should share memory.
- **Request timeout**: 1–60 seconds.
- **Automatic memory recall**: enable it and configure the result limit and
  injected-context byte budget.

Save the configuration. The Console schedules an Agent reload so the new
backend instance uses the saved settings; a full QwenPaw process restart is not
required. The equivalent `agent.json` fragment is:

```json
{
  "running": {
    "memory_manager_backend": "powercontext",
    "memory_backend_configs": {
      "powercontext": {
        "base_url": "http://127.0.0.1:8000",
        "token": "",
        "scope_id": "",
        "timeout": 10.0,
        "auto_memory_search_config": {
          "enabled": true,
          "max_results": 3,
          "max_context_bytes": 12000
        }
      }
    }
  }
}
```

`memory_backend_configs.powercontext` is the configuration location. The
former core-owned `powercontext_memory_config` field is no longer supported.
On first start after upgrading, the plugin adopts the former root
`powercontext_installation_id` into
`plugin-state/memory-powercontext/installation-id` under the canonical QwenPaw
working directory. This preserves the installation identity even when an Agent
uses a custom workspace path.

With an empty `scope_id`, the plugin first looks for the previously registered
Scope `qwenpaw:<installation_id>:agent:<agent_id>` and reuses it when present.
Otherwise, it calls `POST /v1/scopes` with a stable idempotency key and uses the
server-assigned `scp_...` Scope ID. The key is specific to the installation and
Agent, so restarting with the same identity reuses the same Scope. Copying the
QwenPaw working directory also copies its installation identity; that copy
shares the default Scope for the same Agent ID.

An explicit `scope_id` must already exist in PowerContext and be accessible to
the token. The plugin binds to that Scope; it does not replace it or create a
different Scope when access fails.

Default Scope creation and replay of the creation request require
`server.admin`. Reading an explicit Scope requires `scope.read`; remembering
requires `scope.contribute`. For restricted tokens, have an administrator
create the Scope, grant the required permissions, and configure its ID
explicitly.

### 5. Verify

```bash
qwenpaw plugin list
```

Confirm that `memory-powercontext` is installed. Ask the Agent to remember a
fact and retrieve it in a later turn. If the backend does not start, verify the
server URL, token, and server availability in the QwenPaw logs.

## Requirements

- A reachable PowerContext server; v1.4.0 is the recommended release.
- QwenPaw with memory-backend plugin support.
- The Python packages in `requirements.txt`; the plugin installer installs
  these automatically.

## Development

Backend code lives in `backend/`; the Console extension lives in `frontend/`.
After changing the frontend, rebuild it and reinstall the plugin:

```bash
qwenpaw plugin install plugins/memory/powercontext --force
```

Real HTTP tests with separate SQLite databases passed on PowerContext
[v1.4.0 (`cab054db`)](https://github.com/oceanbase/powercontext/commit/cab054dbf6d86e2311b079388e5158178257def2),
[master (`fe50f894`)](https://github.com/oceanbase/powercontext/commit/fe50f89406153121883d278c7fe89ea272cd894b),
and legacy [v0.2 (`685b31dd`)](https://github.com/oceanbase/powercontext/commit/685b31dd2961df5e31daa565f87d004755ebd2cf).
The four tests per version cover default Scope creation and reuse, explicit
Scopes, manual and queued writes, search with exact references, recall after
restarting the backend, and Agent/installation isolation. These tests exercise
the plugin backend without a live QwenPaw model session.

Running `pytest plugins/memory/powercontext/tests` skips the real HTTP tests
unless `POWERCONTEXT_TEST_URL` is set. To run them, start a separate disposable
test server with authentication disabled, then run:

```bash
POWERCONTEXT_TEST_URL=http://127.0.0.1:8000 pytest plugins/memory/powercontext/tests/test_server_integration.py
```

The tests create persistent Scopes and memories. Use a dedicated test database
and discard it afterward.
