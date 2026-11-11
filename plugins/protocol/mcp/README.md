# QwenPaw MCP

## MCP optional runtime

The official plugin ID is `qwenpaw-mcp`; the protocol is `mcp`. This release adds
MCP as an optional plugin and public SDK 1.1 driver support. Agent Mail and ACP
are outside this migration.

- **New or unused installations:** no plugin directory, load record, MCP connection,
  driver manager or MCP polling task is created. The `/mcp` navigation and initial
  page remain available. Opening the page does not install or activate the plugin.
  Choose **Install** there to install the bundled offline resource, then configure
  servers in the same page. An installed disabled plugin offers **Enable**.
- **Existing custom MCP configuration:** startup inventories workspaces and installs
  the bundled resource offline when eligible, preserving source settings, credentials,
  OAuth, policy and whitelist. All-disabled custom configurations remain manageable
  without opening connections. Legacy `mcp.clients` conversion is one-time; existing
  DriverCards and migration watermarks prevent duplicate conversion or resurrection.
  The untouched default disabled AnySearch configuration alone does not opt users in.
- **Explicit disable or uninstall:** startup honors that choice and keeps configuration
  and credentials. Re-enable through the MCP page; after uninstall, explicitly install
  again to reuse retained settings. Disabling a source only closes that source; disabling
  the plugin stops its runtime. Update through normal plugin management. Startup never
  overwrites installed plugin code or downloads plugin dependencies in the background.

Upgrade preserves `command`, `args`, `cwd`, `env`, `url`, `headers`, `timeout`,
display names and per-source enabled state, together with credential references,
OAuth, policy and tool whitelists. A configured `tools: []` remains deny-all.
Sources with the same name in different workspaces keep separate identities.

When enabled MCP configuration needs monitoring, the existing **two-second** file scan
continues, including while all custom sources are temporarily disabled. Editing a source
to enable it takes effect on the next scan; connection/discovery may take longer.
An uninstalled or disabled plugin performs no MCP scan. The monitor and connection
conditions are separate, so disabling every source need not disable manual-edit monitoring.

### Recovery

If installation or enabling fails, the original MCP page remains visible with retry.
First check the displayed error and logs. Repair missing local dependencies with the
normal application installer; startup does not run pip/uv. Retry the explicit operation
without deleting DriverCards, credentials or upgrade records. A failed update retains
or rolls back the prior plugin generation; busy resources can require a restart before
retrying. Interrupted upgrades resume through the transaction journal. Invalid metadata
or ambiguous legacy configuration is held for review rather than guessed or discarded.
Back up the affected workspace/configuration before manually repairing damaged files.

Wheel, sdist and desktop resources come from `plugins/protocol/mcp`, including the
prebuilt frontend. They are inert installation resources, separate from plugin discovery.
The Python environment may still contain upstream `mcp` packages for shared consumers;
the guarantee concerns the optional project runtime, not removal of all `mcp.*` imports.

Author SDK: [DriverProtocolSpec](../../../website/public/docs/plugins.en.md).
