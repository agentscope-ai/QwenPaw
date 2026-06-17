---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: security-center-web-e2e-entrypoints
element_kind: SecurityCenterWebE2EEntrypointZone
element_path: tests/e2e/security_center
---

## Implementation Architecture Contract

### Responsibility
- Own the explicit operator Web consumption entrypoints for Security Event Ingestion V1, including the inbox and the observation panel.
- Keep Web acceptance assertions business-readable by routing page/API plumbing through `tests/integration/security/security_event_harness.py`.
- Preserve the stable detail URL, list ordering, source/type/severity/time filter correctness, configured-field display, event type display name, undefined-field display, and bounded raw payload observation points required by `sec-event-ingestion-v1-render-web-list-and-detail`.
- Preserve the default latest 24h observation panel when no explicit range is supplied, latest 1h/24h/7d quick ranges, accepted-event posture summary, HIGH/MEDIUM alert scope, severity-plus-occurredAt alert ordering, raw reception list containing accepted and failed records, failed-reception time-range membership by backend `receivedAt`, and sourceSystem plus eventId alert-to-raw focus required by `security-center-event-observation-panel-v1`.

### Out Of Scope
- Owning production backend routes under `deploy/api`.
- Owning production Web rendering under `deploy/web`.
- Replacing the explicit Web inbox baseline with a unit-only component test.
- Replacing the explicit observation-panel baseline with a unit-only component test or a backend-only projection test.

### Explicit Testcase Entrypoints
- testcase_name: sec-event-ingestion-v1-render-web-list-and-detail
  entry_path: test_security_event_inbox.py::test_web_lists_filters_and_opens_event_detail
  control_point: seed multiple accepted security events through the protected harness, open the operator Web inbox route, apply source/type/severity/time filters, and navigate to a stable detail URL by sourceSystem plus eventId
  observation_point: the inbox defaults to receivedAt descending, source/type/severity/time filters return only matching rows, event type display name and configured list payload fields are visible, the same detail URL reopens, and detail displays base facts, labeled structured payload, undefined fields, and bounded read-only raw payload
- testcase_name: security-center-event-observation-panel-v1-posture-statistics
  entry_path: test_security_event_observation_panel.py::test_observation_panel_summarizes_current_event_posture
  control_point: seed five accepted events in the current 24h range across two source systems, two event types, and multiple severities, then open the observation panel without an explicit range
  observation_point: default panel output matches explicit `range=24h`; total accepted count, HIGH accepted count, sourceSystem distribution, and eventTypeId distribution match those accepted events and exclude failed receptions
- testcase_name: security-center-event-observation-panel-v1-alert-scope
  entry_path: test_security_event_observation_panel.py::test_observation_panel_filters_alerts_by_severity
  control_point: seed DEBUG, LOW, MEDIUM, and HIGH accepted events, then open the observation panel
  observation_point: only MEDIUM and HIGH appear in alerts, while all four successful receptions remain visible as raw records
- testcase_name: security-center-event-observation-panel-v1-alert-ordering
  entry_path: test_security_event_observation_panel.py::test_observation_panel_sorts_alerts_by_severity_and_occurred_at
  control_point: seed interleaved HIGH and MEDIUM accepted events with distinct occurredAt values, then open the alert list
  observation_point: all HIGH alerts precede MEDIUM alerts and same-severity alerts are ordered by occurredAt descending
- testcase_name: security-center-event-observation-panel-v1-failed-receptions-visible
  entry_path: test_security_event_observation_panel.py::test_observation_panel_shows_failed_receptions_in_raw_records
  control_point: seed invalid source, missing required field, and payload type failure records, then open the raw reception list
  observation_point: failed receptions do not count as accepted events or alerts, but raw records show failure reason and bounded raw-payload summary
- testcase_name: security-center-event-observation-panel-v1-alert-to-raw-traceability
  entry_path: test_security_event_observation_panel.py::test_observation_panel_links_alert_to_raw_record
  control_point: seed one HIGH accepted event, open the panel, and select the alert by sourceSystem plus eventId
  observation_point: the raw reception list focuses the same sourceSystem plus eventId raw record and exposes bounded raw payload evidence
- testcase_name: security-center-event-observation-panel-v1-time-range-consistency
  entry_path: test_security_event_observation_panel.py::test_observation_panel_applies_time_range_consistently
  control_point: seed accepted events by occurredAt and failed receptions by backend receivedAt inside latest 1h, inside latest 24h, inside latest 7d, and outside latest 7d, then switch 1h/24h/7d quick ranges
  observation_point: summary, alert list, and raw reception list include only records within the same selected range; accepted rows are ranged by occurredAt, failed reception rows are ranged by backend receivedAt, and the surfaces do not contradict each other

### Protected Fixtures
- `tests/integration/security/security_event_harness.py`
- `tests/e2e/security_center/conftest.py`

### Notes
- This entrypoint is expected to fail until `deploy/api` and `deploy/web` implement the Security Event Ingestion V1 APIs and inbox routes.
- The observation-panel entrypoints are expected to fail until `deploy/api` implements `GET /security-center/v1/operator/event-observation-panel` and `deploy/web` serves `/security-event-observation`.
- Coding/Repair may improve production pages and APIs, but must not move or weaken this explicit entrypoint without a new implementation-architecture change.
- `conftest.py` must continue to load `tests.integration.conftest` so the Web entrypoint uses the same real Security Center API/Web/runtime subprocess baseline as the integration security entrypoints.
