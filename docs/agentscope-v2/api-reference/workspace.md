# REST API: Workspace (MCP & Skills)

> Source:
> - https://docs.agentscope.io/api-reference/workspace/add-mcp.md
> - https://docs.agentscope.io/api-reference/workspace/list-mcps.md
> - https://docs.agentscope.io/api-reference/workspace/remove-mcp.md
> - https://docs.agentscope.io/api-reference/workspace/add-skill.md
> - https://docs.agentscope.io/api-reference/workspace/list-skills.md
> - https://docs.agentscope.io/api-reference/workspace/remove-skill.md
>
> Documented for AgentScope v2 (installed library: agentscope 1.0.20). Docs live at docs.agentscope.io/v2.

## Overview

The Workspace REST API manages two kinds of resources attached to a **session's workspace**:

1. **MCP clients** — Model Context Protocol servers/clients connected to a session, each exposing a set of tools. Configured via either a STDIO transport (`stdio_mcp`) or an HTTP transport (`http_mcp`).
2. **Skills** — named, markdown-described capabilities added to a session's workspace from a filesystem path.

All endpoints are **session-scoped** and **agent-scoped**: every call requires both `agent_id` and `session_id` as **query parameters**, plus an `x-user-id` **header** that carries the caller's identity.

> IMPORTANT identity note (applies to ALL six endpoints): `x-user-id` is described in the spec as
> *"Caller's user ID. Temporary header-based identity; will be replaced by JWT auth."*
> Treat header-based identity as **temporary**. Code that hardcodes `x-user-id` should be flagged as
> a future migration target to JWT-based auth.

Base path for all endpoints: `/workspace`

| Method | Path                              | Purpose                                            |
|--------|-----------------------------------|----------------------------------------------------|
| POST   | `/workspace/mcp`                  | Add an MCP client to the session workspace         |
| GET    | `/workspace/mcp`                  | List MCP clients with live tools + health status   |
| DELETE | `/workspace/mcp/{mcp_name}`       | Remove an MCP client by name                       |
| POST   | `/workspace/skill`                | Add a skill from a filesystem path                 |
| GET    | `/workspace/skill`                | List all skills in the session workspace           |
| DELETE | `/workspace/skill/{skill_name}`   | Remove a skill by name                             |

---

## API Reference

### POST /workspace/mcp — Add MCP

Adds an MCP client to a session's workspace.

**Signature**

```
POST /workspace/mcp?agent_id={agent_id}&session_id={session_id}
Header: x-user-id: {user_id}
Content-Type: application/json
Body: MCPClient
```

**Parameters**

| Name         | In     | Type    | Required | Default | Meaning |
|--------------|--------|---------|----------|---------|---------|
| `agent_id`   | query  | string  | yes      | —       | The agent identifier |
| `session_id` | query  | string  | yes      | —       | The session identifier |
| `x-user-id`  | header | string  | yes      | —       | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body — `MCPClient` object** (`Content-Type: application/json`)

| Field               | Type                                  | Required | Default | Meaning |
|---------------------|---------------------------------------|----------|---------|---------|
| `name`              | string                                | yes      | —       | The MCP name |
| `is_stateful`       | boolean                               | yes      | —       | Whether this is a stateful connection that requires explicit `connect()` and `close()`. **STDIO MCP must be stateful.** |
| `mcp_config`        | `StdioMCPConfig` \| `HttpMCPConfig`   | yes      | —       | Transport configuration (see Configuration section) |
| `enable_tools`      | array of strings                      | no       | —       | Allowlist of tool names to enable |
| `disable_tools`     | array of strings                      | no       | —       | Denylist of tool names to disable |
| `execution_timeout` | number                                | no       | —       | Tool execution timeout |

**Returns**

| Status | Body | Meaning |
|--------|------|---------|
| 201 | empty schema | Successful Response (MCP added) |
| 422 | `HTTPValidationError` | Validation Error |

---

### GET /workspace/mcp — List MCPs

Returns all MCP clients **with live tool list and health status**.

**Signature**

```
GET /workspace/mcp?agent_id={agent_id}&session_id={session_id}
Header: x-user-id: {user_id}
```

**Parameters**

| Name         | In     | Type    | Required | Meaning |
|--------------|--------|---------|----------|---------|
| `agent_id`   | query  | string  | yes      | Agent identifier |
| `session_id` | query  | string  | yes      | Session identifier |
| `x-user-id`  | header | string  | yes      | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns**

