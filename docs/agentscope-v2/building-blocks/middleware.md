# Middleware

> Source:
> - https://docs.agentscope.io/v2/building-blocks/middleware.md

## Overview

Agent middleware is the mechanism for injecting custom logic — logging, tracing, input rewriting, access control — into key points of the agent execution pipeline, without modifying core agent or model code.

AgentScope exposes **6 hook positions** plus an optional tool-provider hook. Middleware instances are passed to the `Agent()` constructor via the `middlewares=[...]` argument.

### Hook positions

| Hook | Type | Purpose |
|------|------|---------|
| `on_reply` | Onion | Wraps complete replies across all ReAct rounds |
| `on_reasoning` | Onion | Wraps single ReAct reasoning steps |
| `on_acting` | Onion | Wraps tool execution |
| `on_model_call` | Onion | Wraps underlying ChatModel API calls |
| `on_compress_context` | Onion | Wraps context compression decisions |
| `on_system_prompt` | Transformer | Fires during system prompt assembly |
| `list_tools` | Tool source | Returns optional `list[ToolBase]` contributions |

### Hook types

- **Onion**: Middleware wraps handlers; allows before/after logic around `next_handler()`. The middleware calls `next_handler(...)` to invoke the inner layer, and can run logic before and after it.
- **Transformer**: Forms a sequential pipeline; the previous middleware's output feeds into the next one. (Used by `on_system_prompt`.)
- **Tool source**: Not runtime-invoked; tools are explicitly collected from middlewares via `list_tools`.

## API Reference

### `MiddlewareBase`

Base class for all middleware. Subclass it and implement only the hooks you need. All hooks are `async`.

Import path: `from agentscope.middleware import MiddlewareBase`

The full set of implementable hooks (signatures taken from the docs' `FullObservabilityMiddleware` example):

#### `on_reply` (Onion)

```python
async def on_reply(
    self,
    agent: Agent,
    input_kwargs: dict,
    next_handler: Callable[..., AsyncGenerator[AgentEvent | Msg, None]],
) -> AsyncGenerator[AgentEvent | Msg, None]:
    ...
```

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `agent` | `Agent` | — | The agent whose reply is being processed |
| `input_kwargs` | `dict` | — | Keyword args forwarded to the inner handler; pass through via `next_handler(**input_kwargs)` |
| `next_handler` | `Callable[..., AsyncGenerator[AgentEvent \| Msg, None]]` | — | The inner handler; async-generator producing `AgentEvent` or `Msg` items |

**Returns:** an async generator yielding `AgentEvent | Msg`. Must `yield` each item from `next_handler(**input_kwargs)`.

Wraps the complete reply across all ReAct rounds.

#### `on_reasoning` (Onion)

```python
async def on_reasoning(
    self,
    agent: Agent,
    input_kwargs: dict,
    next_handler: Callable[..., AsyncGenerator[AgentEvent, None]],
) -> AsyncGenerator[AgentEvent, None]:
    ...
```

| Param | Type | Meaning |
|-------|------|---------|
| `agent` | `Agent` | The agent |
| `input_kwargs` | `dict` | Forwarded kwargs |
| `next_handler` | `Callable[..., AsyncGenerator[AgentEvent, None]]` | Inner reasoning handler |

**Returns:** async generator of `AgentEvent`. Wraps a single ReAct reasoning step.

#### `on_acting` (Onion)

Wraps tool execution (per tool call). Listed as one of the 6 hook positions. (No standalone signature shown in the doc; it follows the Onion pattern — `next_handler` wraps the tool call.)

#### `on_model_call` (Onion)

```python
async def on_model_call(
    self,
    agent: Agent,
    input_kwargs: dict,
    next_handler: Callable[
        ..., Awaitable[ChatResponse | AsyncGenerator[ChatResponse, None]]
    ],
) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
    ...
```

| Param | Type | Meaning |
|-------|------|---------|
| `agent` | `Agent` | The agent |
| `input_kwargs` | `dict` | Forwarded kwargs. Contains `current_model` — access the model name via `input_kwargs["current_model"].model` |
| `next_handler` | `Callable[..., Awaitable[ChatResponse \| AsyncGenerator[ChatResponse, None]]]` | Inner model-call handler; awaitable |

**Returns:** `ChatResponse` or `AsyncGenerator[ChatResponse, None]` (awaited result of `next_handler(...)`).

Wraps the underlying ChatModel API call. You can override the model by passing `current_model=<model>` to `next_handler(...)` (see Model fallback example).

#### `on_compress_context` (Onion)

```python
async def on_compress_context(
    self,
    agent: Agent,
    input_kwargs: dict,
    next_handler: Callable[..., Awaitable[None]],
) -> None:
    ...
```

| Param | Type | Meaning |
|-------|------|---------|
| `agent` | `Agent` | The agent |
| `input_kwargs` | `dict` | Forwarded kwargs |
| `next_handler` | `Callable[..., Awaitable[None]]` | Inner compression handler; awaitable returning `None` |

**Returns:** `None`. Wraps the context-compression decision. Call `await next_handler(**input_kwargs)`.

#### `on_system_prompt` (Transformer)

```python
async def on_system_prompt(
    self,
    agent: Agent,
    current_prompt: str,
) -> str:
    ...
```

| Param | Type | Meaning |
|-------|------|---------|
| `agent` | `Agent` | The agent |
| `current_prompt` | `str` | The current (possibly already-transformed by a previous middleware) system prompt |

**Returns:** `str` — the transformed system prompt. This is a Transformer hook: the returned string feeds into the next middleware's `on_system_prompt`. There is **no** `next_handler`.

#### `list_tools` (Tool source)

```python
async def list_tools(self) -> list[ToolBase]:
    ...
```

**Returns:** `list[ToolBase]` — tools contributed by this middleware. Not invoked at runtime; tools are explicitly collected from middlewares. Return `[]` if none.

### `TracingMiddleware`

Import path: `from agentscope.middleware import TracingMiddleware`

Instruments the agent lifecycle with OpenTelemetry tracing. Constructed with no arguments: `TracingMiddleware()`.

**Setup requirement:** you must register an OpenTelemetry `TracerProvider` before use:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")),
)
trace.set_tracer_provider(provider)
```

**Captured attributes per span:**

| Span | Attributes captured |
|------|---------------------|
| Agent Reply Span | Agent name, session ID, reply ID, input messages, output, pending tool calls |
| Model Call Span | Model name/provider, token counts, message content, streaming wrapping |
| Tool Execution Span | Tool name, call ID, arguments, execution result |

**Adding custom spans** within the lifecycle:

```python
from opentelemetry import trace
from agentscope import __version__

