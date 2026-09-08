# PowerContext Memory Backend

[中文文档](README_ZH.md)

The PowerContext Memory plugin connects QwenPaw to a separately deployed
[PowerContext](https://github.com/oceanbase/powercontext) server. It provides a
remote memory scope for durable task state, explicit remembering, and retrieval
across conversations.

## Capabilities

- Saves a bounded summary of the current task state after user turns.
- Automatically retrieves relevant memories before normal user turns.
- Exposes governed `memory_search` and `memory_remember` tools to the Agent.
- Preserves exact PowerContext citations in search results.
- Supports optional bearer-token authentication, configurable timeouts, result
  limits, and a total UTF-8 byte budget for automatically injected context.
- Creates an installation- and Agent-specific default scope when no explicit
  scope is configured; an explicit shared scope can be used intentionally.

Automatic recall and post-turn persistence are configuration-driven network
operations. The Agent-visible tools are governed network operations. Use only
a server and scope suitable for the data being stored.

## Quick Start

### 1. Start a PowerContext server

For a local development server:

```bash
uv tool install "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
powercontext server run
```

The default local endpoint is `http://127.0.0.1:8000`. QwenPaw does not install
or start the PowerContext server automatically.

### 2. Build the configuration UI

From the QwenPaw source checkout:

```bash
cd plugins/memory/powercontext/frontend
npm install
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
- **Memory scope**: leave empty for the isolated default
  `qwenpaw:<installation_id>:agent:<agent_id>`, or set the same explicit value
  only when Agents should share memory.
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
working directory. An empty `scope_id` therefore continues to address the same
remote memories even when an Agent uses a custom workspace path.

### 5. Verify

```bash
qwenpaw plugin list
```

Confirm that `memory-powercontext` is installed. Ask the Agent to remember a
fact and retrieve it in a later turn. If the backend does not start, verify the
server URL, token, and server availability in the QwenPaw logs.

## Requirements

- A reachable PowerContext server.
- QwenPaw with memory-backend plugin support.
- The Python packages in `requirements.txt`; the plugin installer installs
  these automatically.

## Development

Backend code lives in `backend/`; the Console extension lives in `frontend/`.
After changing the frontend, rebuild it and reinstall the plugin:

```bash
qwenpaw plugin install plugins/memory/powercontext --force
```
