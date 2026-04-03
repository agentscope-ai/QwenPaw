# Config & Working Directory

This page covers:

- **Directory structure** — Where files are stored and the purpose of each directory
- **Environment variables** — How to customize paths and behavior
- **Configuration files** — Complete field description for `config.json` and `agent.json`

From **v0.1.0**, CoPaw supports **multi-agent**. Configuration is split into two layers:

1. **Global config** (`config.json`) — Model providers, agent list, global settings
2. **Agent config** (`agent.json`) — Independent config for each agent (channels, heartbeat, tools, etc.)

---

## Directory Structure

The default working directory is `~/.copaw`. After running `copaw init`, the complete structure looks like:

```
$COPAW_WORKING_DIR/                      # Default ~/.copaw
├── config.json                          # Global config
├── workspaces/
│   ├── default/                         # Default agent workspace
│   │   ├── agent.json                   # Agent config
│   │   ├── chats.json                   # Conversation history
│   │   ├── jobs.json                    # Cron jobs
│   │   ├── token_usage.json             # Token usage records
│   │   ├── AGENTS.md                    # Persona file
│   │   ├── SOUL.md                      # Persona file
│   │   ├── PROFILE.md                   # Persona file
│   │   ├── BOOTSTRAP.md                 # Initial setup guide (auto-deleted after completion)
│   │   ├── MEMORY.md                    # Long-term memory
│   │   ├── skills/                      # Workspace-local skills
│   │   ├── skill.json                   # Skill enabled state and config
│   │   ├── memory/                      # Daily memory files
│   │   └── browser/                     # Browser user data (cookies, cache, etc.)
│   └── abc123/                          # Other agent workspace
│       └── ...
└── skill_pool/                          # Local shared skill pool
    ├── skill.json                       # Pool metadata
    └── ...

$COPAW_SECRET_DIR/                       # Default ~/.copaw.secret
├── providers.json                       # Model provider config and API keys
└── envs.json                            # Environment variables
```

> **Path explanation:** `$COPAW_WORKING_DIR` and `$COPAW_SECRET_DIR` are environment variables, with default values of `~/.copaw` and `~/.copaw.secret` respectively. They can be customized via environment variables, see "Environment Variables" section below.

### Directory Explanation

**Global Directory (`~/.copaw/`)**

| File / Directory | Purpose                                               |
| ---------------- | ----------------------------------------------------- |
| `config.json`    | Global config (model providers, env vars, agent list) |
| `workspaces/`    | All agent workspace directories                       |

**Agent Workspace (`~/.copaw/workspaces/{agent_id}/`)**

| File / Directory   | Purpose                                                      |
| ------------------ | ------------------------------------------------------------ |
| `agent.json`       | Agent config (channels, heartbeat, tools, skills, MCP, etc.) |
| `chats.json`       | Conversation history                                         |
| `jobs.json`        | Cron job list                                                |
| `token_usage.json` | Token usage records                                          |
| `AGENTS.md`        | Persona file (see [Agent Persona](./persona))                |
| `SOUL.md`          | Persona file (see [Agent Persona](./persona))                |
| `PROFILE.md`       | Persona file (see [Agent Persona](./persona))                |
| `BOOTSTRAP.md`     | Initial setup guide (auto-deleted after completion)          |
| `MEMORY.md`        | Long-term memory (see [Memory](./memory))                    |
| `skills/`          | Skills available in this workspace                           |
| `skill.json`       | Skill enabled state, channel routing, and config             |
| `memory/`          | Daily memory files (see [Memory](./memory))                  |
| `browser/`         | Browser user data (cookies, cache, localStorage, etc.)       |

> **Persona files:** Agent behavior and personality are defined by persona files. Running `copaw init` automatically creates template files based on your chosen language (`zh` / `en` / `ru`). For detailed explanation and management, see [Agent Persona](./persona).

> **Multi-Agent:** See the [Multi-Agent](./multi-agent) documentation for details.

---

## Environment Variables

You can customize paths and behavior via environment variables:

**Path-related:**

