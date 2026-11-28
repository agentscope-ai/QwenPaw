# QwenPaw File Browser

A small PawApp reference implementation for bounded, read-only directory
listing. It exercises managed task execution, structured results, App-owned
setup and the frontend SDK without a model or external Engine.

## Dependency and delivery

This App is extracted from [QwenPaw #7874](https://github.com/agentscope-ai/QwenPaw/pull/7874)
and requires that PR's shared SDK. Its separate branch is based on main to keep
the App review independent. Rebase after #7874 merges, then rerun CI before
merging this App. The Data integration in #8363 is not a prerequisite.

This extraction preserves the existing implementation and manifest version;
it does not publish or install the App. Upstream attribution and source details
are retained in [UPSTREAM.md](UPSTREAM.md).

## Actions and configuration

- `browse-directory` is the public managed action, available to Main Chat and
  the App UI. It returns a structured, bounded listing of one directory.
- `list-directory` remains private for recovery of already accepted tasks;
  new callers use `browse-directory` and need a grant for its exact descriptor.
- An explicit directory can be supplied per request. If omitted, the App uses
  the saved default for the authenticated user and workspace.
- Missing defaults open the App's directory settings through the shared setup
  contract. Saving a directory preference does not authorize filesystem access
  or automatically start a listing; execution still checks the Host grant.

Listings are non-recursive and do not follow symlinks. The App does not provide
file editing, terminal execution or model-backed assistance. The Host retains
task identity, authorization and delivery; the App owns directory preferences
and its UI. The legacy adapter retains its own replay receipts for recovery.

## Verification

After applying this App on top of the SDK dependency:

```bash
python -m pytest -q plugins/apps/qwenpaw-file-browser/backend/tests
node --check plugins/apps/qwenpaw-file-browser/ui/index.js
```

The `PawApp File Browser Tests` workflow runs the same checks. Tests cover
bounded listings, symlinks, scoped preferences, revision conflicts, setup
receipts, replay, registration and structured managed-handler results. Generic
managed execution and setup tests remain in the SDK PR.
