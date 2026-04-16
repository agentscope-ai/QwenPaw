# ACP Server — QwenPaw as an ACP Agent

This module exposes QwenPaw as an [Agent Client Protocol (ACP)](https://github.com/agentclientprotocol/python-sdk) compliant agent server over stdio JSON-RPC. External clients — such as [Zed](https://zed.dev), [OpenCode](https://github.com/nicholasgasior/opencode), or any ACP-compatible editor — can connect to QwenPaw via the `qwenpaw acp` CLI command and interact with it programmatically.

---

## Quick Start

```bash
# Start QwenPaw as an ACP agent
qwenpaw acp

# Use a specific agent profile
qwenpaw acp --agent mybot

# Use a custom workspace directory
qwenpaw acp --workspace /path/to/workspace

# Enable debug logging to stderr
qwenpaw acp --debug
```

The process communicates over stdin/stdout using the ACP JSON-RPC protocol. stderr is used for logging.

---

## Supported ACP Methods

| Method              | Description                                                  |
| ------------------- | ------------------------------------------------------------ |
| `initialize`        | Handshake — returns agent capabilities and version info      |
| `new_session`       | Create a new conversation session                            |
| `load_session`      | Load/attach to an existing session by ID                     |
| `resume_session`    | Resume a previously closed session                           |
| `list_sessions`     | List active sessions, optionally filtered by `cwd`           |
| `close_session`     | Close and clean up a session                                 |
| `prompt`            | Send a user message and stream back agent responses          |
| `set_session_model` | Switch the active LLM model (format: `provider_id:model_id`) |
| `set_config_option` | Toggle session config options (e.g. Tool Guard on/off)       |
| `cancel`            | Cancel an in-progress prompt                                 |

---

## Streaming Updates

During a `prompt` call, the agent streams real-time updates back to the client via `session_update` notifications:

| Update Type           | When                                       |
| --------------------- | ------------------------------------------ |
| `agent_message_chunk` | Agent text response (streaming)            |
| `agent_thought_chunk` | Agent internal reasoning / system messages |
| `tool_call`           | Tool invocation started                    |
| `tool_call_update`    | Tool execution completed with output       |

---

## Capabilities Declared

The agent declares the following capabilities during `initialize`:

```json
{
  "load_session": true,
  "session_capabilities": {
    "close": {},
    "list": {},
    "resume": {}
  }
}
```

---

## Session Config Options

When a new session is created, the agent returns config options that the client can change via `set_config_option`:

| Config ID | Type   | Category | Default   | Options                                                                                       |
| --------- | ------ | -------- | --------- | --------------------------------------------------------------------------------------------- |
| `mode`    | select | `mode`   | `default` | `default` — Normal mode with Tool Guard enabled; `bypassPermissions` — Skip tool guard checks |

---

## Configuration

The ACP agent resolves its configuration in the following order:

1. **CLI arguments** — `--agent` and `--workspace` take highest priority
2. **WORKING_DIR config** — reads `agents.active_agent` from the `config.json` inside `WORKING_DIR` (default `~/.qwenpaw`, or `~/.copaw` for legacy installations; overridable via `QWENPAW_WORKING_DIR` env var)
3. **Defaults** — falls back to agent ID `"default"` and workspace directory `WORKING_DIR/workspaces/default/`
