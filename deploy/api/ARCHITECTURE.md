---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: security-center-backend-api
element_kind: SecurityCenterBackendApi
element_path: deploy/api
---

## Implementation Architecture Contract

### Responsibility
- Own the backend HTTP API service for Security Center.
- Receive edge-side uplinks from src/qwenpaw/security through repository-owned HTTP endpoints only.
- Expose operator-facing query APIs for anomaly state, rejected-event evidence, recovery-handshake status, and shadow-hash continuity.
- Expose operator-facing query APIs for anomaly state, lease expiry and trust state, rejected-event evidence, recovery-handshake status, and shadow-hash continuity.
- Expose a realtime operator push channel over Server-Sent Events (SSE) or WebSocket for Security_Rejection_Nonce receipt, hash-divergence updates, and trust-state escalation.
- Own cloud-side shadow-state comparison, rejected-event intake, and recovery-handshake orchestration.
- Own cloud-side lease registry, TTL-expiry downgrade decisions, shadow-state comparison, rejected-event intake, and recovery-handshake orchestration.
- Own Security Event Ingestion V1 backend semantics: intake, contract-config validation, durable-before-success accepted-event persistence, failed reception records, idempotency, list/detail query APIs, persistence-failure response, and oversized invalid payload bounding.
- Own Security Event Observation Panel V1 backend semantics as a read-only projection over accepted events and failed reception records: shared 1h/24h/7d time ranges, default latest 24h range when no `range` query is supplied, accepted-event summary statistics, HIGH/MEDIUM alert rows, severity-plus-occurredAt alert ordering, raw reception rows, and sourceSystem plus eventId focus.

### Out Of Scope
- Owning edge runtime behavior or local audit files.
- Rendering operator UI directly.
- Exposing non-HTTP transports to the edge runtime for this slice.
- Rendering the Security Event Inbox UI directly.
- Defining authentication, external third-party intake, alerting, ticketing, remediation, assignment, comments, export, statistics dashboard, retention promises, Web configuration editing, or historical schema display policy for Security Event Ingestion V1.
- Turning the observation panel into a disposition, ticketing, assignment, approval, risk scoring, custom analytics, raw-payload full-text search, raw-payload export, requester identity, or authentication platform.

### Dependency Direction
- src/qwenpaw/security may call this boundary only through HTTP.
- deploy/web may consume this boundary's APIs for visualization and operator workflows.
- deploy/web may consume this boundary's SSE or WebSocket push stream for red-alert popups and shadow-hash divergence updates.
- This boundary must not read edge-local files, share edge durable storage, or be imported into the edge runtime as a library.
- For Security Event Ingestion V1, `deploy/api` reads `deploy/config/security-event-contracts.v1.json` as configuration input and owns its own durable store. `deploy/web` and tests may consume API responses only; they must not read or write the event store directly.
- The observation-panel read model must be derived from the same accepted-event and failed-reception stores owned by this boundary. `deploy/web` must not recompute summary, alert scope, alert ordering, raw-record membership, or alert-to-raw focus from a separate client-side store.

### Required API Roles
- audit uplink intake API
- rejected-event evidence API
- recovery-handshake API
- operator query API for anomaly and trust state
- operator query API for anomaly, lease expiry, and trust state
- shadow-hash divergence timeline API that returns local-hash and cloud-shadow-hash curve series plus the fork point marker
- nonce voucher API surface that exposes Security_Rejection_Nonce as a human-verifiable operator artifact
- realtime operator alert stream over Server-Sent Events (SSE) or WebSocket
- `POST /security-center/v1/events` accepts internal-system event submissions, validates `sourceSystem`, `eventTypeId`, `schemaVersion`, `summary`, `occurredAt`, `severity`, and configured payload fields, persists legal events before success, returns `duplicate=false` for new events, returns `duplicate=true` for identical sourceSystem plus eventId repeats, and rejects conflicting same-key submissions.
- `GET /security-center/v1/operator/events` returns accepted security events receivedAt-descending with filters for time range, sourceSystem, eventTypeId, and severity, core fields, and configured list payload fields only.
- `GET /security-center/v1/operator/events/{sourceSystem}/{eventId}` returns stable detail for one accepted event, including base facts, labeled structured payload, undefined payload fields, and bounded read-only raw payload.
- `GET /security-center/v1/operator/event-reception-failures` returns traceable failed reception records with received time, submitted source field, submitted event type field, failure reason, and bounded request summary.
- `GET /security-center/v1/operator/event-observation-panel` without an explicit `range` returns the same projection as `range=24h`; this default latest 24h behavior is part of the frozen acceptance boundary.
- `GET /security-center/v1/operator/event-observation-panel?range={1h|24h|7d}` returns the read-only observation-panel projection for one quick range. It must include `selectedRange`, available quick ranges, summary fields `totalAcceptedEvents`, `highAcceptedEvents`, `sourceSystemDistribution`, `eventTypeIdDistribution`, an `alerts` list containing only HIGH/MEDIUM accepted events ordered HIGH before MEDIUM then occurredAt descending, and `rawRecords` containing accepted and failed reception rows in the same selected range.
- `GET /security-center/v1/operator/event-observation-panel?range={1h|24h|7d}&focusSourceSystem={sourceSystem}&focusEventId={eventId}` returns the same projection plus `focusedRawRecord` for the matching raw reception record when present.

