# Deploy: Agent Service

> Source: https://docs.agentscope.io/v2/deploy/agent-service.md

## Overview

Agent Service is AgentScope's FastAPI-based hosting layer that transforms agents into a **multi-tenant, multi-session HTTP service**. It manages everything surrounding agent execution: request routing, session lifecycle, persistence, scheduling, and tool orchestration.

### Core Capabilities

- **Agent teams**: Leader agents spawn and coordinate worker agents through built-in team tools.
- **Workspace management**: Pluggable isolation strategies (per-agent, per-session, per-user).
- **Background task offloading**: Long-running tool calls execute asynchronously.
- **Cron scheduling**: Time-based agent execution with stateful/stateless sessions.
- **Session replay**: Late-joining clients receive buffered history before live events.
- **Protocol adaptation**: Middleware-based conversion to external protocols (AG-UI, A2A).

### Quick Start

The repository includes ready-to-use examples:

```bash
git clone https://github.com/agentscope-ai/agentscope.git
cd agentscope/examples/agent_service
python main.py  # Runs on http://localhost:8000
```

In another terminal, start the web UI:

```bash
cd examples/web_ui
pnpm install && pnpm dev
```

### Resource Model

The service manages seven resource types scoped to `user_id`:

| Resource | Purpose |
|----------|---------|
| **Credential** | Model provider connection config (API keys, settings) |
| **Agent** | Reusable template with display name, system prompt, runtime config |
| **Session** | Active conversation unit, carries agent state and message transcript |
| **Workspace** | Agent runtime environment (filesystem, MCP clients, skills) |
| **Schedule** | Cron-based agent execution with execution history |
| **MessageBus** | Redis-backed runtime layer for session coordination |
| **Messages** | Persisted conversation transcript with pagination |

---

## API Reference

### `create_app(...)`

Factory function that builds the FastAPI application hosting the agent service.

```python
from agentscope.app import create_app
from agentscope.app.storage import RedisStorage
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.workspace_manager import LocalWorkspaceManager

storage = RedisStorage(host="localhost", port=6379)
message_bus = RedisMessageBus(host="localhost", port=6379)
workspace_manager = LocalWorkspaceManager(basedir="/data/workspaces", ttl=3600.0)

app = create_app(
    storage=storage,
    message_bus=message_bus,
    workspace_manager=workspace_manager,
)
```

**Parameters:**

| Parameter | Type | Default | Required | Meaning |
|-----------|------|---------|----------|---------|
| `storage` | `StorageBase` | — | Yes | Persistence layer for all records |
| `message_bus` | `MessageBus` | — | Yes | Redis-backed coordination primitives |
| `workspace_manager` | `WorkspaceManagerBase` | — | Yes | Workspace lifecycle management |
| `extra_credentials` | `list[Type[CredentialBase]]` | — | No | Additional credential types |
| `extra_middlewares` | `list[Middleware]` | — | No | ASGI middlewares |
| `extra_agent_middlewares` | `AgentMiddlewareFactory` | — | No | Per-agent middlewares |
| `extra_agent_tools` | `AgentToolFactory` | — | No | Per-agent tools |
| `sub_agent_templates` | `list[SubAgentTemplate]` | — | No | Team sub-agent blueprints |
| `title` | `str` | `"AgentScope"` | No | OpenAPI title |
| `version` | `str` | `"2.0.0"` | No | API version |

**Returns:** A FastAPI application instance.

---

### REST Endpoints

| Category | Method + Path | Purpose |
|----------|---------------|---------|
| Chat | `POST /chat` | Fire a chat run; returns immediately with status |
| Stream | `GET /sessions/{id}/stream` | SSE stream of `AgentEvent` objects with replay |
| Sessions | `GET/POST/PATCH/DELETE /sessions` | Create and manage chat sessions |
| Messages | `GET /sessions/{id}/messages` | Paginated message transcript |
| Agents | `GET/POST/PATCH/DELETE /agent` | Manage agent records |
| Credentials | `GET/POST/PATCH/DELETE /credential` | CRUD for API keys |
| Credential schemas | `GET /credential/schemas` | Discover credential types and JSON schemas |
| Models | `GET /model?provider=<name>` | List models with `ModelCard` metadata |
| Schedules | `GET/POST/PATCH/DELETE /schedule` | Manage cron-based execution |

