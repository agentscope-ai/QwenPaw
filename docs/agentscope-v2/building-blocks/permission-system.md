# Permission System

> Source: https://docs.agentscope.io/v2/building-blocks/permission-system.md
>
> Note: The upstream docs page is served as clean markdown, but the fetch layer
> refused verbatim reproduction of the full copyrighted text. The content below
> was reconstructed from exhaustive structured extraction of the page (enums,
> class signatures, parameter tables, pattern syntax, dangerous-path lists,
> decision pipeline, and code examples). Signatures and parameter defaults are
> reproduced as documented. Where a method's exact signature was described
> only implicitly on the page, that is flagged inline.

## Overview

AgentScope v2's permission system provides fine-grained control over agent tool
execution. Every tool call is intercepted and resolved to one of the
`PermissionBehavior` outcomes: **ALLOW**, **DENY**, **ASK** (user confirmation),
or **PASSTHROUGH** (defer to rules/mode).

The decision is produced by combining three elements:

1. **Rules** — explicit allow / deny / ask patterns per tool, sourced from static
   configuration (`userSettings`, `projectSettings`) or user-accepted suggestions
   during runtime (`session`).
2. **Mode** — a global default policy: `DEFAULT`, `EXPLORE`, `ACCEPT_EDITS`,
   `BYPASS`, `DONT_ASK`.
3. **Built-in / per-tool checks** — dynamic analysis: read-only detection,
   dangerous-path protection, and any custom `check_permissions()` logic a tool
   implements.

Safety prompts can be marked `bypass_immune=True` so that allow rules cannot
silence them — except in `BYPASS` mode, which is an explicit opt-out of safety
checks.

## API Reference

### PermissionMode (enum)

Global default permission policy.

| Member | Meaning |
|--------|---------|
| `DEFAULT` | All operations require an explicit rule or user confirmation (read-only commands still auto-allowed). |
| `EXPLORE` | Read-only access only; modifications are denied. Does not call `check_permissions()` — the read-only verdict is final. |
| `ACCEPT_EDITS` | Auto-allows file operations inside working directories. |
| `BYPASS` | Skips permission checks except deny/ask rules; ignores `bypass_immune` safety ASKs. |
| `DONT_ASK` | Converts all ASKs (default, ask rules, and safety ASKs) to DENY — safe for unattended/non-interactive runs. |

### PermissionBehavior (enum)

Outcome of a permission evaluation.

| Member | Meaning |
|--------|---------|
| `ALLOW` | Permit the tool call. |
| `DENY` | Block the tool call. |
| `ASK` | Prompt the user for confirmation. |
| `PASSTHROUGH` | Tool defers the decision; engine continues with rules/mode (see PASSTHROUGH note below). |

### PermissionContext

Holds the active permission configuration carried on `AgentState`.

```python
PermissionContext(
    mode: PermissionMode = PermissionMode.DEFAULT,
    allow_rules: dict[str, list[PermissionRule]] = None,
    deny_rules: dict[str, list[PermissionRule]] = None,
    ask_rules: dict[str, list[PermissionRule]] = None,
    working_directories: dict[str, AdditionalWorkingDirectory] = None,
)
```

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `mode` | `PermissionMode` | `PermissionMode.DEFAULT` | Global default policy. |
| `allow_rules` | `dict[str, list[PermissionRule]]` | `None` | Pre-configured allow patterns keyed by tool name. |
| `deny_rules` | `dict[str, list[PermissionRule]]` | `None` | Pre-configured deny patterns keyed by tool name. |
| `ask_rules` | `dict[str, list[PermissionRule]]` | `None` | Pre-configured ask-user patterns keyed by tool name. |
| `working_directories` | `dict[str, AdditionalWorkingDirectory]` | `None` | Safe directories used by `ACCEPT_EDITS` mode for auto-allow. |

### PermissionRule

A single allow/deny/ask pattern for one tool.

```python
PermissionRule(
    tool_name: str,
    rule_content: str | None,
    behavior: PermissionBehavior,
    source: str,
)
```

