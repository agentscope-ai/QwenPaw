---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: security-center-deployment-boundary
element_kind: SecurityCenterDeploymentBoundary
element_path: deploy
---

## Implementation Architecture Contract

### Responsibility
- Own the stable repository deployment boundary for the physically separate Security Center process.
- Preserve the cloud-side integrity mirror, rejected-event projection, and recovery-handshake bootstrap as an independent fact source reached only through audit uplink.
- Preserve the cloud-side integrity mirror, lease registry, rejected-event projection, and recovery-handshake bootstrap as an independent fact source reached only through audit uplink.
- Own the Security Event Ingestion V1 deployment boundary for internal-system event intake, accepted-event and failure-record persistence, operator list/detail query, Web inbox delivery, and the read-only observation panel over the same records.
- Freeze the deploy-owned decomposition into a backend HTTP API service plus an operator-facing web frontend.
- Freeze the real-time operator alert path: deploy/api must publish Security_Rejection_Nonce and hash-divergence updates to deploy/web through Server-Sent Events (SSE) or WebSocket rather than operator polling.
- Freeze the real-time operator alert path: deploy/api must publish Security_Rejection_Nonce, lease-expiry trust-state changes, and hash-divergence updates to deploy/web through Server-Sent Events (SSE) or WebSocket rather than operator polling.
- Freeze the boundary where container bootstrap assets, runtime configuration, cloud-side durable storage, HTTP ingress, and operator web delivery will be materialized during Coding/Repair.

### Out Of Scope
- Owning edge runtime behavior under src/qwenpaw/.
- Reading or sharing the edge node's local working directory directly.
- Rehosting Security Center logic inside the edge process or explicit testcase bodies.

### Children
- path: api
  kind: security-center-backend-api
  role: stable backend service boundary that receives edge HTTP uplinks, exposes operator-facing query APIs and push streams, and owns cloud-side shadow-state comparison
- path: web
  kind: security-center-operator-web
  role: stable frontend boundary that renders anomaly, rejection, recovery state, hash-break curve charts, nonce vouchers, and real-time red alerts for human operators by consuming the backend API
- path: Dockerfile
  kind: deployment-bootstrap
  role: container build contract for the separate Security Center process
- path: entrypoint.sh
  kind: runtime-bootstrap
  role: process startup contract for the separate Security Center boundary
- path: config
  kind: deployment-config
  role: stable configuration zone for the Security Center deployment environment, including `security-event-contracts.v1.json` for source/event/schema/display metadata

### Dependency Direction
- deploy/ may consume uplink summaries from the edge runtime, but it must not read local edge files or share the edge durable store.
- Edge runtime access to Security Center is frozen to HTTP only. The edge must not import deploy code as a library, mount deploy storage, or bypass the backend API through direct database or file access.
- deploy/web depends on deploy/api for operator-visible state and push delivery, must not be used as a backchannel from the edge runtime, and must not rely on manual refresh for Security_Rejection_Nonce alerting.
- tests/integration/security may observe cloud-visible results only through the stable projection seam owned by this boundary.
- src/qwenpaw/security owns edge-side evidence production and uplink initiation; deploy/api owns cloud-side HTTP reception, shadow-state comparison, SSE or WebSocket alert publication, and operator query APIs; deploy/web owns operator-facing anomaly projection, hash-break visualization, nonce voucher display, and sub-500ms red-alert rendering.
- deploy/api owns Security Event Ingestion V1 API behavior, durable stores, and the observation-panel read model; deploy/web owns the operator Security Event Inbox and Security Event Observation Panel by consuming deploy/api only. Tests may observe this through `tests/integration/security/security_event_harness.py`, but production code must not depend on tests.

### Notes
- Current repository evidence only confirms deployment bootstrap assets, not a realized cloud-side intake, HTTP API service, operator web, or shadow-hash service.
- Coding/Repair must materialize a separate process and durable store behind this contract rather than collapsing Security Center into src/qwenpaw/security or into the test harness.
- For `sec-event-ingestion-v1`, Coding/Repair must implement the API and Web behavior under this deploy boundary. The V1 API surface is frozen to `POST /security-center/v1/events`, `GET /security-center/v1/operator/events`, `GET /security-center/v1/operator/events/{sourceSystem}/{eventId}`, and `GET /security-center/v1/operator/event-reception-failures`.
- For `security-center-event-observation-panel-v1`, Coding/Repair must implement the observation-panel API and Web behavior under this deploy boundary. The V1 observation API surface is frozen to `GET /security-center/v1/operator/event-observation-panel?range={1h|24h|7d}` with optional `focusSourceSystem` and `focusEventId` for alert-to-raw traceability; deploy/web must expose `/security-event-observation` as the operator page.
- `deploy/config/security-event-contracts.v1.json` is the frozen configuration baseline for V1. It defines enabled sources, event type authorization, schema versions, payload field labels/types/required flags/enums/max lengths/list flags, and bounded failure/raw-payload display limits only; it must not grow hidden workflow, status, retention, authentication, alerting, ticketing, export, or Web editing semantics.
- For sec-e2e-027, this boundary must project exactly one operator-visible terminal per live edge runtime. Session or browser metadata may remain display aliases, but deploy-owned state must not let one online runtime surface as multiple canonical clients or as a false `DIVERGED`/`OPEN` fork while no real fork occurred.
- Live operator acceptance for this boundary must start from a reset showcase state plus restarted processes: run `scripts/reset-showcase-demo-state.ps1`, then restart Security Center and the QwenPaw runtime before reading operator overview or timeline state so stale ports, stale store files, or stale long-running processes do not contaminate the observation point.
