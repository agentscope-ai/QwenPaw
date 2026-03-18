# Config & Working Directory

This page covers:

- **Working directory** — Where things are stored
- **config.json** — What every field means and its defaults
- **Environment variables** — How to customize paths

> No code required — just edit JSON and go.

---

## What is the working directory?

By default, all config and data live in one folder — the **working directory**:

- **`~/.copaw`** (the `.copaw` folder under your home directory)

Starting from **v0.1.0**, CoPaw supports **multi-agent workspace**. When you run `copaw init`, the new structure looks like:

```
~/.copaw/
├── config.json              # Global config (providers, environment variables)
└── workspaces/
    ├── default/             # Default agent workspace
    │   ├── agent.json       # Agent config
    │   ├── chats.json       # Conversation history
    │   ├── jobs.json        # Cron jobs
    │   ├── AGENTS.md        # Detailed workflows, rules, and guidelines
    │   ├── SOUL.md          # Core identity and behavioral principles
    │   ├── active_skills/   # Enabled skills
    │   ├── customized_skills/ # Custom skills
    │   └── memory/          # Memory files
    └── abc123/              # Other agent workspace
        └── ...
```

### Directory Explanation

**Global Directory (`~/.copaw/`)**

| File / Directory | Purpose                                               |
| ---------------- | ----------------------------------------------------- |
| `config.json`    | Global config (model providers, env vars, agent list) |
| `workspaces/`    | All agent workspace directories                       |

**Agent Workspace (`~/.copaw/workspaces/{agent_id}/`)**

| File / Directory     | Purpose                                                      |
| -------------------- | ------------------------------------------------------------ |
| `agent.json`         | Agent config (channels, heartbeat, tools, skills, MCP, etc.) |
| `chats.json`         | Conversation history                                         |
| `jobs.json`          | Cron job list                                                |
| `token_usage.json`   | Token usage records                                          |
| `AGENTS.md`          | _(required)_ Detailed workflows, rules, and guidelines       |
| `SOUL.md`            | _(required)_ Core identity and behavioral principles         |
| `active_skills/`     | Currently enabled skills                                     |
| `customized_skills/` | User-created custom skills                                   |
| `memory/`            | Memory files (auto-managed)                                  |

> **Tip:** `SOUL.md` and `AGENTS.md` are the minimum required Markdown files
> for the agent's system prompt. Without them, the agent falls back to a
> generic "You are a helpful assistant" prompt. Run `copaw init` to auto-copy
> them based on your language choice (`zh` / `en` / `ru`). You can also
> change the language later via the Console (Agent → Configuration).

> **Multi-Agent Workspace:** See the [Multi-Agent Workspace](./multi-agent) documentation for details.

---

## Changing paths with environment variables (optional)

If you don't want to use `~/.copaw`, you can override the working directory or
specific file names:

| Variable                 | Default            | Meaning                                                                                                                                                                                 |
| ------------------------ | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `COPAW_WORKING_DIR`      | `~/.copaw`         | Working directory; config, heartbeat, jobs, chats, skills, and memory all live here                                                                                                     |
| `COPAW_SECRET_DIR`       | `~/.copaw.secret`  | Secret directory (sibling of working dir); stores `providers.json` (model provider settings, API keys) and `envs.json` (environment variables). In Docker, set to `/app/working.secret` |
| `COPAW_CONFIG_FILE`      | `config.json`      | Config file name (relative to working dir)                                                                                                                                              |
| `COPAW_HEARTBEAT_FILE`   | `HEARTBEAT.md`     | Heartbeat prompt file name (relative to working dir)                                                                                                                                    |
| `COPAW_JOBS_FILE`        | `jobs.json`        | Cron jobs file name (relative to working dir)                                                                                                                                           |
| `COPAW_CHATS_FILE`       | `chats.json`       | Chats file name (relative to working dir)                                                                                                                                               |
| `COPAW_TOKEN_USAGE_FILE` | `token_usage.json` | Token usage record file name (relative to working dir)                                                                                                                                  |

| `COPAW_LOG_LEVEL` | `info` | Log level for the app (`debug`, `info`, `warning`, `error`, `critical`) |
| `COPAW_MEMORY_COMPACT_THRESHOLD` | `100000` | Character threshold to trigger memory compaction |
| `COPAW_MEMORY_COMPACT_KEEP_RECENT` | `3` | Number of recent messages kept after compaction |
| `COPAW_MEMORY_COMPACT_RATIO` | `0.7` | Threshold ratio for triggering compaction (relative to context window) |
| `COPAW_CONSOLE_STATIC_DIR` | _(auto-detect)_ | Path to the console front-end static files |

