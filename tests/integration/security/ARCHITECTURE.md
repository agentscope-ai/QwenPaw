---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: security-acceptance-entrypoints
element_kind: ExplicitSecurityEntrypointZone
element_path: tests/integration/security
---

## Implementation Architecture Contract

### Responsibility
- Own the read-only explicit security acceptance entrypoints required by the intent graph for audit-foundation scenarios and Integrity Protection delivery (ip-e2e-001 through ip-e2e-007, excluding deferred ip-e2e-003).
- Keep testcase bodies business-readable and GIVEN/WHEN/THEN-shaped by routing live app-subprocess HTTP, logs, and working-directory inspection through local harness abstractions instead of raw plumbing in the testcase body.
- Freeze runtime-inspection expectations for `sec-e2e-024`, `sec-e2e-025`, `sec-e2e-027`, `sec-e2e-028`, and `sec-e2e-021`: tool-boundary context spying, direct physical ledger inspection, local hash-chain verification, second committed non-tail audit-record tamper detection with readable `UNTRUSTED` state, lease-expiry-driven `UNTRUSTED` downgrade plus reconnect gating, normal-offline reconnect CLEAR projection, durable rejected-event evidence with trace-bound nonce semantics, and pre-execution evidence ordering.
- Freeze Security Event Ingestion V1 explicit API/data entrypoints: legal event durable acceptance, invalid config/schema/payload rejection, undefined payload field preservation, sourceSystem plus eventId idempotency, and bounded failed reception records.
- Freeze the protected Security Event harness vocabulary used by Security Event Observation Panel V1 Web e2e entrypoints for posture summary, alert scope, alert ordering, failed reception raw evidence, alert-to-raw focus, and time-range consistency.
- Constrain the explicit security slice to run against the real `app_server` fixture rather than repository source inspection or in-memory-only doubles.

### Out Of Scope
- Owning product runtime behavior under `src/qwenpaw/`.
- Owning root architecture guardrails under `tests/architecture/`.

### Children
- path: harness.py
  kind: protected-explicit-test-fixture
  role: business-readable harness abstraction that drives the real app subprocess, observes runtime HTTP/log/file evidence, reads the physical audit ledger seam, and reports architecture-stage security gaps with business categories
- path: test_audit_foundation.py
  kind: explicit-testcase-entry
  role: single explicit security entrypoint file for audit-foundation scenario baselines
- path: security_event_harness.py
  kind: protected-explicit-test-fixture
  role: business-readable harness abstraction that drives real Security Center API/Web subprocesses and reports Security Event Ingestion V1 and Observation Panel V1 gaps with business categories
- path: test_security_event_ingestion.py
  kind: explicit-testcase-entry
  role: single explicit security event ingestion API/data entrypoint file for V1 acceptance baselines
- path: integrity_harness.py
  kind: protected-explicit-test-fixture
  role: business-readable harness for Integrity Protection delivery (persona, health check, default-off menu semantics)
- path: test_integrity_protection.py
  kind: explicit-testcase-entry
  role: Integrity Protection delivery acceptance bodies (ip-e2e-001, 002, 004, 006, 007; ip-e2e-002 is P2)

### Explicit Testcase Entrypoints — Integrity Protection
- testcase_name: ip-e2e-001-integrity-security-menu-default-off
  entry_path: test_integrity_protection.py::test_integrity_security_menu_default_off
- testcase_name: ip-e2e-002-persona-drift-alert-restore-accept
  entry_path: test_integrity_protection.py::test_file_baseline_drift_alert_restore_accept
- testcase_name: ip-e2e-004-health-check-scan-and-confirmed-fix
  entry_path: test_integrity_protection.py::test_health_check_scan_and_confirmed_fix
- testcase_name: ip-e2e-005-rule-integrity-entry-visible
  entry_path: ../../extension/rule_integrity/tests/test_integration_entry.py::test_rule_integrity_entry_visible
- testcase_name: ip-e2e-006-security-i18n-progress-carousel
  entry_path: test_integrity_protection.py::test_security_i18n_and_healthcheck_progress_carousel
- testcase_name: ip-e2e-007-healthcheck-full-doctor-coverage
  entry_path: test_integrity_protection.py::test_healthcheck_full_doctor_coverage_projection

### Explicit Testcase Entrypoints — Audit Foundation
- testcase_name: sec-e2e-024-end-to-end-non-repudiation-evidence-chain
  entry_path: test_audit_foundation.py::test_end_to_end_non_repudiation_evidence_chain
  control_point: authenticate an employee, request a delegated high-risk action through the real app subprocess, and provide the required confirmation through the harness
  observation_point: the resulting observations prove or disprove tool-boundary implicit context propagation, a complete user -> agent -> plugin -> tool evidence chain, a physical USER_CONFIRMATION audit record on disk inside the isolated working directory, local hash-chain integrity, and the order 'store evidence before releasing the high-risk tool'