Additional workspace endpoints referenced in the operation flow:

- `POST /workspace/mcp` — Configure MCP clients for a workspace.
- `POST /workspace/skill` — Configure skills for a workspace.

#### `POST /chat`
Fires a chat run and returns immediately with a status (asynchronous dispatch). Subscribe to the session stream to receive events.

#### `GET /sessions/{id}/stream`
Server-Sent Events (SSE) stream of `AgentEvent` objects. Supports **replay**: late-joining clients receive buffered history before live events.

#### `GET /sessions/{id}/messages`
Returns the paginated persisted message transcript for a session.

#### `GET /model?provider=<name>`
Lists models for the given provider, each exposed with `ModelCard` metadata.

- Query param: `provider` (str) — provider name.

#### `GET /credential/schemas`
Discovers available credential types and their JSON schemas.

---

### `ProtocolMiddlewareBase`

Base class for implementing custom chat protocols. Installed via the `extra_middlewares` parameter of `create_app`.

```python
from agentscope.app import ProtocolMiddlewareBase
from agentscope.event import AgentEvent

class MyProtocolMiddleware(ProtocolMiddlewareBase):
    def _convert_to_protocol(self, event: AgentEvent) -> dict:
        return {"type": event.type, "data": event.model_dump()}
```

**Method to override:**

| Method | Signature | Meaning |
|--------|-----------|---------|
| `_convert_to_protocol` | `(self, event: AgentEvent) -> dict` | Convert an internal `AgentEvent` into the external protocol's dict shape |

---

### `CredentialBase`

Base class for credential (model provider) types. A new credential type requires two classes: a `ChatModelBase` subclass and a `CredentialBase` subclass.

```python
from agentscope.credential import CredentialBase
from agentscope.model import ChatModelBase

class MyProviderChatModel(ChatModelBase):
    # Implement streaming chat interface
    ...

class MyProviderCredential(CredentialBase):
    api_key: str
    endpoint: str = "https://api.my-provider.com"

    @classmethod
    def get_chat_model_class(cls):
        return MyProviderChatModel

app = create_app(
    storage=storage,
    extra_credentials=[MyProviderCredential],
)
```

**Fields/methods:**

| Member | Type / Signature | Default | Meaning |
|--------|------------------|---------|---------|
| `api_key` | `str` | — | Provider API key |
| `endpoint` | `str` | `"https://api.my-provider.com"` | Provider endpoint URL |
| `get_chat_model_class` | `classmethod -> Type[ChatModelBase]` | — | Returns the `ChatModelBase` subclass to instantiate |

`ChatModelBase` — subclass and implement the streaming chat interface.

---

### `ModelCard`

Metadata object describing a model (returned by `GET /model`).

| Field | Meaning |
|-------|---------|
| `name` | Provider-side identifier |
| `label` | Display name |
| `status` | `active`, `deprecated`, or `sunset` |
| `input_types` | MIME types accepted (e.g., `text/plain`, `image/png`) |
| `output_types` | MIME types emitted |
| `context_size` | Maximum context window (tokens) |
| `output_size` | Maximum output tokens |
| `parameter_schema` | JSON schema for request parameters |

---

### `StorageBase`

Base class for persistence backends. Implement as an async context manager.

```python
class PostgresStorage(StorageBase):
    async def __aenter__(self):
        # Open connection pool
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Close connection pool
        ...
```

**Manages six record types:** `AgentRecord`, `SessionRecord`, `CredentialRecord`, `ScheduleRecord`, `TeamRecord`, and `Msg`.

Built-in implementation: `RedisStorage(host=..., port=...)` (from `agentscope.app.storage`).

---

### Workspace Managers (`WorkspaceManagerBase` implementations)

Three built-in implementations from `agentscope.app.workspace_manager`:

