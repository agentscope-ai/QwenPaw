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
