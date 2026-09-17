# Middleware Demo Plugins

Two example plugins demonstrating `PluginApi.register_middleware()` — the
plugin-based mechanism for injecting AgentScope `MiddlewareBase` instances
into the agent's reasoning loop.

## Included Demos

| Plugin | Hook | Behavior |
|--------|------|----------|
| `tracing-middleware` | `on_acting` | Logs every tool call (name, duration) to a file. Conditionally activated only when `QWENPAW_TRACE` env var is set. |
| `thinking-log-middleware` | `on_reasoning` | Prints model reasoning stream events to stdout (`[THINKING]` for chain-of-thought, `[TEXT]` for text responses). Always active. |

## Installation

These plugins are **not** auto-loaded. Install them explicitly:

```bash
# While QwenPaw is running (hot-load, no restart needed):
qwenpaw plugin install plugins/middleware-demo/tracing-middleware
qwenpaw plugin install plugins/middleware-demo/thinking-log-middleware

# Or when QwenPaw is stopped (loaded on next start):
qwenpaw plugin install plugins/middleware-demo/tracing-middleware
qwenpaw plugin install plugins/middleware-demo/thinking-log-middleware
```

## Uninstall

```bash
qwenpaw plugin uninstall middleware-demo-tracing
qwenpaw plugin uninstall middleware-demo-thinking-log
```

## How It Works

Each plugin registers a **middleware factory** via `api.register_middleware(factory, priority=N)`.

The factory is called once per request during agent assembly:

```python
def my_factory(ctx, agent_config):
    # ctx: HookContext (session_id, agent_id, workspace_dir, ...)
    # agent_config: AgentProfileConfig
    #
    # Return a MiddlewareBase instance to activate, or None to skip.
    return MyMiddleware()
```

The returned middleware wraps the agent's inner reasoning loop using the
standard AgentScope 2.0 onion model (`on_reply`, `on_reasoning`, `on_acting`).

## Priority

Lower priority values run as the outermost layer (execute first on the way
in, last on the way out). The built-in middlewares use implicit ordering;
plugin middlewares append after them sorted by priority.
