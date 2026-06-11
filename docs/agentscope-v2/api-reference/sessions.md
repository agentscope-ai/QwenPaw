# REST API: Sessions

> Source:
> - https://docs.agentscope.io/api-reference/sessions/create-a-new-session.md
> - https://docs.agentscope.io/api-reference/sessions/update-a-session.md
> - https://docs.agentscope.io/api-reference/sessions/list-sessions-for-an-agent.md
> - https://docs.agentscope.io/api-reference/sessions/list-messages-for-a-session.md
> - https://docs.agentscope.io/api-reference/sessions/subscribe-to-a-sessions-event-stream-sse.md
> - https://docs.agentscope.io/api-reference/sessions/delete-a-session.md
>
> Library: agentscope 1.0.20 (docs published under docs.agentscope.io/v2). This file documents the
> REST "Sessions" unit of the AgentScope HTTP API server.

## Overview

The Sessions unit is a set of six REST endpoints, all rooted at `/sessions`, that manage the
lifecycle of agent chat sessions and their event/message streams.

A **session** represents a persisted conversation context bound to an agent (and optionally a
workspace) for a given user. Key concepts:

- Identity is currently supplied via the **`x-user-id` request header** on every endpoint. The docs
  repeatedly note this is a *temporary, header-based identity that will be replaced by JWT auth*.
  Code written against this API must send `x-user-id` today, but should be structured so the
  identity mechanism can be swapped for JWT later.
- **Uniqueness rule:** at most one session exists per `(user_id, agent_id, workspace_id)` triple.
  A second `POST /sessions/` with the same triple **updates the existing session instead of
  creating a duplicate** (upsert semantics on create).
- `agent_id` is a **required query parameter** on every per-session endpoint (PATCH, GET messages,
  GET stream, DELETE) and a required field/query param on create and list. It is not derived from
  the path; you must pass it explicitly.
- **Messages are never embedded** in session listings. They are paginated separately through
  `GET /sessions/{session_id}/messages`.

Endpoint summary:

| Method | Path | Purpose | Success |
|--------|------|---------|---------|
| POST | `/sessions/` | Create (or upsert) a session | 201 |
| GET | `/sessions/` | List sessions for an agent | 200 |
| PATCH | `/sessions/{session_id}` | Update a session's config/name/permission mode | 200 |
| GET | `/sessions/{session_id}/messages` | List messages (paginated) | 200 |
| GET | `/sessions/{session_id}/stream` | Subscribe to SSE event stream | 200 |
| DELETE | `/sessions/{session_id}` | Delete a session permanently | 204 |

## API Reference

### POST /sessions/ — Create a new session

Creates a session. Because of the uniqueness rule, this behaves as an **upsert**: calling it again
with the same `(user_id, agent_id, workspace_id)` triple updates the existing session rather than
producing a duplicate.

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | Yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body — `CreateSessionRequest`**

| Field | Type | Required | Default | Meaning |
|-------|------|----------|---------|---------|
| `agent_id` | string | Yes | — | Agent this session belongs to. |
| `workspace_id` | string \| null | No | null | Workspace this session belongs to. Part of the uniqueness triple. |
| `name` | string \| null | No | current datetime | Display name; defaults to the current datetime if omitted. |
| `chat_model_config` | ChatModelConfig \| null | No | null | Model provider and parameters; can be set later via PATCH. |
| `fallback_chat_model_config` | ChatModelConfig \| null | No | null | Fallback model used when the primary model fails; can be set later via PATCH. |

**`ChatModelConfig` schema** (used by `chat_model_config` and `fallback_chat_model_config`)

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `type` | string | Yes | Model provider type. |
| `credential_id` | string | Yes | ID of the stored credential to authenticate with the provider. |
| `model` | string | Yes | Model name/identifier. |
| `parameters` | object (additional properties allowed) | Yes | Provider/model parameters (free-form key/value object). |

**Returns**

- **201** — `CreateSessionResponse`
  - `session_id` (string): Server-assigned session identifier.
- **404** — Agent or credential does not exist or does not belong to the authenticated user.
- **422** — `HTTPValidationError` with validation details.