tracer = trace.get_tracer("agentscope", __version__)

with tracer.start_as_current_span(
    name="your_span_name",
    attributes={...},
    end_on_exit=True,
) as span:
    # your code here
```

### `Agent` (middleware-relevant usage)

Import path: `from agentscope.agent import Agent`

Middleware is wired via the `middlewares` constructor argument:

```python
agent = Agent(
    name="assistant",
    system_prompt="You are a helpful assistant.",
    model=model,
    toolkit=toolkit,
    middlewares=[TracingMiddleware()],
)
```

| Param (middleware-relevant) | Type | Meaning |
|------|------|---------|
| `middlewares` | `list[MiddlewareBase]` | Ordered list of middleware instances. Order determines onion nesting / transformer chaining (see Execution Order) |

## Configuration

| Option | Where | Type / Default | Controls |
|--------|-------|----------------|----------|
| `middlewares` | `Agent(...)` constructor | `list[MiddlewareBase]` | Which middlewares are active and their order |
| `min_interval` | `RateLimitMiddleware(min_interval=...)` (custom example) | `float`, default `1.0` | Minimum seconds between model calls |
| `endpoint` | `OTLPSpanExporter(endpoint=...)` (tracing setup) | `str` (e.g. `"http://localhost:4318/v1/traces"`) | OTLP trace export endpoint |

> Note: `TracingMiddleware` itself takes no constructor configuration in the documented usage. Tracing is configured through the OpenTelemetry `TracerProvider` / exporter, not through the middleware.

## Usage Patterns

### Attaching middleware

```python
from agentscope.agent import Agent
from agentscope.middleware import TracingMiddleware

agent = Agent(
    name="assistant",
    system_prompt="You are a helpful assistant.",
    model=model,
    toolkit=toolkit,
    middlewares=[TracingMiddleware()],
)
```

### Full observability middleware (all hooks)

```python
from typing import AsyncGenerator, Awaitable, Callable
from agentscope.agent import Agent
from agentscope.event import AgentEvent
from agentscope.message import Msg
from agentscope.middleware import MiddlewareBase
from agentscope.model import ChatResponse
from agentscope.tool import ToolBase

class FullObservabilityMiddleware(MiddlewareBase):
    """Example middleware implementing all hook positions."""

    async def on_reply(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator[AgentEvent | Msg, None]],
    ) -> AsyncGenerator[AgentEvent | Msg, None]:
        print(f"[reply] start for {agent.name}")
        async for item in next_handler(**input_kwargs):
            yield item
        print(f"[reply] end for {agent.name}")

    async def on_reasoning(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator[AgentEvent, None]],
    ) -> AsyncGenerator[AgentEvent, None]:
        print("[reasoning] start")
        async for event in next_handler(**input_kwargs):
            yield event
        print("[reasoning] end")

    async def on_model_call(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[
            ..., Awaitable[ChatResponse | AsyncGenerator[ChatResponse, None]]
        ],
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        print(f"[model_call] {input_kwargs['current_model'].model}")
        result = await next_handler(**input_kwargs)
        print("[model_call] done")
        return result

    async def on_compress_context(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., Awaitable[None]],
    ) -> None:
        print(f"[compress_context] checking context for {agent.name}")
        await next_handler(**input_kwargs)
        print("[compress_context] done")

    async def on_system_prompt(
        self,
        agent: Agent,
        current_prompt: str,
    ) -> str:
        print(f"[system_prompt] length={len(current_prompt)}")
        return current_prompt

    async def list_tools(self) -> list[ToolBase]:
        return []