Example — use a different working dir for this shell:

```bash
export COPAW_WORKING_DIR=/home/me/my_copaw
copaw app
```

Config, HEARTBEAT, jobs, memory, etc. will be read/written under
`/home/me/my_copaw`.

---

## What's in config.json?

Below is the **complete structure** with every field, its type, default value,
and what it does. You don't need to fill in everything — missing fields
automatically use defaults.

### Full example

```json
{
  "channels": {
    "imessage": {
      "enabled": false,
      "bot_prefix": "",
      "db_path": "~/Library/Messages/chat.db",
      "poll_sec": 1.0
    },
    "discord": {
      "enabled": false,
      "bot_prefix": "",
      "bot_token": "",
      "http_proxy": "",
      "http_proxy_auth": ""
    },
    "dingtalk": {
      "enabled": false,
      "bot_prefix": "",
      "client_id": "",
      "client_secret": ""
    },
    "feishu": {
      "enabled": false,
      "bot_prefix": "",
      "app_id": "",
      "app_secret": "",
      "encrypt_key": "",
      "verification_token": "",
      "media_dir": "~/.copaw/media"
    },
    "qq": {
      "enabled": false,
      "bot_prefix": "",
      "app_id": "",
      "client_secret": ""
    },
    "console": {
      "enabled": true,
      "bot_prefix": ""
    }
  },
  "agents": {
    "defaults": {
      "heartbeat": {
        "every": "30m",
        "target": "main",
        "activeHours": null
      }
    },
    "running": {
      "max_iters": 50,
      "max_input_length": 131072
    },
    "language": "zh",
    "installed_md_files_language": "zh"
  },
  "last_api": {
    "host": "127.0.0.1",
    "port": 8088
  },
  "user_timezone": "Asia/Shanghai",
  "last_dispatch": null,
  "show_tool_details": true
}
```

### Field-by-field reference

#### `channels` — Messaging channel configs

Each channel has a common base and channel-specific fields.

**Common fields (all channels):**

| Field                  | Type   | Default | Description                                                     |
| ---------------------- | ------ | ------- | --------------------------------------------------------------- |
| `enabled`              | bool   | `false` | Whether the channel is active                                   |
| `bot_prefix`           | string | `""`    | Optional command prefix (e.g. `/paw`)                           |
| `filter_tool_messages` | bool   | `false` | Filter tool call/output messages from being sent (default off)  |
| `filter_thinking`      | bool   | `false` | Filter thinking/reasoning content from being sent (default off) |

**`channels.imessage`** — macOS iMessage

| Field      | Type   | Default                      | Description                   |
| ---------- | ------ | ---------------------------- | ----------------------------- |
| `db_path`  | string | `~/Library/Messages/chat.db` | Path to the iMessage database |
| `poll_sec` | float  | `1.0`                        | Polling interval in seconds   |

**`channels.discord`** — Discord Bot

| Field             | Type   | Default | Description                      |
| ----------------- | ------ | ------- | -------------------------------- |
| `bot_token`       | string | `""`    | Discord bot token                |
| `http_proxy`      | string | `""`    | HTTP proxy URL (useful in China) |
| `http_proxy_auth` | string | `""`    | Proxy authentication string      |

**`channels.dingtalk`** — DingTalk (钉钉)

| Field               | Type   | Default      | Description                                                                |
| ------------------- | ------ | ------------ | -------------------------------------------------------------------------- |
| `client_id`         | string | `""`         | DingTalk app Client ID                                                     |
| `client_secret`     | string | `""`         | DingTalk app Client Secret                                                 |
| `message_type`      | string | `"markdown"` | Message mode: `markdown` (default) or `card` (AI interactive card)         |
| `card_template_id`  | string | `""`         | DingTalk AI Card template ID (required when `message_type` is `card`)      |
| `card_template_key` | string | `"content"`  | AI Card variable key; must exactly match your template variable name       |
| `robot_code`        | string | `""`         | Robot code (recommended explicit config for group card delivery scenarios) |

**`channels.feishu`** — Feishu / Lark (飞书)

