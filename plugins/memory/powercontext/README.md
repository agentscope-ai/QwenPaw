# PowerContext Memory Backend

[中文文档](README_ZH.md)

The PowerContext Memory plugin connects QwenPaw to a separately deployed
[PowerContext](https://github.com/oceanbase/powercontext) server. It provides a
remote Scope for context preparation, durable task state, explicit remembering,
and Artifact access across conversations.

## Capabilities

- Prepares context before normal user turns. By default, the ordered sections
  are Profile (1), Topic Memory (2), Memory (3), and Experience (2).
- Saves a bounded task-state snapshot through QwenPaw's automatic memory workflow.
- Exposes `prepare_context`, two memory tools, and seven Artifact tools as
  governed network operations.
- Preserves exact Artifact references and state versions. Explicit legacy memory
  mode also supports the citation format returned by PowerContext v0.2.
- Supports optional bearer-token authentication, configurable timeouts, and a
  total UTF-8 byte budget for automatically injected context.
- Creates or reuses an installation- and Agent-specific default Scope when no
  explicit Scope is configured; Agents can share an existing Scope intentionally.

Automatic recall and post-turn persistence are configuration-driven network
operations. Use a server and Scope suitable for the data being stored.

### Automatic context

The default `auto_memory_search_config.mode` is `prepare`. The plugin sends the
user query to PowerContext's context preparation endpoint, preserving up to
8,192 characters after trimming surrounding whitespace. It uses the returned Markdown content without rewriting or truncating
it. `max_context_bytes` limits the complete injected message, including its
wrapper, in UTF-8 bytes; a response that cannot fit is not injected.

`context_assembly.sections` defines the included families and their order. Each
family can appear once, with a limit of 1–8; Experience is limited to 1–2. An empty
list requests no context. The default server allows a total section limit of 8;
a server may configure a different total, which it validates. The plugin accepts
per-family limits without imposing the default server's total. Optional `show`
fields are `recall_rank` and `confidence`, each at most once. The output format is
`markdown`.

To use PowerContext v0.2, explicitly set `auto_memory_search_config.mode` to
`memory` (Legacy memory search in the Console). This mode uses `max_results`
(1–50); Prepare uses the limits in `context_assembly`. A Prepare error never
silently falls back to memory search. Legacy mode does not add Artifact or
Prepare support to a server that lacks those endpoints.

### Agent tools

| Tool               | Purpose                                                                        |
| ------------------ | ------------------------------------------------------------------------------ |
| `prepare_context`  | Prepare context for a query using the configured assembly and Scope.           |
| `memory_search`    | Search memory in the configured Scope.                                         |
| `memory_remember`  | Save an explicit memory.                                                       |
| `artifact_schema`  | Discover the connected server's Artifact content schemas from `/openapi.json`. |
| `artifact_search`  | Search `atomic-memory`, `experience`, `skill`, and `topic-memory`.             |
| `artifact_list`    | List Artifacts by family.                                                      |
| `artifact_get`     | Read an Artifact and its observed ETag.                                        |
| `artifact_history` | Read an Artifact's revision history.                                           |
| `artifact_create`  | Commit a new Artifact using the selected family's content schema.              |
| `artifact_replace` | Replace content with the ETag observed from a prior read.                      |

`prepare_context(query, max_bytes=8000)` lets the Agent explicitly request
prepared context. It uses `context_assembly` from the plugin configuration and
the bound Scope; the Agent supplies the query and response byte budget.

Artifact list, get, history, create, and replace support `atomic-memory`,
`experience`, `skill`, `topic-memory`, `profile`, `handoff`, and `prompt`, subject
to the connected server's family rules and permissions. Use `artifact_schema`
before writing; actual content fields come from that server's schema.
`artifact_create` commits directly, including Experience and Skill: it does not
create a Candidate for later approval. `artifact_replace` requires an observed
ETag and does not automatically retry a version conflict. Read the current
Artifact and review the content before trying again. Pass the ETag returned as
`etag` to the replacement tool's `expected_etag` parameter.

The plugin retains QwenPaw's existing automatic task-state persistence. It does
not add Source capture, special lifecycle operations, Candidate approval, Skill
distribution, or Handoff activation/continuation. Generic Handoff content access
does not execute those lifecycle operations.

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
- **Automatic context**: select Prepare context, edit the ordered family sections,
  and set the injected-context byte budget. For a v0.2 server, select Legacy
  memory search and set its result limit.

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
          "mode": "prepare",
          "max_results": 3,
          "max_context_bytes": 12000
        },
        "context_assembly": {
          "format": "markdown",
          "sections": [
            { "family": "profile", "limit": 1 },
            { "family": "topic-memory", "limit": 2 },
            { "family": "memory", "limit": 3 },
            { "family": "experience", "limit": 2 }
          ],
          "show": []
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
requires `scope.contribute`. Artifact writes may need additional permissions for
the selected family. For restricted tokens, have an administrator create the
Scope, grant the required permissions, and configure its ID explicitly.

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

Real HTTP tests against separate SQLite databases passed on PowerContext
[v1.4.0 (`cab054db`)](https://github.com/oceanbase/powercontext/commit/cab054dbf6d86e2311b079388e5158178257def2)
and [master (`fe50f894`)](https://github.com/oceanbase/powercontext/commit/fe50f89406153121883d278c7fe89ea272cd894b),
with 13 tests passing per version. The four legacy memory tests also passed on
[v0.2 (`685b31dd`)](https://github.com/oceanbase/powercontext/commit/685b31dd2961df5e31daa565f87d004755ebd2cf)
with `mode="memory"`.

The current-server tests cover default Scope creation and reuse, explicit
Scopes, memory persistence and recall, seven-family Artifact create/read/list/
history/replace, four-family search projections, Scope isolation, ETag conflicts,
and byte-for-byte preservation of prepared context containing the four configured
families. These tests run the plugin backend over real HTTP with SQLite. They do
not exercise a complete Console model conversation, Candidate approval, Skill
distribution, or Handoff lifecycle operations.

Running `pytest plugins/memory/powercontext/tests` skips the real HTTP tests
unless `POWERCONTEXT_TEST_URL` is set. To run them, start a separate disposable
test server with authentication disabled, then run:

```bash
POWERCONTEXT_TEST_URL=http://127.0.0.1:8000 pytest \
  plugins/memory/powercontext/tests/test_server_integration.py \
  plugins/memory/powercontext/tests/test_context_artifacts_integration.py
```

For a v0.2 test server, run only the legacy memory suite:

```bash
POWERCONTEXT_TEST_URL=http://127.0.0.1:8000 \
POWERCONTEXT_TEST_RECALL_MODE=memory pytest \
  plugins/memory/powercontext/tests/test_server_integration.py
```

The tests create persistent Scopes and Artifacts. Use a dedicated test database
and discard it afterward.
