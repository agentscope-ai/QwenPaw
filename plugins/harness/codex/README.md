# Codex Harness

Optional `qwenpaw-harness-codex` plugin for QwenPaw SDK 1.1 / QwenPaw 2.3.0b1
or later. It provides backend `codex`, independently of the Qoder plugin.

Install this plugin explicitly through QwenPaw's plugin manager. Its pinned
`openai-codex==0.144.4` dependency supplies the Codex executable on supported
platforms; a standalone executable can be selected through the `binary` setting
or `CODEX_BINARY`. Dependency preparation belongs to explicit plugin installation
or repair, never ordinary host startup. Listing/registering the backend does not
resolve a binary, start a process, or create the backend.

After installation, select Codex for an agent. Existing Codex model, reasoning,
approval/sandbox settings and native account remain valid. The backend forwards
text, reasoning, tools, image/file attachments, model/effort selection and the
`compact`, `review`, `skills`, `status`, `new` and `clear` commands. Account login
and logout are explicit management operations. Approvals use the current host
call's public approval callback; unknown or completed calls cannot request them.

Each workspace stores its mappings in
`plugin-data/qwenpaw-harness-codex/codex_sessions.json`. On its first actual open,
a missing target is atomically copied from `harnesses/codex_sessions.json` after
validation. The old file remains untouched and an existing new target wins.
Corrupt state raises an error instead of replacing it with an empty map. Legacy
plain session mappings are claimed once into trusted user/channel/session keys;
a different user or channel with the same session ID receives its own thread.
Regenerable projection configuration stays in memory; native Codex account and
thread data are not moved or deleted by plugin disable/uninstall/close.

PawPort requires this plugin to be active before inspecting Codex sources. Its
online operations use the host's admitted archive facade. The existing explicit
source-home local-only behavior and rollout recovery remain available after that
plugin check; this plugin does not introduce an import path without the plugin.

For development, install `requirements-test.txt` in an isolated environment
containing the host SDK, then run `python -m pytest plugins/harness/codex/tests`.
Tests use synthetic app-server messages, temporary state and public SDK contexts;
they do not require a Codex account or launch the real executable. CLI/platform
acceptance is a separate release check.

The native host and `full` extra do not include or enable this backend. The
transitional `qwenpaw[codex]` extra only prepares Python dependencies; it does
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

Build the frontend and package both Harness ZIPs from the repository root:

```sh
bash scripts/pack/build_harness_frontends.sh
python scripts/pack/generate_plugin_metadata.py --plugins-root plugins --dist dist/plugins \
  --metadata-out dist/plugins/index.json --only qwenpaw-harness-codex --only qwenpaw-harness-qoder
```

In an environment containing only this plugin's pinned vendor SDK and the host
SDK, run `python -m pytest plugins/harness/codex/tests/test_codex_harness.py -q`.
This includes installing the built ZIP through the host; a missing ZIP fails the
test. Live account and packaged desktop checks remain release acceptance steps.
