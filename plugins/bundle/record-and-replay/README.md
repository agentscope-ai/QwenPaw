# Record & Replay

Optional QwenPaw plugin for macOS 14+. The first release records a minimized
desktop event stream, lets the user review the evidence, and creates a reusable
Skill after explicit consent.

## Ownership

- The plugin registers its own chat header control, settings page and
  `/api/desktop/recording` API family, including Learn review and Skill creation.
- The host supplies authentication, Agent context, plugin lifecycle and the
  existing Desktop Automation HostRuntime. React and Ant Design are shared host
  libraries; they are not bundled again.
- Recording uses `EventStreamClient` and the existing **QwenPaw Computer Use.app**
  Helper. There is no second Helper, TCC identity or legacy runtime fallback.
- Computer Use is a separate optional plugin. It is not required for recording
  or Skill creation; a generated Skill that performs desktop actions requires it
  at execution time.

Turning the feature off interrupts its own capture and cancels its in-flight
requests. Unloading the plugin also removes its UI/API registration. Neither
operation deletes recordings/Skills or stops another plugin's Helper. Merely
navigating away from the UI does not stop capture; use Stop or the native menu.

## Build and test

Use Node 22.13+ (or Node 24) and npm, from `frontend/`:

```sh
npm ci
npm test
npm run build
```

The build emits the checked-in `dist/index.js` entry inside the plugin
directory. The bundle includes its own styles and locale messages.
Frontend sources and `node_modules` are excluded from the distributable by the
existing plugin packer. The lockfile must contain registry dependencies, not
local host `node_modules` links.

Backend tests, from the repository root:

```sh
.venv/bin/pytest tests/unit/desktop
```

## Local integration

Build the frontend first, then package it with the repository's existing plugin
packer (which excludes `node_modules`). Install the resulting ZIP through the
existing upload flow, or install its extracted plugin directory. Do not install
the development source directory containing `frontend/node_modules`: the local
directory installer copies its full tree. The plugin requires the matching
QwenPaw desktop version because EventStream and the shared Helper capability are
provided by the desktop host.

Feature preference lives in
`<working_dir>/plugin_runtime/record-and-replay/feature_state.json`.
Recordings and generated Skills remain in their owning Agent Workspace.

The stable component boundaries and security invariants are documented in
`docs/design/record-and-replay.md`.