- testcase_name: sec-e2e-025-audit-integrity-self-healing-lockdown
  entry_path: test_audit_foundation.py::test_audit_integrity_self_healing_lockdown
  control_point: drive three high-risk actions through the real app subprocess to create a multi-record committed audit baseline, edit the second committed non-tail audit record by operating-system means while leaving later records present, then attempt another high-risk action without manual trust recovery
  observation_point: the resulting observations prove or disprove one business-level continuity anomaly for historical-record tamper, explicit `UNTRUSTED` state, refusal of resumed sensitive tooling, explicit recovery visibility through both the frozen Security Center backend API and the frozen Security Center operator web, no premature `CLEAR` display before cloud-validated full-chain recovery, and a hash-break curve chart with a visually marked fork point between local and cloud shadow hashes
- testcase_name: sec-e2e-027-lease-expiry-active-defense
  entry_path: test_audit_foundation.py::test_lease_expiry_blocks_untrusted_rejoin_until_gap_sync
  control_point: within one frozen explicit entrypoint, first let a previously trusted device session miss its lease heartbeat window and attempt rejoin before missing-gap verification, then drive a second controlled recovery step plus a second model-access attempt after continuity validation
  observation_point: the resulting observations prove or disprove two distinct frames: a pre-recovery frame with lease-heartbeat projection, Security Center `UNTRUSTED` downgrade, denied rejoin at model-access scope, and a frozen `pre_recovery_console_status`; and a post-recovery frame with a distinct recovery control point, distinct backend and operator-web trust-state projection, restored model access only after continuity is proven, and a frozen `post_recovery_console_status`
