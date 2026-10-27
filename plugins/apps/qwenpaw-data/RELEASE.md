# Standalone Data app 1.0.3

## Compatibility and release order

| Component | Version / branch |
| --- | --- |
| Stable QwenPaw platform | 2.2.2 |
| Data app | 1.0.3 |
| QwenPaw-Data Python packages | 0.3.3, coordinated across all four packages |
| QwenPaw-Data release branch | `release/v0.3.3` |
| QwenPaw app release branch | `release/data-app-1.0.3` |

1. Review and merge the QwenPaw-Data release branch; publish its four 0.3.3
   packages and `v0.3.3` tag.
2. Review and merge the QwenPaw Data app branch. The app release workflow uses
   the Engine `v0.3.3` Context console source; a missing tag stops packaging.
3. Install the app and run `scripts/setup-pypi.sh` to upgrade the runtime.
   For branch testing before publication, use `scripts/setup-dev.sh` with
   `QWENPAW_DATA_SOURCE_DIR` pointing to the matching Engine release checkout.

Creating these branches does not publish packages or update the marketplace.

## Included behavior

- Runtime 0.3.3 keeps chat streams open until the final response is available,
  fixing a race that could hide completion or failure from the client.
- Runtime dependencies support Neo4j driver 6.x and OpenAI SDK 3.x; the
  Context console includes the latest validated frontend dependency updates.

- Data analysis follows the Main Chat workspace model by default. Summaries
  and DataBridge follow the analysis model. Optional overrides reference Main
  Chat providers; credentials resolve server-side for each new turn.
- Existing runs retain their model. Later turns pick up changed model choices
  without discarding the session agent's memory.
- Dataset reload queries the selected datasource's catalog. Selected datasets
  are persisted with each chat and supplied to the agent.
- Engine session access is scoped by authenticated user, workspace, and app.
  Session IDs alone do not grant access. Identity hashes match the vNext app.
- Sidecar environment isolation is implemented inside this app, using the
  stable SDK's managed-service lifecycle. Private environment files are mode
  0600 on POSIX and refresh before each managed start. Host process settings
  are unchanged. Windows runs the service module in the supervised Python
  process, preserving its PID for startup, shutdown, and restart.
- Missing or unsupported Main Chat model selections return an actionable
  HTTP 409 before an analysis is submitted, rather than an internal error.

## Separate vNext work

This release invokes `/api/v1/console/chat` and the existing native
stream/cancel/clarification APIs. It does not register generic Host task actions
or require the vNext Host task store, delegation, continuation, permission
grants, or artifact broker. Native console admission retains the Engine's
existing semantics; it does not offer vNext's durable, idempotent submissions.
The existing legacy `/data` bridge remains available.

The QwenPaw diff is limited to this app, its tests, its optional runtime package
minimums, and its release workflow. Shared `src/qwenpaw`, Main Chat console,
Creator, and other apps are outside this branch.

## Validation

- Run `tests/unit/pawapp/test_qwenpaw_data*` using stable QwenPaw sources.
- Run the Engine host-core suite and Context runtime-binding/auth tests using
  the matching Engine release checkout.
- Run `npm ci`, `npm test`, and `npm run build` in `ui/`.
- Run `scripts/verify-data-console.py` and build the public Context console
  with `scripts/sync-context-ui.sh` before packaging.
- Verify session ownership, private model binding, per-turn model refresh,
  selected dataset context, and actual sidecar startup before publication.

An Engine without the scoped-console capability contract fails explicitly;
the app never falls back to an unscoped legacy Engine.

## Existing data

Sessions created by the scoped vNext app use the same identity namespace.
Older unscoped Engine sessions are preserved on disk but are not automatically
assigned to the current user or workspace, so they will not appear in the new
scoped listing. Back up the app data directory before upgrading; any legacy
session migration must explicitly establish its owner. Existing app-specific
model settings remain available under Advanced; the new default is workspace
model inheritance.
