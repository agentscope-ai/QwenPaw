# REST API: Chat & Model

> Source:
> - https://docs.agentscope.io/api-reference/chat/trigger-a-chat-run-fire-and-forget.md
> - https://docs.agentscope.io/api-reference/model/list-all-candidate-models-under-the-given-credential-type.md
>
> Library: agentscope 1.0.20 — docs published under AgentScope v2 (OpenAPI `title: AgentScope`, `version: 2.0.1`).
> OpenAPI document path declared in both pages: `/v2/deploy/openapi.json`.

## Overview

This unit covers two REST endpoints of the AgentScope v2 **deploy** server:

1. **`POST /chat/`** — *Trigger a chat run (fire-and-forget)*. Schedules a background chat
   run for a session. The HTTP response only confirms scheduling; the actual events
   (model output, tool calls, etc.) are streamed separately over the session's SSE stream
   (`GET /sessions/{session_id}/stream`). The caller does **not** receive run events in
   this endpoint's response body.

2. **`GET /model/`** — *List all candidate models under the given credential type*. Returns
   the candidate chat models available for a given `provider` (credential type), each
   described by a `ModelCard`.

Both endpoints share the standard FastAPI/OpenAPI 3.1.0 error envelope
(`HTTPValidationError` / `ValidationError`) and a `404 Not found` response.

---

## API Reference

### `POST /chat/` — Trigger a chat run (fire-and-forget)

- **operationId:** `chat_chat__post`
- **Tag:** `chat`
- **Summary:** Trigger a chat run (fire-and-forget)

**Description (verbatim intent):**
Trigger a chat run for the specified session. The run executes as a **background task**.
Events produced during the run are published to the message bus and delivered to any active
`GET /sessions/{session_id}/stream` SSE subscriber. The caller does **not** receive events
from this endpoint's response body.

Accepts the same `input` payloads as before:
- `Msg` / `list[Msg]`: new user message(s).
- `UserConfirmResultEvent` / `ExternalExecutionResultEvent`: resume a paused tool call
  (human-in-the-loop).
- `None`: continue from current state.

**Handler signature (from docs):**
```
chat(request: ChatRequest, user_id: str, chat_service: ChatService) -> ChatTriggerResponse
```
- `request` (`ChatRequest`): JSON body with `agent_id`, `session_id`, and `input`.
- `user_id` (`str`): Injected user id (supplied via the `x-user-id` header — see params).
- `chat_service` (`ChatService`): Injected application-wide chat service (dependency, not a
  client-supplied value).

**Parameters (header):**

| Name | In | Required | Type | Description |
|------|-----|----------|------|-------------|
| `x-user-id` | header | yes | string | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body:** required, `application/json`, schema `ChatRequest`.

**Responses:**

| Status | Description | Schema |
|--------|-------------|--------|
| `200` | Successful Response | `ChatTriggerResponse` |
| `404` | Not found | — |
| `422` | Validation Error | `HTTPValidationError` |

**Returns:** `ChatTriggerResponse` — confirms the run was scheduled. Events arrive separately
via the session's SSE stream endpoint.

---

### `GET /model/` — List all candidate models under the given credential type

- **operationId:** `list_models_model__get`
- **Tag:** `model`
- **Summary:** List all candidate models under the given credential type

**Description (verbatim intent):**
Return all candidate models under the given credential type.
- `body (ListModelsRequest)`: The request body. *(Doc note: the docstring references a
  `ListModelsRequest` body, but the actual OpenAPI operation declares NO request body — the
  only input is the required `provider` query parameter. See Gotchas.)*

**Returns:** `ListModelsResponse` — the response body.

**Parameters (query):**

| Name | In | Required | Type | Description |
|------|-----|----------|------|-------------|
| `provider` | query | yes | string | The credential type / provider whose candidate models are listed. (title: "Provider") |

**Responses:**

| Status | Description | Schema |
|--------|-------------|--------|
| `200` | Successful Response | `ListModelsResponse` |
| `404` | Not found | — |
| `422` | Validation Error | `HTTPValidationError` |