| Status | Body | Meaning |
|--------|------|---------|
| 200 | array of `MCPClientStatus` | Successful Response |
| 422 | `HTTPValidationError` | Validation Error |

**`MCPClientStatus` schema** (extends the `MCPClient` shape with health/tool fields)

Required fields: `name`, `is_stateful`, `mcp_config`.

| Field               | Type                                | Default | Meaning |
|---------------------|-------------------------------------|---------|---------|
| `name`              | string                              | —       | MCP identifier |
| `is_stateful`       | boolean                             | —       | Whether connection requires explicit connect/close |
| `mcp_config`        | `StdioMCPConfig` \| `HttpMCPConfig` | —       | Transport configuration |
| `enable_tools`      | array of strings (optional)         | —       | Enabled tool allowlist |
| `disable_tools`     | array of strings (optional)         | —       | Disabled tool denylist |
| `execution_timeout` | number (optional)                   | —       | Tool execution timeout |
| `is_healthy`        | boolean                             | `false` | Live health status of the MCP client |
| `tools`             | array of `ToolInfo`                 | —       | Live list of tools exposed by the MCP client |

---

### DELETE /workspace/mcp/{mcp_name} — Remove MCP

Removes an MCP client from the active session's workspace using its name identifier.

**Signature**

```
DELETE /workspace/mcp/{mcp_name}?agent_id={agent_id}&session_id={session_id}
Header: x-user-id: {user_id}
```

**Parameters**

| Name         | In     | Type    | Required | Meaning |
|--------------|--------|---------|----------|---------|
| `mcp_name`   | path   | string  | yes      | The name identifier of the MCP client to remove |
| `agent_id`   | query  | string  | yes      | The agent identifier |
| `session_id` | query  | string  | yes      | The session identifier |
| `x-user-id`  | header | string  | yes      | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns**

| Status | Body | Meaning |
|--------|------|---------|
| 204 | (no content) | Successful Response (MCP removed) |
| 422 | `HTTPValidationError` | Validation Error |

> Note: success is **204 No Content** (not 200). Callers must not expect a response body.

---

### POST /workspace/skill — Add Skill

Adds a skill to the session's workspace **from the given path**.

**Signature**

```
POST /workspace/skill?agent_id={agent_id}&session_id={session_id}
Header: x-user-id: {user_id}
Content-Type: application/json
Body: AddSkillRequest
```

**Parameters**

| Name         | In     | Type    | Required | Meaning |
|--------------|--------|---------|----------|---------|
| `agent_id`   | query  | string  | yes      | The agent identifier |
| `session_id` | query  | string  | yes      | The session identifier |
| `x-user-id`  | header | string  | yes      | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body — `AddSkillRequest` object** (`Content-Type: application/json`)

| Field        | Type   | Required | Meaning |
|--------------|--------|----------|---------|
| `skill_path` | string | yes      | The file system location of the skill to add |

**Returns**

| Status | Body | Meaning |
|--------|------|---------|
| 201 | empty JSON object `{}` | Successful operation (skill added) |
| 422 | `HTTPValidationError` | Validation error (location, message, error type, input, context) |

---

### GET /workspace/skill — List Skills

Returns all skills available in the session's workspace.

**Signature**

```
GET /workspace/skill?agent_id={agent_id}&session_id={session_id}
Header: x-user-id: {user_id}
```

**Parameters**

| Name         | In     | Type    | Required | Meaning |
|--------------|--------|---------|----------|---------|
| `agent_id`   | query  | string  | yes      | Agent Id |
| `session_id` | query  | string  | yes      | Session Id |
| `x-user-id`  | header | string  | yes      | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns**

| Status | Body | Meaning |
|--------|------|---------|
| 200 | array of `Skill` objects | Successful Response |
| 422 | `HTTPValidationError` | Validation Error |

**`Skill` schema** (all properties required)

| Field         | Type   | Required | Meaning |
|---------------|--------|----------|---------|
| `name`        | string | yes      | Skill name |
| `description` | string | yes      | Skill description |
| `dir`         | string | yes      | Directory of the skill |
| `markdown`    | string | yes      | Markdown content describing the skill |
| `updated_at`  | number | yes      | Last-updated timestamp |

---

### DELETE /workspace/skill/{skill_name} — Remove Skill

Removes a skill from the session's workspace **by name**.

**Signature**

```
DELETE /workspace/skill/{skill_name}?agent_id={agent_id}&session_id={session_id}
Header: x-user-id: {user_id}
```

