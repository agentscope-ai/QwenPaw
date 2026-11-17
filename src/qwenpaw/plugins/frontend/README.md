# QwenPaw frontend SDK

This directory is the standalone `@qwenpaw/plugin-sdk` npm package, shipped
inside the QwenPaw wheel. It contains all host/PawApp declarations and small
runtime helpers. No Console source checkout or relative Console import is needed.

Export it from an installed wheel, then install the local package:

```sh
python -m qwenpaw.plugins.check ./my-plugin --frontend ./qwenpaw-plugin-sdk
npm install ./qwenpaw-plugin-sdk
npm install --save-dev typescript @types/react
```

```ts
import { forApp, capabilities, tasks } from "@qwenpaw/plugin-sdk";
import type { TaskSnapshot, PawSdk } from "@qwenpaw/plugin-sdk";

const paw: PawSdk = forApp("my-app");
const info = await capabilities("my-app");
if (info.status === "supported" && info.capabilities.includes("tasks")) {
  const run: TaskSnapshot = await tasks("my-app").start({message: "Hello"});
  await tasks("my-app").cancel(run.run_id);
}
```

`SDK_VERSION` and `SDK_CAPABILITIES` describe this **library**, not the running
server. `capabilities(appId)` queries the app's authenticated `/.sdk` endpoint.
An old app or an unreachable server produces `status: "unknown"`; a different
SDK major produces `unsupported`. Task helpers require the app's advertised
task capability. Existing `window.QwenPaw` and `paw` entry points are preserved.
Import `@qwenpaw/plugin-sdk/globals` only if your project wants a global Window
declaration; ordinary named imports do not modify global types.

The new `tasks(appId)` operates on SDK `/tasks` routes and true host run IDs.
The older `paw.api.task(customPath)` protocol remains separate and unchanged.
All declarations referring to React use the explicit `@types/react` peer.
Use `tsc --noEmit --strict --target es2020 --moduleResolution bundler
--module esnext --lib es2020,dom --esModuleInterop your-plugin.ts` to check an
author project outside the QwenPaw repository.

`registerRoutes` accepts `label: string | ((locale: string) => string)` and an
optional `title` with the same shape. The host resolves these pure callbacks
using the current Console language when rendering navigation and page titles;
do not read `navigator.language` or call React hooks during registration.
Existing string labels remain unchanged, and omitting `title` preserves the
host's path-derived title.


Theme overrides accept the six original roles (`bg`, `surface`,
`surface-raised`, `border`, `text`, `text-secondary`) at any SDK version. The
semantic colour roles (`accent*`, `success*`, `warning*`, `error*`, `info*`,
`surface-subtle`, `surface-sunken`, `shell-bg`, `text-tertiary`,
`text-quaternary`, `border-subtle`, `border-strong`) require SDK 1.2 and the
`themeTokens` capability. Every role must supply both `light` and `dark`;
unknown names are rejected rather than ignored, so a typo fails loudly.

What an override does not reach: this is a colour surface, not a full UI theme.
Only the roles listed above participate — every other `--app-*` name stays
internal, and layout, spacing, typography, iconography and chart palettes are
out of scope. Host markup that hardcodes `rgb()`/`rgba()` instead of referencing
a token will not follow the override, and neither will anything a third party
paints itself (canvases, embedded charts, plugin-owned component libraries that
ship their own colours). Declaring `themeTokens` therefore means "this plugin
restyles the surfaces that use these roles", not "this plugin rethemes the whole
console".

Harness Settings extensions require SDK 1.1. Import `HarnessSettingsProps` and
`getHost` from this public package and register through
`getHost().harnesses.register(pluginId, extension)`. The host renders only the
selected available backend whose authoritative catalog owner matches that
plugin. Disabled, failed or unknown owners remain inert. `host.fetch` supplies
current authentication and Agent identity; do not copy private Console clients
or maintain an independent token. Dispose registrations on cleanup; stale handles
cannot revoke replacement contributions. The optional Codex/Qoder account UI and
locale text belong to their plugin bundles, not this SDK or the core Console.
