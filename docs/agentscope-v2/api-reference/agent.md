# REST API: Agent

> Source:
> - https://docs.agentscope.io/api-reference/agent/create-a-new-agent.md
> - https://docs.agentscope.io/api-reference/agent/update-an-agent.md
> - https://docs.agentscope.io/api-reference/agent/list-all-agents.md
> - https://docs.agentscope.io/api-reference/agent/delete-an-agent.md
> - https://docs.agentscope.io/api-reference/agent/get-json-schema-fragments-for-the-agent-form.md

## Overview

The **Agent** REST unit of the AgentScope v2 runtime API (installed library `agentscope` 1.0.20; docs at docs.agentscope.io/v2) provides full CRUD over persisted *agent configurations* plus a schema endpoint that feeds the frontend create/edit form. All routes are mounted under the `/agent` prefix.

An agent configuration is built from four logical parts:

1. **Identity** — `name`, `system_prompt`.
2. **`context_config`** — context-window management (a `ContextConfig` object).
3. **`react_config`** — ReAct reasoning-loop tuning (a `ReActConfig` object).

The endpoints in this unit:

| Method | Path | Purpose | Success code |
|--------|------|---------|--------------|
| `POST` | `/agent/` | Create and persist a new agent configuration | `201` |
| `GET` | `/agent/` | List all agents for the authenticated user | `200` |
| `PATCH` | `/agent/{agent_id}` | Partially update an existing agent | `200` |
| `DELETE` | `/agent/{agent_id}` | Permanently delete an agent | `204` |
| `GET` | `/agent/schema` | Get JSON Schema fragments for the agent form | `200` |

**Authentication (all routes):** every request requires the `x-user-id` header. The docs explicitly flag this as temporary: *"Caller's user ID. Temporary header-based identity; will be replaced by JWT auth."* On the server side the user ID is injected into the handler as `user_id (str)` alongside an injected `storage (StorageBase)` backend.

> Documentation index for the whole API is at https://docs.agentscope.io/llms.txt

---

## API Reference

### `POST /agent/` — Create a new agent

Create and persist a new agent configuration.

**Server handler signature (as documented):**

```
create_agent(
    body: CreateAgentRequest,   # Agent configuration to store.
    user_id: str,               # Injected authenticated user ID.
    storage: StorageBase,       # Injected storage backend.
) -> CreateAgentResponse        # The server-assigned agent identifier.
```

**Headers**

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `x-user-id` | string | yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body — `CreateAgentRequest`**

| Field | Type | Required | Default | Meaning |
|-------|------|----------|---------|---------|
| `name` | string | **yes** | — | Display name of the agent. |
| `system_prompt` | string | no | `"You're a helpful assistant."` | Base system prompt fed to the agent. |
| `context_config` | `ContextConfig` | no | — | Context-window management configuration. |
| `react_config` | `ReActConfig` | no | — | ReAct loop configuration. |

**Returns — `CreateAgentResponse`**

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `agent_id` | string | yes | Server-assigned agent identifier. |

**Response codes**

| Status | Meaning | Body |
|--------|---------|------|
| `201` | Successful Response | `CreateAgentResponse` |
| `404` | Not found | — |
| `422` | Validation Error | `HTTPValidationError` |

---

### `GET /agent/` — List all agents

Retrieve all agent records belonging to the authenticated user.

**Headers**

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `x-user-id` | string | yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

No query parameters and no request body — only the `x-user-id` header.

**Returns — `ListAgentsResponse`**

| Field | Type | Meaning |
|-------|------|---------|
| `agents` | array of `AgentRecord` | Collection of the user's agent records. |
| `total` | integer | Count of total agents. |

**Response codes**

| Status | Meaning |
|--------|---------|
| `200` | Success — returns `ListAgentsResponse` |
| `404` | Not found |
| `422` | Validation error (with `detail` array) |

---

### `PATCH /agent/{agent_id}` — Update an agent

Partial update of an existing agent configuration. **Only the fields present in the request body are updated; all other fields keep their current values.**

**Path parameters**

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `agent_id` | string | yes | The agent identifier to update. |

**Headers**

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `x-user-id` | string | yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body — `UpdateAgentRequest`** (every field is nullable / optional; omit a field to leave it unchanged)

