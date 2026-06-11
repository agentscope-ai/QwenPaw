# REST API: Credential

> Source:
> - https://docs.agentscope.io/api-reference/credential/create-a-new-credential.md
> - https://docs.agentscope.io/api-reference/credential/update-a-credential.md
> - https://docs.agentscope.io/api-reference/credential/list-all-credentials.md
> - https://docs.agentscope.io/api-reference/credential/list-json-schemas-for-all-credential-types.md
> - https://docs.agentscope.io/api-reference/credential/delete-a-credential.md
>
> Documented against: AgentScope REST API (OpenAPI 3.1.0), API title "AgentScope", API version **2.0.1**.
> Installed library context: agentscope 1.0.20 / docs.agentscope.io/v2.

## Overview

The **Credential** unit of the AgentScope v2 REST API manages stored credential
records (for example API keys) on a per-user basis. A credential is an opaque
JSON payload (the `data` object) that the server persists and tags with a
server-assigned identifier, the owning `user_id`, and creation/update
timestamps.

All endpoints live under the `/credential` path prefix and are tagged
`credential`. Authentication is currently performed via a **temporary
header-based identity**: every request carries an `x-user-id` header that
identifies the caller. The docs explicitly note this is provisional and "will be
replaced by JWT auth." Credentials are scoped to the owning user — operations on
a credential that does not exist *or does not belong to the authenticated user*
return `404`.

The unit exposes five operations:

| Operation | Method | Path | Success |
|-----------|--------|------|---------|
| Create a new credential | POST | `/credential/` | 201 |
| List all credentials | GET | `/credential/` | 200 |
| List JSON schemas for all credential types | GET | `/credential/schemas` | 200 |
| Update a credential | PATCH | `/credential/{credential_id}` | 200 |
| Delete a credential | DELETE | `/credential/{credential_id}` | 204 |

## API Reference

### POST `/credential/` — Create a New Credential

Stores a new credential and returns a server-generated identifier for later
reference.

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body** — `Content-Type: application/json`, schema `CreateCredentialRequest`

| Field | Type | Required | Default | Meaning |
|-------|------|----------|---------|---------|
| `data` | object (additionalProperties allowed) | yes | — | Credential payload (e.g. API keys). No specific sub-fields are mandated; accepts any key/value pairs. |

**Returns** — `201`, schema `CreateCredentialResponse`

| Field | Type | Meaning |
|-------|------|---------|
| `credential_id` | string (required) | Server-assigned credential identifier. |

**Other responses**

- `404 Not Found` — Resource not found.
- `422 Validation Error` — schema `HTTPValidationError` (array of `ValidationError`).

**Example**

```bash
curl -X POST https://<host>/credential/ \
  -H "x-user-id: user-123" \
  -H "Content-Type: application/json" \
  -d '{ "data": { "api_key": "sk-..." } }'
```

```json
// 201 Created
{ "credential_id": "cred_abc123" }
```

### GET `/credential/` — List All Credentials

Returns all credential records belonging to the authenticated user.

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Query parameters** — none.

**Returns** — `200`, schema `ListCredentialsResponse`

| Field | Type | Meaning |
|-------|------|---------|
| `credentials` | array of `CredentialRecord` | The user's credential records. |
| `total` | integer | Total number of credentials. |