```python
# Local filesystem
from agentscope.app.workspace_manager import LocalWorkspaceManager
manager = LocalWorkspaceManager(basedir="/data/workspaces", ttl=3600.0)

# Docker containers
from agentscope.app.workspace_manager import DockerWorkspaceManager
manager = DockerWorkspaceManager(basedir="/data/docker-workspaces")

# E2B cloud sandbox
from agentscope.app.workspace_manager import E2BWorkspaceManager
manager = E2BWorkspaceManager()  # Uses E2B_API_KEY env var
```

| Class | Constructor params | Notes |
|-------|--------------------|-------|
| `LocalWorkspaceManager` | `basedir: str`, `ttl: float` | Local filesystem workspaces |
| `DockerWorkspaceManager` | `basedir: str` | Docker-container-backed workspaces |
| `E2BWorkspaceManager` | (none) | E2B cloud sandbox; reads `E2B_API_KEY` env var |

---

### `MessageBus` implementations

Built-in: `RedisMessageBus(host=..., port=...)` (from `agentscope.app.message_bus`). Redis-backed coordination primitives for session coordination and wakeup signals.

---

## Configuration

| Option | Where | Type | Default | Controls |
|--------|-------|------|---------|----------|
| `storage` | `create_app` | `StorageBase` | required | Persistence layer for all records |
| `message_bus` | `create_app` | `MessageBus` | required | Redis-backed coordination primitives |
| `workspace_manager` | `create_app` | `WorkspaceManagerBase` | required | Workspace lifecycle management |
| `extra_credentials` | `create_app` | `list[Type[CredentialBase]]` | none | Register additional credential/provider types |
| `extra_middlewares` | `create_app` | `list[Middleware]` | none | Add ASGI / protocol middlewares |
| `extra_agent_middlewares` | `create_app` | `AgentMiddlewareFactory` | none | Per-agent middlewares (appended after framework-supplied ones) |
| `extra_agent_tools` | `create_app` | `AgentToolFactory` | none | Per-agent tools |
| `sub_agent_templates` | `create_app` | `list[SubAgentTemplate]` | none | Team sub-agent blueprints |
| `title` | `create_app` | `str` | `"AgentScope"` | OpenAPI title |
| `version` | `create_app` | `str` | `"2.0.0"` | API version |
| `basedir` | `LocalWorkspaceManager` / `DockerWorkspaceManager` | `str` | — | Base directory for workspaces |
| `ttl` | `LocalWorkspaceManager` | `float` | — | Workspace time-to-live (seconds, e.g. `3600.0`) |
| `host` / `port` | `RedisStorage` / `RedisMessageBus` | `str` / `int` | — | Redis connection target |
| `E2B_API_KEY` | env var | `str` | — | Auth for `E2BWorkspaceManager` |
| `X-User-ID` | HTTP header | `str` | — | Default user identification header (NO security — see Gotchas) |

---

## Usage Patterns

### Minimal app creation

```python
from agentscope.app import create_app
from agentscope.app.storage import RedisStorage
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.workspace_manager import LocalWorkspaceManager

storage = RedisStorage(host="localhost", port=6379)
message_bus = RedisMessageBus(host="localhost", port=6379)
workspace_manager = LocalWorkspaceManager(basedir="/data/workspaces", ttl=3600.0)

app = create_app(
    storage=storage,
    message_bus=message_bus,
    workspace_manager=workspace_manager,
)
```

### Override user authentication via dependency injection

The default `X-User-ID` header provides **no security**. Override it:

```python
from fastapi import Header, HTTPException, status

async def get_current_user_id(authorization: str = Header(...)) -> str:
    try:
        payload = decode_jwt(authorization.removeprefix("Bearer "))
        return payload["sub"]
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

app.dependency_overrides[default_dependency] = get_current_user_id
```

### Custom protocol middleware

```python
from agentscope.app import ProtocolMiddlewareBase
from agentscope.event import AgentEvent

class MyProtocolMiddleware(ProtocolMiddlewareBase):
    def _convert_to_protocol(self, event: AgentEvent) -> dict:
        return {"type": event.type, "data": event.model_dump()}
```

Install via the `extra_middlewares` parameter.