| Variable                 | Default            | Description                                                                                                 |
| ------------------------ | ------------------ | ----------------------------------------------------------------------------------------------------------- |
| `COPAW_WORKING_DIR`      | `~/.copaw`         | Working directory root path                                                                                 |
| `COPAW_SECRET_DIR`       | `~/.copaw.secret`  | Sensitive data directory (stores `providers.json` and `envs.json`). Docker default is `/app/working.secret` |
| `COPAW_CONFIG_FILE`      | `config.json`      | Config file name (relative to `COPAW_WORKING_DIR`)                                                          |
| `COPAW_HEARTBEAT_FILE`   | `HEARTBEAT.md`     | Heartbeat file name (relative to agent workspace)                                                           |
| `COPAW_JOBS_FILE`        | `jobs.json`        | Cron jobs file name (relative to agent workspace)                                                           |
| `COPAW_CHATS_FILE`       | `chats.json`       | Conversation history file name (relative to agent workspace)                                                |
| `COPAW_TOKEN_USAGE_FILE` | `token_usage.json` | Token usage record file name (relative to agent workspace)                                                  |

**Other configuration:**

| Variable                           | Default         | Description                                                                 |
| ---------------------------------- | --------------- | --------------------------------------------------------------------------- |
| `COPAW_LOG_LEVEL`                  | `info`          | Log level (`debug` / `info` / `warning` / `error` / `critical`)             |
| `COPAW_MEMORY_COMPACT_THRESHOLD`   | `100000`        | Character threshold to trigger memory compaction                            |
| `COPAW_MEMORY_COMPACT_KEEP_RECENT` | `3`             | Number of recent messages to keep after compaction                          |
| `COPAW_MEMORY_COMPACT_RATIO`       | `0.7`           | Threshold ratio for triggering compaction (relative to context window size) |
| `COPAW_CONSOLE_STATIC_DIR`         | _(auto-detect)_ | Console frontend static files path                                          |

**Security & Authentication:**

| Variable                   | Default | Description                                        |
| -------------------------- | ------- | -------------------------------------------------- |
| `COPAW_AUTH_ENABLED`       | `false` | Whether to enable Web console login authentication |
| `COPAW_AUTH_USERNAME`      | -       | Admin username for auto-registration (optional)    |
| `COPAW_AUTH_PASSWORD`      | -       | Admin password for auto-registration (optional)    |
| `COPAW_TOOL_GUARD_ENABLED` | `true`  | Whether to enable tool guard                       |
| `COPAW_SKILL_SCAN_MODE`    | `warn`  | Skill scanning mode (`block` / `warn` / `off`)     |

**Memory & Retrieval:**

| Variable               | Default | Description                                                     |
| ---------------------- | ------- | --------------------------------------------------------------- |
| `FTS_ENABLED`          | `true`  | Whether to enable BM25 full-text search                         |
| `MEMORY_STORE_BACKEND` | `auto`  | Memory storage backend (`auto` / `local` / `chroma` / `sqlite`) |

Example — use a different working dir for this shell:

```bash
export COPAW_WORKING_DIR=/home/me/my_copaw
copaw app
```

Config, HEARTBEAT, jobs, memory, etc. will be read/written under
`/home/me/my_copaw`.

---

## Configuration File Structure

Starting from **v0.1.0**, configuration is split into two layers:

1. **Global config** - `~/.copaw/config.json` (providers, environment variables, agent list)
2. **Agent config** - `~/.copaw/workspaces/{agent_id}/agent.json` (per-agent settings)

### Global config.json

Stores globally shared configuration:

```json
{
  "agents": {
    "active_agent": "default",
    "profiles": {
      "default": {
        "id": "default",
        "name": "Default Agent",
        "description": "Default workspace agent",
        "enabled": true
      },
      "abc123": {
        "id": "abc123",
        "name": "Code Assistant",
        "description": "Focuses on code review and development",
        "enabled": true
      }
    }
  },
  "last_api": {
    "host": "127.0.0.1",
    "port": 8088
  },
  "show_tool_details": true
}
```

