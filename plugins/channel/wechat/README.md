# WeChat channel plugin

Official descriptor-based iLink plugin using the shared channel worker. Static
catalog, environment configuration, authentication custody and host QR sessions
are integrated. The host owns Agent execution, ACL, queues and conversation
history; the worker owns platform HTTP, AES, polling and message delivery.

The worker preserves the `wechat` channel and `wechat:<sender>` /
`wechat:group:<group>` sessions. It uses a configured token first, then reads
`bot_token_file`, and starts QR login when both sources are empty. The token
file defaults to `<workspace>/wechat/wechat_bot_token`. The reply cache always
lives at `<workspace>/wechat/wechat_context_tokens.json`, including when a
custom token file is configured. Console QR login saves the token to the
agent's `agent.json`.

Existing root-level files stay in place. To reuse an old token file, set
`bot_token_file` to its path or scan again. Incoming messages rebuild the
reply cache. An expired token requires reauthentication. Stopping retains
these files, configuration and media.

The private client requires `httpx` and `pycryptodome`. Network and AES operations
run in the channel worker. Explicit static QR fetch/poll and reachability verify
use short-lived clients without reading or writing runtime authentication files.
Credential verification is unsupported. Runtime initial QR login uses the host
connection budget and waits for confirmation before reporting connected.

Text merge uses the shared host policy: text is deferred and coalesced, media is
sent immediately, and the final text is stripped and prefixed once. There is no
private merge buffer or provisional platform acknowledgement. Platform sends use
the durable response journal; an unknown delivery is not replayed. Polling and
typing tasks are owned and awaited on shutdown, and cleanup failures retain
resource references. Media paths must be under the authorized workspace or
configured media directory.

The four old Core implementation files and the host platform QR fallbacks have
been retired. Independent verification maps 94 direct, 19 inherited and 44
adjacent responsibilities, including explicit worker, protocol and lifecycle
contract changes. These 157 mapped responsibilities are not 157 newly run tests.
The C1–C7 simulated scope includes the installed official ZIP through the real
Loader, worker, host queue/ACL, Runtime and QwenPawAgent, plus QR, protected
workspace credential saving and lifecycle checks. C8 distribution acceptance and
a live WeChat account have not been established. The
[migration plan and acceptance index](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md)
records the verification scope.
