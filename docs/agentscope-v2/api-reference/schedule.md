# REST API: Schedule

> Source:
> - https://docs.agentscope.io/api-reference/schedule/create-a-new-schedule.md
> - https://docs.agentscope.io/api-reference/schedule/update-a-schedule.md
> - https://docs.agentscope.io/api-reference/schedule/list-all-schedules.md
> - https://docs.agentscope.io/api-reference/schedule/list-execution-sessions-for-a-schedule.md
> - https://docs.agentscope.io/api-reference/schedule/delete-a-schedule.md
>
> Library: agentscope 1.0.20 (docs published under AgentScope v2 / OpenAPI title "AgentScope", version 2.0.1).
> OpenAPI spec served at `/v2/deploy/openapi.json`.

## Overview

The Schedule REST API lets a user create and manage **schedules** (cron-driven recurring
agent executions) on the AgentScope deploy server. A schedule binds a cron expression +
timezone to an agent and a chat-model configuration; when the schedule fires, the scheduler
(APScheduler under the hood) auto-creates an execution **session** that runs the agent.

All endpoints are tagged `schedule` and are mounted under the `/schedule` path prefix.

Identity is currently passed via a **temporary `x-user-id` request header** ("Caller's user
ID. Temporary header-based identity; will be replaced by JWT auth."). This header is
**required on every endpoint** and is the planned-to-be-deprecated auth mechanism — see
Gotchas.

Endpoint summary:

| Method | Path | Summary | Success | operationId |
|--------|------|---------|---------|-------------|
| POST   | `/schedule/` | Create a new schedule | 201 | `create_schedule_schedule__post` |
| GET    | `/schedule/` | List all schedules | 200 | `list_schedules_schedule__get` |
| PATCH  | `/schedule/{schedule_id}` | Update a schedule (partial) | 200 | `update_schedule_schedule__schedule_id__patch` |
| DELETE | `/schedule/{schedule_id}` | Delete a schedule | 204 | `delete_schedule_schedule__schedule_id__delete` |
| GET    | `/schedule/{schedule_id}/sessions` | List execution sessions for a schedule | 200 | (not given in docs) |

Common error responses across endpoints: `404` Not found, `422` Validation Error
(`HTTPValidationError`).

## API Reference

### POST `/schedule/` — Create a new schedule

Create a new schedule and register it with the scheduler.

- **operationId:** `create_schedule_schedule__post`
- **Tag:** `schedule`
- **Success status:** `201` Created → `CreateScheduleResponse`
- **Errors:** `404` if the specified agent does not exist; `422` Validation Error.

Underlying handler signature (from docs):
```
create_schedule(
    body: CreateScheduleRequest,   # Schedule configuration
    user_id: str,                  # Authenticated user ID
    storage: StorageBase,          # Storage instance
    scheduler: SchedulerManager,   # Scheduler manager
) -> CreateScheduleResponse        # The ID of the newly created schedule
```

**Parameters**

| Name | In | Required | Type | Description |
|------|-----|----------|------|-------------|
| `x-user-id` | header | yes | string | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body:** `CreateScheduleRequest` (application/json, required). See [CreateScheduleRequest](#createschedulerequest).

**Returns:** `CreateScheduleResponse` — `{ "schedule_id": "<server-assigned id>" }`.

**Example request**
```http
POST /schedule/ HTTP/1.1
Content-Type: application/json
x-user-id: user_123

{
  "name": "Weekday morning briefing",
  "description": "Summarize overnight events every weekday at 9am",
  "cron_expression": "0 9 * * 1-5",
  "timezone": "America/New_York",
  "agent_id": "agent_abc",
  "chat_model_config": {
    "type": "openai_chat",
    "credential_id": "cred_xyz",
    "model": "gpt-4o",
    "parameters": { "temperature": 0.7 }
  },
  "enabled": true,
  "stateful": false,
  "permission_mode": "dont_ask"
}
```

**Example response (201)**
```json
{ "schedule_id": "sched_01H..." }
```

---

### GET `/schedule/` — List all schedules

List all schedules owned by the current user.

- **operationId:** `list_schedules_schedule__get`
- **Tag:** `schedule`
- **Success status:** `200` → `ListSchedulesResponse`
- **Errors:** `404` Not found; `422` Validation Error.

Underlying handler signature (from docs):
```
list_schedules(
    user_id: str,        # Authenticated user ID
    storage: StorageBase # Storage instance
) -> ListSchedulesResponse   # Paginated list of schedule records
```

**Parameters**

| Name | In | Required | Type | Description |
|------|-----|----------|------|-------------|
| `x-user-id` | header | yes | string | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

There are **no query parameters documented** for pagination despite the "Paginated list"
description — the response simply returns all of the user's schedules plus a `total` count.

**Returns:** `ListSchedulesResponse` — see [ListSchedulesResponse](#listschedulesresponse).

**Example response (200)**
```json
{
  "schedules": [
    {
      "id": "sched_01H...",
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z",
      "user_id": "user_123",
      "agent_id": "agent_abc",
      "data": {
        "name": "Weekday morning briefing",
        "description": "",
        "enabled": true,
        "timezone": "Asia/Shanghai",
        "cron_expression": "0 9 * * 1-5",
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": null,
        "chat_model_config": { "type": "openai_chat", "credential_id": "cred_xyz", "model": "gpt-4o", "parameters": {} },
        "stateful": false,
        "permission_mode": "dont_ask",
        "source": "USER",
        "source_session_id": ""
      }
    }
  ],
  "total": 1
}
```

---

### PATCH `/schedule/{schedule_id}` — Update a schedule

Partially update a schedule. Fields omitted from the request body keep their current values.
Changing `cron_expression` or `timezone` immediately reschedules the APScheduler job. Setting
`enabled=False` removes the job from the scheduler **without deleting the record**; setting it
back to `True` re-registers it.

- **operationId:** `update_schedule_schedule__schedule_id__patch`
- **Tag:** `schedule`
- **Success status:** `200` → `ScheduleRecord`
- **Errors:** `404` if the schedule does not exist; `422` Validation Error.

Underlying handler signature (from docs):
```
update_schedule(
    schedule_id: str,              # ID of the schedule to update
    body: UpdateScheduleRequest,   # Fields to update
    user_id: str,                  # Authenticated user ID
    storage: StorageBase,          # Storage instance
    scheduler: SchedulerManager,   # Scheduler manager
) -> ScheduleRecord                # The updated schedule record
```

**Parameters**

| Name | In | Required | Type | Description |
|------|-----|----------|------|-------------|
| `schedule_id` | path | yes | string | ID of the schedule to update. |
| `x-user-id` | header | yes | string | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body:** `UpdateScheduleRequest` (application/json, required). All fields are
nullable/optional; omit a field to keep its current value. See
[UpdateScheduleRequest](#updateschedulerequest).

**Returns:** `ScheduleRecord` — the full updated record. See [ScheduleRecord](#schedulerecord).

**Example request**
```http
PATCH /schedule/sched_01H... HTTP/1.1
Content-Type: application/json
x-user-id: user_123

{
  "cron_expression": "0 8 * * 1-5",
  "timezone": "Asia/Shanghai",
  "enabled": false
}
```

---

### DELETE `/schedule/{schedule_id}` — Delete a schedule

Permanently delete a schedule. Removes the record from storage and unregisters the APScheduler
job.

- **operationId:** `delete_schedule_schedule__schedule_id__delete`
- **Tag:** `schedule`
- **Success status:** `204` No Content (no response body)
- **Errors:** `404` if the schedule does not exist; `422` Validation Error.

Underlying handler signature (from docs):
```
delete_schedule(
    schedule_id: str,            # ID of the schedule to delete
    user_id: str,                # Authenticated user ID
    storage: StorageBase,        # Storage instance
    scheduler: SchedulerManager, # Scheduler manager
) -> None
```

**Parameters**

| Name | In | Required | Type | Description |
|------|-----|----------|------|-------------|
| `schedule_id` | path | yes | string | ID of the schedule to delete. |
| `x-user-id` | header | yes | string | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns:** nothing (HTTP `204`).

**Example**
```http
DELETE /schedule/sched_01H... HTTP/1.1
x-user-id: user_123
```

---

### GET `/schedule/{schedule_id}/sessions` — List execution sessions for a schedule

Retrieves all execution sessions triggered by a specific schedule, ordered by creation time
with **newest first**.

- **Tag:** `schedule` (operationId not shown in docs)
- **Success status:** `200` → `ScheduleSessionsResponse`
- **Errors:** `404` Schedule not found; `422` Validation error.

**Parameters**

| Name | In | Required | Type | Description |
|------|-----|----------|------|-------------|
| `schedule_id` | path | yes | string | The schedule identifier. |
| `x-user-id` | header | yes | string | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns:** `ScheduleSessionsResponse`:
- `sessions` (array of `SessionRecord`)
- `total` (integer) — total number of execution sessions.

See [SessionRecord](#sessionrecord) and [SessionConfig](#sessionconfig).

> Note: This page is rendered as prose in the docs (not the raw OpenAPI YAML), so exact field
> types/defaults for the session models are summarized rather than verbatim from the spec.

## Configuration

### CreateScheduleRequest

Request body for creating a new schedule.

**Required:** `name`, `cron_expression`, `agent_id`, `chat_model_config`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | yes | — | Display name of the schedule. |
| `description` | string | no | `""` | Optional description. |
| `cron_expression` | string | yes | — | Standard 5-field cron expression, e.g. `'0 9 * * 1-5'`. |
| `timezone` | string | no | `UTC` | IANA timezone name, e.g. `'America/New_York'` or `'Asia/Shanghai'`. |
| `agent_id` | string | yes | — | Agent to run when the schedule fires. |
| `chat_model_config` | `ChatModelConfig` | yes | — | Model configuration for the auto-created session. |
| `enabled` | boolean | no | `true` | Whether the schedule is active immediately after creation. |
| `stateful` | boolean | no | `false` | If `True`, consecutive executions share the same session context. |
| `permission_mode` | `PermissionMode` | no | `dont_ask` | Permission level for the agent during scheduled execution. |

> GOTCHA — `timezone` default differs by model: on **`CreateScheduleRequest` the default is
> `UTC`**, but on the persisted **`ScheduleData` model the default is `Asia/Shanghai`**. Do not
> assume one default applies everywhere.

### CreateScheduleResponse

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schedule_id` | string | yes | Server-assigned schedule identifier. |

### UpdateScheduleRequest

Request body for partially updating a schedule. **Omit any field to keep its current value.**
Every field is `anyOf [type, null]` (nullable, all optional). There are **no required fields**.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string \| null | no | New display name. |
| `description` | string \| null | no | New description. |
| `cron_expression` | string \| null | no | New cron expression. **Reschedules the task immediately.** |
| `timezone` | string \| null | no | New IANA timezone name. (Changing it also reschedules the job.) |
| `enabled` | boolean \| null | no | Set to `False` to pause the schedule without deleting it; `True` re-registers it. |
| `stateful` | boolean \| null | no | Change whether executions share session context. |
| `permission_mode` | `PermissionMode` \| null | no | New permission mode. |

> Note: `UpdateScheduleRequest` does **not** allow changing `agent_id` or `chat_model_config`
> — those fields are absent from the update schema.
>
> Note on naming inconsistency: the prose/description text refers to `enable`/`enable=False`,
> but the actual field name is **`enabled`**. Use `enabled`.

### ScheduleRecord

Persisted schedule record (returned by PATCH and inside list responses).

**Required:** `user_id`, `agent_id`, `data`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | no | Unique identifier for the record. (Description literally reads "Unique identifier for the credential.") |
| `updated_at` | string (date-time) | no | Last update timestamp. |
| `created_at` | string (date-time) | no | Creation timestamp. |
| `user_id` | string | yes | Owner user id. |
| `agent_id` | string | yes | The agent id that will execute the schedule. |
| `data` | `ScheduleData` | yes | Schedule configuration. |

### ScheduleData

The schedule configuration data (nested under `ScheduleRecord.data`).

**Required:** `name`, `cron_expression`, `chat_model_config`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | yes | — | Display name of the schedule. |
| `description` | string | no | `""` | Description (purpose, trigger conditions, etc.). |
| `enabled` | boolean | no | `true` | Whether the schedule is active. Disabled schedules are retained but will not trigger. |
| `timezone` | string | no | `Asia/Shanghai` | IANA timezone name used to evaluate the cron expression. |
| `cron_expression` | string | yes | — | Standard 5-field cron expression, e.g. `'0 9 * * 1-5'`. |
| `started_at` | string (date-time) | no | — | When the schedule was started. |
| `ended_at` | string (date-time) \| null | no | — | When the schedule was ended. |
| `chat_model_config` | `ChatModelConfig` | yes | — | Model configuration for the auto-created session. |
| `stateful` | boolean | no | `false` | Whether consecutive executions share the same session context. If not, each execution has its own state. |
| `permission_mode` | `PermissionMode` | no | `dont_ask` | Permission level during scheduled execution. Defaults to `DONT_ASK` since no user is present to answer prompts. |
| `source` | `ScheduleSource` | no | `USER` | Indicates how this schedule was created. |
| `source_session_id` | string | no | `""` | The source session identifier, used for resource retrieval. |

### ChatModelConfig

The model configuration class. **All four fields required.**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | yes | Model type. |
| `credential_id` | string | yes | Credential identifier. |
| `model` | string | yes | Model name. |
| `parameters` | object (additionalProperties: true) | yes | Free-form model parameters. |

### PermissionMode (enum)

String enum controlling how tool-execution requests are handled during scheduled (unattended)
execution.

Values: `default`, `accept_edits`, `explore`, `bypass`, `dont_ask`.

| Value | Behavior | Use case |
|-------|----------|----------|
| `default` | All operations require explicit permission (unless explicit allow rules). Most secure. | Default/secure mode. |
| `accept_edits` | Auto-allow file writes/reads in working dirs and filesystem commands (mkdir, rm, mv); other ops follow normal rules. | User present, rapid iteration / development. |
| `explore` | Read-only: allow Read/Grep/Glob; deny Write/Edit/Bash. | Exploring codebase, planning. |
| `bypass` | All operations automatically allowed (no permission checks). | Testing/sandbox, fully trusted. |
| `dont_ask` | Convert all ASK decisions to DENY (user not available to answer prompts). | Scheduled / background / unattended execution. **This is the schedule default.** |

### ScheduleSource (enum)

String enum: `USER`, `AGENT`.

| Value | Meaning |
|-------|---------|
| `USER` | Created manually by the user via the UI. |
| `AGENT` | Created automatically by an agent, e.g. via a tool call. |

### ListSchedulesResponse

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schedules` | array of `ScheduleRecord` | yes | Schedule records. |
| `total` | integer | yes | Total number of schedules. |

### ScheduleSessionsResponse

(Response for `GET /schedule/{schedule_id}/sessions`.)

| Field | Type | Description |
|-------|------|-------------|
| `sessions` | array of `SessionRecord` | List of execution sessions, newest first. |
| `total` | integer | Total number of execution sessions. |

### SessionRecord

(Summarized from the prose docs page; not raw OpenAPI.)

**Required:** `id`, `user_id`, `agent_id`, `config`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | — | Session id. |
| `user_id` | string | yes | — | Owner user id. |
| `agent_id` | string | yes | — | Executing agent id. |
| `created_at` | datetime | no | — | Creation time. |
| `updated_at` | datetime | no | — | Update time. |
| `source` | enum (`user` \| `schedule`) | no | `user` | How the session was created. |
| `source_schedule_id` | string \| null | no | — | The schedule that triggered this session (when source = schedule). |
| `team_id` | string \| null | no | — | Optional team id. |
| `config` | `SessionConfig` | yes | — | Session configuration. |
| `state` | `AgentState` | no | — | Optional agent state. |

### SessionConfig

(Summarized from the prose docs page.)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workspace_id` | string | yes | Workspace id. |
| `name` | string | no | Optional session name. |
| `chat_model_config` | (model config) | no | Optional chat model configuration. |
| `fallback_chat_model_config` | (model config) | no | Optional fallback chat model configuration. |

### HTTPValidationError / ValidationError

Standard FastAPI validation error shape returned on `422`.

`HTTPValidationError`:
| Field | Type | Description |
|-------|------|-------------|
| `detail` | array of `ValidationError` | Validation error details. |

`ValidationError` (required: `loc`, `msg`, `type`):
| Field | Type | Description |
|-------|------|-------------|
| `loc` | array of (string \| integer) | Location of the error. |
| `msg` | string | Error message. |
| `type` | string | Error type. |
| `input` | any | The offending input. |
| `ctx` | object | Additional context. |

## Usage Patterns

### Create a schedule (minimal required fields)
```bash
curl -X POST https://<host>/schedule/ \
  -H "x-user-id: user_123" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Daily report",
    "cron_expression": "0 9 * * *",
    "agent_id": "agent_abc",
    "chat_model_config": {
      "type": "openai_chat",
      "credential_id": "cred_xyz",
      "model": "gpt-4o",
      "parameters": {}
    }
  }'
# -> 201 { "schedule_id": "sched_..." }
```
Only `name`, `cron_expression`, `agent_id`, `chat_model_config` are required. With no
`timezone`, the request defaults to `UTC`. `enabled` defaults to `true`, `stateful` to `false`,
`permission_mode` to `dont_ask`.

### List the user's schedules
```bash
curl https://<host>/schedule/ -H "x-user-id: user_123"
# -> 200 { "schedules": [ ...ScheduleRecord ], "total": N }
```

### Pause a schedule without deleting it
```bash
curl -X PATCH https://<host>/schedule/sched_... \
  -H "x-user-id: user_123" -H "Content-Type: application/json" \
  -d '{ "enabled": false }'
```
Setting `enabled=false` removes the APScheduler job but retains the record. Set
`enabled=true` to re-register it.

### Change the cron / timezone (immediate reschedule)
```bash
curl -X PATCH https://<host>/schedule/sched_... \
  -H "x-user-id: user_123" -H "Content-Type: application/json" \
  -d '{ "cron_expression": "30 7 * * 1-5", "timezone": "America/New_York" }'
```
Changing `cron_expression` or `timezone` reschedules the APScheduler job immediately.

### Inspect execution history
```bash
curl https://<host>/schedule/sched_.../sessions -H "x-user-id: user_123"
# -> 200 { "sessions": [ ...SessionRecord ], "total": N }  (newest first)
```

### Delete a schedule
```bash
curl -X DELETE https://<host>/schedule/sched_... -H "x-user-id: user_123"
# -> 204 No Content
```

## Gotchas & Version Notes

- **`x-user-id` header is mandatory on every endpoint.** It is explicitly documented as a
  *temporary* header-based identity that "will be replaced by JWT auth." Code that relies on
  this header should be flagged as auth-transition-sensitive. Do not omit it (missing → `422`).

- **`timezone` default is model-dependent:**
  - `CreateScheduleRequest.timezone` default = **`UTC`**.
  - `ScheduleData.timezone` default = **`Asia/Shanghai`**.
  Never assume a single global default. A schedule created without `timezone` via the create
  endpoint is `UTC`, even though the persisted-data model's schema default is `Asia/Shanghai`.

- **Field name is `enabled`, not `enable`.** The narrative descriptions for the update endpoint
  mention `enable`/`enable=False`, but the real JSON field is `enabled` (boolean). Use
  `enabled` in request bodies.

- **`enabled=false` ≠ delete.** PATCH with `enabled=false` only unregisters the APScheduler job
  and keeps the record; DELETE permanently removes the record *and* unregisters the job. Use
  the right one.

- **Changing `cron_expression` or `timezone` reschedules immediately** via APScheduler — there
  is no separate "apply" step.

- **PATCH cannot change `agent_id` or `chat_model_config`.** `UpdateScheduleRequest` only
  exposes `name`, `description`, `cron_expression`, `timezone`, `enabled`, `stateful`,
  `permission_mode`. To change the agent or model binding you must delete and recreate.

- **`permission_mode` defaults to `dont_ask` for schedules** because no user is present to
  answer permission prompts; `dont_ask` converts all ASK decisions to DENY. Do NOT default
  scheduled tasks to `default`/`bypass` blindly — `bypass` allows all operations with no checks
  (sandbox/trusted only), `default` will effectively deny ASK-gated actions because nobody can
  approve them. For unattended execution `dont_ask` is the intended mode.

- **`cron_expression` is a standard 5-field cron string** (e.g. `'0 9 * * 1-5'`), evaluated in
  the configured IANA `timezone`. Not a 6-field (seconds) cron.

- **`ChatModelConfig` requires all four fields** (`type`, `credential_id`, `model`,
  `parameters`). `parameters` is required even if empty (`{}`).

- **Status codes are exact:** Create → `201`, Update → `200`, List → `200`,
  Sessions → `200`, Delete → `204` (no body). Treat anything else as an error.

- **`404` semantics differ:** On Create, `404` means the *agent* does not exist. On
  Update/Delete/Sessions, `404` means the *schedule* does not exist.

- **`ScheduleRecord.id` description is mislabeled** in the spec as "Unique identifier for the
  credential" — it is the schedule record's id, not a credential id. (Documentation artifact;
  do not infer a credential relationship from it.)

- **No documented pagination query params** on `GET /schedule/` even though the return is
  described as a "Paginated list." The response includes `total`, but no `limit`/`offset`/
  `page` parameters are documented. Do not assume pagination params exist.

- **Sessions models are summarized, not verbatim.** The `GET .../sessions` page is rendered as
  prose (no raw OpenAPI YAML), so `SessionRecord` / `SessionConfig` field types and defaults
  here are best-effort from that prose. `SessionRecord.source` enum values are `user` |
  `schedule` (lowercase), distinct from `ScheduleSource`'s `USER` | `AGENT` (uppercase).

- **Version:** OpenAPI `info.version` is `2.0.1`; spec path `/v2/deploy/openapi.json`. Installed
  package is agentscope 1.0.20 — the v2 docs/API correspond to this deploy server.
