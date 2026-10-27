---
summary: Execute shell commands, supports async execution
---

Execute shell commands.

- Cross-platform support (Windows uses cmd.exe, Linux/macOS use bash)
- `command`: Command to execute
- `timeout`: Timeout in seconds (default 60)
- `cwd`: Working directory (optional, defaults to workspace directory)
- Supports async execution mode (see below)

### Async Execution

- **Sync execution (default)**: Agent waits for command to complete
  - Suitable for: Quick commands (ls, cat), commands requiring immediate output
- **Async execution**: Command runs in background, agent continues immediately
  - Suitable for: Long-running commands (compilation, tests, downloads), tasks that shouldn't block conversation flow

When async execution is enabled, the agent automatically gains the following tools:

- `list_background_tasks` - View all running tasks and their status
- `get_task_output` - Retrieve task output (stdout and stderr)
- `cancel_task` - Cancel a running task

Configure this option on the tool card (only this tool supports async execution).
