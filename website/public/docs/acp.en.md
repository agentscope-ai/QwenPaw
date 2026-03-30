# ACP (Agent Client Protocol)

**ACP (Agent Client Protocol)** allows CoPaw to connect to external coding agents (such as OpenCode, Qwen-code, Gemini CLI) and leverage their capabilities to enhance CoPaw's functionality.

---

## What is ACP?

ACP is a protocol for connecting to external agents. Compared to MCP (Model Context Protocol):

| Feature           | MCP                          | ACP                               |
| ----------------- | ---------------------------- | --------------------------------- |
| Connection Target | External tool servers        | External coding agents            |
| Typical Use       | Filesystem access, API calls | Code generation, project analysis |
| Interaction Mode  | Tool calls                   | Conversational interaction        |
| Examples          | filesystem, brave-search     | OpenCode, Qwen-code               |

---

## Prerequisites

If using `npx` to run ACP harnesses, ensure you have:

- **Node.js** 18 or higher ([download](https://nodejs.org/))

Check Node.js version:

```bash
node --version
```

---

## Configuration

### Configuration File Location

ACP configuration is stored in `~/.copaw/config.json`:

```json
{
  "acp": {
    "enabled": true,
    "require_approval": false,
    "save_dir": "~/.copaw/acp_sessions",
    "harnesses": {
      "opencode": {
        "enabled": true,
        "command": "npx",
        "args": ["-y", "opencode-ai@latest", "acp"],
        "env": {}
      },
      "qwen": {
        "enabled": true,
        "command": "npx",
        "args": ["-y", "@qwen-code/qwen-code@latest", "--acp"],
        "env": {}
      }
    }
  }
}
```

### Configuration Options

| Option             | Type    | Default                   | Description                                       |
| ------------------ | ------- | ------------------------- | ------------------------------------------------- |
| `enabled`          | boolean | `false`                   | Global ACP functionality switch                   |
| `require_approval` | boolean | `false`                   | Whether to require user approval before execution |
| `save_dir`         | string  | `"~/.copaw/acp_sessions"` | Directory to save session states                  |
| `harnesses`        | object  | -                         | Harness configuration object                      |

### Harness Configuration

Each harness supports the following options:

| Option    | Type     | Default | Description                    |
| --------- | -------- | ------- | ------------------------------ |
| `enabled` | boolean  | `false` | Whether to enable this harness |
| `command` | string   | `""`    | Launch command                 |
| `args`    | string[] | `[]`    | Command arguments              |
| `env`     | object   | `{}`    | Environment variables          |

---

## Supported Harnesses

### OpenCode

OpenCode is an AI coding assistant supporting multiple programming languages and frameworks.

```json
{
  "opencode": {
    "enabled": true,
    "command": "npx",
    "args": ["-y", "opencode-ai@latest", "acp"]
  }
}
```

### Qwen-code

Qwen-code ACP support from Tongyi Lingma, requires API key configuration.

```json
{
  "qwen": {
    "enabled": true,
    "command": "npx",
    "args": ["-y", "@qwen-code/qwen-code@latest", "--acp"],
    "env": {
      "QWEN_CODE_API_KEY": "your-api-key"
    }
  }
}
```

### Gemini CLI

Google Gemini CLI experimental ACP support.

```json
{
  "gemini": {
    "enabled": false,
    "command": "npx",
    "args": ["-y", "@google/gemini-cli@latest", "--experimental-acp"]
  }
}
```

---

## Usage Examples

### Trigger via `/acp` command

Enter the following commands in chat to trigger ACP:

```
/acp opencode analyze the code structure of this project
```

```
/acp qwen explain what this function does
```

### Trigger via natural language

CoPaw will automatically recognize scenarios requiring ACP:

```
Help me refactor this code using opencode
```

```
Let qwen analyze this bug
```

### Session Reuse

ACP supports session reuse to maintain context continuity:

```
/acp opencode continue analysis in current session
```

```
/acp opencode continue working using the previous session
```

---

## Configure ACP in Console

1. Open the console and navigate to **Agent → ACP**
2. Enable ACP functionality in "Global Settings"
3. Configure the desired Harnesses (enable, set command arguments, environment variables)
4. Click Save

---

## FAQ

### Q: What is the difference between ACP and MCP?

A: MCP is used to connect to external tool servers (like filesystem, search engines), while ACP is used to connect to external coding agents (like OpenCode, Qwen-code). MCP provides tool capabilities, ACP provides agent collaboration capabilities.

### Q: How do I add a custom Harness?

A: In the ACP configuration page of the console, click "Add Harness", fill in the identifier, launch command, arguments, and environment variables.

### Q: Where are ACP sessions saved?

A: By default saved in `~/.copaw/acp_sessions` directory, you can change the location by modifying `save_dir` in the configuration.

### Q: Why is user approval needed?

A: When `require_approval` is set to `true`, ACP will request user confirmation before executing operations that may modify files or execute commands, increasing security.