**Parameters**

| Name         | In     | Type    | Required | Meaning |
|--------------|--------|---------|----------|---------|
| `skill_name` | path   | string  | yes      | The name of the skill to remove |
| `agent_id`   | query  | string  | yes      | Agent identifier |
| `session_id` | query  | string  | yes      | Session identifier |
| `x-user-id`  | header | string  | yes      | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns**

| Status | Body | Meaning |
|--------|------|---------|
| 204 | (no content) | Successful Response (skill removed) |
| 422 | `HTTPValidationError` | Validation Error |

> Note: success is **204 No Content** (not 200). No response body.

---

## Configuration

### MCP transport configs

`mcp_config` is a discriminated union selected by the `type` field. Exactly one of the two shapes must be supplied.

#### StdioMCPConfig (`type: "stdio_mcp"`)

| Field                     | Type                                       | Required | Default    | Controls |
|---------------------------|--------------------------------------------|----------|------------|----------|
| `type`                    | constant `"stdio_mcp"`                      | yes      | —          | Selects STDIO transport |
| `command`                 | string                                      | yes      | —          | Command to start the MCP server |
| `args`                    | array                                       | no       | —          | Command line arguments |
| `env`                     | object                                      | no       | —          | Environment variables for the server process |
| `cwd`                     | string / path                               | no       | —          | Working directory |
| `encoding_error_handler`  | enum: `strict` \| `ignore` \| `replace`     | no       | `strict`   | How to handle encoding errors on the STDIO stream |

> STDIO MCP **must** be stateful — i.e. the enclosing `MCPClient.is_stateful` must be `true` when using `StdioMCPConfig`.

#### HttpMCPConfig (`type: "http_mcp"`)

| Field      | Type    | Required | Default | Controls |
|------------|---------|----------|---------|----------|
| `type`     | constant `"http_mcp"` | yes | — | Selects HTTP transport |
| `url`      | string  | yes      | —       | MCP server URL |
| `headers`  | object  | no       | —       | Additional HTTP headers |
| `timeout`  | number  | no       | `30`    | HTTP/request timeout in seconds |

### MCPClient tool-filtering / runtime options

| Field               | Type             | Required | Default | Controls |
|---------------------|------------------|----------|---------|----------|
| `name`              | string           | yes      | —       | Logical name of the MCP client |
| `is_stateful`       | boolean          | yes      | —       | Stateful (`connect()`/`close()`) vs stateless connection |
| `enable_tools`      | array of strings | no       | —       | Allowlist of tools to expose |
| `disable_tools`     | array of strings | no       | —       | Denylist of tools to hide |
| `execution_timeout` | number           | no       | —       | Per-tool execution timeout |

### MCPClientStatus extra (read-only) fields

| Field        | Type                | Default | Controls |
|--------------|---------------------|---------|----------|
| `is_healthy` | boolean             | `false` | Live health of the MCP client |
| `tools`      | array of `ToolInfo` | —       | Live list of tools exposed |

---

## Usage Patterns

> The docs pages are OpenAPI-derived and do not contain end-to-end client code examples beyond the
> schemas above. The following request shapes are reconstructed directly from the documented method,
> path, parameters, and body schemas (no invented fields).

### Add a STDIO MCP client

```http
POST /workspace/mcp?agent_id=agent-123&session_id=sess-abc HTTP/1.1
x-user-id: user-42
Content-Type: application/json

{
  "name": "filesystem",
  "is_stateful": true,
  "mcp_config": {
    "type": "stdio_mcp",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"],
    "env": { "LOG_LEVEL": "info" },
    "cwd": "/data",
    "encoding_error_handler": "strict"
  },
  "enable_tools": ["read_file", "list_directory"],
  "execution_timeout": 60
}
```
Expected: `201` on success.

### Add an HTTP MCP client

```http
POST /workspace/mcp?agent_id=agent-123&session_id=sess-abc HTTP/1.1
x-user-id: user-42
Content-Type: application/json

{
  "name": "remote-tools",
  "is_stateful": false,
  "mcp_config": {
    "type": "http_mcp",
    "url": "https://mcp.example.com/sse",
    "headers": { "Authorization": "Bearer <token>" },
    "timeout": 30
  }
}
```

### List MCP clients (with health + live tools)

