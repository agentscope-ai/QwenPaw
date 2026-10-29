# SIP shared-runner plugin

Private schema-v2 SIP payload. The host keeps Agent execution, ACL, display,
commands, queues, and session history. This worker owns SIP/RTP, optional loopback
registrar, LiveKit, ASR and TTS. Audio never enters event.batch or host.state.

The descriptor preserves all 40 current SIPChannelConfig fields (Base17+23),
including their exact defaults and existing constraints. It does not invent an
enum for sip_mode/transport or ranges for the original plain integer ports.
Only exact `sip_mode=livekit` selects LiveKit; other modes select pyVoIP, as the
old backend factory did. Only exact `dev` with an empty sip_server starts the
built-in unauthenticated loopback registrar on 127.0.0.1:5060. The dev phone uses
sip_port (default5061); an external SIP server can use the existing host:port
syntax and SIP credentials. Two built-in registrars cannot share5060. Each dev
listener must use its own SIP port; binding failures and local OS resource-lock
conflicts reject startup instead of sharing a listener.

## Explicit dependencies

`requirements.txt` is the base `sip` dependency entry, matching pyproject:
pyVoIP>=1.6.0, dashscope>=1.0.0, dashscope-realtime>=0.1.0, and audioop-lts on
Python>=3.13. Install it into the chosen shared dependency runtime before use.
The existing application extra `qwenpaw[sip]` is equivalent. For LiveKit, the
explicit optional `requirements-livekit.txt` includes that base file plus
livekit>=1.0.0 and livekit-api>=0.6.0, equivalent to `qwenpaw[sip-livekit]`.
The v2 descriptor has no dependency profiles: normal admission reads the base
requirements file; selecting sip_mode does not install or select an environment.
Provision the optional entry explicitly for LiveKit. No automatic installer,
backend-specific process, or private RPC runtime is added.

Importing the Driver does not import pyVoIP, LiveKit, DashScope or audioop. Each
SDK loads only inside its selected backend/start or actual STT/TTS operation.
A disabled worker does not start native resources. The copied audioop shim is
loaded only for audio conversion or the pyVoIP start path.

## Calls, turns and delivery

Each transcript uses the normal shared event.batch path, stable sip:<call_id>
session and actual backend from_uri as both sender_id and ACL identity. Each new
transcript has a fresh opaque response handle and event ID; IPC retry retains
that same event ID. Connection epoch, generation and turn ID bind the response
to its accepted native call. There is no child Agent wrapper or host-cancel RPC.
Speech-start aborts only the current TTS. A new transcript creates a fresh abort
Event; old speech retains the old Event and cannot write into a new turn or call.

Completed text is cleaned with the original emoji/whitespace helper and spoken
through the original PCM conversions and framing: dev 8kHz/8-bit unsigned,
160-byte frames; LiveKit TTS24kHz/16-bit, 960-byte frames. The original backend
output sample-rate field remains consumed by LiveKit AudioSource; the old TTS
path's fixed24kHz behavior is preserved. No token-level TTS default is added.
Response finish releases the shared response lifecycle; it does not hang up.
Proactive sends can target an existing sip:<call_id> only and capture its current
connection at response-open. There is no outbound dialing implementation in the
old channel or this payload.

SharedResponseDriver owns its128-route journal, locks, ACK admission/retry,
unknown receipts and no-replay rules. Each call can retain at most32 unfinished
response routes. Missing/stale targets fail before audio. Once an audio write
may have occurred, an interrupted/failed result is unknown and is not replayed.
Only text is spoken; media, streaming, preparation and reactions are explicitly
unsupported. Native display rendering is not duplicated in the plugin.

Both native PCM queues keep the original150-frame/drop-oldest policy; pyVoIP
also bounds thread-to-loop pending PCM and posts at most one drain callback.
This policy does not apply to text: ASR keeps32 transcripts, dispatches them
serially and terminates the affected call with an explicit diagnostic on full
queue (or transcript>65536 characters). The TTS callback queue keeps64 chunks
and backpressures the SDK producer. SDK executor work remains awaited when
speech is aborted. Vendor/native operations that never terminate prevent clean
stop; the existing process supervisor owns timeout/forced-exit evidence.

LiveKit accepts one SIP/standard participant per room connection. Audio tracks,
disconnects and write closures require that exact participant and room epoch;
ignored participants cannot feed audio or terminate the accepted call. Different
room names can run independently. A normalized server+room OS file lock rejects
duplicate ownership among workers sharing the same host temporary directory.
The lock is held across reconnect and until cleanup succeeds, and is never
unlinked to bypass another owner. It is local-host custody, not a distributed
LiveKit lease; deployments on different hosts must allocate distinct rooms.

Stop fences new calls first, aborts playback, cancels and joins owned call,
timeout, ASR dispatch, audio-reader, backend callback/reconnect and TTS work, then
closes native backend/registrar resources. Cleanup failure retains the failed
resource references; it is not logged and converted into a successful stop.
Welcome greeting, idle timeout (positive values), concurrency cap (positive
values), SIP credentials and the original pure audio/text helpers are retained.
As before, sip_transport is present in the model but not consumed by the pyVoIP
factory; livekit_sip_trunk_id is stored but does not create/configure a trunk.

## Host compatibility and acceptance

The legacy key resolution is explicit dashscope_api_key, then DASHSCOPE_API_KEY
from the host environment. It does not consult global provider settings.
The official host launch projection now fills the detached runtime key field
from that environment variable when the configured key is empty. Workers do not
inherit the variable, guess worker HOME or load host configuration. Independent
trusted-context checks cover this precedence and preserve caller configuration.

The old SIP completed-event loop checked only object=message/status=completed,
without filtering message type or role. Its extractor preferred get_text_content
(joining truthy .text with spaces), otherwise selected the first .text from
content or nested message.content; it did not read a .refusal field. The helper
is preserved here. The shared neutral raw-completed-text contract now supplies
bounded text-source data with that precedence, including original reasoning/tool
text, without reconstructing raw events from formatted roles or copying the
renderer. Independent compatibility checks cover the original extraction and
unknown-actor authorization boundaries.

The ten old Core Python files have been retired. The original 51 direct and19
inherited responsibilities are mapped to current owners. Independent C1–C7
simulated acceptance includes the installed official ZIP, both child backend
loops, actual Loader/Manager/worker, host ACL/queue/Agent/SafeJSONSession, audio
conversion/playback, workspace isolation, rollback and lifecycle cleanup. The
24 new closeout nodes are separate from reused historical evidence; external
SDK/model boundaries are controlled.

The [official channel pluginization plan](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md)
contains the acceptance index. C8 distribution/release acceptance, telephone
hardware, live LiveKit deployment and platform performance remain unproven.
No A3 HTTP forwarding is required by SIP; A3/Voice and host cancellation remain
separate work.
