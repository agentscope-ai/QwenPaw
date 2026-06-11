# Deploy: Agent Team

> Source: https://docs.agentscope.io/v2/deploy/agent-team.md

## Overview

Agent Team is the multi-agent layer built on top of [Agent Service](https://docs.agentscope.io/v2/deploy/agent-service). A **leader agent** — the session the user talks to — can spawn **worker agents** on demand and exchange messages with them. Every member is just another session with its own state, workspace binding, and event stream. The entire coordination story is expressed through **four built-in tools** rather than a separate orchestration framework.

Key facts:

- The team feature is **built into Agent Service** — no extra configuration is required to use the default behavior.
- Workers run **concurrently** on the same service, each in its own session with its own event stream. They are **not** nested coroutines under the leader.
- All inter-member communication is mediated by the **message bus** (a Redis-backed abstraction), so leader and worker sessions can live in different processes or nodes without code changes.
- The leader orchestrates work by reading worker outputs and sending messages — all through the same chat interface.

### Core concepts

| Concept          | Description                                                                                                                                                                                                                     |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Team**         | A persistent group of agent members owned by one user. A `TeamRecord` carries the team's identity (name, description) and its member list.                                                                                       |
| **Leader**       | The session that created the team. Only the leader can add or remove members or end the team.                                                                                                                                    |
| **Worker**       | A session spawned as a team member. Workers run their own ReAct loop in their own session and inherit the leader's chat model + workspace context.                                                                               |
| **Team message** | A message routed between members through the message bus. Delivered as a `HintBlock` wrapped in a `<team-message from="…">` tag so the recipient's LLM can disambiguate it from a regular user turn.                              |

## API Reference

### Built-in tools (overview)

A leader session is automatically given these four tools. **Workers see only `TeamSay`.**

| Tool          | Purpose                                                                                                                                                |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `TeamCreate`  | Create a new team rooted at the current session and become its leader.                                                                                 |
| `AgentCreate` | Spawn a new worker into the team with a name, role description, first task, and permission mode. The worker begins executing as soon as it is created. |
| `TeamSay`     | Send a message to a named member (or broadcast). The recipient's session receives the message through its inbox and resumes on the next wakeup.        |
| `TeamDelete`  | Dissolve the team and clean up every member session. Only the leader can call this.                                                                    |

These are agent-facing tools (invoked by the LLM via tool calls), not Python functions a developer calls directly. The page does not document explicit Python signatures or parameter types for the tools themselves beyond the descriptions above; the parameter intent for each is captured in the Purpose column. The page describes their parameters in prose:

- **`TeamCreate`** — takes a team `name` and `description` that frame the collaboration goal.
- **`AgentCreate`** — takes a worker `name`, a role `description`, an initial `task`, and a permission mode. When custom templates are registered it additionally exposes a `subagent_type` enum parameter (see below). The worker begins executing immediately upon creation.
- **`TeamSay`** — sends a message to a named member, or broadcasts. Available to both leaders and workers.
- **`TeamDelete`** — dissolves the team and cleans up all worker sessions. Leader-only.

### `create_app(...)` — `sub_agent_templates` parameter

Custom worker blueprints are registered by passing a list of `SubAgentTemplate` instances to `create_app` via the `sub_agent_templates` parameter.

Imports used in the documented example:

```python
from agentscope.app import create_app, SubAgentTemplate
from agentscope.permission import PermissionContext, PermissionMode
```

Documented call shape (other parameters such as `storage`, `message_bus`, `workspace_manager` are shown but documented under Agent Service):

```python
app = create_app(
    storage=storage,
    message_bus=message_bus,
    workspace_manager=workspace_manager,
    sub_agent_templates=[ ... ],   # list[SubAgentTemplate]
)
```

| Parameter             | Type                       | Meaning                                                                                                   |
| --------------------- | -------------------------- | --------------------------------------------------------------------------------------------------------- |
| `sub_agent_templates` | `list[SubAgentTemplate]`   | List of reusable worker blueprints the leader agent can choose from when creating workers via `AgentCreate`. |

(`storage`, `message_bus`, `workspace_manager` belong to the Agent Service unit and are referenced here only as context.)

### `SubAgentTemplate`

Imported from `agentscope.app`. A reusable blueprint that defines a worker role's system prompt, permission boundary, and context/loop configuration. Registering templates lets the leader pick different capability boundaries per worker (e.g. a read-only explorer vs. a full-access coder).

#### Fields

| Field                    | Required | Default               | Description                                                                                                                          |
| ------------------------ | -------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `type`                   | Yes      | —                     | Template identifier (e.g. `"explorer"`, `"coder"`). Becomes an enum value of the `subagent_type` parameter in `AgentCreate`.        |
| `description`            | Yes      | —                     | Agent-readable description exposed in the `AgentCreate` tool schema so the leader can choose the appropriate type.                  |
| `system_prompt_template` | Yes      | —                     | Python format string for the worker's system prompt. See placeholders below.                                                       |
| `permission_context`     | No       | `PermissionContext()` | Permission context applied to the worker. Controls what the worker is allowed to do (e.g. `PermissionMode.EXPLORE` for read-only). |
| `context_config`         | No       | `ContextConfig()`     | Context window configuration for the worker.                                                                                       |
| `react_config`           | No       | `ReActConfig()`       | ReAct loop configuration for the worker.                                                                                           |
| `tasks_context`          | No       | `TaskContext()`       | Pre-defined task context, allowing the template to seed an initial workflow.                                                       |

#### `system_prompt_template` placeholders

The `system_prompt_template` string is formatted (Python `str.format`-style) with these variables when a worker is created:

| Placeholder            | Value                                                  |
| ---------------------- | ------------------------------------------------------ |
| `{team_name}`          | The team's name as set by `TeamCreate`.                |
| `{team_description}`   | The team's description as set by `TeamCreate`.         |
| `{member_name}`        | The worker's name as set by `AgentCreate`.             |
| `{member_description}` | The worker's role description as set by `AgentCreate`. |
| `{leader_name}`        | The leader agent's display name.                       |

### Supporting types referenced

| Type                | Module                   | Use                                                                               |
| ------------------- | ------------------------ | --------------------------------------------------------------------------------- |
| `PermissionContext` | `agentscope.permission`  | Wraps the permission settings applied to a worker. Default is `PermissionContext()`. |
| `PermissionMode`    | `agentscope.permission`  | Enum of permission modes; `PermissionMode.EXPLORE` is documented as read-only.    |
| `ContextConfig`     | (AgentScope)             | Context window configuration; default `ContextConfig()`.                          |
| `ReActConfig`       | (AgentScope)             | ReAct loop configuration; default `ReActConfig()`.                                |
| `TaskContext`       | (AgentScope)             | Pre-defined task context; default `TaskContext()`.                                |
| `TeamRecord`        | (AgentScope)             | Carries a team's identity (name, description) and member list.                    |
| `HintBlock`         | (AgentScope)             | Block type used to deliver team messages into a recipient's context.              |
| `HintBlockEvent`    | (AgentScope)             | Event form the queued team messages take in the recipient's context.              |

## Configuration

| Option / Field                            | Where                       | Default               | Controls                                                                                          |
| ----------------------------------------- | --------------------------- | --------------------- | ------------------------------------------------------------------------------------------------ |
| `sub_agent_templates`                     | `create_app(...)`           | (none / built-in only) | List of `SubAgentTemplate` blueprints available to the leader.                                   |
| `SubAgentTemplate.type`                   | `SubAgentTemplate`          | required              | Unique template id; becomes a `subagent_type` enum value in `AgentCreate`.                       |
| `SubAgentTemplate.description`            | `SubAgentTemplate`          | required              | Agent-readable text in the `AgentCreate` schema guiding leader's choice.                          |
| `SubAgentTemplate.system_prompt_template` | `SubAgentTemplate`          | required              | Format-string system prompt for the worker.                                                      |
| `SubAgentTemplate.permission_context`     | `SubAgentTemplate`          | `PermissionContext()` | Worker capability boundary (e.g. `PermissionMode.EXPLORE` = read-only).                           |
| `SubAgentTemplate.context_config`         | `SubAgentTemplate`          | `ContextConfig()`     | Worker context window configuration.                                                             |
| `SubAgentTemplate.react_config`           | `SubAgentTemplate`          | `ReActConfig()`       | Worker ReAct loop configuration.                                                                 |
| `SubAgentTemplate.tasks_context`          | `SubAgentTemplate`          | `TaskContext()`       | Seeds an initial workflow for the worker.                                                        |
| `AgentCreate.subagent_type` (runtime)     | `AgentCreate` tool schema   | absent unless templates registered | Enum selecting which template a new worker uses; includes `"default"` when templates registered. |

## Usage Patterns

### Default team behavior (no configuration)

The team feature is built into Agent Service. When a user sends a task that benefits from multi-agent collaboration, the leader agent automatically uses the built-in team tools to assemble and coordinate a team of workers. Out of the box the leader can:

- **Create a team** with a name and description that frames the collaboration goal.
- **Spawn workers** by giving each a name, role description, and an initial task. Workers begin executing immediately upon creation.
- **Exchange messages** with workers for follow-up instructions or to collect results.
- **Dissolve the team** when the task is complete, cleaning up all worker sessions.

Every worker runs concurrently in its own session with its own event stream, visible in the frontend UI alongside the leader's conversation. By default, all workers share the same system prompt template and permission settings.

### Quickstart with bundled examples

The bundled [`examples/agent_service`](https://github.com/agentscope-ai/agentscope/tree/main/examples/agent_service) backend ships with the team tools enabled, and the matching [`examples/web_ui`](https://github.com/agentscope-ai/agentscope/tree/main/examples/web_ui) frontend renders team membership and per-worker streams out of the box. After booting both (see the Agent Service quickstart, "try the bundled example"), ask the leader agent to assemble a team — you will see it call `TeamCreate` / `AgentCreate` automatically, watch workers come online, and observe them exchange messages in the UI.

### Registering custom sub-agent templates (read-only explorer example)

Verbatim documented example:

```python
from agentscope.app import create_app, SubAgentTemplate
from agentscope.permission import PermissionContext, PermissionMode

app = create_app(
    storage=storage,
    message_bus=message_bus,
    workspace_manager=workspace_manager,
    sub_agent_templates=[
        SubAgentTemplate(
            type="explorer",
            description=(
                "Read-only agents specialized in exploration tasks. "
                "Use this type when you need to investigate the "
                "codebase without making any changes."
            ),
            system_prompt_template="""You are {member_name}, an explorer \
agent in team '{team_name}' led by {leader_name}.

Team purpose: {team_description}

Your role: {member_description}

## Responsibilities
- Complete the exploration tasks assigned by the team leader.
- You are read-only: you may inspect files and the codebase, but \
you must never modify, create, or delete anything.

## Reporting
- Always report the task result back to {leader_name} using the \
TeamSay tool, whether the task succeeds or fails.""",
            permission_context=PermissionContext(
                mode=PermissionMode.EXPLORE,
            ),
        ),
    ],
)
```

Note: `PermissionContext` is constructed with `mode=PermissionMode.EXPLORE` to produce a read-only worker.

## Gotchas & Version Notes

### Runtime behavior of `subagent_type` in `AgentCreate`

- **No custom templates registered** — `AgentCreate` does **not** expose a `subagent_type` parameter at all. All workers use the built-in default template. This keeps the tool schema clean when templates are not needed. Do not assume `subagent_type` is always present.
- **Custom templates registered** — `AgentCreate` automatically gains a `subagent_type` enum field listing all available types (**including `"default"`**). The leader agent sees each type's description and chooses one.
- **Overriding the default** — registering a template with `type="default"` **replaces the built-in default template entirely**.
- **Uniqueness** — template `type` names must be unique. **Duplicate types cause a `ValueError` at startup.**

### Tool visibility

- A **leader** session is automatically given all four tools (`TeamCreate`, `AgentCreate`, `TeamSay`, `TeamDelete`).
- **Workers see only `TeamSay`.** Do not expect workers to spawn sub-workers or delete teams.
- **`TeamDelete` is leader-only** — only the leader (the session that created the team) can add/remove members or end the team.

### Concurrency / architecture correctness rules

- Workers run **concurrently on the same service**; they are **NOT nested coroutines under the leader**. Code must not assume in-process nesting or synchronous leader control over workers.
- The leader observes a worker's progress by **reading its session stream** or by having the worker `TeamSay` back to it — there is no direct return value from spawning a worker.
- All inter-member communication is mediated by the **message bus (Redis-backed)**. Leader and worker sessions may live in different processes/nodes. Communication reuses the same **inbox + wakeup** primitives used for scheduled fires and background-tool completions.

### Team-message delivery mechanics

The coordination flow (for correct mental model when modifying related code):

1. The sender's tool call (`TeamSay`, `AgentCreate`'s initial prompt, …) pushes a `HintBlock` onto the recipient session's inbox via the message bus.
2. A wakeup is enqueued for the recipient.
3. The wakeup dispatcher running on **any** process picks up the wakeup and drives `ChatService.run` for that session.
4. `InboxMiddleware` drains the inbox before the next reasoning step, so the queued team messages land in the recipient's context as `HintBlockEvent`s.

Team messages are delivered wrapped in a `<team-message from="…">` tag so the recipient's LLM can disambiguate them from a regular user turn.

### Defaults to respect

- `permission_context` defaults to `PermissionContext()` (i.e. full default permissions) if omitted — explicitly set `PermissionMode.EXPLORE` for read-only roles.
- `context_config`, `react_config`, and `tasks_context` default to `ContextConfig()`, `ReActConfig()`, and `TaskContext()` respectively.

### Version note

Documented for AgentScope v2 (docs.agentscope.io/v2; installed package `agentscope` 1.0.20). No deprecations or "use X instead of Y" migrations are stated on this page.
