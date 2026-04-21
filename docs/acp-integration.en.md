# ACP Integration

QwenPaw supports **ACP (Agent Client Protocol)** in two complementary ways:

1. **QwenPaw as an ACP Server** — external clients connect to QwenPaw over ACP
2. **QwenPaw using ACP as a Tool** — QwenPaw connects to external ACP runners and collaborates with them as delegated agents

This page explains both modes and when to use each one.

---

## QwenPaw as ACP Server

In this mode, QwenPaw exposes itself as an [Agent Client Protocol (ACP)](https://github.com/agentclientprotocol/python-sdk) compliant agent server over stdio JSON-RPC. External clients — such as [Zed](https://zed.dev), [OpenCode](https://github.com/nicholasgasior/opencode), or any ACP-compatible editor — can connect to QwenPaw via the `qwenpaw acp` CLI command and interact with it programmatically.

### Quick Start

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

### Supported ACP Methods

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

### Streaming Updates

During a `prompt` call, the agent streams real-time updates back to the client via `session_update` notifications:

| Update Type           | When                                       |
| --------------------- | ------------------------------------------ |
| `agent_message_chunk` | Agent text response (streaming)            |
| `agent_thought_chunk` | Agent internal reasoning / system messages |
| `tool_call`           | Tool invocation started                    |
| `tool_call_update`    | Tool execution completed with output       |

### Capabilities Declared

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

### Session Config Options

When a new session is created, the agent returns config options that the client can change via `set_config_option`:

| Config ID | Type   | Category | Default   | Options                                                                                       |
| --------- | ------ | -------- | --------- | --------------------------------------------------------------------------------------------- |
| `mode`    | select | `mode`   | `default` | `default` — Normal mode with Tool Guard enabled; `bypassPermissions` — Skip tool guard checks |

### Configuration

The ACP agent resolves its configuration in the following order:

1. **CLI arguments** — `--agent` and `--workspace` take highest priority
2. **WORKING_DIR config** — reads `agents.active_agent` from the `config.json` inside `WORKING_DIR` (default `~/.qwenpaw`, or `~/.copaw` for legacy installations; overridable via `QWENPAW_WORKING_DIR` env var)
3. **Defaults** — falls back to agent ID `"default"` and workspace directory `WORKING_DIR/workspaces/default/`

---

## QwenPaw using ACP as a Tool

QwenPaw can also use ACP in the opposite direction: instead of being the server that external clients connect to, it can act as an **ACP client / orchestrator** that connects to **configured and enabled external ACP runners** and brings them into the current session as delegated collaboration capabilities.

The actual entry point for this mode is the built-in tool `delegate_external_agent`. It is intended for scenarios where QwenPaw needs to collaborate with other ACP-capable external agent runtimes. In the source code, the built-in runner set includes `opencode`, `qwen_code`, `claude_code`, and `codex`. For more ACP-compatible agents, see the official ACP agent list and integration guide: <https://agentclientprotocol.com/get-started/agents>. In other words, QwenPaw does not directly talk to arbitrary external agents by default — it talks to runners that have been registered in ACP configuration and are available to the current agent.

### What this mode does

In this mode, QwenPaw uses the built-in `delegate_external_agent` tool to:

- start a session with an external ACP runner
- send follow-up messages to that runner
- respond to permission requests raised by that runner
- close the delegated session when work is complete

Conceptually, this allows QwenPaw to treat an external agent as a cooperative tool-like capability, while QwenPaw remains the primary orchestrator of the main conversation.

### How to configure external runners

Before using an external runner, make sure you have installed an ACP-compatible external agent and completed any required login or API key setup so it can be started and used normally from the command line. You can refer to the official ACP agent list here: <https://agentclientprotocol.com/get-started/agents>.

![qwen](https://gw.alicdn.com/imgextra/i1/O1CN017f6aVo1tWpstPL4GK_!!6000000005910-2-tps-1226-408.png)

Once the command-line side is ready, you can either configure a custom agent in QwenPaw or use one of the built-in agents for collaboration.

External runners must be configured and enabled on the **Workspace → ACP** page before they can be used by `delegate_external_agent`.

The current ACP configuration UI supports these fields for each runner:

- `enabled`
- `command`
- `args`
- `env`
- `trusted`
- `tool_parse_mode`
- `stdio_buffer_limit_bytes`

Specifically:

- `command` and `args` define how the external runner process is launched;
- `env` passes environment variables;
- `tool_parse_mode` and `stdio_buffer_limit_bytes` control ACP output parsing and stdio buffering behavior.

The source code ships with these built-in runner examples: `opencode`, `qwen_code`, `claude_code`, and `codex`. You can also add custom runners on the ACP page as long as they can run via ACP and are configured correctly.

![config](https://gw.alicdn.com/imgextra/i3/O1CN01QQjKIv1jAibICuR7Q_!!6000000004508-2-tps-1224-480.png)

After that, enable the `delegate_external_agent` tool in the toolbar.

![config](https://gw.alicdn.com/imgextra/i4/O1CN01XS6D6W1Yzap02Jnjk_!!6000000003130-2-tps-1224-700.png)

You can then specify in the conversation which external agent you want to collaborate with.

![comm](https://gw.alicdn.com/imgextra/i3/O1CN01LpUJWZ1QOTniYDnrP_!!6000000001966-2-tps-1986-946.png)

### Typical workflow

A typical delegated ACP workflow looks like this:

1. Configure and enable a runner on the **Workspace → ACP** page.
2. In a conversation, call `delegate_external_agent(action="start", runner="...", message="...")` to start a new delegated session for that runner.
3. If you want to continue the collaboration, call `delegate_external_agent(action="message", runner="...", message="...")` to send follow-up instructions to the existing runner session.
4. If the external runner raises a permission request, first let the user choose from the options shown in the UI, then call `delegate_external_agent(action="respond", runner="...", message="<exact option id>")` to resume execution. Here, `message` must be the **exact option id** returned by that permission request.
5. After the delegated work is complete, call `delegate_external_agent(action="close", runner="...")` to close the runner session.

You can pass task prompts such as “analyze the current working directory structure” or “write your self-introduction into a markdown file” in `start` or `message`, but the underlying flow always maps to the same four actions: `start`, `message`, `respond`, and `close`.

### Supported delegated actions

The built-in delegation flow supports these action types:

| Action    | Purpose                                                            |
| --------- | ------------------------------------------------------------------ |
| `start`   | Start a new delegated ACP session                                  |
| `message` | Send a follow-up message to an existing delegated session          |
| `respond` | Reply to a pending permission request using the selected option id |
| `close`   | Close the delegated ACP session                                    |

### Permission handling

When an external ACP runner asks for permission, QwenPaw does **not** decide on the user's behalf.

Instead, it:

- pauses the delegated flow
- shows the permission details and available options
- waits for the user to choose how to proceed

This keeps delegated ACP execution aligned with the same user-controlled safety model used elsewhere in QwenPaw.

### When to use ACP as a Tool

Use this mode when:

- you want QwenPaw to collaborate with another agent runtime
- you have a specialized external ACP-compatible runner for a certain class of tasks
- you want to keep QwenPaw as the main orchestrator while delegating part of the work outward

### ACP Tool vs MCP

ACP-as-Tool and MCP solve different problems:

- **MCP** connects QwenPaw to external services and tool servers
- **ACP as Tool** connects QwenPaw to an external **agent** runtime

If you need APIs, databases, filesystems, or service integrations, use **MCP**.
If you need agent-to-agent collaboration, use **ACP as Tool**.

---

## ACP Server vs ACP Tool

| Aspect               | QwenPaw as ACP Server                         | QwenPaw using ACP as Tool                              |
| -------------------- | --------------------------------------------- | ------------------------------------------------------ |
| QwenPaw's role       | Server / target agent                         | Client / orchestrator                                  |
| Connection direction | External client connects to QwenPaw           | QwenPaw connects to external runner                    |
| Main purpose         | Let editors or external clients drive QwenPaw | Let QwenPaw delegate work to another agent             |
| Typical entry point  | `qwenpaw acp`                                 | Delegation tool + ACP runner config                    |
| Best for             | Editor integration, programmatic control      | Multi-agent collaboration, external specialist runners |

---

## Summary

ACP in QwenPaw is not just one feature — it supports both directions:

- **Expose QwenPaw outward** as an ACP server
- **Reach outward from QwenPaw** to external ACP agents as delegated tools

If you are integrating QwenPaw into another client, start with **ACP Server**.
If you want QwenPaw to coordinate with another agent runtime, use **ACP as Tool**.
