# Tool

> Source: https://docs.agentscope.io/v2/building-blocks/tool.md
> Library: agentscope 1.0.20 (docs at docs.agentscope.io/v2)

## Overview

Tools define, register, and manage the capabilities an agent can call (running shell commands, reading files, calling APIs). Each tool exposes itself to the LLM as a JSON Schema, and the agent invokes it through a unified streaming interface.

AgentScope organizes tool-related building blocks under three concepts:

- **Tool** — any class that satisfies the `ToolBase` interface, including the built-ins shipped with AgentScope and the `FunctionTool` / `MCPTool` adapters that wrap plain functions or MCP-server tools.
- **Toolkit** — the container that registers tools, MCP clients, and skills, exposes their JSON schemas to the model, and dispatches each tool call to the right tool object.
- **Tool Group** — a named bundle of tools, MCP clients, and skills that can be activated or deactivated as a unit. The agent toggles groups at runtime via the built-in meta tool (`reset_tools`) to keep its context focused.

Minimal example:

```python
from agentscope.tool import Toolkit, Bash, Read, Write, Edit

toolkit = Toolkit(
    tools=[Bash(), Read(), Write(), Edit()],
)
```

A `Toolkit` created with `tools` alone exposes those tools in the special `"basic"` group, which is always active. Adding `mcps`, `skills_or_loaders`, or extra `tool_groups` extends what the agent can reach.

## API Reference

### ToolBase

Abstract base class every tool satisfies. AgentScope ships built-in tools for common operations and exposes the same interface for developers to build custom tools.

Import: `from agentscope.tool import ToolBase, ToolChunk`

**Attributes** (describe the tool to the agent and the runtime):

| Attribute | Type | Description |
| --- | --- | --- |
| `name` | `str` | The tool name presented to the agent |
| `description` | `str` | Agent-oriented description of what the tool does |
| `input_schema` | `dict` | JSON Schema defining the tool's parameters |
| `is_concurrency_safe` | `bool` | Whether the tool is safe to call in parallel |
| `is_read_only` | `bool` | Whether the tool only reads data without side effects |
| `is_external_tool` | `bool` | If `True`, execution is delegated externally (see External Execution Tool) |
| `is_state_injected` | `bool` | If `True`, the agent state is injected via the `_agent_state` argument |
| `is_mcp` | `bool` | Whether the tool comes from an MCP server |
| `mcp_name` | `str \| None` | The MCP server name when `is_mcp` is `True` |

**Methods** (hook into execution and the permission system):

| Method | Required | Returns | Description |
| --- | --- | --- | --- |
| `check_permissions(tool_input, context)` | Yes | `PermissionDecision` | Runtime permission check before execution |
| `check_read_only(tool_input)` | Optional | `bool` | Per-invocation read-only check. Defaults to `self.is_read_only`. Override when read-only-ness depends on the input (e.g. `Bash` — `ls` is read-only, `rm` is not). Used by the permission engine to decide auto-allow in EXPLORE / ACCEPT_EDITS. |
| `match_rule(rule_content, tool_input)` | Optional | `bool` | Custom rule-matching logic for the permission system |
| `generate_suggestions(tool_input)` | Optional | `list[PermissionRule]` | Generate suggested permission rules from a tool call |
| `__call__(**kwargs)` | Optional | `ToolChunk` or `AsyncGenerator[ToolChunk, None]` | The tool's execution logic. Not required for external execution tools. |

`check_permissions` and `__call__` are typically `async`.

### Toolkit

Container that registers tools, MCP clients, and skills, exposes their JSON schemas to the model, and dispatches each tool call to the right tool object.

Import: `from agentscope.tool import Toolkit`

**Constructor arguments:**

| Argument | Type | Description |
| --- | --- | --- |
| `tools` | `list[ToolBase]` | Tools placed in the always-active `"basic"` group |
| `mcps` | `list[MCPClient]` | MCP clients whose tools are exposed (basic group) |
| `skills_or_loaders` | `list[str \| Skill \| SkillLoaderBase]` | Skill sources: directory path strings, `Skill` objects, or `SkillLoaderBase` subclasses |
| `tool_groups` | `list[ToolGroup]` | Extra named, togglable tool groups |

