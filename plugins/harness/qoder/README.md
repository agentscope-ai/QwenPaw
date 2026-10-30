# Qoder Harness

Optional, workspace-owned Qoder backend using the public QwenPaw plugin SDK 1.1
and `qoder-agent-sdk==1.0.9`. Install this plugin separately from the native
QwenPaw runtime. Registration declares metadata only; the first actual operation
opens state, resolves the CLI and creates SDK clients as needed.

The backend preserves Qoder streaming, compact, attachments, PAT/browser login,
models and reasoning effort, permission callbacks, read-only Skill discovery,
and effective QwenPaw Skill/MCP projection. Noninteractive logout and provider
MCP discovery are explicitly unsupported by the SDK integration.

Session mappings live in this workspace's
`plugin-data/qwenpaw-harness-qoder/qoder_sessions.json`. A missing target copies
and validates `harnesses/qoder_sessions.json` without altering it. Existing valid
target state wins; null or corrupt state is rejected without overwriting files.
Legacy session keys are claimed once by a trusted user/channel/session identity.
Other users, channels and workspaces get separate clients and mappings.

The host owns backend close. Calls bind permissions to their live public call
context and cancel/await pending approvals on exit. SDK clients, login/status
processes and filesystem operations remain owned until cleanup actually finishes;
close does not log out or delete Qoder's native conversations. Reset affects only
its admitted conversation identity. Async client state stays on the event loop;
bounded local filesystem/discovery operations run in workers and finish before
cancellation releases their owner or mapping lock.

Run plugin tests in an isolated environment with the host SDK and test
requirements installed. Tests use fake clients and inert process fixtures;
real accounts, CLI operation and platform release acceptance are separate checks.
The native host and `full` extra do not include or enable this backend. The
transitional `qwenpaw[qoder]` extra only prepares Python dependencies; it does
not install the plugin. Install the verified plugin ZIP separately. Disable or
uninstall preserves saved Agent settings, materialized history, plugin data and
the vendor's native account. A saved Agent with an unavailable backend remains
manageable and returns an explicit unavailable error when run.

For an upgrade from the old builtin backend, stop the old host and prepare the
verified plugin package and its matching offline dependencies before starting
the new host. Run the shared migration first with `--dry-run`, then `--apply`:

```sh
QWENPAW_WORKING_DIR="$HOME/.qwenpaw" qwenpaw plugin migrate-legacy-harnesses \
  --plugin-dir /path/to/verified-local-packages --dry-run
QWENPAW_WORKING_DIR="$HOME/.qwenpaw" qwenpaw plugin migrate-legacy-harnesses \
  --plugin-dir /path/to/verified-local-packages --apply
```

The installed CLI uses the working directory selected before process startup.
The source distribution also provides `scripts/pack/migrate_legacy_harnesses.py`
with an explicit `--working-dir`. Both entry points use one implementation and
the formal offline installation transaction. Only used backends are planned;
explicit disable wins, repeated apply is idempotent, and missing packages or
dependencies produce installation actions without replacing Agent/data files.
The migration does not download dependencies or activate resources. Existing
automatic desktop updates do not perform this preparation; a skipped preparation
requires explicit plugin installation and is not a seamless upgrade.

## Frontend build

The plugin owns its account settings, authentication polling and locale assets.
The Console renders this settings component only for its selected active owner.
API calls use public `host.fetch`, preserving Bearer authentication and the
selected Agent header. No private Console imports or copied SDK types are used.

Install normal build dependencies, then the actual public SDK npm directory
(exported from the installed host with `python -m qwenpaw.plugins.check .
--frontend /path/to/qwenpaw-plugin-sdk`):

```sh
cd frontend
npm install
npm install --no-save --package-lock=false /path/to/qwenpaw-plugin-sdk
npm run build
```

For checkout validation the public SDK directory is
`src/qwenpaw/plugins/frontend`. Release builders must explicitly prepare that
same exported package before building. `frontend/dist/index.js` is the actual
self-contained manifest entry; source/build files are excluded from the runtime
archive. Build before packing. Registration uses SDK `harnesses.register` and
host cleanup disposes the extension when disabled or removed.

## Core tests

Build the frontend and package both Harness ZIPs as described in the
[Codex build commands](../codex/README.md#core-tests). In an environment containing
only this plugin's pinned vendor SDK and the host SDK, run
`python -m pytest plugins/harness/qoder/tests/test_qoder_harness.py -q`.
The suite installs the built ZIP through the host; live account and packaged
desktop checks remain release acceptance steps.