| Param | Type | Meaning |
|-------|------|---------|
| `tool_name` | `str` | Target tool: `"Bash"`, `"Read"`, `"Write"`, `"Edit"`, or a custom tool name. |
| `rule_content` | `str \| None` | Match pattern — wildcard prefix for Bash, glob for file tools, JSON for custom tools. |
| `behavior` | `PermissionBehavior` | `ALLOW`, `DENY`, or `ASK`. |
| `source` | `str` | Origin label: `"userSettings"`, `"projectSettings"`, `"session"`, etc. |

### PermissionDecision

Returned by `check_permissions()` (and used internally for final verdicts).

```python
PermissionDecision(
    behavior: PermissionBehavior,
    message: str = None,
    decision_reason: str = None,
    bypass_immune: bool = False,
)
```

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `behavior` | `PermissionBehavior` | — | Resulting action: `ALLOW`, `DENY`, `ASK`, or `PASSTHROUGH`. |
| `message` | `str` | `None` | User-facing explanation shown on ASK prompts. |
| `decision_reason` | `str` | `None` | Internal logging detail. |
| `bypass_immune` | `bool` | `False` | If `True`, this safety ASK survives allow rules in `DEFAULT`/`ACCEPT_EDITS`/`DONT_ASK`. Ignored under `BYPASS`. |

**Returns:** a permission-decision object consumed by the engine.

### AdditionalWorkingDirectory

A safe directory for `ACCEPT_EDITS` auto-allow.

```python
AdditionalWorkingDirectory(
    path: str,
    source: str,
)
```

| Param | Type | Meaning |
|-------|------|---------|
| `path` | `str` | Filesystem directory within which file operations may be auto-allowed. |
| `source` | `str` | Origin label (e.g. `"userSettings"`). |

### UserConfirmResultEvent

Event carrying the user's response to an ASK prompt, including any rule
suggestions the user accepted (to be persisted).

```python
UserConfirmResultEvent(
    confirmed: bool,
    rules: list[PermissionRule] = None,
)
```

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `confirmed` | `bool` | — | Whether the user approved the tool call. |
| `rules` | `list[PermissionRule]` | `None` | Accepted rule suggestions to persist to the engine. |

### ToolBase.check_permissions()

Per-tool dynamic permission check. Override on custom tools.

```python
async def check_permissions(
    self,
    tool_input: dict,
    context: PermissionContext,
) -> PermissionDecision
```

| Param | Type | Meaning |
|-------|------|---------|
| `tool_input` | `dict` | The actual call parameters. |
| `context` | `PermissionContext` | Current permission configuration. |

**Returns:** `PermissionDecision` (with behavior and optional safety message).
Return `PermissionBehavior.PASSTHROUGH` to defer to rules/mode.

### ToolBase.check_read_only()

Reports whether a specific invocation is read-only.

```python
async def check_read_only(self, tool_input: dict) -> bool
```

| Param | Type | Meaning |
|-------|------|---------|
| `tool_input` | `dict` | The actual call parameters. |

**Returns:** `bool` — `True` if the invocation does not modify state. Read-only
invocations are auto-allowed in every mode.

### ToolBase.match_rule()  (described implicitly)

Matches a `rule_content` pattern against `tool_input` using tool-specific syntax:
wildcard prefix for Bash, glob for file tools, JSON equality for custom tools.
The page does not give an explicit signature.

### ToolBase.generate_suggestions()  (described implicitly)

Auto-generates a suggested `PermissionRule` from the current tool call so the user
can accept it during an ASK prompt. The page does not give an explicit signature.

> No explicit manager/engine class or top-level evaluation function (e.g. a named
> `PermissionEngine.evaluate(...)`) is documented on this page.

## Configuration

| Key / Field | Where set | Controls |
|-------------|-----------|----------|
| `PermissionContext.mode` | `AgentState(permission_context=PermissionContext(mode=...))`; runtime via `agent.state.permission_context.mode = PermissionMode.EXPLORE` | Global default policy. |
| `allow_rules` | `PermissionContext(allow_rules={...})` | dict mapping tool name → list of allow `PermissionRule`. |
| `deny_rules` | `PermissionContext(deny_rules={...})` | dict mapping tool name → list of deny `PermissionRule`. |
| `ask_rules` | `PermissionContext(ask_rules={...})` | dict mapping tool name → list of ask `PermissionRule`. |
| `working_directories` | `PermissionContext(working_directories={...})` | dict of `AdditionalWorkingDirectory`; used only by `ACCEPT_EDITS`. |
| `PermissionRule.source` | per-rule | Origin label: `"userSettings"`, `"projectSettings"`, `"session"`. |
| `PermissionDecision.bypass_immune` | per-decision | Makes a safety ASK immune to allow rules (except under `BYPASS`). |
| Tool attribute `is_read_only` | on the tool class | Static read-only hint for the tool. |

