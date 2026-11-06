# Hello SDK

TODO: Maintainers must review and approve the `sdk.version: 1.1.0` declaration
in `plugin.json` before release. Align it with the approved `SDK_VERSION` and
API `since` metadata; this version is provisional.

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

The same plugin also provides a terminal command and a Doctor check. Install
the exported directory, then run the command without starting the App:

```sh
qwenpaw plugin install ./hello-sdk
qwenpaw hello --name SDK greet
qwenpaw hello --name SDK greet
```

The two greetings return `Hello SDK (1)` and `Hello SDK (2)`. The CLI uses
`cli-count.json`; the Tool keeps its existing workspace counter separately.
`main.py` registers the command factory, and imports `cli.py` when the host
builds the selected command. Both use the existing public plugin entry.

`qwenpaw doctor` includes `Hello SDK is installed` under `hello-sdk:hello`.
This check reports plugin availability; it does not probe a model or platform.
Uninstalling `hello-sdk` removes its command and Doctor contribution.

The tool records a structured `context.logger.info` entry. Optional
`use_model: true` makes one request to the workspace's configured default model
through `context.models.complete`; it is off by default and may incur the
configured provider's normal usage costs. No credentials or internal host
objects are imported by this template.
