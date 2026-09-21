---
summary: Delegate work to an external ACP agent runner
---

Use ACP (Agent Client Protocol) to open a session with an external agent runner and delegate work to it.

### How to use

- Before using this feature, prepare the external agent runners you want to connect, such as `claude_code`, `codex`, `qwen_code`, or `opencode`
- Make sure each runner is already logged in or configured with the required API key, and can be launched successfully from your terminal
- Enable the `delegate_external_agent` tool on the **Agent → Tools** page
- Then describe your intent directly in chat
- QwenPaw will call this tool when appropriate, establish a continuous conversation with the external agent, and stream progress and results back into the current chat
- Each runner currently supports only one active session per chat; to start a new conversation, close the current session first

### Parameters and behavior

- Suitable for delegating code analysis, file editing, command execution, and similar tasks to an external coding agent
- Default supported runners: `qwen_code`, `claude_code`, `codex`, `opencode`
- Disabled by default and must be enabled explicitly in **Agent → Tools**
- `action`: supports `start`, `message`, `respond`, and `close`
  - `start`: starts a new external agent session; when `message` is empty, a default `hi` is sent
  - `message`: sends a follow-up message to the external agent session bound to the current chat
  - `respond`: responds to a permission request raised by the external agent; `message` must contain the exact option id from the pending permission request
  - `close`: closes the external agent session bound to the current chat
- `runner`: runner name such as `qwen_code`, `claude_code`, `codex`, or `opencode`
- `message`: message sent to the external agent; in `respond` mode this carries the selected permission option id
- `cwd`: working directory used by the external agent; defaults to the current workspace
- The tool streams intermediate progress back, including text output, tool call updates, permission requests, and final results

### Permissions and Safety

- When an external agent requests permission, the current session is suspended until an explicit response is provided
- Permission responses are strictly matched: you must choose one of the options from the current request and pass its exact id
- Some dangerous command patterns are hard-blocked
- File path access is restricted to the configured workspace where possible
