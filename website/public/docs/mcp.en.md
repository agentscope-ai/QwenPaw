# MCP

**MCP (Model Context Protocol)** allows RyPaw to connect to external MCP servers and use their tools. You can add MCP clients through the Console to extend RyPaw's capabilities.

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

RyPaw supports three JSON formats for importing MCP clients:

### Format 1: Standard mcpServers format (Recommended)

```json
{
  "mcpServers": {
    "client-name": {
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
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {
    "API_KEY": "your-api-key-here"
  }
}
```

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

---

## Managing MCP clients

Once imported, you can:

- **View all clients** — See all MCP clients as cards on the MCP page
- **Enable / Disable** — Toggle clients on or off without deleting them
- **Edit configuration** — Click a card to view and edit the JSON configuration
- **Delete clients** — Remove MCP clients you no longer need
