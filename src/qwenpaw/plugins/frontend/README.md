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

## Added in 1.2.0

`getHost().chat.composer.read()` returns an immutable `ComposerSnapshot` for
the visible composer, or `null`. Keep that exact object and call
`composer.replace(snapshot, text)` after showing the result to the user.
The host returns `false` if the draft, model, conversation or binding changed;
typing and then undoing does not revive an old snapshot. No draft is modified
when replacement fails. The snapshot contains `agentId`, nullable `sessionId`
and `chatId`, `text`, and a monotonically advancing `revision`.

`composer.model()` resolves the current draft's QwenPaw provider model
(`provider_id`, `model_id`) without credentials. It returns `null` if the
composer changed during lookup or the host cannot provide a QwenPaw provider
model for the selection, as can happen with an external execution engine.
For an SDK PawApp request that
needs selected main-chat text or project directories, pass the snapshot's
non-null `chatId` as `X-Chat-Id` and its `agentId` as `agent_id`. The backend
checks the authenticated user's ownership; this does not grant arbitrary
session access. The Python `conversations.history()` API returns saved text
only and takes a bounded `limit`, not a session identifier.

For `checkpoints(appId)`, pass both `chatId` and `agentId` from the selected
saved conversation. Use the same pair for timeline, snapshot, preview, and
restore so they all target that conversation's workspace.

`getHost().host.selectAgent(agentId)` validates the current host list and uses
the normal workspace selection flow. It rejects unavailable workspaces and
will not overwrite a newer selection made while the request was pending.
The host's existing `menu.add()` and `route.add()` return disposable handles.
1.2 adds their missing standalone package declarations (`PluginMenuItem`,
`PluginRoute`) without introducing competing runtime registration aliases.


## Author checks (1.2.0)

After installing TypeScript in your frontend project, run:

```sh
npx qwenpaw-sdk-check ../plugin.json ./tsconfig.json
```

The command compiles the selected project with strict checking and compares
resolved SDK symbols' `@since` annotations with `plugin.json`'s `sdk.version`.
It follows imports, aliases, destructuring, global declarations and typed call
arguments, including a model option stored in a variable. Same-named third-party
methods are not SDK uses. New interface members inherit their interface's
introduction version. The checker never runs plugin code or compiler plugins.
It returns JSON and exits with 1 for findings, 2 for an input/tool failure.
TypeScript `>=5.8 <6` is an optional author dependency; the host does not need Node
or TypeScript to run plugins.

If the root `tsconfig.json` only lists project `references`, run the command
with each referenced `tsconfig` that includes plugin source files, for example
`npx qwenpaw-sdk-check ../plugin.json ./tsconfig.app.json`.

Run the Python SDK checker as well. This command checks only sources included in
the selected TypeScript project, not an omitted entry or deployed bundle. `any`,
casts and TypeScript suppression comments can conceal uses; this is a development
check, not a security boundary or a complete dynamic JavaScript proof. The Python
checker explicitly reports frontend checking as uncovered. Existing legacy
plugins are not rejected merely for lacking TypeScript sources.


Harness Settings extensions require SDK 1.1. Import `HarnessSettingsProps` and
`getHost` from this public package and register through
`getHost().harnesses.register(pluginId, extension)`. The host renders only the
selected available backend whose authoritative catalog owner matches that
plugin. Disabled, failed or unknown owners remain inert. `host.fetch` supplies
current authentication and Agent identity; do not copy private Console clients
or maintain an independent token. Dispose registrations on cleanup; stale handles
cannot revoke replacement contributions. The optional Codex/Qoder account UI and
locale text belong to their plugin bundles, not this SDK or the core Console.
