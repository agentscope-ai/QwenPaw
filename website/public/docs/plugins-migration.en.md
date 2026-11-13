# Plugin System Migration Guide

The new version of QwenPaw keeps most of the public API from the previous plugin system. Most legacy public APIs keep the same signature and can still be called as-is. However, if a plugin depends on agent state, workspace internals, runtime helpers, tool config structures, or frontend page structure, you still need to verify the actual behavior in the new version.

## Scope

This document applies to:

- Backend plugins built against the legacy official documentation
- Plugins that register providers, hooks, tools, HTTP APIs, or commands through `PluginApi`
- Frontend plugins that use the `window.QwenPaw.*` Host SDK

## Pre-migration Checklist

The backend plugin entry point still needs to export a `plugin` instance:

```python
class MyPlugin:
    def register(self, api):
        ...


plugin = MyPlugin()
```

The new validation logic requires the entry module to export a `plugin` instance. Plugins that only export a `Plugin` class without instantiating it need to add the instance.

## Check the Plugin Manifest `plugin.json`

### Version Compatibility Declaration

Legacy plugin manifests usually use `min_version`:

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "type": "general",
  "entry": {
    "backend": "plugin.py"
  },
  "min_version": "1.1.10"
}
```

In the legacy version, `min_version` was mostly manifest metadata — the loader never used it to block plugin loading. The new version checks version compatibility before importing a plugin. Incompatible plugins are recorded with `enabled=false`, and the backend entry's `register()` is never executed.

The new version recommends using `qwenpaw_version`:

```json
{
  "qwenpaw_version": {
    "min": "2.0.0",
    "max": "2.1.0"
  }
}
```

The version range uses `>= min, < max` semantics. When `max` is omitted, the new version derives it from `min` as the next minor version.

| Declaration       | Equivalent range   |
| ----------------- | ------------------ |
| `"min": "2.0.0"`  | `>=2.0.0, <2.1.0`  |
| `"min": "1.1.10"` | `>=1.1.10, <1.2.0` |

So if you drop a legacy plugin into the new version unchanged and it only has `"min_version": "1.1.10"`, the new version interprets it as `>=1.1.10, <1.2.0`, which is judged incompatible under QwenPaw 2.0.x.

### Manifest Field Reference

| Field                                                                                                               | Type     | Legacy                                   | New                                                                               | Migration advice                                            |
| ------------------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `qwenpaw_version`                                                                                                   | `object` | Undefined, ignored                       | New, recommended                                                                  | New plugins should add this field                           |
| `qwenpaw_version.min`                                                                                               | `string` | Undefined                                | Minimum compatible QwenPaw version, inclusive                                     | Set to the lowest new version you actually verified against |
| `qwenpaw_version.max`                                                                                               | `string` | Undefined                                | Highest compatible QwenPaw version, exclusive                                     | Recommended to set explicitly                               |
| `min_version`                                                                                                       | `string` | Supported, but not enforced at load time | Legacy field, only used for compatibility checks when `qwenpaw_version` is absent | Keep it if you need legacy compatibility                    |
| `max_version`                                                                                                       | `string` | Undefined                                | Legacy field, used together with `min_version`                                    | Only for legacy-manifest compatibility scenarios            |
| `id`, `version`, `name`, `type`, `description`, `author`, `entry.backend`, `entry.frontend`, `dependencies`, `meta` | —        | Supported                                | Still supported                                                                   | No change                                                   |
| `entry_point`                                                                                                       | `string` | Legacy field                             | Still compatible                                                                  | New plugins should still use `entry.backend`                |

If a single plugin needs to support both the legacy and new versions, you can keep both the old and new fields:

```json
{
  "min_version": "1.1.10",
  "qwenpaw_version": {
    "min": "2.0.0",
    "max": "2.1.0"
  }
}
```

The legacy version ignores the unknown `qwenpaw_version` field. The new version reads `qwenpaw_version` first, and only falls back to `min_version` / `max_version` when that field is absent.

## Check Backend Plugin Code

### Public API Compatibility

The following legacy APIs keep a compatible signature in the new version and can still be called:

| API                                                                                 | Purpose                            | Migration advice                                                                      |
| ----------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------- |
| `register_provider(provider_id, provider_class, label="", base_url="", **metadata)` | Register a custom LLM provider     | Interface remains compatible; verify provider config and model display                |
| `register_startup_hook(hook_name, callback, priority=100)`                          | Register a startup hook            | Interface remains compatible; verify startup timing                                   |
| `register_shutdown_hook(hook_name, callback, priority=100)`                         | Register a shutdown hook           | Interface remains compatible; verify cleanup behavior                                 |
| `register_uninstall_hook(hook_name, callback, priority=100)`                        | Register an uninstall hook         | Interface remains compatible; verify the uninstall flow                               |
| `register_workspace_created_hook(hook_name, callback, priority=100)`                | Register a workspace-created hook  | Interface remains compatible; verify the new workspace info structure                 |
| `register_http_router(router, *, prefix, tags=None)`                                | Register a FastAPI router          | Interface remains compatible; verify routes, auth, and OpenAPI display                |
| `register_control_command(handler, priority_level=10)`                              | Register a control command handler | Interface remains compatible; new plugins may evaluate `register_slash_command()`     |
| `register_tool(tool_name, tool_func, description="", icon="🔧", enabled=False)`     | Register an agent tool             | Interface remains compatible; verify tool config, enabled state, and agent invocation |
| `register_skill_provider(skills_dir, *, enabled_by_default=True, channels=None)`    | Register a plugin skill directory  | Signature remains compatible; default-value write behavior changed                    |
| `get_tool_config(tool_name, agent_id)`                                              | Read tool config                   | Interface remains compatible; verify the agent id source                              |
| `set_tool_config(tool_name, agent_id, config)`                                      | Save tool config                   | Interface remains compatible; verify config persistence                               |
| `api.runtime`                                                                       | Access runtime helpers             | Property remains available; verify helper capabilities in the new version             |
| `get_tool_config(tool_name)`                                                        | Module-level tool config lookup    | Interface remains compatible; verify the active call context                          |

### `register_prompt_section`

This is the only API in the new version with a **changed argument order**. If your plugin uses this method, check the call style.

Legacy signature (`provider` is the 2nd positional argument, `after` has a default value):

```python
def register_prompt_section(
    self,
    name: str,
    provider: Callable,
    *,
    after: str = "workspace",
    agent_id: Optional[str] = None,
) -> None: ...
```

New signature (`after` moves to the 2nd position and becomes required; `priority` and `condition` are new):

```python
def register_prompt_section(
    self,
    name: str,
    after: str,
    provider: Callable,
    *,
    priority: int = 100,
    condition: Optional[Callable] = None,
    agent_id: Optional[str] = None,
) -> None: ...
```

Argument changes:

| Argument    | Legacy                                  | New                               | Migration advice                                                                       |
| ----------- | --------------------------------------- | --------------------------------- | -------------------------------------------------------------------------------------- |
| `name`      | 1st positional argument                 | 1st positional argument           | No change                                                                              |
| `provider`  | 2nd positional argument                 | 3rd positional argument           | Do not keep passing it as the 2nd positional argument — use a keyword argument instead |
| `after`     | Keyword argument, default `"workspace"` | 2nd required argument, no default | Pass `after=` explicitly                                                               |
| `priority`  | Not supported                           | New, optional, default `100`      | Use when you need to control ordering within the same anchor                           |
| `condition` | Not supported                           | New, optional                     | Use when you need conditional prompt injection                                         |
| `agent_id`  | Optional keyword argument               | Optional keyword argument         | No change                                                                              |

Valid values for `after` are `"workspace"`, `"multimodal"`, and `"env_context"`.

Recommended usage (always use keyword arguments):

```python
api.register_prompt_section(
    name="my.section",
    after="workspace",
    provider=build_prompt,
)
```

Do not keep using the positional-argument style that was common in the legacy version:

```python
# Wrong: the 2nd positional argument in the new version is `after`,
# so passing the provider function here will fail at runtime.
api.register_prompt_section("my.section", build_prompt)
```

If you need conditional prompt injection, use the new `condition` parameter:

```python
api.register_prompt_section(
    name="my.section",
    after="workspace",
    provider=build_prompt,
    condition=lambda agent: agent.config.mode == "coding",
    priority=50,
)
```

### New APIs and Notable Changes

The following are APIs that did not exist in the legacy version. Legacy plugins don't need to adopt them just for migration — new plugins can use them as needed. The signature change for `register_prompt_section()` is covered above.

#### register_middleware

Registers an AgentScope middleware factory. The factory is called each time an agent is built, and returns a `MiddlewareBase` instance or `None`.

```python
api.register_middleware(
    middleware_factory: Callable,  # (ctx, agent_config) -> MiddlewareBase | None
    *,
    priority: int = 100,          # Priority — lower means further outside
)
```

#### register_slash_command

Registers a workspace-level `/command`. The command is registered into every existing workspace, and continues to be registered whenever a new workspace is created.

```python
api.register_slash_command(
    name: str,                    # Command name, without the leading "/"
    handler: Callable,            # async (ctx, args) -> Msg | None
    *,
    aliases: tuple = (),          # Command aliases
    category: str = "plugin",     # Command category
    help_text: str = "",          # Help text
    metadata: Optional[dict] = None,  # Extra metadata
)
```

#### register_mode

Registers a plugin-provided `AgentMode`. The mode is registered into existing workspaces at startup, and into new workspaces as they are created.

```python
api.register_mode(
    mode_cls: Type,  # AgentMode subclass; must provide a unique `name`
)
```

#### register_runtime_hook

Registers a runtime-phase hook. The hook object must provide `phase`, `name`, and `run()`.

```python
api.register_runtime_hook(
    hook: HookBase,  # runtime hook instance
)
```

Available phases:

```text
PRE_DISPATCH
POST_DISPATCH
PRE_AGENT_BUILD
POST_AGENT_BUILD
PRE_EXECUTE
POST_RESPONSE
ON_ERROR
FINALLY
```

#### register_agent_stop_handler

Registers an agent stop-decision handler. The handler can participate in deciding whether the agent should stop, or return information needed to keep it running.

```python
api.register_agent_stop_handler(
    handler: Callable,       # async (ctx) -> StopHandlerResult
    *,
    priority: int = 100,     # Priority — lower runs earlier
    name: str = "",         # Name for debugging
)
```

#### unregister_skill_provider

Revokes the skill-provider capability that the current plugin registered via `register_skill_provider()`, and cleans up skills sourced from this plugin.

```python
api.unregister_skill_provider()
```

## Skill Provider Behavior

The signature of `register_skill_provider()` is unchanged. The new version adjusts the default-value write policy for skills:

| Item                     | Legacy                                                                                | New                                                           | Impact                                                                                               |
| ------------------------ | ------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `enabled` default write  | Written to the plugin's declared default every time the plugin's skills are installed | Only written the first time a skill is claimed by this plugin | Once a user manually disables a skill, the plugin will no longer re-enable it on subsequent startups |
| `channels` default write | Written to the plugin's declared default every time the plugin's skills are installed | Only written the first time a skill is claimed by this plugin | User-adjusted channel settings are preserved                                                         |
| Uninstall cleanup        | Supports cleaning up skills by plugin source                                          | Still supported                                               | Verify the skill directory and manifest cleanup results on uninstall                                 |

If your plugin relies on the behavior of "resetting skill toggles on every startup," you need to re-evaluate it.

## Check Frontend Plugin Code

The new version continues to support the existing `window.QwenPaw.*` frontend Host SDK. Plugins using existing legacy frontend APIs can usually run without changes.

| API                                                            | Type       | Purpose                                                             |
| -------------------------------------------------------------- | ---------- | ------------------------------------------------------------------- |
| `window.QwenPaw.host`                                          | Compatible | Access React, Ant Design, API helpers, runtime state, etc.          |
| `window.QwenPaw.menu`                                          | Compatible | Register sidebar menu items                                         |
| `window.QwenPaw.route`                                         | Compatible | Register page routes                                                |
| `window.QwenPaw.slot`                                          | Compatible | Register UI slots                                                   |
| `window.QwenPaw.chat.requestPayload.add(pluginId, fn, opts?)`  | New        | Append or rewrite request body fields before a chat request is sent |
| `window.QwenPaw.chat.response.set(pluginId, { avatar, nick })` | New        | Set the avatar and nickname for the default AI reply card           |

## Check Dependency Installation

The `requirements.txt` format is unchanged. The new version improves dependency detection and installation:

| Item                                       | Legacy                                          | New                                                                         |
| ------------------------------------------ | ----------------------------------------------- | --------------------------------------------------------------------------- |
| `requirements.txt` format                  | Supports pip requirements syntax                | Still supported                                                             |
| Dependency detection                       | Mainly relies on distribution metadata          | Combines distribution metadata with an import probe                         |
| Distribution name vs. import name mismatch | May be misreported as not installed             | Built-in mapping for common cases, e.g. `pillow` / `PIL`, `pyyaml` / `yaml` |
| Concurrent installs                        | Multiple processes may install at the same time | Adds a cross-process install lock                                           |
| Frozen desktop build                       | Depends on the system Python environment        | Uses a bundled Python runtime and a user-writable dependency directory      |

Usually you can keep your existing `requirements.txt` unchanged, but it's still recommended to re-verify dependency installation and imports in the new version.

## Check Plugin Loading and Unloading

The new version cleans up already-registered state when a plugin fails to load, including registry entries, plugin modules, and any temporarily added `sys.path` entries. Unloading a plugin also cleans up modules imported from the plugin directory more thoroughly.

| Item                               | Legacy                              | New                                                                  |
| ---------------------------------- | ----------------------------------- | -------------------------------------------------------------------- |
| Registry cleanup after failed load | May leave some registrations behind | Automatically cleans up all state registered by the plugin           |
| Module cleanup after failed load   | Limited cleanup                     | Cleans up by module-name prefix and plugin file path                 |
| Module cleanup after unload        | Limited cleanup                     | More thoroughly cleans up modules imported from the plugin directory |
| `sys.path` cleanup                 | Limited cleanup                     | Removes the plugin directory on both failed load and unload          |
| `.disabled` directories            | Not supported                       | Skips plugin directories ending in `.disabled`                       |

Hidden directories starting with `.` and directories ending in `.disabled` are not loaded by the plugin discovery process, and do not trigger dependency installation. If a plugin manually modifies `sys.path`, it's recommended to test the install, uninstall, and reinstall flow.

## Publishing to the Plugin Marketplace

The new version's plugin marketplace catalog filters entries by QwenPaw version. The filtering rules match the loader:

| Field                 | Type     | Read priority | Description                                                                        |
| --------------------- | -------- | ------------- | ---------------------------------------------------------------------------------- |
| `qwenpaw_version`     | `object` | 1             | Recommended field, same format as the plugin manifest                              |
| `qwenpaw_version.min` | `string` | 1             | Minimum compatible QwenPaw version, inclusive                                      |
| `qwenpaw_version.max` | `string` | 1             | Highest compatible QwenPaw version, exclusive                                      |
| `min_version`         | `string` | 2             | Legacy field, only used when `qwenpaw_version` is absent                           |
| `max_version`         | `string` | 2             | Legacy field, only used when `qwenpaw_version` is absent                           |
| No version constraint | -        | 3             | Treated as compatible, but omitting constraints is not recommended when publishing |

When publishing a new-version plugin, keep the version constraints in the packaged `plugin.json` consistent with the marketplace index entry. If an existing entry only has `"min_version": "1.1.10"`, it may get filtered out under QwenPaw 2.0.x.

## Migration Steps

1. Update `plugin.json`, adding `qwenpaw_version` with an explicit `max`.
2. Confirm the backend entry point exports `plugin = MyPlugin()`.
3. Search for `register_prompt_section`, and change calls to keyword-argument style with `after` passed explicitly.
4. If the plugin provides a skill, verify the persistence behavior after a user manually toggles it.
5. Run plugin install and validation in the new version.
6. Start QwenPaw and check the logs for `is incompatible` or plugin registration failure messages.
7. If published to the plugin marketplace, update the version constraints in the marketplace index as well.

## FAQ

### The plugin worked fine in the legacy version but doesn't take effect in the new version

Check the version compatibility declaration first. If a legacy plugin only declared `min_version`, the new version may derive an overly narrow compatible range, causing the plugin to be marked incompatible. You can search the server logs for `is incompatible`.

### The public interface is compatible, so why does it still need testing?

A compatible public interface only means the method names and arguments can still be called. If the plugin internally depends on agent state, workspace information, request context, tool config structures, or frontend page structure, these runtime objects may have changed — so full functional verification in the new version is still required.

### `register_prompt_section()` raises an argument error

Change the call to keyword-argument style and pass `after` explicitly:

```python
api.register_prompt_section(
    name="my.section",
    after="workspace",
    provider=build_prompt,
)
```

### Can the same plugin support both the legacy and new versions?

Yes. The plugin code should only use APIs that exist on both sides, or check the version before calling a new-version-only API. The manifest can keep both `min_version` and `qwenpaw_version`:

```json
{
  "min_version": "1.1.10",
  "qwenpaw_version": {
    "min": "2.0.0",
    "max": "2.1.0"
  }
}
```

### Do I need to migrate to `register_slash_command()`?

No. `register_control_command()` remains available in the new version. `register_slash_command()` is only recommended for new plugins that need workspace-level command registration.

### Can I omit `qwenpaw_version.max`?

Yes, but omitting it means it will be automatically derived as the next minor version. If your plugin has been verified to work across multiple minor versions, it's better to explicitly declare a wider `max`.