### GET /sessions/ — List sessions for an agent

Operation ID: `list_sessions_sessions__get`. Returns all sessions for the given agent that belong to
the calling user.

**Query parameters**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `agent_id` | string | Yes | Filter sessions by agent ID. |

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | Yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns**

- **200** — `ListSessionsResponse`
  - `sessions` (array of `SessionView`, required): Session views (record + is_running + team).
  - `total` (integer, required): Total number of sessions.
- **404** — Agent does not exist or does not belong to the authenticated user.
- **422** — `HTTPValidationError` with validation details.

**`SessionView`** (each entry of `sessions`)

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `session` | SessionRecord | Yes | The persisted session record. Includes `state`. |
| `is_running` | boolean | Yes | Whether a chat run is currently active on this session. |
| `team` | TeamDetailResponse \| null | No | Resolved team detail when the session participates in a team. |

> Messages are intentionally **not** included here — they are paginated separately via
> `GET /sessions/{session_id}/messages`.

### PATCH /sessions/{session_id} — Update a session

Modifies an existing session's name, model configuration, and/or permission mode. Returns the full
updated `SessionRecord`.

**Path parameter**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `session_id` | string | Yes | The session identifier to update. |

**Query parameter**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `agent_id` | string | Yes | Agent the session belongs to. |

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | Yes | Caller's user ID (temporary header-based identity pending JWT migration). |

**Request body — `UpdateSessionRequest`** (all fields optional; semantics of omit vs null matter)

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `name` | string \| null | No | New display name. |
| `chat_model_config` | ChatModelConfig \| null | No | New model configuration; **replaces the existing one entirely**. Pass `null` to clear it; **omit** the field to leave it unchanged. |
| `fallback_chat_model_config` | ChatModelConfig \| null | No | New fallback configuration. `null` clears it; **omit** leaves it unchanged. |
| `permission_mode` | PermissionMode \| null | No | New permission mode for the session. |

> Gotcha: `chat_model_config` is a full replacement, not a merge. Omitting a field leaves it
> unchanged; explicitly sending `null` clears it.

**Returns**

- **200** — `SessionRecord` (see model below).
- **404** — Session, agent, or credential not found or unauthorized access.
- **422** — Validation error with detailed error array.

### GET /sessions/{session_id}/messages — List messages for a session

Returns the session's messages in chronological order, with pagination, plus whether the session is
currently running.

**Path parameter**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `session_id` | string | Yes | The session to query. |

**Query parameters**

| Param | Type | Required | Default | Constraints | Meaning |
|-------|------|----------|---------|-------------|---------|
| `agent_id` | string | Yes | — | — | Agent the session belongs to. |
| `offset` | integer | No | 0 | minimum 0 | Pagination offset. |
| `limit` | integer | No | 50 | minimum 1, maximum 200 | Maximum number of messages returned. |

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | Yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns**

- **200** — `ListMessagesResponse`
  - `messages` (array): Messages in chronological order.
  - `is_running` (boolean): Whether the session is currently running.
- **404** — Not found.
- **422** — `HTTPValidationError` (detail array of `ValidationError` objects with `loc`, `msg`, `type`, `input`, and `ctx` fields).

Example 200 body shape:

```json
{
  "messages": [],
  "is_running": false
}
```

> The underlying function accepts: `session_id`, `agent_id`, `offset`, `limit`, plus injected
> `user_id`, `storage`, and `message_bus`.

### GET /sessions/{session_id}/stream — Subscribe to a session's event stream (SSE)

Opens a Server-Sent Events stream of `AgentEvent` objects for the session.

**Path parameter**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `session_id` | string | Yes | The session identifier. |

**Query parameter**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `agent_id` | string | Yes | Agent the session belongs to. |

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | Yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns**

- **200** — Server-Sent Events stream of `AgentEvent` objects, content type `application/json`.
- **404** — Not found.
- **422** — `HTTPValidationError` with validation details.

**Streaming behavior (critical for clients):**

- On connect, the endpoint **first replays any buffered events** from the current run's replay log
  (if a run is in progress or just finished), **then streams live events**.