`CredentialRecord` shape — see [Schemas](#credentialrecord-schema) below.

**Other responses**

- `404` — Not found.
- `422` — Validation Error.

**Example**

```bash
curl https://<host>/credential/ -H "x-user-id: user-123"
```

```json
// 200 OK
{
  "credentials": [
    {
      "id": "cred_abc123",
      "user_id": "user-123",
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z",
      "data": { "api_key": "sk-..." }
    }
  ],
  "total": 1
}
```

### GET `/credential/schemas` — List JSON Schemas for All Credential Types

Returns JSON schemas for all registered credential types. Used by the frontend
to render credential creation forms dynamically.

- **Operation ID:** `list_credential_schemas_credential_schemas_get`
- **Tags:** `credential`

**Headers** — none explicitly documented.

**Query parameters** — none.

**Returns** — `200`, schema `ListCredentialSchemasResponse`

```json
{
  "type": "object",
  "required": ["schemas"],
  "properties": {
    "schemas": {
      "type": "array",
      "title": "Schemas",
      "description": "JSON schemas for all registered credential types.",
      "items": { "type": "object", "additionalProperties": true }
    }
  }
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `schemas` | array of object (each an arbitrary JSON-schema object, `additionalProperties: true`) | JSON schemas for all registered credential types. |

**Other responses**

- `404` — Not found.

**Example**

```bash
curl https://<host>/credential/schemas
```

### PATCH `/credential/{credential_id}` — Update a Credential

Replaces the stored payload of an existing credential with a new one.

**Path parameters**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `credential_id` | string | yes | Identifier of the credential to update. |

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Request body** — `Content-Type: application/json`, schema `UpdateCredentialRequest`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `data` | object (additionalProperties allowed) | yes | New credential payload. |

**Returns** — `200`, schema `CredentialRecord`

See [`CredentialRecord`](#credentialrecord-schema) below.

**Other responses**

- `404` — Not Found. Returned if the credential does not exist or doesn't belong to the authenticated user.
- `422` — Validation Error (schema `HTTPValidationError`).

**Example**

```bash
curl -X PATCH https://<host>/credential/cred_abc123 \
  -H "x-user-id: user-123" \
  -H "Content-Type: application/json" \
  -d '{ "data": { "api_key": "sk-new-..." } }'
```

```json
// 200 OK
{
  "id": "cred_abc123",
  "user_id": "user-123",
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-06-10T12:00:00Z",
  "data": { "api_key": "sk-new-..." }
}
```

### DELETE `/credential/{credential_id}` — Delete a Credential

Permanently deletes a credential belonging to the authenticated user.

**Path parameters**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `credential_id` | string | yes | The credential identifier to delete. |

**Headers**

| Header | Type | Required | Meaning |
|--------|------|----------|---------|
| `x-user-id` | string | yes | Caller's user ID. Temporary header-based identity; will be replaced by JWT auth. |

**Returns** — `204` No Content (empty body on success).

**Other responses**

- `404` — Not found. Raised if the credential does not exist or does not belong to the authenticated user.
- `422` — Validation Error.

**Example**

```bash
curl -X DELETE https://<host>/credential/cred_abc123 \
  -H "x-user-id: user-123"
# -> 204 No Content
```

## Schemas

### `CredentialRecord` schema

Returned by GET `/credential/` (inside `credentials[]`) and by PATCH `/credential/{credential_id}`.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `id` | string | — | Unique identifier for the credential. |
| `user_id` | string | — | User identifier (owner). |
| `created_at` | string (date-time) | — | Creation timestamp. |
| `updated_at` | string (date-time) | — | Update timestamp. |
| `data` | object (additionalProperties allowed) | **yes** | Credential payload. |

### `CreateCredentialRequest`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `data` | object | yes | Credential payload (e.g. API keys). |

### `CreateCredentialResponse`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `credential_id` | string | yes | Server-assigned credential identifier. |

### `UpdateCredentialRequest`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `data` | object | yes | New credential payload. |

### `ListCredentialsResponse`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `credentials` | array of `CredentialRecord` | yes | The user's credential records. |
| `total` | integer | yes | Total number of credentials. |

### `ListCredentialSchemasResponse`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `schemas` | array of object (each `additionalProperties: true`) | yes | JSON schemas for all registered credential types. |

### `HTTPValidationError` / `ValidationError`

Standard FastAPI validation error envelope used on `422` responses:

```json
{
  "detail": [
    {
      "loc": ["string or integer"],
      "msg": "string",
      "type": "string",
      "input": "any",
      "ctx": {}
    }
  ]
}
```

Each `ValidationError` carries: `loc` (location), `msg` (message), `type`,
`input`, and `ctx` (context) fields.

## Configuration

| Option / field | Where | Type | Required | Controls |
|----------------|-------|------|----------|----------|
| `x-user-id` | request header | string | yes (all data endpoints; not documented for `/credential/schemas`) | Identifies the caller/owner. Temporary; to be replaced by JWT auth. |
| `credential_id` | path param | string | yes (update, delete) | Targets a specific credential record. |
| `data` | request body | object (free-form) | yes (create, update) | The credential payload itself (e.g. API keys); accepts arbitrary key/value pairs. |
| `Content-Type: application/json` | request header | string | yes (create, update) | Body encoding. |

**Backend (FastAPI) injected dependencies** noted in the docs (not client-facing
configuration, but relevant for the guardian): handlers receive `user_id: str`
(injected authenticated user ID) and `storage: StorageBase` (injected storage
backend). Update additionally receives `body: UpdateCredentialRequest`; delete
and update receive `credential_id: str`.

## Usage Patterns

**1. Create then reference by returned id**

```bash
# create
curl -X POST https://<host>/credential/ \
  -H "x-user-id: user-123" -H "Content-Type: application/json" \
  -d '{ "data": { "openai_api_key": "sk-..." } }'
# -> { "credential_id": "cred_abc123" }
```

**2. Discover available credential types for dynamic forms**

```bash
# Frontend calls this to render credential-creation forms dynamically.
curl https://<host>/credential/schemas
# -> { "schemas": [ { ...json-schema... }, ... ] }
```

**3. Rotate a key (update)**

```bash
curl -X PATCH https://<host>/credential/cred_abc123 \
  -H "x-user-id: user-123" -H "Content-Type: application/json" \
  -d '{ "data": { "openai_api_key": "sk-rotated-..." } }'
# -> full CredentialRecord with refreshed updated_at
```

**4. List then delete**

```bash
curl https://<host>/credential/ -H "x-user-id: user-123"
curl -X DELETE https://<host>/credential/cred_abc123 -H "x-user-id: user-123"
# -> 204
```

## Gotchas & Version Notes

- **Trailing slash matters.** Create and list use `/credential/` (with trailing
  slash). The schemas endpoint is `/credential/schemas`; per-record operations
  are `/credential/{credential_id}` (no trailing slash). Do not normalize these
  away.
- **`x-user-id` is a temporary auth mechanism.** The docs state on every data
  endpoint: "Temporary header-based identity; will be replaced by JWT auth." Code
  that hard-codes the `x-user-id` header is using the current (provisional)
  contract — expect a future migration to JWT/Authorization-bearer auth. Treat
  reliance on `x-user-id` as a known migration risk.
- **Ownership-scoped 404.** Update and delete return `404` not only when the
  credential is missing but also when it exists yet belongs to another user.
  Never assume `404` means "never existed"; it can mean "not yours." There is no
  separate `403`.
- **Correct verb per operation:** use **POST** to create, **GET** to list,
  **PATCH** (not PUT) to update, **DELETE** to remove. PATCH replaces the `data`
  payload ("New credential payload").
- **Distinct success codes:** create returns **201**, list/schemas/update return
  **200**, delete returns **204** (no body). Do not expect a body from a
  successful delete, and do not expect `200` from create.
- **`data` is required and free-form.** Both create and update require a top-level
  `data` object; the credential fields go *inside* `data`, not at the top level.
  Sending the payload fields at the request root (instead of nested under `data`)
  is a `422`.
- **Create returns only `credential_id`**, not a full `CredentialRecord`. To get
  timestamps/`user_id`/`data` back you must list or update. Update returns the
  full `CredentialRecord`.
- **`/credential/schemas` has no documented `x-user-id` requirement** and no
  query params; it is intended for frontends to render forms. Don't add auth
  headers as if they were required by the contract (though sending one is
  harmless).
- **API version is 2.0.1** (OpenAPI 3.1.0), even though the installed Python
  package reports `agentscope 1.0.20`. These version numbers refer to different
  artifacts (REST service vs. Python library); do not conflate them.
- **No pagination parameters** are documented on list; it returns all of the
  user's credentials plus a `total` count.