```http
GET /workspace/mcp?agent_id=agent-123&session_id=sess-abc HTTP/1.1
x-user-id: user-42
```
Returns `200` with an array of `MCPClientStatus` objects (each includes `is_healthy` and `tools`).

### Remove an MCP client

```http
DELETE /workspace/mcp/filesystem?agent_id=agent-123&session_id=sess-abc HTTP/1.1
x-user-id: user-42
```
Returns `204 No Content`.

### Add a skill from a path

```http
POST /workspace/skill?agent_id=agent-123&session_id=sess-abc HTTP/1.1
x-user-id: user-42
Content-Type: application/json

{
  "skill_path": "/workspace/skills/my-skill"
}
```
Returns `201` with empty body `{}`.

### List skills

```http
GET /workspace/skill?agent_id=agent-123&session_id=sess-abc HTTP/1.1
x-user-id: user-42
```
Returns `200` with an array of `Skill` objects:

```json
[
  {
    "name": "my-skill",
    "description": "Does a thing",
    "dir": "/workspace/skills/my-skill",
    "markdown": "# My Skill\n...",
    "updated_at": 1718000000
  }
]
```

### Remove a skill

```http
DELETE /workspace/skill/my-skill?agent_id=agent-123&session_id=sess-abc HTTP/1.1
x-user-id: user-42
```
Returns `204 No Content`.

---

## Gotchas & Version Notes

- **Identity header is temporary.** Every endpoint requires the `x-user-id` header, documented as
  *"Temporary header-based identity; will be replaced by JWT auth."* Code relying on `x-user-id`
  is a known future-migration point — do not treat it as the permanent auth mechanism.

- **`agent_id` and `session_id` are mandatory query params on EVERY call** (including DELETE/GET).
  Omitting either yields a `422` Validation Error. They are query parameters, **not** path or body fields.

- **STDIO MCP must be stateful.** When `mcp_config.type == "stdio_mcp"`, the parent `MCPClient.is_stateful`
  must be `true` (STDIO requires explicit `connect()`/`close()`). Setting `is_stateful: false` with a
  STDIO config is invalid. HTTP MCP may be stateless.

- **`is_stateful` is REQUIRED**, not inferred from the config type. It must be supplied explicitly in the body.

- **Success codes differ by verb:**
  - POST `/workspace/mcp` → **201** (empty body)
  - POST `/workspace/skill` → **201** (body is empty JSON object `{}`)
  - GET endpoints → **200** (array body)
  - DELETE endpoints → **204 No Content** (no body — do not parse a body)

- **`mcp_config` is a discriminated union on `type`.** Use `"stdio_mcp"` or `"http_mcp"` exactly;
  the wrong/missing `type` field will fail validation. STDIO uses `command`/`args`/`env`/`cwd`/
  `encoding_error_handler`; HTTP uses `url`/`headers`/`timeout`. Do **not** mix fields across the two.

- **Defaults to remember:** `HttpMCPConfig.timeout = 30` (seconds); `StdioMCPConfig.encoding_error_handler = "strict"`;
  `MCPClientStatus.is_healthy = false`. `execution_timeout`, `enable_tools`, `disable_tools` have no default (optional/unset).

- **`enable_tools` vs `disable_tools`.** Both are optional arrays of tool names; `enable_tools` acts as an
  allowlist and `disable_tools` as a denylist. The docs do not specify precedence when both are set —
  prefer using only one.

- **Skills are added by filesystem path** (`skill_path`), not by uploading content. The server reads the
  skill from `skill_path`; the listed `Skill` object then exposes `name`, `description`, `dir`,
  `markdown`, and `updated_at` (all required in responses).

- **Removal is by name, not by id/path.** MCP removal uses `{mcp_name}` (the `MCPClient.name`); skill
  removal uses `{skill_name}` (the `Skill.name`) — not `dir` or `skill_path`.

- **List MCPs returns live state.** GET `/workspace/mcp` returns `MCPClientStatus` (with `is_healthy`
  and live `tools`), which is a superset of the `MCPClient` you POSTed. Do not assume the response
  shape equals the request shape.

- **422 error shape** is the standard FastAPI `HTTPValidationError`: `{ "detail": [ ValidationError, ... ] }`
  where each `ValidationError` has required `loc` (array of string|int), `msg` (string), `type` (string),
  and optional `input` and `ctx` (object).

- **Version context:** documented against AgentScope v2 docs (installed `agentscope==1.0.20`). The v2 docs
  use the `/v2` doc tree; ensure code targets the v2 workspace API surface described here.
