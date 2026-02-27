# CLI

`copaw` is the command-line tool for CoPaw. This page is organized from
"get-up-and-running" to "advanced management" — read from top to bottom if
you're new, or jump to the section you need.

> Not sure what "channels", "heartbeat", or "cron" mean? See
> [Introduction](./intro) first.

---

## Getting started

These are the commands you'll use on day one.

### copaw init

First-time setup. Walks you through configuration interactively.

```bash
copaw init              # Interactive setup (recommended for first time)
copaw init --defaults   # Non-interactive, use all defaults (good for scripts)
copaw init --force      # Overwrite existing config files
```

**What the interactive flow covers (in order):**

1. **Heartbeat** — interval (e.g. `30m`), target (`main` / `last`), optional
   active hours.
2. **Show tool details** — whether tool call details appear in channel messages.
3. **Language** — `zh` or `en` for agent persona files (SOUL.md, etc.).
4. **Channels** — optionally configure iMessage / Discord / DingTalk / Feishu /
   QQ / Console.
5. **LLM provider** — select provider, enter API key, choose model (**required**).
6. **Skills** — enable all / none / custom selection.
7. **Environment variables** — optionally add key-value pairs for tools.
8. **HEARTBEAT.md** — edit the heartbeat checklist in your default editor.

### copaw app

Start the CoPaw server. Everything else — channels, cron jobs, the Console
UI — depends on this.

```bash
copaw app                             # Start on 127.0.0.1:8088
copaw app --host 0.0.0.0 --port 9090 # Custom address
copaw app --reload                    # Auto-reload on code change (dev)
copaw app --workers 4                 # Multi-worker mode
copaw app --log-level debug           # Verbose logging
```

| Option        | Default     | Description                                                   |
| ------------- | ----------- | ------------------------------------------------------------- |
| `--host`      | `127.0.0.1` | Bind host                                                     |
| `--port`      | `8088`      | Bind port                                                     |
| `--reload`    | off         | Auto-reload on file changes (dev only)                        |
| `--workers`   | `1`         | Number of worker processes                                    |
| `--log-level` | `info`      | `critical` / `error` / `warning` / `info` / `debug` / `trace` |

### Console

Once `copaw app` is running, open `http://127.0.0.1:8088/` in your browser to
access the **Console** — a web UI for chat, channels, cron, skills, models,
and more. See [Console](./console) for a full walkthrough.

If the frontend was not built, the root URL returns `{"message": "Hello World"}`
but the API still works.

**To build the frontend:** in the project's `console/` directory run
`npm ci && npm run build` (output in `console/dist/`). Docker images and pip
packages already include the Console.

---

## Models & environment variables

Before using CoPaw you need at least one LLM provider configured. Environment
variables power many built-in tools (e.g. web search).

### copaw models

Manage LLM providers and the active model.

| Command                                | What it does                                         |
| -------------------------------------- | ---------------------------------------------------- |
| `copaw models list`                    | Show all providers, API key status, and active model |
| `copaw models config`                  | Full interactive setup: API keys → active model      |
| `copaw models config-key [provider]`   | Configure a single provider's API key                |
| `copaw models set-llm`                 | Switch the active model (API keys unchanged)         |
| `copaw models download <repo_id>`      | Download a local model (llama.cpp / MLX)             |
| `copaw models local`                   | List downloaded local models                         |
| `copaw models remove-local <model_id>` | Delete a downloaded local model                      |
| `copaw models ollama-pull <model>`     | Download an Ollama model                             |
| `copaw models ollama-list`             | List Ollama models                                   |
| `copaw models ollama-remove <model>`   | Delete an Ollama model                               |

```bash
copaw models list                    # See what's configured
copaw models config                  # Full interactive setup
copaw models config-key modelscope   # Just set ModelScope's API key
copaw models config-key dashscope    # Just set DashScope's API key
copaw models config-key custom       # Set custom provider (Base URL + key)
copaw models set-llm                 # Change active model only
```

#### Local models

CoPaw can also run models locally via llama.cpp or MLX — no API key needed.
Install the backend first: `pip install 'copaw[llamacpp]'` or
`pip install 'copaw[mlx]'`.

```bash
# Download a model (auto-selects Q4_K_M GGUF)
copaw models download Qwen/Qwen3-4B-GGUF

# Download an MLX model
copaw models download Qwen/Qwen3-4B --backend mlx

# Download from ModelScope
copaw models download Qwen/Qwen2-0.5B-Instruct-GGUF --source modelscope

# List downloaded models
copaw models local
copaw models local --backend mlx

# Delete a downloaded model
copaw models remove-local <model_id>
copaw models remove-local <model_id> --yes   # skip confirmation
```

| Option      | Short | Default       | Description                                                           |
| ----------- | ----- | ------------- | --------------------------------------------------------------------- |
| `--backend` | `-b`  | `llamacpp`    | Target backend (`llamacpp` or `mlx`)                                  |
| `--source`  | `-s`  | `huggingface` | Download source (`huggingface` or `modelscope`)                       |
| `--file`    | `-f`  | _(auto)_      | Specific filename. If omitted, auto-selects (prefers Q4_K_M for GGUF) |

