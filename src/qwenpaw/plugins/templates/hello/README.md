# Hello SDK

This template imports only public SDK types. `hello_sdk` validates a name,
returns a tool result and stores a counter separately for each workspace.
Reload preserves the counter; uninstall follows the host's existing data policy.

Create your own copy from an installed wheel:

```sh
python -m qwenpaw.plugins.check --template ./hello-sdk
python -m qwenpaw.plugins.check ./hello-sdk
python -m qwenpaw.plugins.check ./hello-sdk --runtime
```

`--runtime` executes trusted plugin code inside an isolated test host. It
observes loading, activation and cleanup; it does not execute every tool or
prove all lifecycle scenarios. Install the directory through the normal
plugin installer, or use `PluginTestHost.install` for an isolated transaction.

Use `PluginTestHost.call_tool("hello_sdk", {"name": "SDK"})` to exercise the
real tool registry and governance. `PluginTestHost` defaults to an explicit
ALLOW policy; production permissions still follow the host's policy.

The tool records a structured `context.logger.info` entry. Optional
`use_model: true` makes one request to the workspace's configured default model
through `context.models.complete`; it is off by default and may incur the
configured provider's normal usage costs. No credentials or internal host
objects are imported by this template.