---

## Schemas

### `ChatRequest` (request body for `POST /chat/`)

Description: "Request body for the chat endpoint."

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `agent_id` | string | yes | — | Agent ID for the chat endpoint. |
| `session_id` | string | yes | — | The session to send the message to. |
| `input` | `Msg` \| `list[Msg]` \| `UserConfirmResultEvent` \| `ExternalExecutionResultEvent` \| `null` | yes | — | The input message(s), or agent event, or None. **Note:** `input` is a required field even though `null` is a valid value — you must include the key. |

### `ChatTriggerResponse` (response for `POST /chat/`)

Description: "Response body for the fire-and-forget chat trigger. Confirms that the chat run
was scheduled. Events produced by the run arrive separately via the session's SSE stream
endpoint."

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `status` | string | no | `"started"` | Always `"started"` when the trigger succeeded. |
| `session_id` | string | yes | — | Echo of the session id the run was started for. |

### `ListModelsResponse` (response for `GET /model/`)

Description: "List the candidate models response."

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `models` | array of `ModelCard` | yes | The candidate models. |
| `total` | integer | yes | The total number of candidates. |

### `ModelCard`

Description: "The model card class."

| Field | Type | Required | Default | Constraints | Description |
|-------|------|----------|---------|-------------|-------------|
| `type` | string | no | `"chat_model"` | const `chat_model` | Discriminator; always `chat_model`. |
| `name` | string | yes | — | — | The name of the model. |
| `label` | string | yes | — | — | The model label. |
| `status` | string enum | yes | — | one of `active`, `deprecated`, `sunset` | The model status. |
| `deprecated_at` | string (date-time) \| null | no | — | format `date-time` | The model deprecation date and time. |
| `input_types` | array of string | no | `["text/plain"]` | — | The supported model input types. |
| `output_types` | array of string | no | `["text/plain"]` | — | The supported model output types. |
| `context_size` | integer | yes | — | exclusiveMinimum 0 (> 0) | The context size. |
| `output_size` | integer | yes | — | exclusiveMinimum 0 (> 0) | Max output tokens. |
| `parameter_schema` | object (free-form, additionalProperties true) | yes | — | — | Parameter schema for the model. |
| `parameters_overrides` | object → object (map of maps, additionalProperties true) | yes | — | — | Per-key parameter overrides. |

### `Msg` (used in `ChatRequest.input`)

Description: "The message class in AgentScope, responsible for information storage and
transmission among different agents."

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Sender name. |
| `content` | array of (`TextBlock` \| `ThinkingBlock` \| `HintBlock` \| `ToolCallBlock` \| `ToolResultBlock` \| `DataBlock`) | yes | Message content blocks. |
| `role` | string enum (`user`, `assistant`, `system`) | yes | Message role. |
| `id` | string | no | Message id. |
| `metadata` | object (additionalProperties true) | no | Arbitrary metadata. |
| `created_at` | string | no | Creation timestamp. |
| `finished_at` | string \| null | no | Finish timestamp. |
| `usage` | `Usage` \| null | no | Token usage info. |

### `UserConfirmResultEvent` (resume a paused tool call — HITL)

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | no | — | Event id. |
| `created_at` | string | no | — | Creation timestamp. |
| `type` | string | no | `USER_CONFIRM_RESULT` | const `USER_CONFIRM_RESULT`. |
| `reply_id` | string | yes | — | Id of the reply being confirmed. |
| `confirm_results` | array of `ConfirmResult` | yes | — | The confirmation results. |

### `ExternalExecutionResultEvent` (resume a paused tool call — HITL)

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | no | — | Event id. |
| `created_at` | string | no | — | Creation timestamp. |
| `type` | string | no | `EXTERNAL_EXECUTION_RESULT` | const `EXTERNAL_EXECUTION_RESULT`. |
| `reply_id` | string | yes | — | Id of the reply being resumed. |
| `execution_results` | array of `ToolResultBlock` | yes | — | The external execution results. |