| Field | Type | Meaning |
|-------|------|---------|
| `name` | string \| null | New display name. |
| `system_prompt` | string \| null | New system prompt. |
| `context_config` | `ContextConfig` \| null | New context configuration. |
| `react_config` | `ReActConfig` \| null | New ReAct loop configuration. |

**Returns (HTTP 200) — `AgentRecord`** (the complete updated record; see schema below).

**Response codes**

| Status | Meaning |
|--------|---------|
| `200` | Success — returns the full `AgentRecord` |
| `404` | Agent doesn't exist or doesn't belong to the authenticated user |
| `422` | Validation error |

---

### `DELETE /agent/{agent_id}` — Delete an agent

Permanently removes an agent configuration from the system.

**Path parameters**

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `agent_id` | string | yes | Identifier of the agent to remove. |

**Headers**

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `x-user-id` | string | yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Response codes**

| Status | Meaning |
|--------|---------|
| `204` | Successful deletion (no content) |
| `404` | Agent not found or doesn't belong to the authenticated user |
| `422` | Validation error |

The server raises an `HTTPException` with status `404` *"if the agent does not exist or does not belong to the authenticated user."* Validation errors return `422` with structured error details (location, message, error type).

---

### `GET /agent/schema` — Get JSON Schema fragments for the agent form

Retrieves JSON Schema fragments used to render the agent create/edit form on the frontend. The API returns **three separate** JSON Schema sections rather than one combined schema.

**Returns — `AgentSchemaResponse`** (all three properties are required; each is an object that allows additional properties)

| Field | Type | Meaning |
|-------|------|---------|
| `identity` | object (JSON Schema) | Schema for the agent's identity fields (`name`, `system_prompt`). |
| `context_config` | object (JSON Schema) | Schema for `ContextConfig`. |
| `react_config` | object (JSON Schema) | Schema for `ReActConfig`. |

**Response codes**

| Status | Meaning |
|--------|---------|
| `200` | Success — returns `AgentSchemaResponse` |
| `404` | Not Found |

**Design detail:** *"each fragment is a self-contained JSON Schema object so the frontend doesn't need to follow `$ref` links across fragments."* This modular layout lets the frontend pair each property with its own i18n keys, so labels and descriptions are independently localizable.

---

## Configuration

### `ContextConfig` — context-window management

| Option | Type | Default | Constraint / UI | Controls |
|--------|------|---------|-----------------|----------|
| `trigger_ratio` | number | `0.8` | `0 < x < 0.9` | Context-window fill ratio at which compression/summarization is triggered. |
| `reserve_ratio` | number | `0.1` | `0 < x < 0.9` | Fraction of the context window reserved (kept free). |
| `compression_prompt` | string | — | textarea | Prompt used when compressing context. |
| `summary_template` | string | — | textarea | Template used when summarizing context. |
| `summary_schema` | object | — | — | Structured schema for the summary output. |
| `tool_result_limit` | integer | `3000` | — | Maximum length of tool results, in tokens. |

### `ReActConfig` — ReAct reasoning loop

| Option | Type | Default | Controls |
|--------|------|---------|----------|
| `max_iters` | integer | `20` | Maximum reasoning–acting iterations in one reply. |
| `stop_on_reject` | boolean | `false` | Whether to stop replying when rejected from executing tools. |

### Identity fields

| Option | Type | Default | Controls |
|--------|------|---------|----------|
| `name` | string | (required on create) | Display name of the agent. |
| `system_prompt` | string | `"You're a helpful assistant."` | Base system prompt fed to the agent. |

---

## Response object schemas

### `AgentRecord` (returned by `PATCH`; elements of `ListAgentsResponse.agents`)

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Record identifier. |
| `user_id` | string | Owner user ID. |
| `source` | enum (`user` / `team`) | Whether the record is a user or team agent. |
| `created_at` | timestamp | Creation time. |
| `updated_at` | timestamp | Last update time. |
| `data` | `AgentData` | The agent configuration payload. |

### `AgentData` (the `data` object inside `AgentRecord`)

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Agent ID. |
| `name` | string | Display name. |
| `system_prompt` | string | System prompt. |
| `context_config` | `ContextConfig` | Context configuration. |
| `react_config` | `ReActConfig` | ReAct configuration. |

### `HTTPValidationError` (422 body)

`detail` is an array of validation error entries; each entry includes the error **location**, **message** (`msg`), and **type**.

---

## Usage Patterns

