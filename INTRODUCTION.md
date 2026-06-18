# QwenPaw Security Center Introduction

QwenPaw now includes a deploy-owned Security Center slice that stays physically separate from the edge runtime. The edge node remains responsible for local audit evidence and tool-boundary enforcement, while Security Center receives HTTP uplinks only, maintains cloud-side shadow state, and surfaces operator-facing anomaly and rejection evidence without reading the edge working directory directly.

## External Interfaces

- Backend API: `deploy/api/app.py`
  - Recovery handshake: `POST /security-center/v1/recovery/handshake`
    - Accepts edge-reported head hash plus anchor and sequence metadata, session-scoped alias identity, and canonical runtime lease TTL so Security Center can durably persist `last_heartbeat_at`, `lease_ttl_seconds`, and `lease_expires_at` for the canonical client.
    - Uses the authenticated session alias for operator lookup while keeping the canonical runtime client id stable across startup heartbeat, recovery, and lock-mode recovery flows.
    - Distinguishes `ALIGNED`, `DIVERGED`, and `GAP_VALIDATION_REQUIRED` instead of treating head-hash equality as automatic recovery.
  - Trusted-anchor uplink: `POST /security-center/v1/uplinks/trusted-anchors`
    - Accepts normal critical anchor evidence such as `USER_CONFIRMATION`, recomputes the anchor materials server-side, and advances the cloud trusted anchor only when the uploaded evidence is independently reproducible.
  - Rejected-event uplink: `POST /security-center/v1/uplinks/rejections`
  - Lockdown uplink: `POST /security-center/v1/uplinks/lockdowns`
  - Operator overview: `GET /security-center/v1/operator/overview`
    - Projects canonical Security Center client state while also exposing session-scoped alias entries so operator and acceptance clients can continue to look up the live runtime by the authenticated session id.
  - Voucher lookup: `GET /security-center/v1/operator/vouchers/{nonce}`
  - Divergence timeline: `GET /security-center/v1/operator/timelines/{client_id}`
    - Accepts either the canonical Security Center client id or a session alias and returns last trusted anchor, current edge-reported head, gap status, fork point, recovery gate state, and `canonical_client_id` for operator review.
  - Realtime alerts: `GET /security-center/v1/operator/stream`
  - Security event intake: `POST /security-center/v1/events`
    - Accepts V1 internal-system submissions, validates `sourceSystem`, `eventTypeId`, `schemaVersion`, `summary`, `occurredAt`, `severity`, and configured payload fields against `deploy/config/security-event-contracts.v1.json`.
    - Persists legal events before returning success, returns `duplicate=false` for new events, and returns `duplicate=true` for identical `(sourceSystem, eventId)` repeats without creating a second business event.
    - Rejects invalid source/type/schema/payload submissions, idempotency conflicts, and write failures without adding them to the accepted event list.
  - Security event list: `GET /security-center/v1/operator/events`
    - Returns accepted events in backend `receivedAt` descending order with filters for `sourceSystem`, `eventTypeId`, `severity`, `occurredFrom`, and `occurredTo`.
  - Security event detail: `GET /security-center/v1/operator/events/{sourceSystem}/{eventId}`
    - Returns stable detail by source plus event id, including base facts, labeled structured payload, separated undefined payload fields, and bounded read-only raw payload.
  - Security event failure records: `GET /security-center/v1/operator/event-reception-failures`
    - Returns bounded trace records for rejected or failed event receptions.
  - Security event observation panel: `GET /security-center/v1/operator/event-observation-panel?range={1h|24h|7d}`
    - Defaults to latest 24 hours when `range` is omitted.
    - Returns accepted-event summary statistics, HIGH/MEDIUM alert rows ordered by severity then `occurredAt`, accepted and failed raw reception records, and optional `focusSourceSystem` plus `focusEventId` raw-evidence focus.

- Operator web: `deploy/web/index.html`
  - Renders anomaly dashboard, trust-state and recovery view, rejected-event evidence, hash-break curve chart, gap-validation state, recovery gate state, and Security_Rejection_Nonce Voucher display.
  - Subscribes to deploy/api over Server-Sent Events instead of manual refresh.
  - Renders the Security Event Inbox at `/security-events` and stable detail pages at `/security-events/{sourceSystem}/{eventId}` by consuming deploy/api only.
  - Renders the Security Event Observation Panel at `/security-event-observation` by consuming the backend observation-panel API only.

## Security Event Ingestion V1 Calling Examples

The Security Event Ingestion V1 API is intended for company-internal systems. Start the backend API first:

```powershell
python -m deploy.api.app
```

By default the API listens on `http://127.0.0.1:8091`.

### Submit a legal event with curl

```bash
curl -sS -X POST "http://127.0.0.1:8091/security-center/v1/events" \
  -H "Content-Type: application/json" \
  -d '{
    "sourceSystem": "endpoint_edr",
    "eventId": "edr-demo-20260612-0001",
    "eventTypeId": "malware_detected",
    "schemaVersion": "1.0",
    "severity": "HIGH",
    "summary": "Endpoint malware blocked on finance workstation",
    "occurredAt": "2026-06-12T03:00:00Z",
    "payload": {
      "assetId": "finance-workstation-7",
      "detectionName": "EICAR-Test-File",
      "actionTaken": "blocked",
      "collectorBuildFingerprint": "edr-agent-5.4.1+20260612"
    }
  }'
```