- testcase_name: sec-e2e-028-normal-offline-reconnect-clear-state
  entry_path: test_audit_foundation.py::test_normal_offline_reconnect_clears_without_gap_recovery
  control_point: establish trusted audit-head continuity through ordinary model access, stop the runtime through a normal offline path without mutating local audit evidence, restart the same canonical client before lease expiry, then attempt ordinary model access again
  observation_point: the resulting observations prove or disprove that Security Center backend and operator web project the same canonical client as `ALIGNED` or `TRUSTED` with `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, `recovery_required=false`, no missing-gap validation incident, and model access `200`
- testcase_name: sec-e2e-021-prompt-injection-tool-guard-enforced
  entry_path: test_audit_foundation.py::test_prompt_injection_cannot_bypass_high_risk_tool_guard
  control_point: submit deceptive nested instructions that claim test mode or maintenance mode while targeting a configured High risk tool without trusted provenance or confirmation
  observation_point: the resulting observations prove or disprove tool-call-boundary interception, missing-trust rejection with a non-static Security_Rejection_Nonce bound to the current trace chain, durable rejected-event evidence, visible nonce Voucher presentation in the frozen Security Center operator web, and a red alert pushed from deploy/api over SSE or WebSocket to the operator web in under 500ms without manual refresh
- testcase_name: sec-event-ingestion-v1-accept-legal-event
  entry_path: test_security_event_ingestion.py::test_accepts_legal_event_after_persistence
  control_point: submit a legal HTTP security event from enabled sourceSystem `endpoint_edr` with allowed eventTypeId, valid schemaVersion, required summary, occurredAt, severity, and payload fields, then query event list and detail
  observation_point: the API returns success with eventId and duplicate=false only after persistence, the event is list/detail visible by sourceSystem plus eventId, and backend-generated receivedAt overrides caller input
- testcase_name: sec-event-ingestion-v1-reject-invalid-config-boundary
  entry_path: test_security_event_ingestion.py::test_rejects_invalid_event_config_boundary
  control_point: submit source allow-list, disabled source, source-to-type authorization, unknown event type, unknown schemaVersion, base required summary, required payload field, payload type, and payload enum violations
  observation_point: each request returns a clear business failure reason, rejected submissions stay out of the accepted event list, and failed reception records contain received time, submitted source/type, failure reason, and bounded summary
- testcase_name: sec-event-ingestion-v1-preserve-undefined-payload-fields
  entry_path: test_security_event_ingestion.py::test_preserves_undefined_payload_fields_in_detail_only
  control_point: submit a legal event with all configured payload fields plus `collectorBuildFingerprint`, which is not declared by the V1 configuration
  observation_point: the event is accepted, configured fields remain list/detail primary fields, the undefined field is absent from list columns, and the undefined field appears only in undefined-fields detail and raw payload
- testcase_name: sec-event-ingestion-v1-enforce-idempotency
  entry_path: test_security_event_ingestion.py::test_enforces_source_event_id_idempotency
  control_point: submit the same normalized event twice, submit the same sourceSystem plus eventId with conflicting content, then submit the same eventId from a different sourceSystem
  observation_point: identical repeat returns duplicate=true without a second business event, conflicting same-key content is rejected and recorded, and different sourceSystem plus same eventId is accepted distinctly
- testcase_name: sec-event-ingestion-v1-bound-failure-records
  entry_path: test_security_event_ingestion.py::test_records_failed_receptions_without_business_event_pollution
  control_point: submit illegal source/type/schema/payload cases, create an accepted idempotency baseline, submit conflicting same-key content, use the test-only `X-QwenPaw-Test-Persistence-Failure` failure-injection seam, and submit an oversized illegal payload
  observation_point: accepted event list stays clean except for the intentional idempotency baseline, illegal/idempotency-conflict/persistence-error/oversized-invalid branches each have queryable bounded failure records, persistence failure returns failure instead of success, and oversized invalid payload handling avoids unbounded storage/display

### Protected Harness For Observation Panel Web Entrypoints
- testcase_file: ../../e2e/security_center/test_security_event_observation_panel.py
  harness_path: security_event_harness.py
  control_point: each Web e2e entrypoint seeds accepted and failed Security Event V1 records through the protected harness, opens `/security-event-observation` without range for the default case, switches quick ranges, or focuses an alert by sourceSystem plus eventId
  observation_point: the harness reports `Security_Event_Observation_Panel_Gap` with explicit checks for default latest 24h equivalence to `range=24h`, summary statistics, HIGH/MEDIUM alert scope, alert ordering, raw reception evidence, alert-to-raw focus, and 1h/24h/7d range consistency where accepted events are ranged by occurredAt and failed receptions are ranged by backend receivedAt

### Protected Fixtures
- harness.py
- security_event_harness.py
- integrity_harness.py

### Notes
- Integrity Protection acceptance is verified through `integrity_harness.py` against as-built paths in `extension/{file_baseline,health_check,rule_integrity}/` and `console/src/extension/`. ip-e2e-005 backend passive check is exercised from `extension/rule_integrity/tests/`; Console PassiveCard/Banner are as-built UI not fully covered by that harness.
- The testcase body in `test_audit_foundation.py` is frozen as a business contract baseline. Coding/Repair may realize runtime behavior underneath the harness, but should not rewrite the business wording, GIVEN/WHEN/THEN structure, or explicit entrypoint paths without an upstream architecture change.
- In the current repository state, the harness is still expected to fail with business-readable `Audit_Integrity_Lockdown_Gap` if the live runtime only detects checkpoint loss or tail truncation and does not detect OS-level editing of the second committed non-tail audit record before the next high-risk boundary.
- sec-e2e-027 is now frozen around two control points and two console observation points inside one explicit entrypoint, and the current repository evidence shows that baseline can execute without sharing one mutable final console status across both frames.
- sec-e2e-028 is now frozen around a separate normal-offline branch. It must not be satisfied by weakening sec-e2e-027: before lease expiry and without tamper, missing sequence, clone, replay, or hash divergence, no gap validation is required and backend/web must remain CLEAR.
- When the shared real-environment bootstrap itself is incomplete, the explicit entrypoint must still fail inside the testcase body with a readable runtime bootstrap blocker rather than disappearing behind fixture setup noise.
- Security Event Ingestion V1 entrypoints are expected to fail in the current repository state with business categories such as `Security_Event_Ingestion_API_Missing`, because `deploy/api` has not yet implemented `POST /security-center/v1/events` or the event list/detail/failure-record routes.
- Security Event Observation Panel V1 entrypoints are expected to fail in the current repository state with `Security_Event_Observation_Panel_Gap` and route-specific missing API/Web signals, because `deploy/api` has not yet implemented `GET /security-center/v1/operator/event-observation-panel` and `deploy/web` has not yet implemented `/security-event-observation`.
- `X-QwenPaw-Test-Persistence-Failure` is a protected test-environment failure-injection seam only. Coding/Repair may use it to prove persistence-failure behavior in the explicit entrypoint, but must not expose it as public production V1 API semantics.
- Coding/Repair may implement production routes, stores, and Web rendering behind `security_event_harness.py`, but must not rewrite `test_security_event_ingestion.py`, `../../e2e/security_center/test_security_event_observation_panel.py`, or the harness business vocabulary to make absent implementation pass.