**Global config.json field descriptions:**

| Field                 | Type           | Default             | Description                                                       |
| --------------------- | -------------- | ------------------- | ----------------------------------------------------------------- |
| `agents.active_agent` | string         | `"default"`         | Currently active agent ID                                         |
| `agents.profiles`     | object         | `{}`                | Agent profile references (key is agent_id)                        |
| `last_api.host`       | string \| null | `null`              | Host address from last `copaw app` start                          |
| `last_api.port`       | int \| null    | `null`              | Port from last `copaw app` start                                  |
| `show_tool_details`   | bool           | `true`              | Whether to show tool call/return details in channel messages      |
| `user_timezone`       | string         | _(system timezone)_ | IANA timezone name (e.g., `"Asia/Shanghai"`)                      |
| `last_dispatch`       | object \| null | `null`              | Last message dispatch target (used for heartbeat `target="last"`) |

**`agents.profiles[agent_id]` reference fields:**

| Field           | Type   | Required | Description                                                                 |
| --------------- | ------ | -------- | --------------------------------------------------------------------------- |
| `id`            | string | Yes      | Agent unique identifier                                                     |
| `name`          | string | Yes      | Agent display name                                                          |
| `description`   | string | No       | Agent description (used for multi-agent collaboration)                      |
| `enabled`       | bool   | Yes      | Whether to enable this agent                                                |
| `workspace_dir` | string | No       | Workspace path (optional, defaults to `$COPAW_WORKING_DIR/workspaces/{id}`) |

> **Backward compatibility:** The global config.json still supports `channels`, `mcp`, `tools`, `security` and other fields for backward compatibility with older versions. In multi-agent mode, these configurations should be set in each agent's `agent.json`.
>
> **Configuration priority:** The agent's `agent.json` takes precedence over the global `config.json`. When the same field is configured in both places, the system uses the value from `agent.json`. For multi-agent mode, it's recommended to put all configurations in each agent's `agent.json`.

> **Model provider configuration** is stored in `$COPAW_SECRET_DIR/providers.json` (default `~/.copaw.secret/providers.json`).
> **Environment variables** are stored in `$COPAW_SECRET_DIR/envs.json` (default `~/.copaw.secret/envs.json`).

### Agent config (agent.json)

Each agent has an independent `agent.json` in its workspace directory (`~/.copaw/workspaces/{agent_id}/`) that stores all of its configuration (channels, tools, heartbeat, MCP, security, etc.). This allows different agents to have completely different configurations without interfering with each other.

```json
{
  "id": "default",
  "name": "Default Agent",
  "description": "Default workspace agent",
  "workspace_dir": "",
  "channels": {
    "console": {
      "enabled": true,
      "bot_prefix": ""
    },
    "dingtalk": {
      "enabled": false,
      "bot_prefix": "",
      "client_id": "",
      "client_secret": ""
    }
  },
  "mcp": {
    "clients": {
      "filesystem": {
        "name": "Filesystem Access",
        "enabled": true,
        "command": "npx",
        "args": [
          "-y",
          "@modelcontextprotocol/server-filesystem",
          "/path/to/folder"
        ]
      }
    }
  },
  "heartbeat": {
    "enabled": false,
    "every": "30m",
    "target": "main",
    "activeHours": null
  },
  "running": {
    "max_iters": 50,
    "llm_retry_enabled": true,
    "llm_max_retries": 3,
    "llm_backoff_base": 1.0,
    "llm_backoff_cap": 10.0,
    "max_input_length": 131072
  },
  "active_model": null,
  "language": "en",
  "system_prompt_files": ["AGENTS.md", "SOUL.md", "PROFILE.md"],
  "tools": {
    "builtin_tools": {}
  },
  "security": {
    "tool_guard": {
      "enabled": true
    },
    "file_guard": {
      "enabled": true
    },
    "skill_scanner": {
      "mode": "warn"
    }
  },
  "last_dispatch": null
}
```

> **Note:** The complete field list and descriptions are provided in the sections below. Agent configuration can be managed in the Console or by directly editing the `agent.json` file.

