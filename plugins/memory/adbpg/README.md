# ADBPG Memory Backend

[中文文档](README_ZH.md)

The ADBPG Memory plugin connects QwenPaw to an AnalyticDB for PostgreSQL
memory service over its REST API. It is intended for deployments that need
durable, centrally managed memory, cross-device access, or semantic retrieval
beyond a single local workspace.

## Capabilities

- Persists user messages through the ADBPG memory service, where facts can be
  extracted and stored server-side.
- Searches remote memories semantically and combines them with keyword matches
  from the Agent's local `MEMORY.md` and `memory/*.md` files.
- Supports automatic recall before a normal user turn.
- Isolates remote memories by Agent by default, with an explicit shared mode.
- Keeps the Agent running if a remote request fails. Local Markdown keyword
  search remains available when remote search fails.

This backend performs configuration-driven network reads and writes. Use only
an ADBPG endpoint appropriate for the conversation data you intend to store.

## Quick Start

### 1. Build the configuration UI

From the QwenPaw source checkout:

```bash
cd plugins/memory/adbpg/frontend
npm ci
npm run build
cd ../../../../
```

### 2. Install the plugin

```bash
qwenpaw plugin install plugins/memory/adbpg
```

When QwenPaw is stopped, start it after installation. When it is running, the
CLI uses the hot-install API. Add `--force` when reinstalling an existing copy.

### 3. Configure an Agent

In the Console, open the Agent's running configuration, select **ADBPG** as the
long-term-memory backend, and set:

- **REST Base URL**: the base URL of the ADBPG memory service.
- **REST API Key**: the token used as `Authorization: Token <key>`.
- **Per-agent isolation**: keep enabled unless Agents should share one remote
  identity.
- **Search timeout**: remote search timeout in seconds.
- **Automatic memory recall**: enable it and choose the maximum result count if
  memories should be injected before each normal user turn.

Save the configuration. The Console schedules an Agent reload. Changing the
backend or its effective configuration creates a new backend instance;
unchanged backend context can reuse the existing instance. A full QwenPaw
process restart is not required. The equivalent `agent.json` fragment is:

```json
{
  "running": {
    "memory_manager_backend": "adbpg",
    "memory_backend_configs": {
      "adbpg": {
        "rest_base_url": "https://your-adbpg-memory-api.example.com",
        "rest_api_key": "your-rest-api-key",
        "memory_isolation": true,
        "search_timeout": 10.0,
        "auto_memory_search_config": {
          "enabled": true,
          "max_results": 3
        }
      }
    }
  }
}
```

`memory_backend_configs.adbpg` is the configuration location. The former
core-owned `adbpg_memory_config` field is no longer supported.

### 4. Verify

```bash
qwenpaw plugin list
```

Confirm that `memory-adbpg` is installed, then ask the Agent to remember a fact.
Allow time for server-side extraction before trying to retrieve it in a later
turn. Check `/auto_memory_status` and the QwenPaw logs for submission failures.

## Remote identity

| Setting                   | `agent_id`       | `user_id` | `run_id` on writes |
| ------------------------- | ---------------- | --------- | ------------------ |
| `memory_isolation: true`  | Current Agent ID | `shared`  | `shared`           |
| `memory_isolation: false` | `shared`         | `shared`  | `shared`           |

Search filters contain `agent_id` and `user_id`; they do not restrict `run_id`,
so recall works across sessions. Isolation is per Agent, not per chat user or
session. Agents using shared mode in the same service dataset access the same
remote namespace. Changing isolation switches namespaces without migrating
existing memories. Local Markdown files always belong to the Agent workspace.

## Requirements

- A running ADBPG memory service exposing `/v3/memories/add/` and
  `/v3/memories/search/`.
- QwenPaw with memory-backend plugin support.
- The Python packages in `requirements.txt`; the plugin installer installs
  these automatically.

## Development

Backend code lives in `backend/`; the Console extension lives in `frontend/`.
After changing the frontend, rebuild it and reinstall the plugin:

```bash
qwenpaw plugin install plugins/memory/adbpg --force
```
