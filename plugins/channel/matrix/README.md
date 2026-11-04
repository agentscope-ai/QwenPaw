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

## Dependencies and encryption

`requirements.txt` is the single mandatory dependency list. Matrix requires
matrix-nio 0.26 with its E2EE dependencies and `httpx>=0.27.0`; Markdown HTML
uses `markdown-it-py` and `linkify-it-py`, with escaped plain HTML fallback.

The E2EE dependencies, including vodozemac, are installed by default with the
Matrix plugin and the `channels`/`full` Python extras. The Matrix `encryption`
configuration still defaults to `false`; enabling it requires no additional
package installation.

If an upgraded or damaged runtime lacks the required backend, startup logs an
error and sets `encryption=False`, preserving the existing plaintext fallback.
A missing usable device identity can also disable E2EE. An initial key upload
rejection prevents a connected startup. Maintenance, room-state encryption
checks and the previous warning behavior remain.
Live encrypted-peer interoperability is not claimed by migration acceptance.

## Authentication and state

Explicit `user_id` plus password takes precedence over `access_token`.
Tokens are checked with `whoami`; a configured user mismatch is rejected.
Transient login failures retain the 5-second initial / 60-second capped retry
schedule and stop interrupts backoff. Startup keeps `restore_token=False`:
existing auth JSON does not silently enable cached-token login.

The official factory supplies an authorized `workspace_dir`. Files live in
`workspace_dir/channel_state/matrix/<sha256(homeserver, user, device)>/`.
`auth.json`, `sync_token` and `owner.json` belong to that workspace, account and
device; crypto remains in `crypto_store`. Passwords are never persisted.
Existing workspace state is preferred, including when switching accounts and
later switching back.

A trusted execution-only `legacy_state_dir` may refer to the old host global
working directory. If its `matrix_auth_state.json` user and device match the
live authenticated identity, the sync token and matching crypto store are copied
into the workspace. Legacy files remain unchanged, and the new login token is
saved instead of the old token. A mismatched legacy identity is skipped without
blocking the current account from creating independent state.

OS advisory locks protect the active workspace and account/device only while
running. Stopping or exiting releases the device lock, so another workspace can
then use it. Device metadata identifies the most recent workspace so a handoff
copies its latest sync and crypto state rather than the stale legacy snapshot.
Historical owner/capture JSON files do not create a persistent startup block.
Use a distinct Matrix device per workspace when independent devices are
intended. Unsafe SDK crypto filenames are rejected explicitly.

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