### Security Event Data Model
- Accepted event identity is `(sourceSystem, eventId)`.
- Accepted events store `eventTypeId`, `schemaVersion`, `severity`, caller-provided `summary`, caller-provided `occurredAt`, backend-generated `receivedAt`, configured structured payload fields, undefined payload fields, and bounded raw payload for detail display.
- Failure records store received time, submitted source field, submitted event type field, submitted eventId when present, failure reason, and bounded request summary for source rejection, type rejection, schema rejection, payload validation failure, idempotency conflict, persistence failure, and oversized invalid payload handling.
- Canonical idempotency comparison must normalize event content using the accepted request fields and configured payload values. `sourceSystem` is part of the key; global `eventId` uniqueness is not required.
- Observation-panel summary and alerts count only accepted legal events by occurredAt within the selected quick range. Failed reception records are visible only in `rawRecords` and must not increase legal-event totals, HIGH counts, source distributions, event-type distributions, or alerts.
- Observation-panel raw records include accepted events and failed receptions by the same selected time range. Accepted rows use accepted-event `occurredAt` for time-range membership and expose bounded raw payload evidence; failed reception rows use backend-generated `receivedAt` as the time-range source of truth and expose failure reason plus bounded raw-payload/request summary.

### Notes
- Coding/Repair may choose concrete framework and route layout, but must preserve HTTP as the edge transport, keep this backend as the only cloud-side control point for edge interactions, require missing-gap verification before an `UNTRUSTED` client regains model access, and publish Security_Rejection_Nonce-triggered operator alerts to deploy/web in under 500ms from uplink receipt without requiring manual refresh.
- For `sec-event-ingestion-v1`, the current repository state has no implemented event intake/list/detail/failure-record API routes. The explicit entrypoints under `../../tests/integration/security/test_security_event_ingestion.py` and `../../tests/e2e/security_center/test_security_event_inbox.py` are expected to fail with `Security_Event_Ingestion_API_Missing` until Coding/Repair implements this backend contract.
- For `security-center-event-observation-panel-v1`, the current repository state has accepted-event and failed-reception APIs, but no `GET /security-center/v1/operator/event-observation-panel` read model. The explicit entrypoints under `../../tests/e2e/security_center/test_security_event_observation_panel.py` are expected to fail with `Security_Event_Observation_Panel_API_Missing` until Coding/Repair implements this backend contract.
- Legal event persistence must complete before `POST /security-center/v1/events` returns success. If the store write fails, the API must return failure and create or preserve a bounded failure reception record when possible; it must not return accepted success for an event that cannot be queried.
- Security Event records must be durably persisted before success is returned to the caller.
- `X-QwenPaw-Test-Persistence-Failure` is reserved only as a test-environment failure-injection seam for the frozen explicit acceptance entrypoint. It must not become public production V1 API semantics, must not be documented as an integration feature, and must be ignored or unavailable outside explicit test mode.
- Undefined payload fields are preserved for traceability but must not become configured list columns unless `deploy/config/security-event-contracts.v1.json` declares them as payload fields with `showInList=true`.
- For sec-e2e-025, editing the second committed non-tail audit record after three high-risk actions must project as `UNTRUSTED` or recovery-required through the operator overview and timeline APIs until full-chain cloud validation succeeds. Returning `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, or `recovery_required=false` for that tampered client before validation is a Security Center backend failure.
- The lease registry and recovery model are keyed by one canonical runtime client id per live edge runtime. A startup heartbeat must not create a separate bootstrap-only client whose shadow hash is later compared against the real audit chain for that same runtime.
- Current repository evidence now also proves the backend admits a freshly started online runtime as a normal canonical terminal: clean startup heartbeat now converges to `trust_state=ALIGNED`, `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, and `recovery_required=false` before any offline lease-expiry or recovery workflow begins, and the prior `missing_gap_proof` startup misclassification is closed.
- Current repository evidence also proves the explicit-gap-verification shortcut no longer returns clients to `ALIGNED` without an accepted full-chain gap proof.
- The supporting contract test at `../../tests/contract/security/test_lease_recovery_semantics_contract.py` now guards those semantics as passing regression tests: one for TTL-driven lease downgrade and one for rejecting hash-only recovery shortcuts without full-chain cloud validation.
- A newer supporting contract in that same file now passes as a regression guard: runtime startup registers a lease client before user prompt traffic begins, so the product background Heartbeat Emitter requirement from the updated intent handoff is now closed and deploy/api continues to project lease timing as soon as heartbeats arrive.
- The critical architecture guard at `../../tests/architecture/security-runtime-client-identity-boundary.test.js` still passes, but it is only a static boundary guard.
- The live supporting guard at `../../tests/contract/security/test_lease_recovery_semantics_contract.py::test_security_center_projects_one_online_runtime_as_one_canonical_terminal` now currently passes as a behavior-level regression guard: after startup heartbeat plus one session-scoped security flow, deploy/api continues to report one canonical terminal for one live runtime while allowing session ids only as aliases or metadata.
- The supporting guard at `../../tests/contract/security/test_lease_recovery_semantics_contract.py::test_security_center_persists_runtime_lease_fields_and_downgrades_after_stop` now passes and remains frozen as regression protection for durable lease timing plus post-stop TTL downgrade.
- The critical architecture guard at `../../tests/architecture/security-runtime-lease-persistence-boundary.test.js` now passes and remains frozen as regression protection for the API/store lease-persistence seam.
- The supporting guard at `../../tests/contract/security/test_lease_recovery_semantics_contract.py::test_security_center_projects_fresh_runtime_startup_as_aligned_clear_terminal` now passes and remains frozen as regression protection for startup normal-admission semantics. Control point: start API, web, and runtime from a fresh bootstrap, then observe Security Center before any intentional runtime stop, offline lease-expiry demonstration, or session-scoped recovery workflow. Observation point: overview and timeline must show one canonical startup terminal with nonzero durable lease fields, `trust_state=ALIGNED`, `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, `recovery_required=false`, and no `missing_gap_proof` or other startup divergence reason.
- The supporting guard at `../../tests/contract/security/test_lease_recovery_semantics_contract.py::test_security_center_live_reconnect_gap_proof_restores_access` now passes and remains frozen as the live reconnect recovery regression gate. Control point: after the canonical client downgrades to `UNTRUSTED` with `divergence_reason=lease_ttl_expired`, restart the same runtime and attempt restored model access without manual `/security-center/v1/recovery/handshake` proof injection. Observation point: deploy/api must observe the same canonical client return to `ALIGNED` or `TRUSTED` with `gap_status=VALIDATED` or `CLEAR`, `recovery_gate_status=CLEAR`, `recovery_required=false`, and refreshed durable lease timing.
- Live acceptance must begin from a reset demo state and restarted processes. Before operator-side overview validation, run `scripts/reset-showcase-demo-state.ps1`, then restart Security Center API, Security Center web, and the QwenPaw runtime so stale store contents or stale processes cannot fabricate extra terminals or stale divergence state.
- deploy/api must preserve that repaired single-terminal model and bootstrap alignment so a live non-forked runtime does not regress to `DIVERGED` with `recovery_gate_status=OPEN` on `local_hash_mismatch` alone.
- deploy/api must also preserve `lease_ttl_seconds` on the recovery-handshake HTTP contract and durably write `last_heartbeat_at`, `lease_ttl_seconds`, and `lease_expires_at` for the canonical runtime client before operator queries observe lease timing. Read-model projection from `updated_at_ns` is not an acceptable substitute for this contract.
- deploy/api must also admit a clean startup heartbeat for the canonical runtime terminal as normal online state. Unless a real expired lease, fork, tamper event, or validated missing continuity gap already exists, startup heartbeat must converge to `trust_state=ALIGNED`, `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, and `recovery_required=false` rather than `GAP_VALIDATION_REQUIRED` with `missing_gap_proof`.
- deploy/api must continue to require cloud-side validation before an expired client regains access, but once the restarted runtime supplies a valid reconnect proof plus fresh canonical heartbeat, the same canonical client must remain durably observable as recovered instead of immediately falling back to `lease_ttl_expired`.
- For `sec-e2e-028`, deploy/api must keep normal offline reconnect distinct from lease-expiry recovery. Control point: the same canonical client returns before lease expiry with an aligned audit head and no tamper, missing sequence, clone, replay, or hash divergence. Observation point: overview and timeline must show `trust_state=ALIGNED` or `TRUSTED`, `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, `recovery_required=false`, and no `missing_gap_proof` or `GAP_VALIDATION_REQUIRED` display state.