Behavior:
- A toolkit created with `tools` alone exposes those tools in the special `"basic"` group, which is always active.
- The `"basic"` group is created automatically from the constructor's top-level `tools`, `mcps`, and `skills_or_loaders` arguments and is always active.
- When at least one non-basic tool group exists, `Toolkit` auto-registers the `reset_tools` meta tool.
- When skills are registered, `Toolkit` auto-registers the built-in `Skill` viewer tool.

### Built-in Tools

Instantiate and pass into `Toolkit(tools=[...])`. Import from `agentscope.tool`.

| Tool | Description | Read-only |
| --- | --- | --- |
| `Bash` | Execute shell commands | No |
| `Read` | Read file contents with line numbers | Yes |
| `Write` | Create or overwrite files | No |
| `Edit` | Perform exact string replacements in files | No |
| `Glob` | Find files by glob pattern | Yes |
| `Grep` | Search file contents using ripgrep | Yes |
| `TaskCreate` | Create a structured task for progress tracking | No |
| `TaskGet` | Retrieve task details by ID | Yes |
| `TaskList` | List all tasks and their status | Yes |
| `TaskUpdate` | Update task status or metadata | No |

Two more tools — the `reset_tools` meta tool and the `Skill` viewer — are auto-registered by `Toolkit` whenever extra tool groups or skills exist. Developers do NOT instantiate them directly.

### Bash

Executes shell commands and returns stdout/stderr. Implements every optional interface method to provide fine-grained permission control.

**Constructor:**

```python
from agentscope.tool import Bash

bash = Bash(
    additional_dangerous_files=[".secrets"],
    additional_dangerous_directories=[".credentials"],
)
```

| Argument | Type | Description |
| --- | --- | --- |
| `additional_dangerous_files` | `list[str]` | Extra entries appended to the dangerous-files list |
| `additional_dangerous_directories` | `list[str]` | Extra entries appended to the dangerous-directories list |

`check_permissions()` runs a layered safety analysis on the command string:

1. **Injection risk detection** — flags dynamic shell structures (`$(...)`, backticks, process substitution) that cannot be statically analyzed → ASK
2. **Read-only command detection** — auto-allows safe commands (`git status`, `ls`, `cat`, `grep`, `docker ps`, etc.), including compound commands where every subcommand is read-only → ALLOW
3. **Dangerous command patterns** — detects destructive operations (e.g. `chmod 777`, `mkfs`) → ASK
4. **Sed constraint check** — blocks in-place `sed -i` against dangerous files → ASK
5. **Dangerous path protection** — checks if the command operates on sensitive config files (`.bashrc`, `.ssh/`, `.env`) → ASK
6. **Dangerous removal detection** — catches `rm` / `rmdir` targeting critical system paths (`/`, `~`, `/usr`) → ASK
7. **ACCEPT_EDITS mode** — auto-allows filesystem commands (`mkdir`, `touch`, `rm`, `rmdir`, `mv`, `cp`, `sed`) **only when every target path resolves inside a configured working directory**. A command that touches any path outside the working set (e.g. `cp /etc/hosts /tmp/x`) falls through to PASSTHROUGH instead of auto-allowing.

`check_read_only()` returns `True` for any command identified by the read-only detector (step 2), `False` otherwise.

`match_rule()` uses prefix-based wildcard matching against the command string:

| Pattern | Matches | Does not match |
| --- | --- | --- |
| `npm run:*` | `npm run build`, `npm run test` | `npm install` |
| `git commit:*` | `git commit -m "fix"` | `git push` |
| `rm:*` | `rm file.txt`, `rm -rf /tmp/x` | `ls` |

`generate_suggestions()` extracts the command prefix (first two tokens) and proposes a prefix rule. For example, `git commit -m "fix bug"` produces the suggestion `git commit:*`.

### Read, Write, Edit (File Tools)

Enforce a read-before-write rule: `Write` and `Edit` require the target file to have been read via `Read` first. This prevents blind overwrites and ensures the agent always operates on current content.

| Tool | Operation | Key behavior |
| --- | --- | --- |
| `Read` | Read file contents | Returns content with line numbers; supports offset/limit for large files; results cached in agent state |
| `Write` | Create or overwrite a file | Fails if the file exists but has not been read first |
| `Edit` | Replace exact strings in a file | Fails if `old_string` is not found or is not unique (unless `replace_all=True`); requires prior read |