### Custom credential / provider

```python
from agentscope.credential import CredentialBase
from agentscope.model import ChatModelBase

class MyProviderChatModel(ChatModelBase):
    ...

class MyProviderCredential(CredentialBase):
    api_key: str
    endpoint: str = "https://api.my-provider.com"

    @classmethod
    def get_chat_model_class(cls):
        return MyProviderChatModel

app = create_app(storage=storage, extra_credentials=[MyProviderCredential])
```

### Custom storage backend

```python
class PostgresStorage(StorageBase):
    async def __aenter__(self):
        ...   # Open connection pool

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        ...   # Close connection pool
```

### Typical operation flow

1. Create an agent: `POST /agent`
2. Create a credential: `POST /credential`
3. Create a session: `POST /sessions`
4. Configure MCPs/skills: `POST /workspace/mcp`, `POST /workspace/skill`
5. Start chatting: `POST /chat` and subscribe to `GET /sessions/{id}/stream`

For scheduled runs, complete steps 1-2, then `POST /schedule` without requiring direct chat calls.

---

## Service Architecture

Manager components that make up the service:

| Component | Role |
|-----------|------|
| **MessageBus** | Redis primitives for session coordination and wakeup signals |
| **WakeupDispatcher** | Responds to signal events and drives `ChatService` |
| **BackgroundTaskManager** | Asyncio task registry for offloaded tools |
| **SchedulerManager** | APScheduler-based cron execution |
| **ChatService** | Single entry point for running sessions |
| **WorkspaceManager** | Workspace lifecycle and caching |

### Agent-level middlewares (built-in)

Three framework-supplied middlewares wrap each agent execution:

| Middleware | Behavior |
|------------|----------|
| **InboxMiddleware** | Drains session inbox and yields `HintBlock`s |
| **ToolOffloadMiddleware** | Moves timeout-exceeded tools to background tasks |
| **StateChangeMiddleware** | Emits `CustomEvent`s on agent state changes |

Custom middlewares supplied via the `extra_agent_middlewares` factory are **appended after** the framework-supplied ones.

---

## Gotchas & Version Notes

- **`X-User-ID` header has NO security.** The default user-identification header is unauthenticated and trusts the caller blindly. For any real deployment, override user resolution via FastAPI `app.dependency_overrides[default_dependency] = get_current_user_id` (e.g., JWT-based). Do not rely on the default in production.
- **`POST /chat` is asynchronous.** It returns immediately with a status; it does NOT return the agent's reply. Consume results by subscribing to `GET /sessions/{id}/stream` (SSE) or by reading `GET /sessions/{id}/messages`.
- **All resources are scoped to `user_id`.** Seven resource types (Credential, Agent, Session, Workspace, Schedule, MessageBus, Messages) are partitioned by user; correct user resolution is therefore security-critical.
- **`create_app` requires all three of `storage`, `message_bus`, `workspace_manager`.** They have no defaults.
- **`E2BWorkspaceManager` requires the `E2B_API_KEY` environment variable** — it is read implicitly, not passed as a constructor arg.
- **Custom agent middlewares run *after* the built-in ones** (`InboxMiddleware`, `ToolOffloadMiddleware`, `StateChangeMiddleware`). Ordering matters when your middleware depends on inbox draining or tool offloading already having occurred.
- **`ModelCard.status` may be `deprecated` or `sunset`.** When listing models via `GET /model`, prefer models with `status == "active"`; avoid `deprecated`/`sunset` models.
- **Storage backends must implement the async context-manager protocol** (`__aenter__` / `__aexit__`) and manage all six record types (`AgentRecord`, `SessionRecord`, `CredentialRecord`, `ScheduleRecord`, `TeamRecord`, `Msg`).
- **Default `create_app` `version` is `"2.0.0"` and `title` is `"AgentScope"`** — these are OpenAPI metadata values, not the installed package version (the package is `agentscope` 1.0.20).
- **Custom credentials require BOTH a `ChatModelBase` subclass and a `CredentialBase` subclass**, wired together via the `get_chat_model_class` classmethod; registering only the credential without the model class is insufficient.
