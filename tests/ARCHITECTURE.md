---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: qwenpaw-verification-suite
element_kind: VerificationSuite
element_path: tests
---

## Implementation Architecture Contract

### Responsibility
- Own the physical repository entrypoints for explicit and non-explicit verification assets.
- Keep architecture guardrails under `tests/architecture` and product behavior tests under `unit/`, `integration/`, `contract/`, and `e2e/`.
- Keep explicit security acceptance bodies business-readable by routing low-level live-runtime inspection through harness helpers inside `tests/integration/security`.
- Own the Security Event Ingestion V1 explicit acceptance entrypoints and guardrails, including the Security Event Observation Panel V1 Web e2e entrypoints, while keeping business assertions behind `tests/integration/security/security_event_harness.py`.

### Out Of Scope
- Defining acceptance scope independently from `design/KG/SystemArchitecture.json`.
- Owning production code or runtime bootstrap logic.

### Children
- path: unit
  kind: explicit-entrypoint-zone
  role: lightweight pytest entrypoints used as the current CLI and backend explicit testcase baselines
- path: architecture
  kind: architecture-guard-zone
  role: critical non-explicit tests protecting architecture deliverables, validator wiring, and security-entrypoint traceability
- path: integration/security
  kind: explicit-entrypoint-zone
  role: business-readable security acceptance entrypoints and protected harness helpers
- path: integration
  kind: supporting-verification-zone
  role: integration-level regression coverage owned by implementation
- path: e2e
  kind: supporting-verification-zone
  role: end-to-end behavior coverage, including the Security Center Web inbox and observation-panel explicit baselines under `e2e/security_center`

### Explicit Testcase Entrypoints
- unit/cli/test_cli_version.py::test_cli_version_option_outputs_current_version
- unit/cli/test_cli_agents.py::test_agents_list_uses_shared_tool_helper
- unit/cli/test_cli_task.py::test_task_command_registered_in_cli
- unit/routers/test_settings.py::test_put_then_get_roundtrip
- unit/routers/test_git.py::test_git_helper_uses_shared_command_runner
- integration/security/test_audit_foundation.py::test_end_to_end_non_repudiation_evidence_chain
- integration/security/test_audit_foundation.py::test_audit_integrity_self_healing_lockdown
- integration/security/test_audit_foundation.py::test_lease_expiry_blocks_untrusted_rejoin_until_gap_sync
- integration/security/test_audit_foundation.py::test_normal_offline_reconnect_clears_without_gap_recovery
- integration/security/test_audit_foundation.py::test_prompt_injection_cannot_bypass_high_risk_tool_guard
- integration/security/test_security_event_ingestion.py::test_accepts_legal_event_after_persistence
- integration/security/test_security_event_ingestion.py::test_rejects_invalid_event_config_boundary
- integration/security/test_security_event_ingestion.py::test_preserves_undefined_payload_fields_in_detail_only
- integration/security/test_security_event_ingestion.py::test_enforces_source_event_id_idempotency
- integration/security/test_security_event_ingestion.py::test_records_failed_receptions_without_business_event_pollution
- e2e/security_center/test_security_event_inbox.py::test_web_lists_filters_and_opens_event_detail
- e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_summarizes_current_event_posture
- e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_filters_alerts_by_severity
- e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_sorts_alerts_by_severity_and_occurred_at
- e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_shows_failed_receptions_in_raw_records
- e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_links_alert_to_raw_record
- e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_applies_time_range_consistently

### Critical Non-Explicit Tests
- architecture/root-architecture-contracts.test.js
- architecture/root-architecture-deliverables.test.js
- architecture/validator-bootstrap-traceability.test.js
- architecture/security-audit-contract-boundaries.test.js
- architecture/security-explicit-entrypoint-traceability.test.js
- architecture/security-runtime-client-identity-boundary.test.js
- architecture/security-runtime-lease-persistence-boundary.test.js
- architecture/security-event-ingestion-contract-boundaries.test.js
- architecture/security-event-observation-panel-contract-boundaries.test.js

### Supporting Non-Explicit Tests
- integration/test_security_config.py
- contract/security/test_lease_recovery_semantics_contract.py

### Protected Fixtures
- integration/security/harness.py
- integration/security/security_event_harness.py