- A **heartbeat comment frame (`:\n\n`) is sent every 30 seconds** to keep the connection alive
  through reverse proxies. Clients must tolerate/ignore these comment frames.
- The connection **remains open across subsequent runs** on the same session (it does not close when
  a single run finishes).

> Injected (not in the OpenAPI spec, not client-supplied): `user_id`, `storage`, `message_bus`.

### DELETE /sessions/{session_id} — Delete a session

Permanently removes a session and its associated state.

**Path parameter**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `session_id` | string | Yes | The session identifier to delete. |

**Query parameter**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `agent_id` | string | Yes | The agent the session belongs to. |

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | Yes | Caller's user ID for authentication (temporary header-based identity). |

**Returns**

- **204 No Content** — Success (empty body).
- **404 Not Found** — Session doesn't exist or doesn't belong to the authenticated user.
- **422 Unprocessable Entity** — Validation error; `HTTPValidationError` with a `detail` array of `ValidationError` objects (each with `loc`, `msg`, `type`).

> Injected: `user_id` (authenticated user ID), `storage` (StorageBase backend for persistence).

## Shared Data Models

### SessionRecord

Returned by PATCH and embedded in each `SessionView` from the list endpoint.

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Session ID. |
| `created_at` | datetime | Creation timestamp. |
| `updated_at` | datetime | Last-update timestamp. |
| `user_id` | string | Owning user ID. |
| `agent_id` | string | Owning agent ID. |
| `source` | SessionSource (`"user"` \| `"schedule"`, default `"user"`) | How the session was created. |
| `source_schedule_id` | string \| null | Schedule ID when `source` is `"schedule"`. |
| `team_id` | string \| null | Team ID when the session belongs to a team. |
| `config` | SessionConfig | Session configuration (see below). |
| `state` | AgentState | Session runtime state (see below). |

### SessionConfig

| Field | Meaning |
|-------|---------|
| `workspace_id` | Workspace this session belongs to. |
| `name` | Display name. |
| `chat_model_config` | Primary model configuration (`ChatModelConfig`). |
| `fallback_chat_model_config` | Fallback model configuration (`ChatModelConfig`). |

### AgentState

Contains session context, summary, permissions, tools, and tasks. The list endpoint specifically
notes `state` includes `permission_context`, `tool_context`, and `tasks_context`.

### ChatModelConfig

`{ type, credential_id, model, parameters }` — see the create endpoint for full field definitions.

### TeamDetailResponse

Included in `SessionView.team`. Contains the team record, `leader_agent`, and a `members` array
(each member bundling agent records and session IDs).

### PermissionMode

An enum used by the PATCH endpoint's `permission_mode` field. (The pages do not enumerate its
allowed string values.)

### HTTPValidationError / ValidationError

`HTTPValidationError` has a `detail` array of `ValidationError` objects. Each `ValidationError`
includes `loc`, `msg`, `type`, and (on the messages endpoint) `input` and `ctx` fields.

## Configuration

Request-shaping options across the unit:

| Option | Endpoint(s) | Type | Default | Controls |
|--------|-------------|------|---------|----------|
| `x-user-id` (header) | all | string | — (required) | Caller identity; temporary, will become JWT. |
| `agent_id` | all | string | — (required) | The agent the session belongs to / filter by. |
| `workspace_id` | POST | string \| null | null | Workspace binding; part of the uniqueness triple. |
| `name` | POST, PATCH | string \| null | current datetime (create) | Session display name. |
| `chat_model_config` | POST, PATCH | ChatModelConfig \| null | null | Primary model; PATCH replaces entirely (null clears, omit keeps). |
| `fallback_chat_model_config` | POST, PATCH | ChatModelConfig \| null | null | Fallback model on primary failure. |
| `permission_mode` | PATCH | PermissionMode \| null | — | Session permission mode. |
| `offset` | GET messages | integer | 0 | Pagination offset (min 0). |
| `limit` | GET messages | integer | 50 | Page size (min 1, max 200). |
| ChatModelConfig.`type` | POST, PATCH | string | — (required) | Model provider type. |
| ChatModelConfig.`credential_id` | POST, PATCH | string | — (required) | Stored credential to use. |
| ChatModelConfig.`model` | POST, PATCH | string | — (required) | Model identifier. |
| ChatModelConfig.`parameters` | POST, PATCH | object | — (required) | Free-form model parameters. |