---

### agent.json Field Reference

#### `channels` — Messaging channel configs

Each channel has common fields (like `enabled`, `bot_prefix`, access control policies, etc.) and channel-specific fields (like DingTalk's `client_id`, `client_secret`).

**Supported channels:**

- **console** — Console (enabled by default)
- **dingtalk** — DingTalk
- **feishu** — Feishu/Lark
- **discord** — Discord
- **telegram** — Telegram
- **qq** — QQ bot
- **imessage** — iMessage (macOS only)
- **mattermost** — Mattermost
- **matrix** — Matrix
- **wecom** — WeCom (WeChat Work)
- **weixin** — WeChat Personal (iLink)
- **xiaoyi** — Huawei XiaoYi
- **mqtt** — MQTT
- **voice** — Voice

> **Complete configuration:** Common fields, channel-specific fields (like DingTalk's `client_id`, Feishu's `app_id`), and detailed configuration steps for each channel are documented in [Channels](./channels).

Management: Console (Agent → Channels) or directly edit `agent.json`.

> **Hot reload:** The system automatically detects `agent.json` changes every 2 seconds. After modifying channel config, it will auto-reload without restart.

---

#### `mcp` — MCP client configuration

MCP (Model Context Protocol) allows agents to connect to external services (like Filesystem, Git, SQLite MCP servers, etc.).

Each MCP client includes name, enabled state, transport method (stdio/HTTP/SSE), startup command or URL, and other fields.

> **Complete configuration:** Full field descriptions, config formats, examples, and usage for MCP clients are documented in [MCP](./mcp).

Management: Console (Agent → MCP) or directly edit `agent.json`.

---

#### `heartbeat` — Heartbeat configuration

Heartbeat is a scheduled self-check feature that executes tasks from `HEARTBEAT.md` at regular intervals.

| Field         | Type           | Default  | Description                                                                                                  |
| ------------- | -------------- | -------- | ------------------------------------------------------------------------------------------------------------ |
| `enabled`     | bool           | `false`  | Whether to enable heartbeat feature                                                                          |
| `every`       | string         | `"30m"`  | Run interval. Supports `Nh`, `Nm`, `Ns` combos, e.g. `"1h"`, `"30m"`, `"2h30m"`, `"90s"`                     |
| `target`      | string         | `"main"` | `"main"` = run in main session only; `"last"` = dispatch result to the last channel/user that sent a message |
| `activeHours` | object \| null | `null`   | Optional time window (if set, heartbeat only runs during this period)                                        |

**`heartbeat.activeHours`** (when not null):

| Field   | Type   | Default   | Description                 |
| ------- | ------ | --------- | --------------------------- |
| `start` | string | `"08:00"` | Start time (HH:MM, 24-hour) |
| `end`   | string | `"22:00"` | End time (HH:MM, 24-hour)   |

See [Heartbeat](./heartbeat) for detailed guide.

---

#### `running` — Runtime configuration

Controls agent runtime behavior, retry strategies, context management, and memory configuration.

**Basic Runtime:**

| Field       | Type | Default | Description                                                                 |
| ----------- | ---- | ------- | --------------------------------------------------------------------------- |
| `max_iters` | int  | `100`   | Maximum number of reasoning-acting iterations for ReAct agent (must be ≥ 1) |

**LLM Retry & Rate Limiting:**

| Field                   | Type  | Default | Description                                                                                           |
| ----------------------- | ----- | ------- | ----------------------------------------------------------------------------------------------------- |
| `llm_retry_enabled`     | bool  | `true`  | Whether to auto-retry transient LLM API failures such as rate limits, timeouts, and connection errors |
| `llm_max_retries`       | int   | `3`     | Maximum retry attempts for transient LLM API failures (must be ≥ 1)                                   |
| `llm_backoff_base`      | float | `1.0`   | Base delay in seconds for exponential retry backoff (must be ≥ 0.1)                                   |
| `llm_backoff_cap`       | float | `10.0`  | Maximum backoff delay cap in seconds (must be ≥ 0.5 and greater than or equal to `llm_backoff_base`)  |
| `llm_max_concurrent`    | int   | `10`    | Maximum concurrent LLM calls (shared across all agents)                                               |
| `llm_max_qpm`           | int   | `600`   | Maximum queries per minute (QPM). 0 = no limit                                                        |
| `llm_rate_limit_pause`  | float | `5.0`   | Global pause duration in seconds after receiving a 429 rate limit response                            |
| `llm_rate_limit_jitter` | float | `1.0`   | Random jitter range in seconds added to rate limit pause to avoid thundering herd                     |
| `llm_acquire_timeout`   | float | `300.0` | Maximum timeout in seconds to wait for acquiring a rate limit slot                                    |

**Context Management:**

| Field                | Type   | Default         | Description                                                             |
| -------------------- | ------ | --------------- | ----------------------------------------------------------------------- |
| `max_input_length`   | int    | `131072` (128K) | Maximum input length (tokens) for model context window (must be ≥ 1000) |
| `history_max_length` | int    | `10000`         | Maximum output length (characters) for `/history` command               |
| `context_compact`    | object | _(see below)_   | Context compaction configuration object                                 |

**Context Compaction (`context_compact` object):**

| Field                          | Type   | Default     | Description                                                               |
| ------------------------------ | ------ | ----------- | ------------------------------------------------------------------------- |
| `context_compact_enabled`      | bool   | `true`      | Whether to enable automatic context compaction                            |
| `memory_compact_ratio`         | float  | `0.75`      | Threshold ratio (relative to `max_input_length`) that triggers compaction |
| `memory_reserve_ratio`         | float  | `0.1`       | Ratio of recent context to preserve after compaction for continuity       |
| `compact_with_thinking_block`  | bool   | `true`      | Whether to include thinking blocks during compaction                      |
| `token_count_model`            | string | `"default"` | Model to use for token counting                                           |
| `token_count_use_mirror`       | bool   | `false`     | Whether to use HuggingFace mirror for token counting                      |
| `token_count_estimate_divisor` | float  | `4.0`       | Divisor for byte-based token estimation (byte_len / divisor)              |

**Tool Result Compaction (`tool_result_compact` object):**

| Field              | Type | Default | Description                                        |
| ------------------ | ---- | ------- | -------------------------------------------------- |
| `enabled`          | bool | `true`  | Whether to enable tool result compaction           |
| `recent_n`         | int  | `2`     | Number of recent messages using `recent_max_bytes` |
| `old_max_bytes`    | int  | `3000`  | Byte threshold for older tool results              |
| `recent_max_bytes` | int  | `50000` | Byte threshold for recent tool results             |
| `retention_days`   | int  | `5`     | Number of days to retain tool result files         |

**Memory Configuration:**

| Field                    | Type   | Default       | Description                                                |
| ------------------------ | ------ | ------------- | ---------------------------------------------------------- |
| `memory_summary`         | object | _(see below)_ | Memory summarization and search configuration object       |
| `embedding_config`       | object | _(see below)_ | Embedding model configuration for semantic retrieval       |
| `memory_manager_backend` | string | `"remelight"` | Memory manager backend type (currently only `"remelight"`) |

**Memory Summary Configuration (`memory_summary` object):**

| Field                           | Type  | Default | Description                                                                              |
| ------------------------------- | ----- | ------- | ---------------------------------------------------------------------------------------- |
| `memory_summary_enabled`        | bool  | `true`  | Whether to enable memory summarization during compaction                                 |
| `force_memory_search`           | bool  | `false` | Whether to force memory search on every conversation turn                                |
| `force_max_results`             | int   | `1`     | Maximum results for forced memory search                                                 |
| `force_min_score`               | float | `0.3`   | Minimum relevance score for forced memory search (0.0 - 1.0)                             |
| `rebuild_memory_index_on_start` | bool  | `false` | Whether to rebuild memory search index on startup. false = only monitor new file changes |

**Embedding Configuration (`embedding_config` object):**

| Field              | Type   | Default    | Description                                             |
| ------------------ | ------ | ---------- | ------------------------------------------------------- |
| `backend`          | string | `"openai"` | Embedding backend type (e.g., `"openai"`)               |
| `api_key`          | string | `""`       | API key for the embedding provider                      |
| `base_url`         | string | `""`       | Custom API URL (optional)                               |
| `model_name`       | string | `""`       | Embedding model name (e.g., `"text-embedding-3-small"`) |
| `dimensions`       | int    | `1024`     | Embedding vector dimensions                             |
| `enable_cache`     | bool   | `true`     | Whether to enable embedding cache                       |
| `use_dimensions`   | bool   | `false`    | Whether to use custom dimensions                        |
| `max_cache_size`   | int    | `3000`     | Maximum cache size                                      |
| `max_input_length` | int    | `8192`     | Maximum input length for embeddings                     |
| `max_batch_size`   | int    | `10`       | Maximum batch size for batch processing                 |

These settings can also be changed in the Console under **Agent → Runtime Config**. Changes apply to new LLM requests after saving; restarting the service is not required.

---

#### `language` & `system_prompt_files` — Persona file configuration

| Field                 | Type          | Default                                  | Description                                     |
| --------------------- | ------------- | ---------------------------------------- | ----------------------------------------------- |
| `language`            | string        | `"zh"`                                   | Agent language (`zh` / `en` / `ru`)             |
| `system_prompt_files` | array[string] | `["AGENTS.md", "SOUL.md", "PROFILE.md"]` | List of persona files loaded into system prompt |

**Persona files** define agent behavior and personality, stored in the workspace directory. You can:

- Manage persona files in the Console's **Agent → Workspace** page (edit, enable/disable, reorder)
- Directly edit the `system_prompt_files` array to control which files are loaded
- Switch language in the Console's **Agent → Runtime Config** page (overwrites existing persona files)

**Detailed explanation:** See [Agent Persona](./persona) documentation.

---

#### `user_timezone` — User timezone

| Field           | Type   | Default             | Description                                                                                                            |
| --------------- | ------ | ------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `user_timezone` | string | _(system timezone)_ | IANA timezone name (e.g. `"Asia/Shanghai"`, `"America/New_York"`). Defaults to the system timezone detected at startup |

This timezone is used for:

- Displaying the current time in the agent's system prompt
- The `get_current_time` tool
- Default timezone for new cron jobs (CLI and console)
- Heartbeat active hours evaluation

You can also change it via the Console (Agent → Runtime Config).

---

#### `active_model` — Current model in use

Specifies the model used by this agent.

| Field         | Type   | Default | Description                                         |
| ------------- | ------ | ------- | --------------------------------------------------- |
| `provider_id` | string | `""`    | Model provider ID (e.g., `"dashscope"`, `"openai"`) |
| `model`       | string | `""`    | Model name (e.g., `"qwen-max"`, `"gpt-4"`)          |

When `null`, uses the global default model. Can be configured in Console (Agent → Model Settings).

---

#### `tools` — Tool configuration

Controls the built-in tools available to the agent. Each tool can be individually enabled/disabled, configured whether to show to users, and whether to execute asynchronously.

> **Complete configuration:** Detailed field structure, configuration examples, etc. for tools are documented in [MCP & Built-in Tools](./mcp).

Management: Console (Agent → Tool Config) or directly edit `agent.json`.

---

#### `security` — Security configuration

Contains three protection modules:

- **`tool_guard`** — Tool guard (runtime detection of dangerous commands and injection attacks)
- **`file_guard`** — File guard (protects sensitive file access)
- **`skill_scanner`** — Skill scanner (scans for malicious code before enabling skills)

> **Complete configuration:** Detailed field descriptions, security rules, custom rule configuration, etc. for each module are documented in [Security](./security).

Management: Console (Settings → Security Config) or directly edit `agent.json`.

---

#### `last_dispatch` — Last message dispatch target

Records the last user message source, used for sending messages when heartbeat `target = "last"`.

| Field        | Type   | Default | Description                                   |
| ------------ | ------ | ------- | --------------------------------------------- |
| `channel`    | string | `""`    | Channel name (e.g. `"discord"`, `"dingtalk"`) |
| `user_id`    | string | `""`    | User ID in that channel                       |
| `session_id` | string | `""`    | Session/conversation ID                       |

Auto-updated; no manual configuration needed.

---

## Model Providers

CoPaw needs an LLM provider to work. You can set it up in three ways:

- **`copaw init`** — interactive wizard, the easiest way
- **Console UI** — in Settings → Models page
- **API** — `PUT /providers/{id}` and `PUT /providers/active_llm`

**Built-in providers:**

| Provider                     | ID                      | Default Base URL                                    | API Key Prefix |
| ---------------------------- | ----------------------- | --------------------------------------------------- | -------------- |
| CoPaw Local                  | `copaw-local`           | _(local)_                                           | _(none)_       |
| Ollama                       | `ollama`                | `http://localhost:11434`                            | _(none)_       |
| LM Studio                    | `lmstudio`              | `http://localhost:1234/v1`                          | _(none)_       |
| ModelScope                   | `modelscope`            | `https://api-inference.modelscope.cn/v1`            | `ms`           |
| DashScope                    | `dashscope`             | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `sk`           |
| Aliyun Coding Plan           | `aliyun-codingplan`     | `https://coding.dashscope.aliyuncs.com/v1`          | `sk-sp`        |
| OpenAI                       | `openai`                | `https://api.openai.com/v1`                         | _(any)_        |
| Azure OpenAI                 | `azure-openai`          | _(you set it)_                                      | _(any)_        |
| Anthropic                    | `anthropic`             | `https://api.anthropic.com`                         | _(any)_        |
| Google Gemini                | `gemini`                | `https://generativelanguage.googleapis.com`         | _(any)_        |
| DeepSeek                     | `deepseek`              | `https://api.deepseek.com`                          | `sk-`          |
| Kimi (China)                 | `kimi-cn`               | `https://api.moonshot.cn/v1`                        | _(any)_        |
| Kimi (International)         | `kimi-intl`             | `https://api.moonshot.ai/v1`                        | _(any)_        |
| MiniMax (China)              | `minimax-cn`            | `https://api.minimaxi.com/anthropic`                | _(any)_        |
| MiniMax (International)      | `minimax`               | `https://api.minimax.io/anthropic`                  | _(any)_        |
| Zhipu (BigModel)             | `zhipu-cn`              | `https://open.bigmodel.cn/api/paas/v4`              | _(any)_        |
| Zhipu Coding Plan (BigModel) | `zhipu-cn-codingplan`   | `https://open.bigmodel.cn/api/coding/paas/v4`       | _(any)_        |
| Zhipu (Z.AI)                 | `zhipu-intl`            | `https://api.z.ai/api/paas/v4`                      | _(any)_        |
| Zhipu Coding Plan (Z.AI)     | `zhipu-intl-codingplan` | `https://api.z.ai/api/coding/paas/v4`               | _(any)_        |
| Custom                       | `custom`                | _(you set it)_                                      | _(any)_        |

For each provider you need to set:

| Setting    | Description                                      |
| ---------- | ------------------------------------------------ |
| `base_url` | API base URL (pre-filled for built-in providers) |
| `api_key`  | Your API key                                     |

Then choose which provider + model to activate:

| Setting       | Description                              |
| ------------- | ---------------------------------------- |
| `provider_id` | Which provider to use (e.g. `dashscope`) |
| `model`       | Which model to use (e.g. `qwen3-max`)    |

> **Tip:** Run `copaw init` and follow the prompts — it will list available
> models for each provider so you can pick one directly.
>
> **Note:** You are responsible for ensuring the API key and base URL are valid.
> CoPaw does not verify whether the key is correct or has sufficient quota —
> make sure the chosen provider and model are accessible.

---

## Tool Environment Variables

Some tools and MCP services need extra API keys (e.g. `TAVILY_API_KEY` for web search). You can
manage them in three ways:

- **`copaw init`** — prompts "Configure environment variables?" during setup
- **Console UI** — edit on the settings page
- **API** — `GET/PUT/DELETE /envs`

Set variables are auto-loaded at app startup, so all tools and child processes
can read them via `os.environ`.

> **Note:** You are responsible for ensuring the values (e.g. third-party API
> keys) are valid. CoPaw only stores and injects them — it does not verify
> correctness.

---

## Skills

Skills extend the agent's capabilities. Skill files are distributed across two locations:

| Directory                                | Purpose                                           |
| ---------------------------------------- | ------------------------------------------------- |
| `~/.copaw/skill_pool/`                   | Local shared pool for built-ins and shared skills |
| `~/.copaw/workspaces/{agent_id}/skills/` | Skills present in a specific agent's workspace    |

Each skill is a directory with a `SKILL.md` file (YAML front matter with `name` and `description`), and optional `references/` and `scripts/` subdirectories.

Skill enabled state and configuration are controlled by `~/.copaw/workspaces/{agent_id}/skill.json`.

**Manage skills via:**

- Console (Agent → Skills) — Visual management, import, create, enable/disable
- `copaw init` (choose all / none / custom during setup)
- `copaw skills config` (interactive toggle)

See [Skills](./skills) for detailed documentation.

---

## Memory

CoPaw has persistent cross-conversation memory: it automatically compresses context and saves key information to Markdown files for long-term retention.

Memory files are stored in the agent workspace:

| File / Directory                                      | Purpose                                                               |
| ----------------------------------------------------- | --------------------------------------------------------------------- |
| `~/.copaw/workspaces/{agent_id}/MEMORY.md`            | Long-lived key information (decisions, preferences, persistent facts) |
| `~/.copaw/workspaces/{agent_id}/memory/YYYY-MM-DD.md` | Daily logs (notes, runtime context, auto-generated summaries)         |

### Embedding Configuration

Memory search relies on vector embeddings for semantic retrieval. Configuration priority: **config file > env var > default**.

Recommended to configure in `agent.json` under `running.embedding_config`, which supports more parameters (e.g., `use_dimensions`). Environment variables serve as fallback only:

| Variable (Fallback)    | Description                       | Default |
| ---------------------- | --------------------------------- | ------- |
| `EMBEDDING_API_KEY`    | API key for the embedding service | ``      |
| `EMBEDDING_BASE_URL`   | Embedding service URL             | ``      |
| `EMBEDDING_MODEL_NAME` | Embedding model name              | ``      |

> `api_key`, `model_name`, and `base_url` must all be non-empty to enable vector search in hybrid retrieval. See [Memory](./memory#embedding-configuration-optional) for full configuration details.

---

## Summary

- Everything lives under **`~/.copaw`** by default; override with `COPAW_WORKING_DIR` (and related env vars) if needed.
- From **v0.1.0**, configuration is split into:
  - **Global config** (`~/.copaw/config.json`) — providers, environment variables, agent list
  - **Agent config** (`~/.copaw/workspaces/{agent_id}/agent.json`) — per-agent settings
- Daily management is primarily done through the **Console**, or by directly editing configuration files.
- Agent personality is defined by Markdown files in the workspace directory. See [Agent Persona](./persona) for details.
- LLM providers are globally configured via `copaw init` or the Console.
- Config changes are **auto-reloaded** without restart (polled every 2 seconds).
- Call the Agent API: **POST** `/api/agent/process` with `X-Agent-Id` header, JSON body, SSE streaming; see [Quick start — Verify install](./quickstart#verify-install-optional) for examples.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Agent Persona](./persona) — Detailed explanation and management of persona files
- [Channels](./channels) — How to configure messaging channels
- [Heartbeat](./heartbeat) — Heartbeat configuration
- [Multi-Agent](./multi-agent) — Multi-agent setup, management, and collaboration
- [Memory](./memory) — Memory system details
- [Skills](./skills) — Skills system details
