# MCP & Built-in Tools

CoPaw uses **MCP (Model Context Protocol)** to connect to external services and provides a suite of **built-in tools** that enable agents to access filesystems, execute commands, browse the web, and more.

---

## Concepts

CoPaw provides two types of tools for agents:

1. **Built-in Tools**: Ready-to-use tools provided by CoPaw core, such as file operations, command execution, and browser automation

   - Managed on the **Agent → Tools** page
   - Can be individually enabled/disabled

2. **MCP Tools**: Connect to external services via MCP protocol to extend additional capabilities
   - Configure clients on the **Agent → MCP** page
   - MCP clients register new tools with the agent

Both types can be used simultaneously without conflict.

---

## MCP

**MCP (Model Context Protocol)** allows CoPaw to connect to external MCP servers, extending the agent's ability to access filesystems, databases, APIs, and other external resources.

### Prerequisites

For local MCP servers, you need:

- **Node.js** 18+ ([download](https://nodejs.org/))

```bash
node --version  # Check version
```

> Remote MCP servers require no local dependencies.

---

### Adding MCP Clients

1. Open the Console and go to **Agent → MCP**
2. Click **+ Create** button
3. Paste your MCP client JSON configuration
4. Click **Create** to import

<!-- TODO: Add screenshot - Show MCP creation modal -->

---

### Configuration Formats

CoPaw supports three JSON formats—choose one:

#### Format 1: Standard mcpServers Format (**Recommended**)

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/path/to/folder"
      ],
      "env": {
        "API_KEY": "your-api-key"
      }
    }
  }
}
```

#### Format 2: Direct Key-Value Format

Omit the `mcpServers` wrapper:

```json
{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"]
  }
}
```

#### Format 3: Single Client Format

```json
{
  "key": "filesystem",
  "name": "Filesystem Access",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"]
}
```

> All formats support importing multiple clients at once.

---

### Configuration Examples

#### Filesystem Access

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

#### Web Search (Tavily)

Tavily is an AI-optimized web search service that enables agents to perform real-time web searches.

```json
{
  "mcpServers": {
    "tavily": {
      "command": "npx",
      "args": ["-y", "tavily-mcp@latest"],
      "env": {
        "TAVILY_API_KEY": "tvly-xxxxxxxxxxxxx"
      }
    }
  }
}
```

> **Built-in Support**: A `tavily_search` client is automatically created at system startup. It auto-enables when the `TAVILY_API_KEY` environment variable is set. You can also directly modify the tavily mcp configuration.

#### Remote MCP Service

```json
{
  "mcpServers": {
    "remote-api": {
      "transport": "streamable_http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer your-token"
      }
    }
  }
}
```

---

### Advanced Options

#### Transport Types

MCP supports three transport protocols, usually auto-detected:

- **stdio** — Local command-line tools, requires `command` field
- **streamable_http** — Remote HTTP services, requires `url` field
- **sse** — Server-Sent Events, requires `url` and `transport: "sse"`

#### Configuration Fields

- `command` — Launch command (required for stdio)
- `args` — Command arguments
- `env` — Environment variables (e.g., API keys)
- `cwd` — Working directory
- `url` — Remote service URL (required for HTTP/SSE)
- `headers` — Request headers (for authentication)
- `transport` — Transport type (usually auto-detected)

#### Configuration Validation Rules

- **stdio transport**: `command` field is required and cannot be empty
- **streamable_http / sse transport**: `url` field is required and cannot be empty
- Invalid configurations will return an error when creating the client

---

## Built-in Tools

CoPaw provides a set of ready-to-use built-in tools that agents can directly call to perform various tasks.

---

### Tool Management

<!-- TODO: Add screenshot - Show tool management page with grid layout of tool cards, displaying tool names, status indicators, descriptions, and enable/disable switches -->

#### Enable and Disable Tools

1. Open the Console and go to **Agent → Tools**
2. View all built-in tools and their status (each tool displays as a card)
3. Use the toggle switch in the bottom-right corner of each card to individually enable or disable tools
4. Use the **Enable All** or **Disable All** buttons at the top for batch operations

**Impact of enabling tools:**

- **Enabled**: Tool is loaded into agent context and can be called in conversations
- **Disabled**: Tool is not available in agent's tool list and cannot be called

> For optimal performance, enable only the tools you need to reduce context overhead. Configuration changes are hot-reloaded automatically—no server restart needed.

> **Multi-Agent Support**: Each agent has independent tool configuration. After switching agents in the agent selector at the top of the Console, you'll see that agent's dedicated tool configuration. See [Multi-Agent](./multi-agent) for details.

#### Async Execution

The `execute_shell_command` tool supports async execution mode:

- **Sync execution (default)**: Agent waits for command to complete
  - Suitable for: Quick commands (ls, cat), commands requiring immediate output
- **Async execution**: Command runs in background, agent continues immediately
  - Suitable for: Long-running commands (compilation, tests, downloads), tasks that shouldn't block conversation flow

**Background Task Management:**
When async execution is enabled, the agent automatically gains the following tools:

- `list_background_tasks` - View all running tasks and their status
- `get_task_output` - Retrieve task output (stdout and stderr)
- `cancel_task` - Cancel a running task

Configure this option on the `execute_shell_command` tool card (only this tool supports async execution).

---

### Built-in Tool List

| Type               | Tool Name               | Description                                                                   |
| ------------------ | ----------------------- | ----------------------------------------------------------------------------- |
| File Operations    | `read_file`             | Read file contents, supports line range reading                               |
| File Operations    | `write_file`            | Create or overwrite file                                                      |
| File Operations    | `edit_file`             | Modify file using find-and-replace (replaces all occurrences)                 |
| File Operations    | `append_file`           | Append content to file end                                                    |
| File Search        | `grep_search`           | Search by content, supports regex and context                                 |
| File Search        | `glob_search`           | Find files by name pattern                                                    |
| Command Execution  | `execute_shell_command` | Execute shell commands, supports async execution                              |
| Browser Automation | `browser_use`           | Browser automation with 30+ operations (navigation, interaction, screenshots) |
| Screenshots        | `desktop_screenshot`    | Capture desktop or window screenshot                                          |
| Image Analysis     | `view_image`            | Load image into context for model analysis                                    |
| File Transfer      | `send_file_to_user`     | Send file to user, auto-detects file type                                     |
| Memory Search      | `memory_search`         | Semantic search in MEMORY.md for past information                             |
| Time               | `get_current_time`      | Get current time and timezone                                                 |
| Time               | `set_user_timezone`     | Set user timezone preference                                                  |
| Statistics         | `get_token_usage`       | Query LLM token usage statistics                                              |

### Tool Details

**File Operations**

- `read_file`: Read file contents
  - Specify `start_line` and `end_line` to read specific line ranges
  - Large files are automatically truncated (default 50KB), with instructions to use `start_line` to continue
  - Truncation shows total line count and next starting line number
- `edit_file`: Full-file find-and-replace for all occurrences, suitable for precise modifications
- `append_file`: Append content to file end
  - Doesn't overwrite existing content
  - Suitable for: appending logs, accumulating data, adding records
  - Auto-creates file if it doesn't exist

**File Search**

- `grep_search`: Search by content
  - `pattern`: Search string or regex pattern
  - `path`: Search path (file or directory), defaults to working directory
  - `is_regex`: Treat pattern as regex (default False)
  - `case_sensitive`: Case-sensitive matching (default True)
  - `context_lines`: Context lines before/after match (default 0, max 5)
  - `include_pattern`: Filter by filename, e.g. "\*.py"
- `glob_search`: Supports recursive patterns like `**/*.json`

**Command Execution**

- `execute_shell_command`: Execute shell commands
  - Cross-platform support (Windows uses cmd.exe, Linux/macOS use bash)
  - `command`: Command to execute
  - `timeout`: Timeout in seconds (default 60)
  - `cwd`: Working directory (optional, defaults to workspace directory)
  - Supports async execution mode

**Browser Automation**

- `browser_use`: Supports 30+ operations
  - **Basic Navigation**: start, stop, open, navigate, navigate_back, close
  - **Page Interaction**: click, type, hover, drag, select_option
  - **Page Analysis**: snapshot, screenshot, console_messages, network_requests
  - **Form Operations**: fill_form, file_upload, press_key
  - **JavaScript Execution**: eval, evaluate, run_code
  - **Advanced Features**: cookies_get, cookies_set, cookies_clear, tabs, wait_for, pdf, resize, handle_dialog, install, connect_cdp, list_cdp_targets, clear_browser_cache
- Use `action` parameter to specify operation type
- Runs in headless mode by default; use `headed=True` to launch a visible browser window
- Supports multiple tabs (use different `page_id` values)

**CDP Mode (Advanced Feature):**
The browser tool supports connecting to a running Chrome browser via Chrome DevTools Protocol (CDP):

- **Start with CDP port exposed**: Use `action="start"` with `cdp_port` (e.g., 9222) to launch Chrome with `--remote-debugging-port`
- **Connect to external browser**: Use `action="connect_cdp"` with `cdp_url` (e.g., `http://localhost:9222`) to connect to an already-running Chrome
- **Discover CDP endpoints**: Use `action="list_cdp_targets"` to scan local port range (default 9000-10000) and find available CDP connections

**CDP Mode Use Cases:**

- Connect to a user's manually opened Chrome (preserving login state, bookmarks, extensions, etc.)
- Integrate with external debugging tools
- Perform automation in an existing browser session

**Screenshots and Images**

- `desktop_screenshot`: Capture desktop or window screenshot
  - `path`: Save path (optional, defaults to workspace directory)
  - `capture_window`: macOS only, when True allows clicking to select a window
- `view_image`: After loading image, model can perform visual analysis
  - **Note**: This tool's output is not displayed in the user interface; it only loads the image into the model's context

**Memory Search**

- `memory_search`: Semantic search in memory files to find relevant past conversations and decisions
  - **Prerequisites**:
    - Enable "Memory Management" in **Agent → Runtime Config**
    - If not configured, tool calls will return an error message
  - `query`: Semantic search query
  - `max_results`: Max number of results (default 5)
  - `min_score`: Minimum similarity threshold (default 0.1)
  - Search scope: MEMORY.md and memory/\*.md files in the current agent's workspace root directory

**Time Tools**

- `get_current_time`: Get current time in format `YYYY-MM-DD HH:MM:SS Timezone (Day)`
- `set_user_timezone`: Set user timezone preference
  - `timezone_name`: IANA timezone name, e.g. "Asia/Shanghai", "America/New_York", "UTC"

**Statistics Tools**

- `get_token_usage`: Query LLM token usage statistics
  - `days`: Query past N days (default 30)
  - `model_name`: Filter by model name (optional)
  - `provider_id`: Filter by provider (optional)