### Pattern-matching syntax

**Bash rules** — command-prefix wildcard `COMMAND_PREFIX:*`:
- `"npm run:*"` matches `npm run build`, `npm run test`
- `"git commit:*"` matches `git commit -m "fix"`
- `"rm:*"` matches `rm file.txt`, `rm -rf /tmp/x`

**File tool rules (Read / Write / Edit)** — glob via `fnmatch`:
- `"src/**"` matches any file under `src/`
- `"src/**/*.py"` matches Python files under `src/`
- `"config.json"` exact file match

**Custom tools** — match via the tool's `match_rule()`; default behavior is exact
JSON-serialized parameter match.

### Import paths

```python
from agentscope.permission import (
    PermissionContext,
    PermissionMode,
    PermissionRule,
    PermissionBehavior,
    PermissionDecision,
    AdditionalWorkingDirectory,
)
from agentscope.tool import ToolBase
from agentscope.state import AgentState
from agentscope.agent import Agent
from agentscope.event import UserConfirmResultEvent
```

## Usage Patterns

### Initialize an agent with allow/deny rules

```python
from agentscope.agent import Agent
from agentscope.state import AgentState
from agentscope.permission import (
    PermissionContext, PermissionMode, PermissionRule, PermissionBehavior
)

agent = Agent(
    name="my_agent",
    system_prompt="...",
    model=model,
    state=AgentState(
        permission_context=PermissionContext(
            mode=PermissionMode.DEFAULT,
            allow_rules={
                "Bash": [PermissionRule(tool_name="Bash", rule_content="npm run:*",
                                        behavior=PermissionBehavior.ALLOW, source="userSettings")],
            },
            deny_rules={
                "Bash": [PermissionRule(tool_name="Bash", rule_content="rm:*",
                                        behavior=PermissionBehavior.DENY, source="userSettings")],
            },
        )
    ),
)
```

### Custom tool with check_permissions + check_read_only

```python
from agentscope.tool import ToolBase
from agentscope.permission import PermissionContext, PermissionDecision, PermissionBehavior

class MyTool(ToolBase):
    name = "MyTool"
    is_read_only = False

    async def check_read_only(self, tool_input: dict) -> bool:
        return tool_input.get("operation") in {"list", "describe", "get"}

    async def check_permissions(
        self,
        tool_input: dict,
        context: PermissionContext,
    ) -> PermissionDecision:
        target = tool_input.get("target")
        if target and target.startswith("prod-"):
            return PermissionDecision(
                behavior=PermissionBehavior.ASK,
                message=f"Operation targets production resource: {target}",
                decision_reason="Safety check: production resource",
                bypass_immune=True,
            )
        return PermissionDecision(behavior=PermissionBehavior.PASSTHROUGH)
```

### Persisting an accepted rule from a user confirmation

```python
from agentscope.event import UserConfirmResultEvent

result = UserConfirmResultEvent(
    confirmed=True,
    rules=[suggested_rule],  # accepted rules persisted to engine
)
```

### Switching mode at runtime

```python
agent.state.permission_context.mode = PermissionMode.EXPLORE
```

## Decision Pipeline

When a tool call arrives, the engine evaluates in this order (across all modes):

1. **Deny rules** — if matched, return `DENY` immediately.
2. **Ask rules** — if matched, return `ASK` immediately.
3. **Tool's `check_permissions()`** — analyze the actual call inputs.
4. **Evaluate the tool's response:**
   - `ALLOW` → return `ALLOW`
   - `DENY` → return `DENY`
   - Safety ASK (`bypass_immune=True`) → return `ASK` (honored in `DEFAULT` / `ACCEPT_EDITS`; converted to `DENY` in `DONT_ASK`)
   - `PASSTHROUGH` or regular ASK → continue
5. **Allow rules** — if matched, return `ALLOW`.
6. **Mode default** — apply the active mode's default behavior to produce the final decision.