`check_permissions()` — `Write` and `Edit` share the same permission logic:

1. **Dangerous path protection** — operations on sensitive files (`.bashrc`, `.env`, `.ssh/`) return a bypass-immune ASK (`bypass_immune=True`), so allow rules cannot silently authorize them. The ASK is still skipped in `BYPASS` mode and converted to DENY in `DONT_ASK` mode.
2. **ACCEPT_EDITS mode** — auto-allows operations on files within configured working directories
3. **PASSTHROUGH** — falls through to the permission engine for rule matching

`Read` is read-only and always returns PASSTHROUGH (the engine handles EXPLORE-mode and ACCEPT_EDITS-mode auto-allow via `check_read_only`).

`match_rule()` — all three tools use `fnmatch` glob matching against the `file_path` argument:

| Pattern | Matches |
| --- | --- |
| `src/**` | Any file under `src/` |
| `src/**/*.py` | Python files under `src/` |
| `config.json` | Exact file match |

`generate_suggestions()` proposes a glob covering the parent directory. For example, editing `/project/src/main.py` produces the suggestion `src/**`.

### FunctionTool

Adapter that wraps a plain Python function as a tool. Auto-extracts the tool name from `func.__name__`, the description from the function docstring, and the input schema from type hints.

Import: `from agentscope.tool import FunctionTool`

```python
from agentscope.tool import FunctionTool, Toolkit

def get_weather(city: str, unit: str = "celsius") -> str:
    """Get the current weather for a city.

    Args:
        city: The city name to look up.
        unit: Temperature unit, either "celsius" or "fahrenheit".
    """
    return f"The weather in {city} is 22°{unit[0].upper()}"

toolkit = Toolkit(tools=[FunctionTool(get_weather)])
```

**Constructor arguments / overrides:**

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `func` | `Callable` | (required) | The Python function to wrap |
| `name` | `str \| None` | `func.__name__` | Override the tool name |
| `description` | `str \| None` | the docstring | Override the description |
| `is_concurrency_safe` | `bool` | `True` | Whether parallel calls are safe |
| `is_read_only` | `bool` | `False` | Whether the function has side effects |
| `is_state_injected` | `bool` | `False` | Whether the agent state is injected as `_agent_state` |

IMPORTANT: Wrapped functions default to `ASK` permission behavior — the user must explicitly allow each call. Subclass `ToolBase` directly when you need custom permission logic.

### MCPTool

Adapter that wraps a tool exposed by an MCP server. Obtained from `await client.list_tools()` and usable like any other `ToolBase` instance. MCP tools are namespaced as `mcp__{server_name}__{tool_name}`.

### MCPClient

Connects AgentScope to an MCP server. Pass instances to `Toolkit(mcps=[...])`.

Import: `from agentscope.mcp import MCPClient, StdioMCPConfig, HttpMCPConfig`

**Constructor arguments:**

| Argument | Type | Description |
| --- | --- | --- |
| `name` | `str` | Server name, used in the `mcp__{name}__{tool}` namespace |
| `is_stateful` | `bool` | `True` = persistent session with `connect()` / `close()` lifecycle; `False` = ephemeral session per tool call (HTTP only) |
| `mcp_config` | `StdioMCPConfig \| HttpMCPConfig` | Transport configuration |
| `enable_tools` | `list[str]` | Allowlist: expose only these tools from the server |
| `disable_tools` | `list[str]` | Blocklist: hide these tools from the server |

**Methods:**

| Method | Description |
| --- | --- |
| `await client.connect()` | Open a stateful session. Must be called before constructing the `Toolkit` for stateful clients. |
| `await client.close()` | Close a stateful session |
| `await client.list_tools()` | Returns a list of `MCPTool` adapters for invoking MCP tools outside a `Toolkit` |

Connection modes:
- **Stateful** (STDIO or HTTP) — persistent session with explicit `connect()` / `close()` lifecycle.
- **Stateless** (HTTP only) — ephemeral session created per tool call, no lifecycle management needed.

Tools annotated with `readOnlyHint` are recognized as read-only by the permission system (auto-allowed in EXPLORE and ACCEPT_EDITS modes; in DEFAULT they still ASK unless an allow rule matches).

**StdioMCPConfig:**

