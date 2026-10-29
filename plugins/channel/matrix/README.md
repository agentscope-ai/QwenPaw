# Matrix channel plugin

This official descriptor-based plugin uses the schema v2 shared worker, dependency
interpreter, RPC transport and `SharedResponseDriver`. The host retains Agent
execution, the queue, ACL, display rendering and response coordination.
`driver.MatrixDriver` imports the Matrix platform only when started; importing
the package or reading `channel.json` does not import matrix-nio or connect.

The descriptor retains all 32 `MatrixConfig` fields, their defaults, enums and
constraints. There is no model `device_id` field. The platform still accepts
that legacy raw runtime input; otherwise `device_name.strip()` is the fallback
device ID and the server's returned device ID takes precedence. The retained
model defaults are `enabled=False`, `vision_enabled=True`; legacy raw inputs
that omit them still use `enabled=True`, `vision_enabled=False`.

## Dependencies and optional encryption

`requirements.txt` is the single mandatory dependency list. Ordinary Matrix
requires `matrix-nio>=0.25.0` and `httpx>=0.27.0`; Markdown HTML uses
`markdown-it-py` and `linkify-it-py`, with escaped plain HTML fallback.

E2EE is an explicit optional installation in the selected shared interpreter:

```sh
python -m pip install 'matrix-nio[e2e]>=0.25.0'
```

Configure the optional encryption dependencies for the matrix-nio version in the
selected interpreter. Native availability differs by OS and Python version;
ordinary Matrix installation does not force this extra on every OS. Startup
checks the real `nio.crypto.ENCRYPTION_ENABLED`
flag. As in the old implementation, a missing backend logs an error and sets
`encryption=False`; a missing usable device identity can also disable E2EE.
This migration does not introduce a new policy that forbids plaintext fallback.
An initial key upload rejection prevents a connected startup. Maintenance,
room-state encryption checks and the previous warning behavior remain.
Live encrypted-peer interoperability is not claimed by migration acceptance.

## Authentication and state

Explicit `user_id` plus password takes precedence over `access_token`.
Tokens are checked with `whoami`; a configured user mismatch is rejected.
Transient login failures retain the 5-second initial / 60-second capped retry
schedule and stop interrupts backoff. Startup keeps `restore_token=False`:
existing auth JSON does not silently enable cached-token login.

The official factory supplies an authorized `workspace_dir`. New files live in
`workspace_dir/channel_state/matrix/<sha256(homeserver, user, device)>/`.
`auth.json`, `sync_token` and `owner.json` are owned by that workspace/account/
device; crypto remains in `crypto_store`. Passwords are never persisted.
Small response routing/receipt data uses host state; crypto databases do not.
OS advisory locks protect the active workspace and account/device. A durable
claim under the trusted legacy state root (when supplied) prevents silently
selecting a second workspace for the same device; use a distinct Matrix device
per workspace. Without that root, the OS temporary directory is the fallback
claim registry. It provides concurrent exclusion but cannot promise durable
device ownership after OS temporary-file cleanup; trusted host projection is
therefore also required for the complete persistent ownership guarantee.
Existing claims are not deleted or stolen on start failure.

A trusted execution-only `legacy_state_dir` may refer to the OLD host global
working directory. It is not a configuration-model or descriptor field. The
worker does not guess this directory from its HOME or import `WORKING_DIR`.
Without the trusted host projection, only new workspace state is used and
legacy compatibility is not complete.

The compatibility reader understands `matrix_auth_state.json`,
`matrix_sync_token` and `matrix_crypto_store`. The old auth JSON has no
homeserver metadata. Before repairing/migrating persisted configuration, Core
captures the historical homeserver and a unique workspace assignment in
`<legacy_state_dir>/channel_state/matrix/legacy-capture.json`. This immutable
capture stores the old auth file's SHA and configuration provenance, never the
cached token or password. Without persisted profiles the workspace is
`<legacy_state_dir>/workspaces/default`; otherwise only real persisted profiles
are candidates. A missing agent.json inherits the old global channels, while an
existing file without Matrix does not invent an account. Multiple compatible
workspaces/homeservers remain unresolved; full configured MXIDs that differ
from the old hint are excluded, and local login aliases are not guessed into MXIDs.