## Usage Patterns

> Note: the source pages provide schema/JSON examples but few full curl examples. The snippets below
> reflect the documented method, path, headers, and body shapes exactly. The only verbatim response
> JSON example in the docs is the messages-list shape.

Create (upsert) a session:

```http
POST /sessions/
x-user-id: <user-id>
Content-Type: application/json

{
  "agent_id": "<agent-id>",
  "workspace_id": "<workspace-id>",
  "name": "My session",
  "chat_model_config": {
    "type": "<provider-type>",
    "credential_id": "<credential-id>",
    "model": "<model-name>",
    "parameters": {}
  }
}
```

Response (201):

```json
{ "session_id": "<server-assigned-id>" }
```

List sessions for an agent:

```http
GET /sessions/?agent_id=<agent-id>
x-user-id: <user-id>
```

Update only the name (leave model config untouched by omitting it):

```http
PATCH /sessions/<session-id>?agent_id=<agent-id>
x-user-id: <user-id>
Content-Type: application/json

{ "name": "Renamed session" }
```

Clear the fallback model explicitly (send null):

```http
PATCH /sessions/<session-id>?agent_id=<agent-id>
x-user-id: <user-id>
Content-Type: application/json

{ "fallback_chat_model_config": null }
```

List messages (paginated):

```http
GET /sessions/<session-id>/messages?agent_id=<agent-id>&offset=0&limit=50
x-user-id: <user-id>
```

Response (200) — verbatim shape from docs:

```json
{
  "messages": [],
  "is_running": false
}
```

Subscribe to the SSE event stream:

```http
GET /sessions/<session-id>/stream?agent_id=<agent-id>
x-user-id: <user-id>
Accept: text/event-stream
```

Delete a session:

```http
DELETE /sessions/<session-id>?agent_id=<agent-id>
x-user-id: <user-id>
```

Response: `204 No Content` (empty body).

## Gotchas & Version Notes

- **`x-user-id` header is mandatory on every endpoint.** It is explicitly documented as a
  *temporary, header-based identity that will be replaced by JWT auth*. Code must send it now, but
  the identity layer is expected to migrate to JWT — design call sites to make that swap easy.
- **`agent_id` is required on every per-session call** (PATCH, GET messages, GET stream, DELETE) as
  a **query parameter**, in addition to the `session_id` in the path. It is not inferred from the
  session. Omitting it triggers a 422.
- **Create is an upsert, not a hard create.** At most one session exists per
  `(user_id, agent_id, workspace_id)`. A repeat POST with the same triple updates the existing
  session — do not rely on POST always producing a new `session_id`.
- **PATCH `chat_model_config` / `fallback_chat_model_config` replace entirely.** They are not merged
  into the existing config. Three distinct behaviors:
  - omit the field → unchanged,
  - send `null` → cleared,
  - send an object → full replacement.
- **Messages are never returned by the list-sessions or session-record payloads.** Always page them
  via `GET /sessions/{session_id}/messages`. `limit` is capped at 200 (default 50, min 1); `offset`
  min 0 (default 0).
- **SSE stream replays buffered events first, then goes live**, and **stays open across multiple
  runs** on the same session. Clients must (a) handle replayed-then-live ordering, (b) ignore the
  30-second heartbeat comment frames (`:\n\n`), and (c) not assume the stream closes when a single
  run ends. Note the documented `Content-Type` for the success response is `application/json` even
  though the body is an SSE stream of `AgentEvent` objects.
- **DELETE is permanent** (removes the session and its associated state) and returns **204 with no
  body** — do not attempt to parse a JSON response on success.
- **Status code per endpoint differs:** create → 201, list/patch/messages/stream → 200, delete →
  204. Validation failures are 422 everywhere; missing/unauthorized agent/session/credential are
  404 everywhere.
- **Injected dependencies** (`user_id`, `storage`, `message_bus`) appear in the underlying function
  signatures but are **not** part of the public OpenAPI/HTTP contract — never send them as params.