| Argument | Type | Description |
| --- | --- | --- |
| `command` | `str` | Executable to launch the MCP server |
| `args` | `list[str]` | Command-line arguments |

**HttpMCPConfig:**

| Argument | Type | Description |
| --- | --- | --- |
| `url` | `str` | MCP server URL |
| `headers` | `dict` | Optional HTTP headers (e.g. `{"Authorization": "Bearer xxx"}`) |

### Skill (viewer tool) and Skill registration

Skills are markdown-based instruction sets (a directory containing a `SKILL.md` with frontmatter metadata and detailed instructions). They are NOT callable directly. The auto-registered `Skill` viewer tool reads a skill's instructions; the agent then follows them using its existing tools.

Register via `Toolkit(skills_or_loaders=[...])`. Each entry can be a directory path string, a `Skill` object, or a `SkillLoaderBase` subclass.

**LocalSkillLoader** — `from agentscope.skill import LocalSkillLoader`

| Argument | Type | Description |
| --- | --- | --- |
| `directory` | `str` | Directory containing skill subdirectories |
| `scan_subdir` | `bool` | Whether to scan subdirectories for skills |

How it works — at initialization the toolkit scans every registered skill source, collects each skill's name/description/directory, auto-registers the `Skill` viewer, and composes a system-prompt fragment listing available skills (name + description) instructing the agent to invoke the viewer. At runtime the agent picks a skill by name, calls the `Skill` viewer, which reads the corresponding `SKILL.md` and returns its full markdown; the agent then follows those instructions using its already-equipped tools.

### ToolGroup

A named bundle of tools, MCP clients, and skills that can be activated/deactivated as a unit. Pass to `Toolkit(tool_groups=[...])`.

Import: `from agentscope.tool import ToolGroup`

**Constructor arguments:**

| Argument | Type | Description |
| --- | --- | --- |
| `name` | `str` | Group name (becomes a boolean field on the `reset_tools` schema) |
| `description` | `str` | Shown to the agent in the meta tool schema |
| `instructions` | `str` (optional) | Returned when the group is activated; tells the agent how to use the group |
| `tools` | `list[ToolBase]` | Tools in the group |
| `mcps` | `list[MCPClient]` | MCP clients in the group |
| `skills_or_loaders` | `list` | Skill sources in the group |

The reserved `"basic"` group is created automatically from the constructor's top-level `tools`, `mcps`, and `skills_or_loaders` and is always active.

### reset_tools (meta tool)

Built-in meta tool that lets the agent self-manage which tool groups are active at runtime. Auto-registered by `Toolkit` when at least one non-basic tool group exists. Each non-basic group becomes a boolean field on its schema; the agent calls the meta tool with the desired final state.

Runtime behavior:
- Tools in the `"basic"` group are always exposed; never affected by the meta tool.
- Each call to `reset_tools` overwrites the activated set — any non-basic group not explicitly set to `True` becomes inactive, regardless of its previous state.
- For each group transitioning to active, its `instructions` (when provided) are concatenated and returned in the meta tool's response.
- Tools from inactive groups are hidden from the agent's tool schema, freeing context space.

WARNING: The meta tool input represents the **final state** of all groups, not incremental changes.

### ToolChunk

Return type of a tool's `__call__`. Carries content blocks (e.g. `TextBlock`). Tools return a single `ToolChunk` or stream them via `AsyncGenerator[ToolChunk, None]`.

Example: `return ToolChunk(content=[TextBlock(text=results)])`
(`TextBlock` imported from `agentscope.message`.)

## Configuration

