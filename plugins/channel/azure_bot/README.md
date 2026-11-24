# Azure Bot

Official child-process Bot Framework Connector integration for Teams, Slack,
Web Chat and other Azure Bot Connector channels. Install this directory through
the plugin manager. `plugin.json` selects `channel.json`; the host loads no Azure
SDK. The shared runner owns the HTTP listener at `/api/messages`, JWT validator,
MSAL token refresh, media and native activity sends. Core owns Agent execution,
access control, queuing, approvals and delivery journals.

The 24-field schema retains the 17 public channel fields and the seven original
Azure fields. Credentials marked required by the old UI remain presentation
hints; a disabled empty configuration is valid. Starting an enabled channel
requires App ID and App Password. An empty tenant uses the official Bot Framework
multi-tenant authority. Host/port keep their former falsey defaults, 0.0.0.0:3978.
No inbound listener is reported connected before it is bound and the host accepts
its generation-qualified endpoint registration. Port conflicts remain degraded
and retry through the owned watchdog. Missing endpoint RPC support fails startup.

## Authentication

The Connector path requires a Bearer RS256 signature from Microsoft's Connector
OpenID keys, one of the three exact signed issuers below, exact App ID audience,
expiry/not-before validation (five-minute clock tolerance), and service URL binding.
Signature/audience validation precedes reading the HTTP body; authenticated claims
are then matched to the activity. A signing key's channel endorsements, when
present, must contain the activity channel. HTTPS verification stays enabled.

References:
- [Microsoft Connector authentication](https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication?view=azure-bot-service-4.0)
- [Microsoft Python Connector validation](https://github.com/microsoft/botbuilder-python/blob/main/libraries/botframework-connector/botframework/connector/auth/channel_validation.py)
- [Microsoft Python JWT extractor](https://github.com/microsoft/botbuilder-python/blob/main/libraries/botframework-connector/botframework/connector/auth/jwt_token_extractor.py)

The accepted signed issuers are exactly `https://api.botframework.com`,
`https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/`, and
`https://login.microsoftonline.com/d6d49420-f39b-4df7-a1dc-d59a935871db/v2.0`.
All three use the trusted Connector metadata/key path. Independent RSA/JWKS
checks cover these issuers, and the installed official artifact's exact AAD
issuer reaches the real Core Agent and Connector reply. The former tenant-ID
substring exception remains removed: suffix, embedded-tenant and other
unlisted issuers are rejected. This does not add a separate Emulator/skill
authentication profile or establish live Microsoft interoperability.

## State and lifecycle

New reference state is scoped by workspace, App ID and tenant, protected by an
OS lock. At host policy initialization, Core captures original
`azure_bot_refs.json` bytes and their persisted account/workspace attribution once
in `channel_state/azure_bot/legacy-capture.json` under the former host state root.
The capture contains reference snapshots and source hashes, never App Passwords.
Original files are not rewritten. Local references belong to their workspace's
old account. Global fallback belongs only to the historical default workspace,
and only when its effective account matches the persisted global account.
Missing profiles select `<legacy_state_dir>/workspaces/default`; an explicit
profiles map must contain a valid default to receive global fallback. Conflicting
physical-file owners remain unresolved. Changing configuration or reinstalling
the plugin cannot reassign an existing capture.

The launch packet contains only capture ID, exact owner and snapshot digest.
The child reads the fixed captured snapshot itself; arbitrary reference counts
do not expand launch JSON. An exact authorized owner can proactively send to
captured targets before new ingress. Other owners receive empty authorization
and cannot adopt old aliases. A missing capture permits fresh authenticated
routes without reading flat legacy files; a corrupt existing capture fails Azure
startup with a fixed diagnostic. Host initialization isolates capture errors so
other channels can still start. The automatic path requires the delivered official
catalog owner; the host-only capture argument follows the same owner gate.

Direct private drivers without this host context retain the earlier conservative
behavior: an unowned alias is usable only after authenticated ingress proves the
same service URL, conversation and bot recipient. The optional
`legacy_state_dir` is trusted execution context from Core, not a saved user setting;
the child does not infer the former host directory from its HOME.

Activity recipient/service URL remain per-route, so simultaneous Teams/Slack/Web
Chat replies cannot change each other's recipient. Caller ACL identity remains the
actual aadObjectId/from.id even when group conversation context is shared. Invoke
keeps its native `{status: 200}` response; it does not manufacture an approval action.

Local attachments retain the 180,000-byte limit and original zh/en/id/ru notices.
Files are restricted to workspace/media roots. Successful uploads precede activity
sends; ambiguous uploads or partial sends remain unknown in the shared journal and
are never blindly replayed. Shutdown stops admission/listening, drains owned work,
closes HTTP resources and unregisters the endpoint before releasing state claims.
A failed shutdown retains resource ownership for retry.

The five dormant root Python entry points have been retired; runtime uses the
namespaced Driver. Official catalog/static UI, generation-qualified host endpoint
registration, trusted language/state projection and immutable legacy capture are
integrated. Independent C1–C7 simulated checks exercised the installed artifact
through the real Loader, shared worker, authenticated HTTP, queue/ACL, Agent and
Connector reply, including proactive captured references, workspace isolation,
configuration save/readback, rollback and lifecycle cleanup. Historical input
oracles remain in portable test fixtures rather than the production payload.

The [official channel pluginization plan](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md)
contains the acceptance index. C8 distribution/release assembly and live Microsoft
service-account acceptance remain unproven; the simulated checks do not claim them.
