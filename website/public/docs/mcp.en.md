# MCP

**MCP (Model Context Protocol)** allows CoPaw to connect to external MCP servers and use their tools. You can add MCP clients through the Console to extend CoPaw's capabilities.

---

## Prerequisites

If using `npx` to run MCP servers, ensure you have:

- **Node.js** version 18 or higher ([download](https://nodejs.org/))

Check your Node.js version:

```bash
node --version
```

---

## Adding MCP clients in the Console

1. Open the Console and go to **Agent → MCP**
2. Click **+ Create** button
3. Paste your MCP client configuration in JSON format
4. Click **Create** to import

---

## Configuration formats

CoPaw supports three JSON formats for importing MCP clients:

### Format 1: Standard mcpServers format (Recommended)

```json
{
  "mcpServers": {
    "client-name": {
      "name": "My MCP Client",
      "description": "Optional client description",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem"],
      "env": {
        "API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### Format 2: Direct key-value format

```json
{
  "client-name": {
    "description": "Optional client description",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem"],
    "env": {
      "API_KEY": "your-api-key-here"
    }
  }
}
```

### Format 3: Single client format

```json
{
  "key": "client-name",
  "name": "My MCP Client",
  "description": "Optional client description",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {
    "API_KEY": "your-api-key-here"
  }
}
```

### Common fields (including description)

- `name`: display name (optional, key is used if omitted)
- `description`: free-text description (optional, recommended for clarity)
- `enabled`: whether the client is enabled (optional, default `true`)
- `transport`: transport type (optional, supports `stdio` / `streamable_http` / `sse`)
- `command`, `args`, `env`, `cwd`: common fields for local command-based MCP
- `url`, `headers`: common fields for remote MCP

Transport validation rules:

- `transport=stdio`: requires non-empty `command`
- `transport=streamable_http` or `sse`: requires non-empty `url`
- if `transport` is omitted: config with `url` defaults to `streamable_http`; otherwise defaults to `stdio`

---

## Example: Filesystem MCP server

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/username/Documents"
      ]
    }
  }
}
```

> Replace `/Users/username/Documents` with the directory path you want the agent to access.

Remote MCP example (with `description`):

```json
{
  "mcpServers": {
    "example_mcp": {
      "name": "Example Mcp Server",
      "description": "Remote MCP endpoint over HTTP",
      "transport": "streamable_http",
      "url": "http://127.0.0.1:8585/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_TOKEN>"
      }
    }
  }
}
```

---

## Managing MCP clients

Once imported, you can:

- **View all clients** — See all MCP clients as cards on the MCP page
- **Enable / Disable** — Toggle clients on or off without deleting them
- **Edit configuration** — Click a card to view and edit the JSON configuration
- **Delete clients** — Remove MCP clients you no longer need