#### Ollama models

CoPaw integrates with Ollama to run models locally. Models are dynamically loaded from your Ollama daemon — install Ollama first from [ollama.com](https://ollama.com).

Install the Ollama SDK: `pip install ollama`

```bash
# Download an Ollama model
copaw models ollama-pull mistral:7b
copaw models ollama-pull qwen3:8b

# List Ollama models
copaw models ollama-list

# Remove an Ollama model
copaw models ollama-remove mistral:7b
copaw models ollama-remove qwen3:8b --yes   # skip confirmation

# Use in config flow (auto-detects Ollama models)
copaw models config           # Select Ollama → Choose from model list
copaw models set-llm          # Switch to a different Ollama model
```

**Key differences from local models:**

- Models come from Ollama daemon (not downloaded by CoPaw)
- Use `ollama-pull` / `ollama-remove` instead of `download` / `remove-local`
- Model list updates dynamically when you add/remove via Ollama CLI or CoPaw

> **Note:** You are responsible for ensuring the API key is valid. CoPaw does
> not verify key correctness. See [Config — LLM Providers](./config#llm-providers).

### copaw env

Manage environment variables used by tools and skills at runtime.

| Command                   | What it does                  |
| ------------------------- | ----------------------------- |
| `copaw env list`          | List all configured variables |
| `copaw env set KEY VALUE` | Set or update a variable      |
| `copaw env delete KEY`    | Delete a variable             |

```bash
copaw env list
copaw env set TAVILY_API_KEY "tvly-xxxxxxxx"
copaw env set GITHUB_TOKEN "ghp_xxxxxxxx"
copaw env delete TAVILY_API_KEY
```

> **Note:** CoPaw only stores and loads these values; you are responsible for
> ensuring they are correct. See
> [Config — Environment Variables](./config#environment-variables).

---

## Channels

Connect CoPaw to messaging platforms.

### copaw channels

| Command                 | What it does                                                  |
| ----------------------- | ------------------------------------------------------------- |
| `copaw channels list`   | Show all channels and their status (secrets masked)           |
| `copaw channels config` | Interactively enable/disable channels and fill in credentials |

```bash
copaw channels list     # See current status
copaw channels config   # Interactive configuration
```

The interactive flow lets you pick a channel, enable/disable it, and enter its
credentials. It loops until you choose "Save and exit".

| Channel      | Fields to fill in                             |
| ------------ | --------------------------------------------- |
| **iMessage** | Bot prefix, database path, poll interval      |
| **Discord**  | Bot prefix, Bot Token, HTTP proxy, proxy auth |
| **DingTalk** | Bot prefix, Client ID, Client Secret          |
| **Feishu**   | Bot prefix, App ID, App Secret                |
| **QQ**       | Bot prefix, App ID, Client Secret             |
| **Console**  | Bot prefix                                    |

> For platform-specific credential setup, see [Channels](./channels).

---

## Cron (scheduled tasks)

Create jobs that run on a timed schedule — "every day at 9am", "every 2 hours
ask CoPaw and send the reply". **Requires `copaw app` to be running.**

### copaw cron

| Command                      | What it does                                  |
| ---------------------------- | --------------------------------------------- |
| `copaw cron list`            | List all jobs                                 |
| `copaw cron get <job_id>`    | Show a job's spec                             |
| `copaw cron state <job_id>`  | Show runtime state (next run, last run, etc.) |
| `copaw cron create ...`      | Create a job                                  |
| `copaw cron delete <job_id>` | Delete a job                                  |
| `copaw cron pause <job_id>`  | Pause a job                                   |
| `copaw cron resume <job_id>` | Resume a paused job                           |
| `copaw cron run <job_id>`    | Run once immediately                          |

### Creating jobs

**Option 1 — CLI arguments (simple jobs)**

Two task types:

- **text** — send a fixed message to a channel on schedule.
- **agent** — ask CoPaw a question on schedule and deliver the reply.

```bash
# Text: send "Good morning!" to DingTalk every day at 9:00
copaw cron create \
  --type text \
  --name "Daily 9am" \
  --cron "0 9 * * *" \
  --channel dingtalk \
  --target-user "your_user_id" \
  --target-session "session_id" \
  --text "Good morning!"

# Agent: every 2 hours, ask CoPaw and forward the reply
copaw cron create \
  --type agent \
  --name "Check todos" \
  --cron "0 */2 * * *" \
  --channel dingtalk \
  --target-user "your_user_id" \
  --target-session "session_id" \
  --text "What are my todo items?"
```

Required: `--type`, `--name`, `--cron`, `--channel`, `--target-user`,
`--target-session`, `--text`.

**Option 2 — JSON file (complex or batch)**

```bash
copaw cron create -f job_spec.json
```

JSON structure matches the output of `copaw cron get <job_id>`.

### Additional options

| Option                       | Default | Description                                           |
| ---------------------------- | ------- | ----------------------------------------------------- |
| `--timezone`                 | `UTC`   | Timezone for the cron schedule                        |
| `--enabled` / `--no-enabled` | enabled | Create enabled or disabled                            |
| `--mode`                     | `final` | `stream` (incremental) or `final` (complete response) |
| `--base-url`                 | auto    | Override the API base URL                             |

### Cron expression cheat sheet

Five fields: **minute hour day month weekday** (no seconds).

| Expression     | Meaning                   |
| -------------- | ------------------------- |
| `0 9 * * *`    | Every day at 9:00         |
| `0 */2 * * *`  | Every 2 hours on the hour |
| `30 8 * * 1-5` | Weekdays at 8:30          |
| `0 0 * * 0`    | Sunday at midnight        |
| `*/15 * * * *` | Every 15 minutes          |

---

## Chats (sessions)

Manage chat sessions via the API. **Requires `copaw app` to be running.**

### copaw chats

| Command                                | What it does                                                  |
| -------------------------------------- | ------------------------------------------------------------- |
| `copaw chats list`                     | List all sessions (supports `--user-id`, `--channel` filters) |
| `copaw chats get <id>`                 | View a session's details and message history                  |
| `copaw chats create ...`               | Create a new session                                          |
| `copaw chats update <id> --name "..."` | Rename a session                                              |
| `copaw chats delete <id>`              | Delete a session                                              |

```bash
copaw chats list
copaw chats list --user-id alice --channel dingtalk
copaw chats get 823845fe-dd13-43c2-ab8b-d05870602fd8
copaw chats create --session-id "discord:alice" --user-id alice --name "My Chat"
copaw chats create -f chat.json
copaw chats update <chat_id> --name "Renamed"
copaw chats delete <chat_id>
```

---

## Skills

Extend CoPaw's capabilities with skills (PDF reading, web search, etc.).

### copaw skills

| Command               | What it does                                      |
| --------------------- | ------------------------------------------------- |
| `copaw skills list`   | Show all skills and their enabled/disabled status |
| `copaw skills config` | Interactively enable/disable skills (checkbox UI) |

```bash
copaw skills list     # See what's available
copaw skills config   # Toggle skills on/off interactively
```

In the interactive UI: ↑/↓ to navigate, Space to toggle, Enter to confirm.
A preview of changes is shown before applying.

> For built-in skill details and custom skill authoring, see [Skills](./skills).

---

## Maintenance

### copaw clean

Remove everything under the working directory (default `~/.copaw`).

```bash
copaw clean             # Interactive confirmation
copaw clean --yes       # No confirmation
copaw clean --dry-run   # Only list what would be removed
```

---

## Global options

Every `copaw` subcommand inherits:

| Option          | Default     | Description                                    |
| --------------- | ----------- | ---------------------------------------------- |
| `--host`        | `127.0.0.1` | API host (auto-detected from last `copaw app`) |
| `--port`        | `8088`      | API port (auto-detected from last `copaw app`) |
| `-h` / `--help` |             | Show help message                              |

If the server runs on a non-default address, pass these globally:

```bash
copaw --host 0.0.0.0 --port 9090 cron list
```

## Working directory

All config and data live in `~/.copaw` by default: `config.json`,
`HEARTBEAT.md`, `jobs.json`, `chats.json`, skills, memory, and agent persona
files.

| Variable            | Description                         |
| ------------------- | ----------------------------------- |
| `COPAW_WORKING_DIR` | Override the working directory path |
| `COPAW_CONFIG_FILE` | Override the config file path       |

See [Config & Working Directory](./config) for full details.

---

## Command overview

| Command          | Subcommands                                                                                                                            | Requires server? |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------- | :--------------: |
| `copaw init`     | —                                                                                                                                      |        No        |
| `copaw app`      | —                                                                                                                                      |  — (starts it)   |
| `copaw models`   | `list` · `config` · `config-key` · `set-llm` · `download` · `local` · `remove-local` · `ollama-pull` · `ollama-list` · `ollama-remove` |        No        |
| `copaw env`      | `list` · `set` · `delete`                                                                                                              |        No        |
| `copaw channels` | `list` · `config`                                                                                                                      |        No        |
| `copaw cron`     | `list` · `get` · `state` · `create` · `delete` · `pause` · `resume` · `run`                                                            |     **Yes**      |
| `copaw chats`    | `list` · `get` · `create` · `update` · `delete`                                                                                        |     **Yes**      |
| `copaw skills`   | `list` · `config`                                                                                                                      |        No        |
| `copaw clean`    | —                                                                                                                                      |        No        |

---

## Related pages

- [Introduction](./intro) — What CoPaw can do
- [Console](./console) — Web-based management UI
- [Channels](./channels) — DingTalk, Feishu, iMessage, Discord, QQ setup
- [Heartbeat](./heartbeat) — Scheduled check-in / digest
- [Skills](./skills) — Built-in and custom skills
- [Config & Working Directory](./config) — Working directory and config.json