### Notes
- The current explicit testcases are intentionally anchored to repository-owned pytest entrypoints so the architecture baseline stays executable in the current workspace state.
- `tests/integration/security/harness.py` is a protected fixture for explicit security acceptance bodies. Coding/Repair may realize the runtime behind it, but should not rewrite its business-facing vocabulary, runtime-inspection method names, the required `app_server` real-environment binding, or the read-only testcase entrypoints without an upstream architecture change.
- For `sec-e2e-027`, that protected fixture now freezes two separate console observation points, `pre_recovery_console_status` and `post_recovery_console_status`, so the denied rejoin frame and restored-access frame remain independently observable.
- `tests/contract/security/test_lease_recovery_semantics_contract.py` is a supporting contract-test entrypoint that now guards the closed sec-e2e-027 intent semantics beneath the explicit acceptance path: Security Center must keep a true TTL-driven lease downgrade path and a full-chain cloud-side gap-validation path. These tests are now expected to pass and serve as regression guards.
- That same contract-test entrypoint now also guards the closed startup-heartbeat requirement from the updated intent handoff: a real runtime must register a lease heartbeat automatically before any user prompt mentions lease warmup or lease expiry. That startup-heartbeat contract is now expected to pass and serves as a regression guard for the product background Heartbeat Emitter.
- That same contract-test entrypoint now also owns the live supporting guard `contract/security/test_lease_recovery_semantics_contract.py::test_security_center_projects_one_online_runtime_as_one_canonical_terminal`.
- Control point: start a real runtime, allow automatic startup heartbeat registration, then drive one session-scoped lease warmup through the live console without forking the runtime.
- Observation point: Security Center must still project exactly one canonical terminal for that online runtime and must not show a false `DIVERGED`/`OPEN` local-hash mismatch when no fork point exists. Current repository state is expected to pass, and this entrypoint remains the behavior-level regression guard for canonical-runtime-client-id-003.
- That same contract-test entrypoint now also owns the durable-lease regression guard `contract/security/test_lease_recovery_semantics_contract.py::test_security_center_persists_runtime_lease_fields_and_downgrades_after_stop`.
- Control point: start a real runtime, observe a projected lease-bearing canonical client, inspect the durable Security Center store exposed by `tests/integration/conftest.py`, stop the runtime, then wait past the TTL window.
- Observation point: the durable store must already persist nonzero `last_heartbeat_at`, `lease_ttl_seconds`, and `lease_expires_at` for that same canonical client before runtime stop, and operator overview plus timeline must later expose `UNTRUSTED` with `divergence_reason=lease_ttl_expired`. Current repository state is expected to pass, and this entrypoint remains regression protection.
- That same contract-test entrypoint now also owns the startup normal-admission regression guard `contract/security/test_lease_recovery_semantics_contract.py::test_security_center_projects_fresh_runtime_startup_as_aligned_clear_terminal`.
- Control point: start a real runtime from a fresh bootstrap and observe Security Center before any intentional runtime stop, offline lease-expiry demonstration, or session-scoped recovery flow.
- Observation point: overview and timeline must show one canonical startup terminal with nonzero durable lease fields, `trust_state=ALIGNED`, `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, `recovery_required=false`, and no `missing_gap_proof` or other startup divergence reason. Current repository state is expected to pass, and this entrypoint remains regression protection for startup normal-admission semantics.
- That same contract-test entrypoint now also owns the live reconnect recovery guard `contract/security/test_lease_recovery_semantics_contract.py::test_security_center_live_reconnect_gap_proof_restores_access`.
- Control point: start API/Web/runtime from a reset state, establish a trusted canonical client, stop the runtime until Security Center projects `UNTRUSTED` with `divergence_reason=lease_ttl_expired`, then restart the same runtime and attempt restored model access without manual `/security-center/v1/recovery/handshake` proof injection.
- Observation point: the restarted runtime must first materialize a local missing-gap proof for the same reconnect session, then automatically drive Security Center back to `ALIGNED` or `TRUSTED` with `gap_status=VALIDATED` or `CLEAR`, `recovery_gate_status=CLEAR`, `recovery_required=false`, refreshed durable lease timing, and no continued 423 recovery-gated blocking at the端侧 access boundary. Current repository state is expected to pass, and this entrypoint remains regression protection for live reconnect recovery.
- `tests/integration/security/test_audit_foundation.py::test_normal_offline_reconnect_clears_without_gap_recovery` now owns the explicit `sec-e2e-028` normal-offline reconnect baseline. Control point: establish trusted audit-head continuity, gracefully stop the runtime, restart the same canonical client before lease expiry, then attempt ordinary model access through the real app subprocess. Observation point: Security Center backend and operator web must show `ALIGNED` or `TRUSTED`, `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, `recovery_required=false`, no missing-gap validation incident, and model access `200`.
- `tests/unit/security/tool_guard/test_rules_integrity.py::test_builtin_rule_line_ending_invariant` now owns the explicit `sec-e2e-029` built-in rule line-ending invariant baseline. Control point: stage the official signed manifest bundle into a temporary rules directory and verify LF-canonical, CRLF-only, and semantic-tamper content through `verify_builtin_rule_files`. Observation point: LF/CRLF branches return `ok=true` with `status=ok`; semantic tamper returns `ok=false` with `status=tampered` and `sha256_mismatch`.
- Live acceptance prerequisite: before reading operator overview or replaying the live guard against repository-local processes, reset the demo state with `scripts/reset-showcase-demo-state.ps1` and restart Security Center plus the QwenPaw runtime so stale store contents or stale processes do not create false positives.
- `tests/architecture/security-runtime-client-identity-boundary.test.js` is a critical non-explicit architecture guard for sec-e2e-027. Its control point is static code-boundary inspection of `src/qwenpaw/security/audit_foundation.py` and `deploy/api/store.py`; its observation point is that startup heartbeat, recovery preflight, lockdown, and restored-access projection must share one canonical Security Center client id instead of splitting a live runtime across `runtime-heartbeat::<fingerprint>` and browser-session ids.
- `tests/architecture/security-runtime-lease-persistence-boundary.test.js` is a critical non-explicit architecture guard for the reopened sec-e2e-027 lease-persistence gap. Its control point is static code-boundary inspection of `deploy/api/app.py` and `deploy/api/store.py`; its observation point is that the RecoveryHandshakeRequest contract must carry `lease_ttl_seconds`, the Security Center store must durably write `last_heartbeat_at`, `lease_ttl_seconds`, and `lease_expires_at`, and the implementation must not rely on projection-only fallback from `updated_at_ns` to hide zero lease fields.
- `tests/integration/conftest.py` now carries the shared real-app subprocess bootstrap baseline for integration entrypoints; when runtime startup fails, it must surface a readable `startup_error` to test bodies instead of terminating those entrypoints during fixture setup.
- `tests/integration/security/test_audit_foundation.py::test_audit_integrity_self_healing_lockdown` now owns the clarified sec-e2e-025 historical-record tamper branch. Control point: drive three high-risk actions, edit the second committed non-tail audit record through `tests/integration/security/harness.py`, then attempt another high-risk action without manual recovery. Observation point: the runtime must detect whole-ledger divergence before release, block the high-risk action, and keep Security Center backend/web recovery-required or `UNTRUSTED` rather than `CLEAR` until cloud-validated recovery.
- `tests/integration/security/test_security_event_ingestion.py` owns five Security Event Ingestion V1 explicit API/data entrypoints. Control point: drive legal, invalid, undefined-field, idempotency, real idempotency conflict, test-injected persistence-failure, and oversized-illegal-payload submissions through the real Security Center API subprocess. Observation point: accepted events, rejected submissions, failure records for every failed branch, idempotency semantics, persistence-failure event exclusion, and bounded summaries are visible through API list/detail/failure surfaces. Current repository state is expected to fail until `deploy/api` implements the event routes.
- `tests/e2e/security_center/test_security_event_inbox.py` owns the Security Event Inbox Web explicit entrypoint. Control point: seed accepted events, open the Web inbox, apply source/type/severity/time filters, and navigate to stable detail. Observation point: receivedAt-descending list, core/configured fields, event type display name, filter correctness, stable detail URL, base facts, structured payload, undefined fields, and bounded raw payload are observable through Web/API. Current repository state is expected to fail until `deploy/web` implements the inbox.
- `tests/architecture/security-event-ingestion-contract-boundaries.test.js` is a critical non-explicit explicit-entrypoint-correctness and implementation-traceability guard. Its control point is static inspection of `design/KG/SystemArchitecture.json`, `design/KG/ImplementationToCodingHandoff.json`, `OVERALL_ARCHITECTURE.md`, `deploy/api/ARCHITECTURE.md`, `deploy/web/ARCHITECTURE.md`, `deploy/config/security-event-contracts.v1.json`, `tests/integration/security/test_security_event_ingestion.py`, `tests/integration/security/security_event_harness.py`, and `tests/e2e/security_center/test_security_event_inbox.py`; its observation point is that all six V1 acceptance baselines, invalid-config branches, failed-reception branches, Web filter/detail assertions, protected failure-injection seam, business failure categories, and expected-failing handoff state remain frozen.
- `tests/e2e/security_center/test_security_event_observation_panel.py` owns six Security Event Observation Panel V1 explicit Web e2e entrypoints. Control point: seed accepted and failed reception records through the protected Security Event harness, open `/security-event-observation` without range for the default case, select quick ranges, and focus alerts by sourceSystem plus eventId. Observation point: deploy/api/deploy-web together expose default latest 24h posture summary equivalent to explicit `range=24h`, HIGH/MEDIUM alert scope, severity-plus-occurredAt ordering, failed reception raw evidence ranged by backend `receivedAt`, alert-to-raw focus, and 1h/24h/7d time-range consistency.
- `tests/architecture/security-event-observation-panel-contract-boundaries.test.js` is a critical non-explicit explicit-entrypoint-correctness and implementation-traceability guard. Its control point is static inspection of `design/KG/SystemArchitecture.json`, `design/KG/ImplementationToCodingHandoff.json`, `OVERALL_ARCHITECTURE.md`, `deploy/api/ARCHITECTURE.md`, `deploy/web/ARCHITECTURE.md`, `tests/ARCHITECTURE.md`, `tests/e2e/security_center/ARCHITECTURE.md`, `tests/integration/security/security_event_harness.py`, and `tests/e2e/security_center/test_security_event_observation_panel.py`; its observation point is that all six observation-panel acceptance baselines, protected Harness category strings, API/Web route markers, business-readable GIVEN/WHEN/THEN bodies, and expected failing handoff state remain frozen.