| Option | Where | Controls |
| --- | --- | --- |
| `tools` | `Toolkit` / `ToolGroup` | Tools placed in a group (top-level = `"basic"`) |
| `mcps` | `Toolkit` / `ToolGroup` | MCP clients exposed |
| `skills_or_loaders` | `Toolkit` / `ToolGroup` | Skill sources (path string / `Skill` / `SkillLoaderBase`) |
| `tool_groups` | `Toolkit` | Extra named togglable groups |
| `additional_dangerous_files` | `Bash` | Extra sensitive files flagged in safety analysis |
| `additional_dangerous_directories` | `Bash` | Extra sensitive directories flagged |
| `name` | `MCPClient` | Server name for `mcp__{name}__{tool}` namespacing |
| `is_stateful` | `MCPClient` | Stateful (connect/close) vs stateless (per-call) |
| `mcp_config` | `MCPClient` | `StdioMCPConfig` or `HttpMCPConfig` |
| `enable_tools` | `MCPClient` | Allowlist subset of server tools |
| `disable_tools` | `MCPClient` | Blocklist subset of server tools |
| `command` / `args` | `StdioMCPConfig` | STDIO server launch |
| `url` / `headers` | `HttpMCPConfig` | HTTP server connection |
| `directory` / `scan_subdir` | `LocalSkillLoader` | Skill directory + recursive scan |
| `name` / `description` / `instructions` | `ToolGroup` | Group identity and activation guidance |
| Tool attributes | custom `ToolBase` | `name`, `description`, `input_schema`, `is_concurrency_safe`, `is_read_only`, `is_external_tool`, `is_state_injected`, `is_mcp`, `mcp_name` |
| `name` / `description` / `is_concurrency_safe` / `is_read_only` / `is_state_injected` | `FunctionTool` | Override auto-extracted values |
| `bypass_immune` | `PermissionDecision` | Mark an ASK that allow rules cannot silence |

## Usage Patterns

### Built-in tools in the basic group

```python
from agentscope.tool import Toolkit, Bash, Read, Write, Edit

toolkit = Toolkit(
    tools=[Bash(), Read(), Write(), Edit()],
)
```

### Bash with extra dangerous-path entries

```python
from agentscope.tool import Bash

bash = Bash(
    additional_dangerous_files=[".secrets"],
    additional_dangerous_directories=[".credentials"],
)
```

### Custom tool by subclassing ToolBase

```python
from agentscope.tool import ToolBase, ToolChunk
from agentscope.permission import (
    PermissionContext, PermissionDecision, PermissionBehavior,
)
from agentscope.message import TextBlock

class WebSearch(ToolBase):
    name = "WebSearch"
    description = "Search the web for information on a given query."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
        },
        "required": ["query"],
    }
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(
        self, tool_input: dict, context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Web search is read-only.",
        )

    async def __call__(self, query: str) -> ToolChunk:
        results = await do_search(query)
        return ToolChunk(content=[TextBlock(text=results)])
```

### Wrap a function as a tool

```python
from agentscope.tool import FunctionTool, Toolkit

def get_weather(city: str, unit: str = "celsius") -> str:
    """Get the current weather for a city.

    Args:
        city: The city name to look up.
        unit: Temperature unit, either "celsius" or "fahrenheit".
    """
    return f"The weather in {city} is 22°{unit[0].upper()}"

toolkit = Toolkit(tools=[FunctionTool(get_weather)])
```

### External execution tool (human-in-the-loop)

Set `is_external_tool = True` and do NOT implement `__call__`. When called, the agent emits a `RequireExternalExecutionEvent` and pauses until the result arrives via `ExternalExecutionResultEvent`.

```python
from agentscope.tool import ToolBase
from agentscope.permission import (
    PermissionContext, PermissionDecision, PermissionBehavior,
)

class HumanApproval(ToolBase):
    name = "HumanApproval"
    description = "Request human approval for a sensitive operation."
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "The action requiring approval."},
            "reason": {"type": "string", "description": "Why this action needs approval."},
        },
        "required": ["action", "reason"],
    }
    is_concurrency_safe = True
    is_read_only = False
    is_external_tool = True

    async def check_permissions(
        self, tool_input: dict, context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="External tool dispatch is always allowed.",
        )
```

### Register MCP tools — stateful STDIO

```python
from agentscope.mcp import MCPClient, StdioMCPConfig
from agentscope.tool import Toolkit

client = MCPClient(
    name="filesystem",
    is_stateful=True,
    mcp_config=StdioMCPConfig(
        command="mcp-server-filesystem",
        args=["--root", "/my/project"],
    ),
)

await client.connect()

toolkit = Toolkit(mcps=[client])
```

### Register MCP tools — stateful HTTP

```python
from agentscope.mcp import MCPClient, HttpMCPConfig
from agentscope.tool import Toolkit

client = MCPClient(
    name="weather",
    is_stateful=True,
    mcp_config=HttpMCPConfig(
        url="https://api.weather.com/mcp",
        headers={"Authorization": "Bearer xxx"},
    ),
)

await client.connect()

toolkit = Toolkit(mcps=[client])
```