> Note: the documentation pages describe the schemas and endpoints but do not ship complete copy-paste curl/JSON request examples. The examples below are constructed strictly from the documented field names, defaults, and shapes — they introduce no fields beyond what the docs define.

### Create an agent

```http
POST /agent/
x-user-id: <user-id>
Content-Type: application/json

{
  "name": "Research Assistant",
  "system_prompt": "You're a helpful assistant.",
  "context_config": {
    "trigger_ratio": 0.8,
    "reserve_ratio": 0.1,
    "tool_result_limit": 3000
  },
  "react_config": {
    "max_iters": 20,
    "stop_on_reject": false
  }
}
```

Response `201`:

```json
{ "agent_id": "<server-assigned-id>" }
```

### List agents

```http
GET /agent/
x-user-id: <user-id>
```

Response `200`:

```json
{
  "agents": [
    {
      "id": "...",
      "user_id": "...",
      "source": "user",
      "created_at": "...",
      "updated_at": "...",
      "data": {
        "id": "...",
        "name": "Research Assistant",
        "system_prompt": "You're a helpful assistant.",
        "context_config": { },
        "react_config": { }
      }
    }
  ],
  "total": 1
}
```

### Partial update (only changed fields)

```http
PATCH /agent/<agent_id>
x-user-id: <user-id>
Content-Type: application/json

{ "name": "Renamed Assistant" }
```

Omitted fields (`system_prompt`, `context_config`, `react_config`) keep their current values. Response `200` returns the full `AgentRecord`.

### Delete

```http
DELETE /agent/<agent_id>
x-user-id: <user-id>
```

Response `204` (no body).

### Fetch form schema fragments

```http
GET /agent/schema
x-user-id: <user-id>
```

Response `200`:

```json
{
  "identity": { },
  "context_config": { },
  "react_config": { }
}
```

---

## Gotchas & Version Notes

- **Auth is header-based and temporary.** Every endpoint requires the `x-user-id` header. The docs explicitly say this is a *"Temporary header-based identity; will be replaced by JWT auth."* Code written today should isolate this header so the future JWT migration is a single-point change — do not hardcode `x-user-id` throughout call sites.
- **`PATCH` is a true partial update.** *"Only the fields present in the request body are updated; all other fields keep their current values."* Do **not** send a full object with `null`s expecting to clear fields — omit fields to leave them unchanged. All `UpdateAgentRequest` fields are nullable/optional.
- **Use `PATCH`, not `PUT`.** The update route is `PATCH /agent/{agent_id}`; there is no documented `PUT` route. Do not assume full-replacement semantics.
- **Trailing slash matters.** Create and list use `/agent/` (with trailing slash). Update and delete use `/agent/{agent_id}`. Schema is `/agent/schema`.
- **Success codes differ per verb.** Create returns `201`, list/update/schema return `200`, delete returns `204` (empty body — do not parse a JSON body on delete).
- **404 on update/delete is ownership-scoped.** A `404` means the agent either doesn't exist *or* doesn't belong to the authenticated user — it is not solely a "missing record" signal. Treat 404 as "not yours / not found," not necessarily "deleted elsewhere."
- **`ContextConfig` ratio constraints.** Both `trigger_ratio` (default `0.8`) and `reserve_ratio` (default `0.1`) must satisfy `0 < x < 0.9`. Sending `0`, a negative value, `0.9`, or anything ≥ `0.9` will fail `422` validation.
- **`tool_result_limit` is in tokens** (default `3000`), not characters/bytes.
- **`max_iters` default is `20`** — guards the ReAct loop per reply. `stop_on_reject` defaults to `false`.
- **Default `system_prompt`** is exactly `"You're a helpful assistant."` (note the contraction/apostrophe). If you rely on a default, this is the literal value applied.
- **Schema fragments are intentionally self-contained.** `GET /agent/schema` returns three independent JSON Schema objects (`identity`, `context_config`, `react_config`) with **no cross-fragment `$ref`s**, so the frontend can render and localize each section independently. Do not merge them expecting shared `$ref` resolution.
- **422 shape.** Validation errors return `HTTPValidationError` with a `detail` array of `{location, msg, type}` entries — handle this structured shape rather than a flat error string.
- **Version context.** Docs reference AgentScope v2 (the update page cites `v2.0.1`), corresponding to the installed `agentscope` 1.0.20 runtime API. No deprecated agent endpoints are documented in this unit.