| Field                | Type   | Default          | Description                         |
| -------------------- | ------ | ---------------- | ----------------------------------- |
| `app_id`             | string | `""`             | Feishu App ID                       |
| `app_secret`         | string | `""`             | Feishu App Secret                   |
| `encrypt_key`        | string | `""`             | Event encryption key (optional)     |
| `verification_token` | string | `""`             | Event verification token (optional) |
| `media_dir`          | string | `~/.copaw/media` | Directory for received media files  |

**`channels.qq`** — QQ Bot

| Field           | Type   | Default | Description          |
| --------------- | ------ | ------- | -------------------- |
| `app_id`        | string | `""`    | QQ Bot App ID        |
| `client_secret` | string | `""`    | QQ Bot Client Secret |

**`channels.console`** — Console (terminal I/O)

| Field     | Type | Default | Description                                          |
| --------- | ---- | ------- | ---------------------------------------------------- |
| `enabled` | bool | `true`  | Enabled by default; prints agent responses to stdout |

> **Tip:** The system auto-watches `config.json` for changes (every 2 seconds).
> If you edit a channel's config while the app is running, it will
> automatically reload that channel — no restart needed.

---

#### `agents` — Multi-agent configuration

From **v0.1.0**, the `agents` section now contains agent profiles:

| Field                 | Type   | Default     | Description                                   |
| --------------------- | ------ | ----------- | --------------------------------------------- |
| `agents.active_agent` | string | `"default"` | Currently active agent ID                     |
| `agents.profiles`     | object | `{}`        | Dictionary of agent profiles (key = agent ID) |

**`agents.profiles[agent_id]`** — Agent profile reference

| Field         | Type   | Required | Description                  |
| ------------- | ------ | -------- | ---------------------------- |
| `id`          | string | Yes      | Agent unique ID              |
| `name`        | string | Yes      | Agent display name           |
| `description` | string | No       | Agent description            |
| `enabled`     | bool   | Yes      | Whether the agent is enabled |

Each agent's detailed configuration is stored in `~/.copaw/workspaces/{agent_id}/agent.json`:

| Field                         | Type           | Default   | Description                                                             |
| ----------------------------- | -------------- | --------- | ----------------------------------------------------------------------- |
| `channels`                    | object         | See below | Channel configurations                                                  |
| `heartbeat`                   | object \| null | See below | Heartbeat configuration                                                 |
| `running`                     | object         | See below | Agent runtime behavior configuration                                    |
| `language`                    | string         | `"zh"`    | Language for agent MD files (`"zh"` / `"en"` / `"ru"`)                  |
| `installed_md_files_language` | string \| null | `null`    | Tracks which language's MD files are installed; managed by `copaw init` |

**`agents.running`** — Agent runtime behavior

| Field              | Type | Default         | Description                                                                                                              |
| ------------------ | ---- | --------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `max_iters`        | int  | `50`            | Maximum number of reasoning-acting iterations for ReAct agent (must be ≥ 1)                                              |
| `max_input_length` | int  | `131072` (128K) | Maximum input length (tokens) for model context window. Memory compaction triggers at 80% of this value (must be ≥ 1000) |

**`agents.defaults.heartbeat`** — Heartbeat scheduling

| Field         | Type           | Default  | Description                                                                                                  |
| ------------- | -------------- | -------- | ------------------------------------------------------------------------------------------------------------ |
| `every`       | string         | `"30m"`  | Run interval. Supports `Nh`, `Nm`, `Ns` combos, e.g. `"1h"`, `"30m"`, `"2h30m"`, `"90s"`                     |
| `target`      | string         | `"main"` | `"main"` = run in main session only; `"last"` = dispatch result to the last channel/user that sent a message |
| `activeHours` | object \| null | `null`   | Optional time window. If set, heartbeat only runs during this period                                         |

**`agents.defaults.heartbeat.activeHours`** (when not null):

| Field   | Type   | Default   | Description                 |
| ------- | ------ | --------- | --------------------------- |
| `start` | string | `"08:00"` | Start time (HH:MM, 24-hour) |
| `end`   | string | `"22:00"` | End time (HH:MM, 24-hour)   |

> See [Heartbeat](./heartbeat) for a detailed guide.

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

You can also change it via the Console (Agent → Configuration).

---

#### `last_api` — Last used API address

| Field  | Type           | Default | Description                   |
| ------ | -------------- | ------- | ----------------------------- |
| `host` | string \| null | `null`  | Last host used by `copaw app` |
| `port` | int \| null    | `null`  | Last port used by `copaw app` |