Expected success shape:

```json
{
  "success": true,
  "eventId": "edr-demo-20260612-0001",
  "sourceSystem": "endpoint_edr",
  "duplicate": false,
  "receivedAt": "2026-06-12T03:00:01Z"
}
```

Submitting the exact same normalized event again returns `success=true` with `duplicate=true` and does not create a second business event.

### Submit from Python

```python
from __future__ import annotations

import requests

base_url = "http://127.0.0.1:8091"

event = {
    "sourceSystem": "cloud_siem",
    "eventId": "siem-demo-20260612-0001",
    "eventTypeId": "correlation_rule_match",
    "schemaVersion": "1.0",
    "severity": "MEDIUM",
    "summary": "Correlation rule matched suspicious cloud activity",
    "occurredAt": "2026-06-12T03:15:00Z",
    "payload": {
        "ruleId": "CLOUD-RULE-1842",
        "assetId": "prod-cloud-account-12",
        "actionTaken": "opened-investigation",
    },
}

response = requests.post(
    f"{base_url}/security-center/v1/events",
    json=event,
    timeout=10,
)
response.raise_for_status()
print(response.json())
```

### Query events and details

```bash
curl -sS "http://127.0.0.1:8091/security-center/v1/operator/events?sourceSystem=endpoint_edr&eventTypeId=malware_detected&severity=HIGH"
```

The list response is sorted by backend-generated `receivedAt` descending and includes configured list payload fields only.

```bash
curl -sS "http://127.0.0.1:8091/security-center/v1/operator/events/endpoint_edr/edr-demo-20260612-0001"
```

The detail response includes base facts, labeled structured payload, `undefinedPayloadFields`, and bounded read-only `rawPayload`.

### Query failed receptions

```bash
curl -sS "http://127.0.0.1:8091/security-center/v1/operator/event-reception-failures"
```

Invalid source/type/schema/payload submissions, idempotency conflicts, and persistence failures are recorded here with bounded request summaries. They do not appear in the accepted event list.

### Query the observation panel

```bash
curl -sS "http://127.0.0.1:8091/security-center/v1/operator/event-observation-panel?range=24h"
```

Use `range=1h`, `range=24h`, or `range=7d`; omitting `range` is equivalent to `range=24h`. Add `focusSourceSystem` and `focusEventId` to locate the raw reception record for a selected alert.

### Integration Notes

- V1 does not implement request authentication or source credential management. Only call this API from trusted internal integration paths until a future authenticated intake design exists.
- `sourceSystem`, `eventTypeId`, `schemaVersion`, `severity`, and payload fields must match `deploy/config/security-event-contracts.v1.json`.
- Supported V1 severities are `DEBUG`, `LOW`, `MEDIUM`, and `HIGH`; the backend normalizes submitted severity to uppercase. `DEBUG` is intended for non-anomalous operational audit history such as successful OpenSandbox MCP calls.
- OpenSandbox MCP audit events use `sourceSystem=opensandbox`, `eventTypeId=opensandbox`, and `schemaVersion=1.0`. Successful calls use `DEBUG`; tool failures and nonzero command exits use `HIGH`.
- `receivedAt` is generated by Security Center. If a caller sends `receivedAt`, it is ignored for accepted event timing.
- `sourceSystem + eventId` is the idempotency key. Reuse the same `eventId` only for the same event fact; use a new `eventId` for a new fact.
- Extra payload fields are preserved for traceability, but they are shown only in detail `undefinedPayloadFields` and `rawPayload`, not in list columns.
- The API returns success only after durable persistence. A write failure returns a failure response instead of an accepted success.
- Do not use or document `X-QwenPaw-Test-Persistence-Failure` for external integrations. It is a test-only failure-injection seam and is ignored unless the API process is explicitly started with `QWENPAW_SECURITY_CENTER_ENABLE_TEST_FAILURE_INJECTION=1`.

- QwenPaw runtime Integrity Protection API: `src/qwenpaw/app/routers/config.py`
  - Default-off settings: `GET /api/config/security/integrity-protection/settings`
    - Projects Integrity Check and Health Check menu availability while keeping persona protection and health check disabled by default.
  - Scan-only health check: `POST /api/config/security/integrity-protection/health-check/scan`
    - Accepts an optional JSON body `{ "deep": false }`; callers must explicitly send `deep: true` to include connectivity-heavy doctor items.
    - Returns read-only qwenpaw doctor projection items with `group`, `id`, `status`, `detail`, `risk`, `recommendation`, `fix_id`, and `deep_only`, plus progress, risks, and repair suggestions without mutating user files.
  - Confirmed health fix: `POST /api/config/security/integrity-protection/health-check/fix`
    - Runs one selected `doctor fix` action only after the caller supplies the explicit confirmation phrase.
  - Rule integrity check entry: `POST /api/config/security/integrity-protection/rules-integrity/check`
    - Invokes the existing dangerous shell command rule integrity verifier and does not repair `dangerous_shell_commands.yaml`.

## Launch

- Backend API: `python -m deploy.api.app`
- Operator web: `python -m deploy.web.server`
- Showcase helper: `python -m deploy.api.showcase show-plan`