```

### Timing middleware (model call duration)

```python
import time
from agentscope.middleware import MiddlewareBase

class TimingMiddleware(MiddlewareBase):
    async def on_model_call(self, agent, input_kwargs, next_handler):
        model_name = input_kwargs["current_model"].model
        start = time.time()
        result = await next_handler()
        elapsed = time.time() - start
        print(f"[timing] {agent.name} → {model_name}: {elapsed:.2f}s")
        return result
```

### Rate-limiting middleware (minimum interval between calls)

```python
import asyncio
import time
from agentscope.middleware import MiddlewareBase

class RateLimitMiddleware(MiddlewareBase):
    def __init__(self, min_interval: float = 1.0):
        self._last_call = 0.0
        self._min_interval = min_interval

    async def on_model_call(self, agent, input_kwargs, next_handler):
        now = time.time()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.time()
        return await next_handler()
```

### Dynamic system prompt middleware (inject real-time context)

```python
from datetime import datetime
from agentscope.middleware import MiddlewareBase

class DynamicContextMiddleware(MiddlewareBase):
    def __init__(self, context_fn):
        self._context_fn = context_fn

    async def on_system_prompt(self, agent, current_prompt):
        context = self._context_fn()
        return f"{current_prompt}\n\n## Current Context\n{context}"

agent = Agent(
    ...
    middlewares=[
        DynamicContextMiddleware(
            lambda: f"Time: {datetime.now().isoformat()}"
        ),
    ],
)
```

### Model fallback middleware (switch to backup on failure)

```python
from agentscope.middleware import MiddlewareBase

class ModelFallbackMiddleware(MiddlewareBase):
    def __init__(self, fallback_model):
        self._fallback = fallback_model

    async def on_model_call(self, agent, input_kwargs, next_handler):
        try:
            return await next_handler()
        except Exception as e:
            print(f"Primary model failed: {e}, switching to fallback")
            return await next_handler(current_model=self._fallback)
```

## Gotchas & Version Notes

- **Onion vs Transformer semantics differ — do not mix them up.**
  - Onion hooks (`on_reply`, `on_reasoning`, `on_acting`, `on_model_call`, `on_compress_context`) receive a `next_handler` and MUST call it to continue the chain. The first middleware in the list is the **outermost** layer.
  - The Transformer hook (`on_system_prompt`) does NOT receive a `next_handler`. It takes `current_prompt: str` and returns a `str`. Middlewares chain **left to right**: `original_prompt → mw1.on_system_prompt() → mw2.on_system_prompt() → final`.

- **Generator hooks must re-yield.** `on_reply` and `on_reasoning` are async generators: you must `async for ... in next_handler(**input_kwargs): yield ...`. Returning instead of yielding breaks the stream.

- **Async/await hooks must return the awaited result.** `on_model_call` and `on_compress_context` are coroutines; `await next_handler(...)` and return its result (for `on_model_call`).

- **Passing args through.** Pass `**input_kwargs` into `next_handler` to forward args unchanged. To modify behavior, override individual kwargs — e.g. `next_handler(current_model=self._fallback)` to swap the model in `on_model_call`.

- **`current_model` lives in `input_kwargs`.** For `on_model_call`, read the model name via `input_kwargs["current_model"].model`.

- **`list_tools` is not invoked at runtime.** It is a tool *source* — tools are explicitly collected from middlewares, not triggered during execution. Return `[]` when contributing nothing.

- **`TracingMiddleware` requires an OpenTelemetry `TracerProvider` to be registered** via `trace.set_tracer_provider(...)` before it produces traces. Without provider setup, no spans are exported.

- **Custom spans** should use `trace.get_tracer("agentscope", __version__)` (importing `__version__` from `agentscope`) so they nest correctly within the agent lifecycle.

- **Full lifecycle order within a single reply** (use this to choose the right hook):
  ```
  on_reply
    └── per ReAct round:
          ├── on_compress_context
          ├── on_reasoning
          │     ├── on_system_prompt
          │     └── on_model_call
          └── on_acting (per tool call)
  ```

- This page documents AgentScope **v2** (docs.agentscope.io/v2; installed package `agentscope` 1.0.20). No explicit deprecations or "use X instead of Y" replacements are stated in the source page.