The official owner-gated host projection provides a bounded execution-only
`legacy_state_owner` authorization. Password login may return a fresh token:
the actual authenticated user/device must still match the old hint and captured
owner, the homeserver/workspace must match, and the old auth bytes must retain
their captured SHA. The reader rechecks this proof under the existing legacy
claim lock before writing the durable owner. A matching persisted
`matrix_plugin_owner.json` then permits authenticated restarts. Configuration
changes or plugin reinstalls never recapture or reassign old state. Missing
capture is read-only and permits fresh installations, but cannot authorize old
global state. Corrupt capture fails Matrix with `MATRIX_LEGACY_CAPTURE_INVALID`
and does not stop other channels' policy initialization.

Direct private drivers without trusted capture retain the earlier explicit-token
proof: only an explicitly configured token matching the old token may be checked
against this homeserver. Unproven password adoption still reports
`MATRIX_LEGACY_OWNER_UNVERIFIED`. No path sends an unrelated cached token to a
new homeserver. Conflicting owner/account/device/database files remain intact.

A verified legacy crypto directory is used in place. Databases, device trust
files and sessions are never copied to every Agent, overwritten or stuffed in
host state. New sync/auth writes use the private workspace directory. A durable
legacy owner claim and live file lock prevent a second workspace from claiming
the same old database. Unsafe SDK crypto filenames are rejected explicitly.

## Retained platform behavior and boundaries

- Sync preserves callback-suppressed initial catch-up, offline events when a
  saved token exists, invite joins, E2EE maintenance and invalid-token failure.
- Room-key requests, SAS start/key/MAC/cancel, raw verification request/done,
  key-share flushing and bounded verification caches retain the old algorithm.
  The old automatic local SAS confirmation behavior remains; users still
  compare and confirm the challenge in Element. Failed ready/done replies
  retain peer data so a later retry can complete.
- DM membership prefers joined-members API with the same TTL/LRU fallback.
  Room overrides use exact room then `*`, `autoReply` and `requireMention`.
  Group history and media are bounded; history clears only after host ACK.
  `/reset` remains `/clear`, known commands bypass history, and `NO_REPLY` is
  suppressed. Sessions remain `matrix:<room_id>`; shared groups use room user
  identity, while disabling sharing uses the real sender as group user identity.
  ACL always receives the real Matrix sender.
- MXC downloads, encrypted attachment decryption, vision image downgrade,
  audio/video/files, data URLs and upload metadata remain platform operations.
  Download names are constrained to the authorized media directory; outbound
  local files must be inside the workspace or its host-projected media root.
  HTTP media upload/download is not a newly claimed capability.
- Markdown becomes escaped Matrix HTML and structured mentions scan actual
  body MXIDs. The legacy implementation did not consume `group_allow_from`,
  `mention_pill_in_body` or `outbound_structured_mentions`; retaining these
  config fields does not claim new behavior for them. Host display/ACL policies
  continue to use the common pipeline.
- `content_source` preserves direct versus content-parts/media presentation;
  host `SendFormatPolicy` owns prefixes and rendering. Streams create `...`
  and edit the same Matrix event with `m.replace`. Each response and stream
  keeps its own typed room/event resource. An unknown edit is journaled and
  cannot be replayed or turned into a new-message fallback. Definitely unsent
  failures remain distinguishable from uncertain/partial sends.
- Typing renews every 25 seconds with a 30-second server timeout and 120-second
  cap. Owners share one room indicator, and finishing one response cannot stop
  another owner's indicator. Read receipts use read plus fully-read markers.
  Stop closes admission, cancels/awaits instance sync, verification/maintenance,
  typing, in-flight HTTP and owned decoder work, then closes SDK HTTP and crypto
  database resources. Failed stop retains the platform and claims for retry.

The official catalog, environment reader and owner-gated legacy-state projection
are integrated. Explicit relative `media_dir` paths are projected against host
CWD before worker startup, without rewriting saved configuration. The two old
Core implementation files have been retired after normal test entry transfer.

Independent C1–C7 simulated acceptance covers the installed official ZIP through
the real Loader, Manager, worker, ACL/queue, Runtime, QwenPawAgent and Session,
native Matrix HTTP, ordinary versus explicit API failures, response uncertainty,
two-account/workspace isolation, and lifecycle rollback. The recorded scope is
30 new passing cases across separate epochs, reusing prior private71 and nine
C6 cases; the102 mapped original responsibilities also identify static and
composed evidence and are not102 freshly executed old nodes. Live homeserver and
encrypted-peer interoperability, native vendor dependencies and C8 distribution
acceptance remain unproven. The
[migration plan and acceptance index](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md)
records the verification scope.