This is auto-saved every time you run `copaw app`. Other CLI subcommands
(like `copaw cron`) use this to know where to send requests.

---

#### `last_dispatch` — Last message dispatch target

| Field        | Type   | Default | Description                                   |
| ------------ | ------ | ------- | --------------------------------------------- |
| `channel`    | string | `""`    | Channel name (e.g. `"discord"`, `"dingtalk"`) |
| `user_id`    | string | `""`    | User ID in that channel                       |
| `session_id` | string | `""`    | Session/conversation ID                       |

Auto-updated when a user sends a message. Used by heartbeat when
`target = "last"` — the heartbeat result will be sent to this
channel/user/session.

---

#### `show_tool_details` — Tool output visibility

| Field               | Type | Default | Description                                                                                                          |
| ------------------- | ---- | ------- | -------------------------------------------------------------------------------------------------------------------- |
| `show_tool_details` | bool | `true`  | When `true`, channel messages include full tool call/result details. When `false`, details are hidden (shows "..."). |

---

## LLM Providers

CoPaw needs an LLM provider to work. You can set it up in three ways:

- **`copaw init`** — interactive wizard, the easiest way
- **Console UI** — click through the settings page at runtime
- **API** — `PUT /providers/{id}` and `PUT /providers/active_llm`

### Built-in providers

| Provider           | ID                  | Default Base URL                                    | API Key Prefix |
| ------------------ | ------------------- | --------------------------------------------------- | -------------- |
| ModelScope         | `modelscope`        | `https://api-inference.modelscope.cn/v1`            | `ms`           |
| DashScope          | `dashscope`         | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `sk`           |
| Aliyun Coding Plan | `aliyun-codingplan` | `https://coding.dashscope.aliyuncs.com/v1`          | `sk-sp`        |
| OpenAI             | `openai`            | `https://api.openai.com/v1`                         | _(any)_        |
| Azure OpenAI       | `azure-openai`      | _(you set it)_                                      | _(any)_        |
| Anthropic          | `anthropic`         | `https://api.anthropic.com`                         | _(any)_        |
| Ollama             | `ollama`            | `http://localhost:11434`                            | _(none)_       |
| LM Studio          | `lmstudio`          | `http://localhost:1234/v1`                          | _(none)_       |
| Custom             | `custom`            | _(you set it)_                                      | _(any)_        |

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

## Environment Variables

Some tools need extra API keys (e.g. `TAVILY_API_KEY` for web search). You can
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

Skills extend the agent's capabilities. They live in three directories:

| Directory                     | Purpose                                                             |
| ----------------------------- | ------------------------------------------------------------------- |
| Built-in (in source code)     | Shipped with CoPaw — docx, pdf, pptx, xlsx, news, email, cron, etc. |
| `~/.copaw/customized_skills/` | User-created skills                                                 |
| `~/.copaw/active_skills/`     | Currently active skills (synced from built-in + customized)         |

Each skill is a directory with a `SKILL.md` file (YAML front matter with `name`
and `description`), and optional `references/` and `scripts/` subdirectories.

Manage skills via:

- `copaw init` (choose all / none / custom during setup)
- `copaw skills config` (interactive toggle)
- API endpoints (`/skills/...`)

---

## Memory

CoPaw has persistent cross-conversation memory: it automatically compresses context and saves key information to Markdown files for long-term retention. See [Memory](./memory.en.md) for full details.

Memory files are stored in two locations:

| File / Directory                | Purpose                                                               |
| ------------------------------- | --------------------------------------------------------------------- |
| `~/.copaw/MEMORY.md`            | Long-lived key information (decisions, preferences, persistent facts) |
| `~/.copaw/memory/YYYY-MM-DD.md` | Daily logs (notes, runtime context, auto-generated summaries)         |

### Embedding Configuration

Memory search relies on vector embeddings for semantic retrieval. Configure via these environment variables:

