# Antigravity Harness Plugin

Optional `qwenpaw-harness-agy` plugin for QwenPaw SDK 1.1 / QwenPaw 2.3.0b1
and later.

## Runtime contract

Registration in `main.py` is pure and opens no subprocesses or filesystem state.
The plugin drives the Antigravity CLI through its Agent Client Protocol server
(`agy acp`): one server process per working directory (or per conversation when
MCP servers are attached), and one ACP session per QwenPaw conversation
identity.

- Session mappings live in plugin storage at
  `plugin-data/qwenpaw-harness-agy/agy_sessions.json`. A missing target copies
  the legacy `harnesses/agy_sessions.json` once without mutating or deleting the
  original file.
- Session state is keyed by `[user_id, channel, session_id]`, isolating
  conversations across users, channels, and workspaces.
- Approval presets map to `default`, `accept-edits`, `plan`, `auto`, and
  `bypassPermissions` (which launches `agy acp --dangerously-skip-permissions`
  so subagent tool calls do not stall waiting on approvals that never reach the
  ACP client).
- Model, thinking level (`thought_level`), and permission mode are applied per
  turn via ACP session config options.
- QwenPaw MCP servers are projected into ACP sessions (`stdio` with optional
  working-directory wrapper, plus `http` / `sse` when advertised by the ACP
  server).
- Workspace identity and memory files (`SOUL.md`, `PROFILE.md`, `MEMORY.md`,
  and any truncated remainder of `AGENTS.md`) plus host background-work rules
  are appended to the CLI's system prompt via ACP `_meta`.
- Active login credentials are fingerprinted without storing secrets so
  switching Google accounts via `agy acp --login` recycles idle servers and
  refreshes cached status/models.

The host owns backend close. Calls bind permissions to their live public call
context and cancel/await pending approvals on exit. Close stops owned `agy acp`
subprocesses without logging out or deleting Antigravity's native sessions.
Reset affects only its admitted conversation identity.

## Frontend build

The plugin owns its locale assets and wraps the private shared settings panel
and connection hook in `../_shared/ui`. Each frontend bundles its own copy; the
installed plugin has no runtime dependency on another Harness plugin.

```sh
cd frontend
npm install
npm install --no-save --package-lock=false ../../../src/qwenpaw/plugins/frontend
npm run build
```

## Core tests

Build the frontend and package the Harness ZIP from the repository root:

```sh
bash scripts/pack/build_harness_frontends.sh
python scripts/pack/generate_plugin_metadata.py --plugins-root plugins --dist dist/plugins \
  --metadata-out dist/plugins/index.json --only qwenpaw-harness-agy
```

Then run:

```sh
python -m pytest plugins/harness/agy/tests/test_agy_harness.py -q
```

## Shared IO helper maintenance

Edit only `plugins/harness/_shared/io_helpers.py`, then run from the repository
root:

```sh
python scripts/pack/sync_harness_helpers.py --write
python scripts/pack/sync_harness_helpers.py --check
```
