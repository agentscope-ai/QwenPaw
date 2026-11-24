# QQ channel plugin

Shared-worker QQ gateway messaging and one-shot Portal QR binding. Configure
`channels.qq.app_id` and `client_secret`; existing channel/session keys and the
C2C, group, guild and guild-DM targets are retained. Install dependencies through
the normal plugin installer. Starting the channel never installs packages.

The worker uses websocket-client, HTTPX and AESGCM. The host retains Agent
execution, sessions, ACL and approval decisions. SDKs and gateway/media/Portal
I/O run in the worker. With `streaming_enabled` the worker streams C2C replies
through the official `stream_messages` API (`input_mode=replace`, `input_state`
1 → 10, incrementing `index`, server-issued `stream_msg_id`). Group, guild and
guild-DM targets keep the completed-message path because QQ documents streaming
for single chat only. The plugin never types, edits or recalls messages.

Streaming covers both `message` and `reasoning` response streams; each response
stream owns its own stream message and the `stream_type` recorded at
`stream.start` is validated on later slices. The worker reserves each update
index before sending so an unknown result cannot cause index reuse. The shared
cleanup hooks close an open stream with a final `input_state=10` slice. If the
outcome of a closing slice is unknown, cleanup preserves the delivery evidence.

The first slice with real text opens the QQ stream. QQ rejects `replace`
slices that change the delivered prefix (`40007`), so the worker keeps that
prefix when Scroll headline removal changes whitespace. Empty replies finish
locally. When QQ explicitly rejects opening the stream, the host sends the
complete reply as a regular message. The descriptor declares the `streaming`
capability so the host can enable the streaming policy.

Text supports the original bounded chunks and explicit QQ validation fallback.
C2C/group upload rich media; group cannot send type4 files (including ordinary
audio). Guild/DM send images and video by URL or multipart, and cannot send
audio/files. Local media is confined to the authorized workspace/media root.
Ambiguous or partial sends return unknown and are never blindly replayed.

Approval clicks receive neutral acknowledgments. A confirmed per-card source
binding and the actual clicker are required for a privileged result presentation;
only the host's typed resolution can display Approved/Denied. An unavailable
binding uses an ordinary native-actor command/result where a native route exists.

Static `QQDriver.manage` implements `qrcode.fetch` and `qrcode.poll` without
starting the gateway or writing credentials. Credentials return to the exact
host-managed workspace/source session. Credential verification is not advertised;
the existing doctor TCP probe is only reachability.

Historical QQ_API_BASE, QQ_TOKEN_URL and QQ_PORTAL_HOST reads remain. The generic
trusted launch environment supplies these values to the worker. Official catalog,
environment configuration and host QR credential saving are integrated. Explicit
relative `media_dir` paths are bound to host CWD without rewriting saved
configuration. The six old Core implementation files have been retired after
independent normal-entry and shared-helper transfer.

Independent C1–C7 simulated acceptance covers the installed official ZIP through
the real Loader, Manager, worker, ACL/queue, Runtime, QwenPawAgent and Session,
native gateway/media/Portal traffic, actual Core approval authority, two-account
and workspace isolation, and lifecycle rollback. The ledger preserves 276 original
records and 537 oracle entries; composed/source mappings and explicit typed
contract changes are distinguished from newly executed cases. This is not a
claim that every old timer, synthetic SDK failure or card callback branch was
freshly replayed. Original AppHTTP integration bodies remain preserved.

Live QQ platform interoperability and C8 distribution acceptance remain unproven.
The [migration plan and acceptance index](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md)
records the verification scope.
