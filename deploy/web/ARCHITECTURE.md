---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: security-center-operator-web
element_kind: SecurityCenterOperatorWeb
element_path: deploy/web
---

## Implementation Architecture Contract

### Responsibility
- Own the operator-facing web frontend for Security Center.
- Present anomaly, rejected-event, trust-state, and recovery-progress views to human operators.
- Present anomaly, lease-expiry `UNTRUSTED` state, rejected-event, trust-state, and recovery-progress views to human operators.
- Present a hash-break curve chart that shows the local hash and cloud shadow hash as separate lines and visually marks the fork point when divergence occurs.
- Present Security_Rejection_Nonce as a Voucher that administrators can cross-check against physical or exported logs.
- Auto-pop a red alert in under 500ms after deploy/api receives Security_Rejection_Nonce, using Server-Sent Events (SSE) or WebSocket rather than manual refresh.
- Consume deploy/api through backend-owned APIs rather than reading cloud durable storage directly.
- Own the Security Event Inbox Web surface for Security Event Ingestion V1 by consuming deploy/api list/detail/failure-record APIs.
- Render accepted security events receivedAt-descending with core fields, configured list payload fields, filters, stable detail URLs, undefined fields, and bounded read-only raw payload.
- Own the Security Event Observation Panel V1 Web surface by consuming deploy/api observation-panel APIs only.
- Render a single read-only operator panel with default latest 24h range when no explicit range is supplied, latest 1h/24h/7d quick ranges, accepted-event summary statistics, HIGH/MEDIUM alert list, raw reception list containing accepted and failed records, failed-reception range membership by backend receivedAt, and alert-to-raw evidence focus by sourceSystem plus eventId.

### Out Of Scope
- Owning edge runtime behavior.
- Owning cloud-side shadow-state comparison logic.
- Serving as an ingress path for edge-to-cloud traffic.
- Editing Security Event Ingestion V1 configuration through the Web UI.
- Owning event validation, idempotency, durable persistence, failure-record creation, retention policy, alerting, ticketing, export, assignment, comments, remediation, or statistics dashboards.
- Adding alert disposition, ticketing, assignment, approval, risk scoring, custom analytics, raw-payload full-text search, raw-payload export, requester identity, or authentication behavior to the observation panel.

### Dependency Direction
- deploy/web depends on deploy/api for state and operator actions.
- src/qwenpaw/security must not call deploy/web; edge access is frozen to deploy/api over HTTP.
- This boundary must not become a hidden control plane that bypasses the backend API.
- Security Event Inbox reads must go through deploy/api only. The Web frontend must not read `deploy/config/security-event-contracts.v1.json` or the backend event store directly.
- Security Event Observation Panel reads must go through deploy/api only. The Web frontend must not recompute summary statistics, alert ordering, raw reception membership, or focused raw evidence from a separate browser-side store.

### Required UI Roles
- anomaly dashboard
- rejected-event evidence view
- trust-state and UNTRUSTED recovery view
- trust-state, lease-expiry downgrade, and UNTRUSTED recovery view
- recovery-handshake progress view
- hash-break curve chart with explicit fork point marker
- nonce Voucher display for Security_Rejection_Nonce verification
- realtime red-alert popup driven by deploy/api SSE or WebSocket push
- Security Event Inbox list with receivedAt descending default ordering
- Security Event Inbox filters for time range, sourceSystem, event type, and severity; source/type/severity/time filter correctness is part of the frozen Web acceptance contract
- Security Event detail route stable by sourceSystem plus eventId
- event type display name in accepted-event list rows
- structured payload area with configured labels
- undefined fields area separated from configured fields
- bounded read-only raw payload area for large payload protection
- Security Event Observation Panel route `/security-event-observation`
- observation panel quick ranges latest 1 hour, latest 24 hours, and latest 7 days, with latest 24 hours selected by default
- observation summary cards for total accepted events, HIGH accepted events, sourceSystem distribution, and eventTypeId distribution
- observation alert list containing only HIGH and MEDIUM accepted events, ordered HIGH before MEDIUM then occurredAt descending
- observation raw reception list containing accepted event rows plus failed reception rows with failure reason and bounded raw-payload summary; failed reception rows are included in quick ranges by backend receivedAt
- alert-to-raw focus interaction keyed by sourceSystem plus eventId

### Notes
- Coding/Repair may choose concrete frontend stack and asset pipeline, but must keep the operator web separate from the edge runtime, route all state reads and actions through deploy/api, and forbid operator polling or manual refresh as the primary path for Security_Rejection_Nonce alert visibility.
- For `sec-event-ingestion-v1`, Coding/Repair may evolve the current static `app.js`/`index.html` frontend, but must preserve a Security Event Inbox route that satisfies `../../tests/e2e/security_center/test_security_event_inbox.py::test_web_lists_filters_and_opens_event_detail`.
- For `security-center-event-observation-panel-v1`, Coding/Repair may evolve the current static `app.js`/`index.html` frontend, but must preserve a Security Event Observation Panel route that satisfies all six entrypoints in `../../tests/e2e/security_center/test_security_event_observation_panel.py`, including default latest 24h behavior when no explicit range is supplied.
- The inbox must show `receivedAt`, `occurredAt`, `sourceSystem`, event type display name, `severity`, `summary`, `eventId`, and configured list payload fields. Undefined payload fields must be absent from primary list columns and present in detail-only undefined/raw areas.
- Stable detail URLs are keyed by `sourceSystem` plus `eventId`; they must reopen the same event after refresh without relying on transient list state.
- The observation panel is intentionally an observation/evidence surface. Rendering buttons, fields, or API calls for disposition status, tickets, assignment, comments, approval, risk scoring, export, raw-payload full-text search, requester identity, or authentication is outside the frozen V1 scope.
- For sec-e2e-025, the operator web must keep a client with second committed non-tail audit-record tamper in `UNTRUSTED` or recovery-required display state until deploy/api reports full-chain cloud validation. Rendering `CLEAR` for that client before validation is a security failure, even if the local tail record or checkpoint appears self-consistent.
- For sec-e2e-027, the operator web must render one live runtime as one terminal narrative. Display aliases may help operators correlate browser or session context, but the UI must not present one online runtime as multiple terminals or show a false `DIVERGED`/`OPEN` recovery gate when no fork point exists.
- For sec-e2e-028, the operator web must not leave a normally offline and promptly reconnected canonical client in `GAP_VALIDATION_REQUIRED`, `gap_status=REQUIRED`, `recovery_gate_status=OPEN`, or the Chinese "缺口待验证" business display once deploy/api projects aligned continuity. It must render the backend `ALIGNED` or `TRUSTED`, `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, and `recovery_required=false` state for that clean reconnect path.
