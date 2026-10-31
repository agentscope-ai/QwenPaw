# OneBot v11 channel plugin

Official descriptor-based v2 plugin for NapCat, go-cqhttp and Lagrange reverse WebSocket
connections. The standard shared worker loads
`qwenpaw_channel_onebot.driver.OneBotDriver`. Dependencies are declared only in
`requirements.txt`: `aiohttp>=3.9.0` and `aiofiles>=24.1.0`.

The descriptor preserves all 25 `OneBotConfig` fields, defaults and constraints.
Enable the channel and configure `ws_host`, `ws_port` and `access_token`.
`127.0.0.1:6199` is the default; `/ws` and `/ws/` are supported. An empty bind
host uses loopback, IPv6 brackets are normalized, and a dynamic hostname bind
resolves to one deterministic address. External binding requires a nonempty
token; loopback also validates a configured token. Only Authorization
Bearer/Token headers are accepted, using constant-time comparison.

The child owns the listener, watchdog, native sockets, echo APIs, media and
per-session queues. Host Agent execution, ACL, task management and durable
admission/delivery journals stay in Core. Native events identify the real QQ
user for ACL. Sessions remain `onebot:<user>`, `onebot:<group>:<user>` or
`onebot:g:<group>` according to `share_session_in_group`.

The WebSocket reader handles echo replies immediately. Message preparation
runs in arrival order within each session while other sessions proceed
concurrently. Queues keep the original limits of 50 messages per session and
500 session workers, alongside the independent native event-task cap. Stable
native message IDs and shared IPC retry preserve event identity; messages
without a platform ID do not claim cross-push deduplication.

Inbound media retains four concurrent downloads, size limits, MIME/magic-byte
checks, safe names, atomic temporary-file rename, file/image/record URL APIs,
quoted/current media alignment and failure placeholders. Media storage uses an
explicit media_dir, then workspace/media, then DEFAULT_MEDIA_DIR. Local media
must belong to configured media/workspace roots. Outbound text retains native
Markdown-link cleaning and the common 3000-character splitter. The child keeps
received text/media/file ordering and the existing optional local-file base64
policy; data URLs keep their legacy conversion to base64://.

Endpoint registration uses `ingress.endpoint.register/update/unregister` and
the existing EndpointParams contract. The listener becomes connected/accepting
only after an actual ready bind and an acknowledged host registration. A port
conflict remains degraded for watchdog recovery. An external bind without a
token remains unavailable. Missing endpoint RPC handlers are an explicit start
failure, not a successful registration. Host ingress fencing and endpoint
revision ownership are a required public G4 dependency.

Outbound API timeouts and uncertain writes return truthful unknown receipts;
an uncertain write is not retried on another native connection. Shared
response lifecycle owns delivery deduplication and unknown replay fences.
OneBot has no extra native finish/card effect, so standard shared finish is
used. Stop disables ingress, cancels and awaits queues/API/readers/watchdog,
closes native connections and HTTP, and unregisters this exact identity.
Unconfirmed cleanup retains resources and fails stop.

The official catalog/environment reader, endpoint handlers/fencing and shared
ordered content-parts contract are integrated. Owner-gated execution projection
binds explicit relative `media_dir` paths to host CWD without rewriting saved
configuration. The five old Core implementation files have been retired;
independent Test owns the remaining normal-entry transfer to the v2 suites.

Independent C1–C7 simulated acceptance covers the unchanged installed ZIP through
the real Loader, Manager, worker, ACL/queue, Runtime, QwenPawAgent and Session,
native reverse WebSocket/API/media behavior, two-workspace isolation, lifecycle
rollback and uncertain delivery/resource ownership. The original 134 direct
responsibilities map to 117 proven responsibilities and 17 explicit contract
changes, with 19 inherited methods passing separately. These 153 responsibilities
are not 153 freshly run tests. In particular, v2 stop fences and cancels owned
work; it does not promise the old quiesce wait for an existing echo ACK. Disabled,
disconnected and uncertain explicit API calls retain truthful typed outcomes.

Live NapCat/go-cqhttp/Lagrange interoperability and C8 distribution acceptance
remain unproven. The
[migration plan and acceptance index](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md)
records the verification scope.