### Register MCP tools — stateless HTTP

```python
from agentscope.mcp import MCPClient, HttpMCPConfig
from agentscope.tool import Toolkit

client = MCPClient(
    name="search",
    is_stateful=False,
    mcp_config=HttpMCPConfig(url="https://api.search.com/mcp"),
)

toolkit = Toolkit(mcps=[client])
```

### MCP subset selection

```python
client = MCPClient(
    name="search",
    is_stateful=False,
    mcp_config=HttpMCPConfig(url="https://api.search.com/mcp"),
    enable_tools=["web_search", "image_search"],
)
```

### Register skills

```python
from agentscope.tool import Toolkit

toolkit = Toolkit(
    skills_or_loaders=["/path/to/skills"],
)
```

```python
from agentscope.tool import Toolkit
from agentscope.skill import LocalSkillLoader

loader = LocalSkillLoader(
    directory="/path/to/skills",
    scan_subdir=True,
)

toolkit = Toolkit(skills_or_loaders=[loader])
```

### Tool groups + meta tool

```python
from agentscope.tool import Toolkit, ToolGroup, Bash, Read, Write, Edit

toolkit = Toolkit(
    tools=[Bash(), Read(), Write(), Edit()],
    tool_groups=[
        ToolGroup(
            name="database",
            description="Tools for database operations.",
            instructions="Always wrap mutations in a transaction.",
            tools=[db_query_tool, db_migrate_tool],
        ),
        ToolGroup(
            name="deployment",
            description="Tools for deploying services.",
            instructions="Confirm the target environment before deploying.",
            tools=[deploy_tool, rollback_tool],
        ),
    ],
)
```

## Gotchas & Version Notes

- **`FunctionTool` defaults to `ASK` permission behavior** — every call requires explicit user allow. If you need custom permission logic, subclass `ToolBase` directly instead of wrapping a function.
- **Read-before-write is enforced**: `Write` fails if the file exists but was not read first; `Edit` requires a prior `Read`. `Edit` also fails if `old_string` is not found or is not unique, unless `replace_all=True`.
- **The `reset_tools` meta tool represents the FINAL state**, not incremental changes. Any non-basic group not explicitly set to `True` is deactivated regardless of its previous state. The `"basic"` group is never affected.
- **`reset_tools` and the `Skill` viewer are auto-registered** — do NOT instantiate them directly. `reset_tools` appears only when a non-basic tool group exists; the `Skill` viewer appears only when skills are registered.
- **Skills are NOT callable tools.** The agent must use the `Skill` viewer to read `SKILL.md`, then act with its existing tools. Do not attempt to invoke a skill directly.
- **Stateful MCP clients must be `connect()`-ed BEFORE the `Toolkit` is constructed.** Stateless clients (HTTP only) need no lifecycle management.
- **MCP tool names are namespaced** as `mcp__{server_name}__{tool_name}` to avoid collisions. Use `enable_tools` / `disable_tools` to scope which server tools are exposed.
- **MCP `readOnlyHint`-annotated tools** are auto-allowed in EXPLORE and ACCEPT_EDITS modes; in DEFAULT mode they still ASK unless an allow rule matches.
- **Bash injection-risk structures** (`$(...)`, backticks, process substitution) always trigger ASK because they cannot be statically analyzed.
- **Bash ACCEPT_EDITS auto-allow is path-scoped**: filesystem commands are auto-allowed only when every target path resolves inside a configured working directory. A path outside the working set (e.g. `cp /etc/hosts /tmp/x`) falls through to PASSTHROUGH.
- **`bypass_immune=True` ASK** (set on `Write`/`Edit` for sensitive files like `.bashrc`/`.env`/`.ssh/`, or in custom tools) cannot be silenced by allow rules. It IS skipped in `BYPASS` mode and converted to DENY in `DONT_ASK` mode. See the permission-system safety-check contract.
- **Override `check_read_only(tool_input)`** when read-only-ness depends on the input (like `Bash`). It defaults to returning the static `is_read_only` attribute and is consulted before EXPLORE / ACCEPT_EDITS auto-allow decisions.
- **External execution tools** (`is_external_tool = True`) must NOT implement `__call__`; execution is delegated externally and the agent pauses on `RequireExternalExecutionEvent` until `ExternalExecutionResultEvent` is delivered.
