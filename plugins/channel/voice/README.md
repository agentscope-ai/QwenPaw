# Voice channel plugin

Twilio ConversationRelay transport with a namespaced `VoiceDriver` extending the
real shared response driver. Core owns Agent execution, ACL, queues and response
journals. The child owns Twilio validation and HTTP calls, the three ingress
routes, one-time WebSocket tokens, native call connections and the Cloudflare
tunnel. It does not run a BaseChannel, Agent, v1 lifecycle controller or lease.

This is the official descriptor-based shared-worker implementation.
The descriptor retains all 26 actual VoiceChannelConfig fields and defaults;
there is no new streaming_enabled field. Dependencies have one requirements file:
aiohttp and Twilio. No SDK or tunnel starts on import or disabled start.

## Public ingress dependency

The paths remain `/voice/incoming`, `/voice/ws` and `/voice/status-callback`.
The child registers its real listener with Core and requires the frozen A3
`forwarding` binding in the register ACK: route_query_key, route_selector,
host_port, three paths and bridge_token. Missing binding raises
`VOICE_HOST_FORWARDING_UNAVAILABLE` **before tunnel creation or webhook apply**.
A1 endpoint ACK alone is insufficient. The tunnel targets the supplied host API
port, never the child listener or a remembered/default API port.

Public URLs include the opaque selector; WebSocket URLs also include the existing
single-use token. The child requires the generation's bridge token in constant
time and uses the trusted original public URL, including its complete raw query,
for Twilio signature validation. It never trusts client-supplied forwarded-host or
forwarded-proto headers. Host ingress strips/overwrites context headers and binds
selectors to the real workspace/instance/generation. Scope-less URLs are only
compatible through Core's unique-candidate selection. Genuinely ownerless HTTP
incoming/status routes retain the legacy unavailable TwiML/empty 204 responses;
explicit selectors and active or fenced owners do not use that fallback.

## Calls and replies

Existing native limits remain 64 connections, 100 pending tokens, 60-second token
TTL, 32 queued events per connection and five-second shutdown work budget. A
connection/turn is bound to a shared response handle; the Driver also bounds active
turns to eight per call within the shared 128-route limit. Each new prompt advances
the connection sequence, even if its text repeats; IPC retries reuse the same event.
Setup, DTMF, interrupt and call close stay local. Interrupt is logged, not represented
as cancellation of a host Agent task.

Caller ACL identity is the actual phone number when available. Signed incoming
From/To are retained with the token and checked against setup. History remains
`voice:<CallSid>`; route
ownership additionally contains the exact connection, generation and turn. A late
old response cannot resolve a newly connected call with the same CallSid. If both
signed From and setup.from are empty, the explicit unknown-actor protocol retains
the empty actor. Open policy may accept ordinary conversation; restricted policy
and privileged approval reject it. No CallSid or fake ACL identity is substituted.

For completed events whose raw text is representable, Voice sends
`{type:text, token:text, last:false}` immediately followed by
`{type:text, token:"", last:true}` under the same connection write lock. Direct
text retains its single final token. Response finish completes a turn and does not
hang up the call. Actual disconnect/status/stop owns call closure. Uncertain first
or final writes remain unknown in the common journal and are not replayed.

The opt-in neutral raw-completed-text contract preserves original TEXT/REFUSAL
fragments from completed messages, including reasoning/tool messages. The private
relay retains its original truthy-fragment selection, strip and space-join behavior.
The native relay remains a text transport; no token-delta streaming is enabled by
default.

## Startup and cleanup

The moved runner-safe platform preserves webhook fetch/snapshot/apply and
ownership-checked rollback. It retains the snapshot through ready ACK, admission
confirmation and successful connected notification; only then is the transaction
committed. Startup failure restores only still-owned values, preserving user changes.
Normal stop does not roll back a committed webhook. Unknown rollback or unregister
results retain failure evidence and prevent a successful stopped receipt.

Listener, provisional sockets, native workers, tunnel, SDK HTTP session and cleanup
tasks retain their owner until settled. Cancellation-resistant cleanup is recorded
and retried without reporting it as complete. Native end is attempted at most once
per connection; close can be retried. Core enforces phone_number_sid ownership
using its existing RuntimeOwners, before external webhook/tunnel side effects.
Different SIDs may run independently under one account. The plugin does not
introduce a second registry or lease.

The official catalog/environment and host forwarding are integrated. Nine old
Core implementation files have been retired after independent test-entry transfer.
The ledger preserves all 66 direct and 19 inherited original responsibilities,
distinguishing executed cases, composed/source evidence and explicit v1/layout/
no-op contract changes; it does not claim 85 freshly executed old nodes.

Independent C1–C7 simulated acceptance includes the installed official ZIP through
the real Loader, Manager, worker, production router/ingress service, ACL/queue,
Runtime, QwenPawAgent and Session. Actual SDK signature checks, one-time WebSocket
tokens, native reply frames, two-workspace/SID ownership, external-resource cleanup
and activated-candidate rollback before host commit are covered. Provider REST,
model and cloudflared boundaries are controlled. The Voice WebSocket authenticates
its token and bridge context; independent Twilio WebSocket signature validation is
not claimed. Complete App/CLI/Desktop startup, live Twilio calls/public tunnels
and C8 distribution acceptance remain unproven. The
[migration plan and acceptance index](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md)
records the verification scope.