## Read-Only Detection

Read-only invocations are auto-allowed in **every** mode (including `DEFAULT`).

Built-in tool defaults:

| Tool | Read-only? |
|------|-----------|
| `Bash` | Input-dependent (overrides `check_read_only()`). |
| `Read` | Read-only by default. |
| `Write` | Not read-only. |
| `Edit` | Not read-only. |
| `Glob` / `Grep` | Return `PASSTHROUGH`; still require ASK unless an allow rule matches. |

Read-only Bash commands recognized (auto-allowed):

- **Git:** `git status`, `git log`, `git diff`, `git show`, `git branch`, `git blame`, `git grep`, `git reflog`, `git config --list`
- **Files:** `ls`, `cat`, `head`, `tail`, `grep`, `rg`, `find`, `tree`, `stat`, `wc`, `pwd`, `which`
- **Docker:** `docker ps`, `docker images`, `docker logs`, `docker inspect`, `docker info`
- **GitHub CLI:** `gh repo view`, `gh issue list`, `gh pr list`, `gh status`
- **Package managers:** `npm list`, `pip list`, `pip show`, `node --version`, `python --version`

Compound commands joined by `&&`, `||`, `;`, or `|` are read-only **only if all**
subcommands are read-only. Output redirections (`>`, `>>`) always make a command
non-read-only.

## Dangerous Paths (bypass-immune ASK triggers)

Operations touching these paths automatically trigger a bypass-immune ASK in most
modes:

- **Shell configs:** `.bashrc`, `.zshrc`, `.bash_profile`, `.profile`
- **Git configs:** `.gitconfig`, `.gitmodules`
- **SSH:** `.ssh/config`, `.ssh/authorized_keys`, `id_rsa`, `id_ed25519`
- **Credentials:** `.env`, `.env.local`, `.npmrc`, `.pypirc`, `.aws/credentials`
- **Directories:** `.git/`, `.ssh/`, `.claude/`, `.vscode/`, `.aws/`, `.kube/`

## Gotchas & Version Notes

- **Rule precedence:** deny → ask → tool `check_permissions()` → allow → mode
  default. **Deny rules and explicit ask rules are always honored in every mode,
  including `BYPASS`.**
- **`bypass_immune=True` safety ASKs:**
  - Honored in `DEFAULT` and `ACCEPT_EDITS`.
  - Converted to `DENY` in `DONT_ASK`.
  - **Ignored in `BYPASS`** by design (the user has opted out of safety prompts;
    only deny/ask rules remain as guardrails).
  - Cannot be overridden by allow rules in `DEFAULT` / `ACCEPT_EDITS`.
- **`BYPASS` mode:** skips all tool safety ASKs; only deny/ask rules act as
  guardrails. Do not rely on a custom tool's bypass-immune ASK to protect anything
  when the agent may run in `BYPASS`.
- **`DONT_ASK` mode:** converts *every* ASK (default, ask rules, and safety ASKs)
  to `DENY`. Use it for non-interactive runs so the agent never blocks waiting on a
  user — but expect operations that would prompt to be denied outright.
- **`EXPLORE` mode:** does **not** call `check_permissions()`; the read-only
  verdict is final and safety ASKs do not apply. A custom tool's permission logic
  is skipped entirely in this mode.
- **`ACCEPT_EDITS` mode:** auto-allows file operations **only** within configured
  `working_directories`. For Bash, **all** target paths must resolve inside a
  working directory for the command to be auto-allowed.
- **Read-only is always auto-allowed**, even in `DEFAULT`. Implement
  `check_read_only()` carefully on custom tools — returning `True` for a mutating
  operation silently grants it in all modes.
- **`PASSTHROUGH`:** returning `PermissionDecision(behavior=PermissionBehavior.PASSTHROUGH)`
  from `check_permissions()` means "I make no decision" — the engine then continues
  with `match_rule()` against allow rules, and if nothing matches, defaults to ASK
  (subject to the active mode). Prefer `PASSTHROUGH` over a bare `ASK` when you want
  rules/mode to have the final say.
- **Output redirection makes Bash non-read-only:** even an otherwise read-only
  command (e.g. `cat`) becomes mutating once it contains `>` or `>>`.