### `ConfirmResult`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `confirmed` | boolean | yes | Whether the tool call was confirmed. |
| `tool_call` | `ToolCallBlock` | yes | The tool call being confirmed. |
| `rules` | array of `PermissionRule` \| null | no | Optional permission rules to record. |

### Content blocks

**`TextBlock`** — "The text block."

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `type` | string const `text` | no | `text` |
| `text` | string | yes | — |
| `id` | string | no | — |

**`ThinkingBlock`** — "The thinking block." Allows extra provider-specific fields (e.g.
Anthropic's `signature`) via `extra="allow"` (`additionalProperties: true`).

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `type` | string const `thinking` | no | `thinking` |
| `thinking` | string | yes | — |
| `id` | string | no | — |

**`HintBlock`** — Instructions/hints to the LLM during the reasoning-acting loop; converted
into a user message when passed to the LLM API. `hint` may be a plain string or a list of
`TextBlock`/`DataBlock` (multimodal).

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `type` | string const `hint` | no | `hint` |
| `hint` | string \| array of (`TextBlock` \| `DataBlock`) | yes | — |
| `id` | string | no | — |
| `source` | string \| null | no | — |

**`ToolCallBlock`** — "The tool call block." Allows extra provider-specific fields (e.g. the
OpenAI Responses API's `call_id`) via `extra="allow"` (`additionalProperties: true`).

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `type` | string const `tool_call` | no | `tool_call` |
| `id` | string | yes | — |
| `name` | string | yes | — |
| `input` | string | yes | — |
| `state` | `ToolCallState` | no | `pending` |
| `suggested_rules` | array of `PermissionRule` | no | — |

**`ToolResultBlock`** — "The tool result block."

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `type` | string const `tool_result` | no | `tool_result` |
| `id` | string | yes | — |
| `name` | string | yes | — |
| `output` | string \| array of (`TextBlock` \| `DataBlock`) | yes | — |
| `state` | `ToolResultState` | no | `running` |

**`DataBlock`** — "The data block for binary content (images, audio, video, etc.)."

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `type` | string const `data` | no | `data` |
| `id` | string | no | — |
| `source` | `Base64Source` \| `URLSource` | yes | — |
| `name` | string \| null | no | — |

**`Base64Source`** — "The base64 source."

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `type` | string const `base64` | no | `base64` |
| `data` | string | yes | — |
| `media_type` | string | yes | — |

**`URLSource`** — "The URL source."

| Field | Type | Required | Default | Constraints |
|-------|------|----------|---------|-------------|
| `type` | string const `url` | no | `url` | — |
| `url` | string | yes | — | minLength 1, format uri |
| `media_type` | string | yes | — | — |

**`Usage`** — "The token usage information of a message."

| Field | Type | Required |
|-------|------|----------|
| `input_tokens` | integer | yes |
| `output_tokens` | integer | yes |

### `PermissionRule`

Description: "Permission rule for tool usage. A permission rule defines whether a specific
tool or tool operation should be allowed, denied, or require user confirmation."
`rule_content` semantics depend on `tool_name`:
- For `"Bash"`: `rule_content` is a substring pattern matched against the command.
  Example: `rule_content="npm install"` matches `"npm install express"`.
- For `"Write"`/`"Read"`: `rule_content` is a glob pattern matched against file paths.
  Example: `rule_content="src/**"` matches `"src/main.py"`.
- For other tools: `rule_content` is a tool-specific filter pattern.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tool_name` | string | yes | Tool the rule applies to. |
| `rule_content` | string \| null | yes | Pattern (semantics depend on `tool_name`). |
| `behavior` | `PermissionBehavior` | yes | allow/deny/ask/passthrough. |
| `source` | string | yes | Where the rule came from. |

### Enums

**`ToolCallState`** — "The state of the tool call.": `pending`, `asking`, `allowed`, `submitted`, `finished`.

**`ToolResultState`** — "The tool result state.": `success`, `error`, `interrupted`, `denied`, `running`.

**`PermissionBehavior`** — "The behavior of permission.":
- `allow` — Allow the operation.
- `deny` — Deny the operation.
- `ask` — Ask the user for permission.
- `passthrough` — Let the permission engine continue with rule matching (used by tools to defer the decision to the engine).

**`ModelCard.status`** enum: `active`, `deprecated`, `sunset`.

### Error schemas (shared)

**`HTTPValidationError`**:

| Field | Type | Required |
|-------|------|----------|
| `detail` | array of `ValidationError` | no |

**`ValidationError`**:

| Field | Type | Required |
|-------|------|----------|
| `loc` | array of (string \| integer) | yes |
| `msg` | string | yes |
| `type` | string | yes |
| `input` | any | no |
| `ctx` | object | no |

---

## Configuration

| Option / field | Endpoint | Where | Type | Default | Controls |
|----------------|----------|-------|------|---------|----------|
| `x-user-id` | `POST /chat/` | request header (required) | string | — | Caller identity. Temporary header-based identity; to be replaced by JWT auth. |
| `agent_id` | `POST /chat/` | body | string | — | Which agent handles the run. |
| `session_id` | `POST /chat/` | body | string | — | Which session the run targets. |
| `input` | `POST /chat/` | body | Msg / list[Msg] / UserConfirmResultEvent / ExternalExecutionResultEvent / null | — | Drives run behavior: new message(s), HITL resume, or continue (`null`). |
| `provider` | `GET /model/` | query (required) | string | — | The credential type whose candidate models are returned. |
| `status` | `ChatTriggerResponse` | response | string | `"started"` | Scheduling confirmation marker. |
| `ModelCard.input_types` | `GET /model/` | response | array[string] | `["text/plain"]` | Supported input MIME types of the model. |
| `ModelCard.output_types` | `GET /model/` | response | array[string] | `["text/plain"]` | Supported output MIME types of the model. |
| `ModelCard.context_size` | `GET /model/` | response | integer (>0) | — | Model context window size. |
| `ModelCard.output_size` | `GET /model/` | response | integer (>0) | — | Max output tokens. |
| `ModelCard.parameter_schema` | `GET /model/` | response | object | — | Schema for the model's accepted parameters. |
| `ModelCard.parameters_overrides` | `GET /model/` | response | map of maps | — | Per-key parameter override definitions. |

---

## Usage Patterns

### Trigger a chat run with a new user message

```bash
curl -X POST 'https://<host>/v2/deploy/chat/' \
  -H 'Content-Type: application/json' \
  -H 'x-user-id: user_123' \
  -d '{
        "agent_id": "agent_abc",
        "session_id": "session_xyz",
        "input": {
          "name": "user",
          "role": "user",
          "content": [
            { "type": "text", "text": "Hello, what is the weather today?" }
          ]
        }
      }'
```

Successful `200` response:

```json
{
  "status": "started",
  "session_id": "session_xyz"
}
```

Then subscribe to events separately via the SSE stream:

```bash
curl -N 'https://<host>/v2/deploy/sessions/session_xyz/stream' \
  -H 'x-user-id: user_123'
```

### Continue from current state (input = null)

```json
{
  "agent_id": "agent_abc",
  "session_id": "session_xyz",
  "input": null
}
```

### Resume a paused tool call (human-in-the-loop confirm)

```json
{
  "agent_id": "agent_abc",
  "session_id": "session_xyz",
  "input": {
    "type": "USER_CONFIRM_RESULT",
    "reply_id": "reply_001",
    "confirm_results": [
      {
        "confirmed": true,
        "tool_call": {
          "type": "tool_call",
          "id": "call_1",
          "name": "Bash",
          "input": "npm install express"
        }
      }
    ]
  }
}
```

### Resume with an external execution result

```json
{
  "agent_id": "agent_abc",
  "session_id": "session_xyz",
  "input": {
    "type": "EXTERNAL_EXECUTION_RESULT",
    "reply_id": "reply_001",
    "execution_results": [
      {
        "type": "tool_result",
        "id": "call_1",
        "name": "Bash",
        "output": "added 50 packages",
        "state": "success"
      }
    ]
  }
}
```

### List candidate models for a provider

```bash
curl -X GET 'https://<host>/v2/deploy/model/?provider=<credential_type>' \
  -H 'Content-Type: application/json'
```

Successful `200` response:

```json
{
  "models": [
    {
      "type": "chat_model",
      "name": "some-model-name",
      "label": "Some Model",
      "status": "active",
      "deprecated_at": null,
      "input_types": ["text/plain"],
      "output_types": ["text/plain"],
      "context_size": 128000,
      "output_size": 4096,
      "parameter_schema": {},
      "parameters_overrides": {}
    }
  ],
  "total": 1
}
```

---

## Gotchas & Version Notes

- **Fire-and-forget — do NOT expect run output in the HTTP response.** `POST /chat/` returns
  only `{ "status": "started", "session_id": ... }`. All model output, tool calls, thinking,
  and tool results are delivered over the session SSE stream at
  `GET /sessions/{session_id}/stream`. Code that reads the model's reply from the `POST /chat/`
  response body is wrong. Subscribe to the stream before/after triggering.

- **`x-user-id` header is required on `POST /chat/`.** It is injected as the `user_id`
  parameter of the handler. Omitting it yields a validation error. This is a **temporary
  header-based identity** that the docs explicitly say "will be replaced by JWT auth" —
  treat it as transitional; do not hard-code reliance on the header for long-term auth.

- **`input` is a required key but accepts `null`.** In `ChatRequest`, `input` is listed in
  `required`, yet `null` is a valid value (meaning "continue from current state"). You must
  send the key; you may set it to `null`. Do not omit it.

- **`input` is polymorphic (anyOf), not a free dict.** It must be exactly one of: a single
  `Msg`, a `list[Msg]`, a `UserConfirmResultEvent`, an `ExternalExecutionResultEvent`, or
  `null`. The two event types are discriminated by their `type` const
  (`USER_CONFIRM_RESULT` / `EXTERNAL_EXECUTION_RESULT`). Use those exact const values.

- **`GET /model/` docstring vs. actual contract mismatch.** The page's prose says
  `body (ListModelsRequest): The request body`, but the OpenAPI operation `list_models_model__get`
  is a **GET with no request body** — the only declared input is the **required `provider`
  query parameter**. There is no `ListModelsRequest` schema in the document. Pass `provider`
  as a query string; do **not** send a JSON body to `GET /model/`. (Treat the docstring's
  `ListModelsRequest` mention as stale/internal.)

- **Model lifecycle status.** `ModelCard.status` is one of `active`, `deprecated`, `sunset`.
  When `status` is `deprecated` or `sunset`, `deprecated_at` may carry a date-time. Prefer
  `active` models; guard against selecting `sunset` models.

- **`ModelCard` numeric fields are strictly positive.** `context_size` and `output_size`
  use `exclusiveMinimum: 0` — they must be `> 0`. Zero or negative values are invalid.

- **`ModelCard.type` is always `chat_model`.** This endpoint lists chat models only (const
  discriminator `chat_model`). Default `input_types`/`output_types` are `["text/plain"]`.

- **Extensible blocks via `extra="allow"`.** `ThinkingBlock` and `ToolCallBlock` permit
  additional provider-specific fields (`additionalProperties: true`) — e.g. Anthropic's
  `signature` on thinking blocks, OpenAI Responses API's `call_id` on tool calls. Do not
  strip unknown fields when round-tripping these blocks.

- **`PermissionRule.rule_content` semantics depend on `tool_name`.** Bash → substring match
  on the command; Write/Read → glob match on file paths; other tools → tool-specific filter.
  Do not assume a single matching strategy across tools.

- **OpenAPI/version context.** Both pages declare `openapi: 3.1.0`, `info.title: AgentScope`,
  `info.version: 2.0.1`, served under the `/v2/deploy/openapi.json` document. Endpoint paths
  as documented are `/chat/` and `/model/` (note trailing slashes). The installed package is
  agentscope 1.0.20; these are the v2 deploy-server REST contracts.