| Variable                     | Description                       | Default                                             |
| ---------------------------- | --------------------------------- | --------------------------------------------------- |
| `EMBEDDING_API_KEY`          | API key for the embedding service | ``                                                  |
| `EMBEDDING_BASE_URL`         | Embedding service URL             | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `EMBEDDING_MODEL_NAME`       | Embedding model name              | `text-embedding-v4`                                 |
| `EMBEDDING_DIMENSIONS`       | Vector dimensions                 | `1024`                                              |
| `EMBEDDING_CACHE_ENABLED`    | Enable Embedding cache            | `true`                                              |
| `EMBEDDING_MAX_CACHE_SIZE`   | Max cache entries for Embedding   | `2000`                                              |
| `EMBEDDING_MAX_INPUT_LENGTH` | Max input length per Embedding    | `8192`                                              |
| `EMBEDDING_MAX_BATCH_SIZE`   | Max batch size for Embedding      | `10`                                                |

> Both `EMBEDDING_API_KEY` and `EMBEDDING_MODEL_NAME` must be non-empty to enable vector search in hybrid retrieval.

---

## Summary

- Everything lives under **`~/.copaw`** by default; override with
  `COPAW_WORKING_DIR` (and related env vars) if needed.
- From **v0.1.0**, configuration is split into:
  - **Global config** (`~/.copaw/config.json`) — providers, environment variables, agent list
  - **Agent config** (`~/.copaw/workspaces/{agent_id}/agent.json`) — per-agent settings
- Day-to-day you edit agent-specific **agent.json** (channels, heartbeat, language) and
  **HEARTBEAT.md** (what to ask on each heartbeat tick); manage cron jobs
  via CLI/API with `--agent-id` parameter.
- Each agent's personality is defined by Markdown files in its workspace directory:
  **SOUL.md** + **AGENTS.md** (required).
- LLM providers are globally configured via `copaw init` or the console UI.
- Config changes to channels are **auto-reloaded** without restart (polled
  every 2 seconds).
- Call the Agent API: **POST** `/agent/process` with `X-Agent-Id` header, JSON body, SSE streaming;
  see [Quick start — Verify install](./quickstart#verify-install-optional) for
  examples.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Channels](./channels) — How to fill in channels in config
- [Heartbeat](./heartbeat) — How to fill in heartbeat in config
- [Multi-Agent Workspace](./multi-agent) — Multi-agent setup and management

---

## Agent Prompt Files at a Glance

> Condensed from [Agent Prompt Files](./agent_md_intro.en.md) — see the full page for details.
>
> The prompt design in this section is inspired by [OpenClaw](https://github.com/openclaw/openclaw).

| File             | Core Purpose                                             | Read/Write                                                                      | Key Contents                                                                                                         |
| ---------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **SOUL.md**      | Defines the agent's **values and behavioral principles** | Read-only (predefined by developer/user)                                        | Be genuinely helpful; have your own opinions; try before asking; respect privacy boundaries                          |
| **PROFILE.md**   | Records the agent's **identity** and **user profile**    | Read-write (auto-generated by BOOTSTRAP, then editable manually or via console) | Agent side: name, role, style, capabilities; User side: name, preferences, background                                |
| **BOOTSTRAP.md** | **First-run onboarding** flow for new agents             | One-time (self-deletes after completion ✂️)                                     | ① Self-introduction → ② Learn about user → ③ Write PROFILE.md → ④ Read SOUL.md → ⑤ Self-delete                       |
| **AGENTS.md**    | Agent's **complete operating manual**                    | Read-only (core runtime reference)                                              | Memory system read/write rules; security & permissions; tool usage specs; heartbeat triggers; operational boundaries |
| **MEMORY.md**    | Stores agent's **tool settings and lessons learned**     | Read-write (maintained by agent, also manually editable)                        | SSH config & connections; local environment paths/versions; user personalization & preferences                       |
| **HEARTBEAT.md** | Defines agent's **background patrol tasks**              | Read-write (empty file = skip heartbeat)                                        | Empty → no patrol; write tasks → auto-execute checklist at configured intervals                                      |

**File collaboration:**

```
BOOTSTRAP.md (🐣 one-time)
    ├── generates → PROFILE.md (🪪 who am I)
    ├── guides reading → SOUL.md (🫀 my soul)
    └── self-deletes after completion ✂️

AGENTS.md (📋 daily manual)
    ├── reads/writes → MEMORY.md (🧠 long-term memory)
    ├── references → HEARTBEAT.md (💓 periodic patrol)
    └── references → PROFILE.md (🪪 know the user)
```

> **In one sentence:** SOUL defines character, PROFILE remembers relationships, BOOTSTRAP handles birth, AGENTS governs behavior, MEMORY accumulates experience, HEARTBEAT stays vigilant.
