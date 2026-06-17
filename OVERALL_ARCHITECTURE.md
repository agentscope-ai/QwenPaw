# Overall Implementation Architecture

## Scope
- Freeze the stable implementation boundaries that currently realize QwenPaw in this repository.
- Materialize `security-center-event-observation-panel-v1` as a Security Event Ingestion V1 read-only operator observation surface over accepted events and failed reception records.
- Materialize the `sec-e2e-024`, `sec-e2e-025`, `sec-e2e-027`, `sec-e2e-028`, `sec-e2e-021`, and `sec-e2e-029` explicit acceptance entrypoints as repository-owned, read-only testcase bodies plus their harness abstractions.
- Constrain the explicit security slice to a real-environment acceptance baseline that uses the live app subprocess, real HTTP surfaces, isolated working directories, and a separately contracted cloud-side Security Center boundary.
- Record where intent is already directly implemented, where current code only provides transitional evidence, and which gaps are intentionally handed to Coding/Repair.

## Stable Elements
- path: src/qwenpaw
  kind: RuntimeRoot
  implements:
    - intent-backend-runtime
  contract: src/qwenpaw/ARCHITECTURE.md
  role: Python runtime root that owns backend orchestration, channel/runtime glue, packaged CLI surfaces, and the stable child security boundary.

- path: src/qwenpaw/security
  kind: SecurityAuditFoundation
  implements:
    - intent-local-security-audit-foundation
    - intent-high-risk-tool-guard
  contract: src/qwenpaw/security/ARCHITECTURE.md
  role: Stable backend-owned boundary for trusted security context provenance, high-risk confirmation evidence, local audit-chain semantics, heartbeat/uplink evidence emission, lease-aware reconnect gating, normal-offline reconnect admission, Integrity Protection backend semantics, and the local projection/query seam consumed by `sec-e2e-024`, `sec-e2e-025`, `sec-e2e-027`, `sec-e2e-028`, and `ip-e2e-007`.

- path: src/qwenpaw/cli
  kind: OperatorCli
  implements:
    - intent-local-operator-cli
  contract: src/qwenpaw/cli/ARCHITECTURE.md
  role: Local operator command surface mounted under the `qwenpaw` entrypoint.

- path: console
  kind: OperatorConsole
  implements:
    - intent-console-frontend
  contract: console/ARCHITECTURE.md
  role: Browser and desktop-oriented operator console built with Vite, React, and Tauri assets.

- path: website
  kind: DocumentationSite
  implements:
    - intent-docs-website
  contract: website/ARCHITECTURE.md
  role: Public documentation and adoption website.

- path: tests
  kind: VerificationSuite
  contract: tests/ARCHITECTURE.md
  role: Physical owner of explicit testcase entrypoints, business-readable security harnesses, and architecture guardrail tests.

- path: tests/integration/security
  kind: ExplicitSecurityEntrypointZone
  contract: tests/integration/security/ARCHITECTURE.md
  role: Read-only explicit security acceptance entrypoints and harness abstractions whose bodies are written for business readability rather than plumbing detail.

- path: deploy
  kind: SecurityCenterDeploymentBoundary
  implements:
    - intent-security-center
    - intent-cloud-integrity-stub
    - intent-security-event-ingestion-v1
  contract: deploy/ARCHITECTURE.md
  role: Stable repository-owned contract boundary for the physically separate Security Center service, including a cloud-side HTTP API backend, an operator-facing web frontend, SSE or WebSocket alert delivery to operators, the integrity mirror seam consumed only through edge-to-cloud HTTP, and the Security Event Ingestion V1 intake/inbox/observation capability for configured internal systems.

- path: deploy/config/security-event-contracts.v1.json
  kind: SecurityEventContractConfig
  implements:
    - intent-security-event-contract-config
  role: Repository-owned V1 configuration artifact for enabled source systems, allowed event types, schema versions, payload field validation, list-display metadata, and bounded failure/raw-payload display limits.

- path: .github/validator
  kind: BootstrapAssetZone
  implements:
    - intent-architecture-validator
  contract: .github/validator/ARCHITECTURE.md
  role: Schema and handoff validator scripts invoked by repository-native npm validation commands.

## Dependency Direction
- `src/qwenpaw/app`, channels, and runner glue may capture transport/session metadata, but `src/qwenpaw/security` owns the stable semantics for trusted provenance, confirmation evidence, and audit continuity. Transport layers must not redefine the acceptance boundary for `sec-e2e-024`.
- `src/qwenpaw/security` must not depend on `console` or `website` implementation details.
- `src/qwenpaw/security` may uplink summaries toward the `deploy` boundary, but the cloud-side Security Center must remain a separate process and independent durable store rather than an in-process branch of the edge runtime.
- `src/qwenpaw/security` owns the canonical runtime client identity used at the cloud boundary for lease heartbeat, recovery preflight, lockdown, restored-access projection, and operator timeline reads. Browser or session ids may remain edge-side audit metadata or display aliases, but they must not increase Security Center `client_count`, become separate canonical terminals, or create a false `DIVERGED`/`OPEN` fork state for one live runtime.
- Edge runtime communication with `deploy` is frozen to repository-owned HTTP APIs only. Coding/Repair must not switch this slice to shared storage, direct database access, or a different transport without a new implementation-architecture change.
- `src/qwenpaw/cli` depends inward on stable runtime and config surfaces in `src/qwenpaw` and does not own backend orchestration state.
- `tests` and `tests/integration/security` may observe all stable elements through declared seams; production code must not depend on test modules.
- `.github/validator` validates design assets and testcase execution wiring but does not own product behavior.

## Intent Realization Mapping
- direct implementation: `src/qwenpaw` realizes `intent-backend-runtime`.
- direct implementation: `src/qwenpaw/security` realizes `intent-local-security-audit-foundation` and its child `intent-high-risk-tool-guard`.
- indirect implementation chain: `src/qwenpaw/app/agent_context.py` provides current contextvars evidence for `intent-implicit-security-context-manager` under the owning `src/qwenpaw/security` contract.
- indirect implementation chain: `src/qwenpaw/app/approvals/service.py` provides current approval-routing evidence that must be converged into durable confirmation evidence under the owning `src/qwenpaw/security` contract.
- indirect implementation chain: `src/qwenpaw/app/inbox_trace_store.py` provides append-only trace evidence that must be converged into canonical audit-chain projection under the owning `src/qwenpaw/security` contract.
- direct architecture boundary materialization: `deploy/ARCHITECTURE.md` realizes the stable repository-owned collaboration contract for `intent-security-center` and `intent-cloud-integrity-stub` while preserving cloud-side process separation from the edge runtime.
- direct sub-boundary materialization: `deploy/api/ARCHITECTURE.md` freezes the Security Center backend HTTP API service consumed by the edge runtime and operator web, including SSE or WebSocket alert publication, nonce voucher APIs, and shadow-hash divergence timeline delivery.
- direct sub-boundary materialization: `deploy/api/ARCHITECTURE.md` freezes the Security Center backend HTTP API service consumed by the edge runtime and operator web, including the lease registry, TTL expiry downgrade path, reconnect recovery gate, SSE or WebSocket alert publication, nonce voucher APIs, and shadow-hash divergence timeline delivery.
- direct sub-boundary materialization: `deploy/web/ARCHITECTURE.md` freezes the operator-facing Security Center web frontend that visualizes anomalies, rejected events, recovery state, hash-break curve forks, and nonce-driven red alerts.
- direct implementation boundary: `deploy/api/ARCHITECTURE.md` owns `intent-security-event-ingestion-v1`, `intent-security-event`, and `intent-security-event-failure-record` for V1 event intake, configuration validation, durable-before-success accepted-event persistence, failure reception records, list/detail query APIs, persistence-error semantics, idempotency, and bounded oversized invalid payload summaries.
- direct implementation boundary: `deploy/web/ARCHITECTURE.md` owns `intent-security-event-inbox-web` by consuming deploy/api list/detail APIs only; it renders receivedAt-descending inbox rows, filters, configured list fields, stable detail URLs, undefined fields, and bounded read-only raw payload without Web configuration editing.
- direct implementation boundary: `deploy/api/ARCHITECTURE.md` owns the observation-panel read model for `intent-security-event-observation-panel-v1`: default latest 24h range when no explicit range is supplied, 1h/24h/7d quick ranges, accepted-event summary statistics, HIGH/MEDIUM alert ordering, raw reception rows for accepted and failed submissions, failed-reception time-range membership by backend `receivedAt`, and sourceSystem plus eventId focus for alert-to-raw traceability.
- direct implementation boundary: `deploy/web/ARCHITECTURE.md` owns the operator observation panel UI for `intent-security-event-observation-panel-v1` by consuming deploy/api only; it must not introduce disposition, ticketing, assignment, approval, risk scoring, custom analytics, raw-payload full-text search, raw-payload export, requester identity, or authentication behavior.
- direct configuration materialization: `deploy/config/security-event-contracts.v1.json` realizes `intent-security-event-contract-config` and is the frozen V1 configuration baseline for `sourceSystem`, `eventTypeId`, `schemaVersion`, payload field labels/types/required flags/enums/max lengths/list flags, and bounded failure/raw display limits.
- direct testcase materialization: `tests/integration/security/test_audit_foundation.py::test_end_to_end_non_repudiation_evidence_chain` is the read-only explicit entrypoint for `sec-e2e-024-end-to-end-non-repudiation-evidence-chain`, and it must run through the real `app_server` fixture rather than repository source inspection.
- direct testcase materialization: `tests/integration/security/test_audit_foundation.py::test_audit_integrity_self_healing_lockdown` is the read-only explicit entrypoint for `sec-e2e-025-audit-integrity-self-healing-lockdown`.
- direct testcase materialization detail: `sec-e2e-025-audit-integrity-self-healing-lockdown` now freezes the historical tamper branch where three high-risk records are created, the second committed non-tail record is edited by operating-system means, the next high-risk boundary must enter `UNTRUSTED`, and Security Center backend/web must remain recovery-required rather than `CLEAR` until cloud-validated full-chain recovery.
- direct testcase materialization: `tests/integration/security/test_audit_foundation.py::test_lease_expiry_blocks_untrusted_rejoin_until_gap_sync` is the read-only explicit entrypoint for `sec-e2e-027-lease-expiry-active-defense`, and its implementation-architecture contract freezes one entrypoint with two control points plus two distinct console observation points: `pre_recovery_console_status` for the denied rejoin frame before missing-gap verification and `post_recovery_console_status` for the restored-access frame after continuity validation.
- direct testcase materialization: `tests/integration/security/test_audit_foundation.py::test_normal_offline_reconnect_clears_without_gap_recovery` is the read-only explicit entrypoint for `sec-e2e-028-normal-offline-reconnect-clear-state`, and its implementation-architecture contract freezes the non-incident reconnect branch: trusted audit head, normal offline stop, same canonical client restarted before lease expiry, Security Center backend/web projecting `ALIGNED` or `TRUSTED` with `gap_status=CLEAR`, `recovery_gate_status=CLEAR`, `recovery_required=false`, and ordinary model access `200`.
- direct testcase materialization: `tests/integration/security/test_audit_foundation.py::test_prompt_injection_cannot_bypass_high_risk_tool_guard` is the read-only explicit entrypoint for `sec-e2e-021-prompt-injection-tool-guard-enforced`.
- direct testcase materialization: `tests/integration/security/test_security_event_ingestion.py::test_accepts_legal_event_after_persistence` is the read-only explicit entrypoint for `sec-event-ingestion-v1-accept-legal-event`.
- direct testcase materialization: `tests/integration/security/test_security_event_ingestion.py::test_rejects_invalid_event_config_boundary` is the read-only explicit entrypoint for `sec-event-ingestion-v1-reject-invalid-config-boundary`.
- direct testcase materialization: `tests/integration/security/test_security_event_ingestion.py::test_preserves_undefined_payload_fields_in_detail_only` is the read-only explicit entrypoint for `sec-event-ingestion-v1-preserve-undefined-payload-fields`.
- direct testcase materialization: `tests/integration/security/test_security_event_ingestion.py::test_enforces_source_event_id_idempotency` is the read-only explicit entrypoint for `sec-event-ingestion-v1-enforce-idempotency`.
- direct testcase materialization: `tests/e2e/security_center/test_security_event_inbox.py::test_web_lists_filters_and_opens_event_detail` is the read-only explicit entrypoint for `sec-event-ingestion-v1-render-web-list-and-detail`.
- direct testcase materialization: `tests/integration/security/test_security_event_ingestion.py::test_records_failed_receptions_without_business_event_pollution` is the read-only explicit entrypoint for `sec-event-ingestion-v1-bound-failure-records`.
- direct testcase materialization: `tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_summarizes_current_event_posture` is the read-only explicit entrypoint for observation-panel posture statistics.
- direct testcase materialization: `tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_filters_alerts_by_severity` is the read-only explicit entrypoint for alert severity scope.
- direct testcase materialization: `tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_sorts_alerts_by_severity_and_occurred_at` is the read-only explicit entrypoint for severity-plus-occurredAt alert ordering.
- direct testcase materialization: `tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_shows_failed_receptions_in_raw_records` is the read-only explicit entrypoint for failed reception visibility in raw records.
- direct testcase materialization: `tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_links_alert_to_raw_record` is the read-only explicit entrypoint for sourceSystem plus eventId alert-to-raw traceability.
- direct testcase materialization: `tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_applies_time_range_consistently` is the read-only explicit entrypoint for shared 1h/24h/7d time-range interpretation.

## Explicit Testcase Materialization
- testcase: cli-version-surface
  intent_element: intent-local-operator-cli
  entrypoint: tests/unit/cli/test_cli_version.py::test_cli_version_option_outputs_current_version

- testcase: agents-list-surface
  intent_element: intent-local-operator-cli
  entrypoint: tests/unit/cli/test_cli_agents.py::test_agents_list_uses_shared_tool_helper

- testcase: task-help-surface
  intent_element: intent-local-operator-cli
  entrypoint: tests/unit/cli/test_cli_task.py::test_task_command_registered_in_cli

- testcase: settings-language-roundtrip
  intent_element: intent-backend-runtime
  entrypoint: tests/unit/routers/test_settings.py::test_put_then_get_roundtrip

- testcase: git-helper-command-runner
  intent_element: intent-backend-runtime
  entrypoint: tests/unit/routers/test_git.py::test_git_helper_uses_shared_command_runner

- testcase: sec-e2e-024-end-to-end-non-repudiation-evidence-chain
  intent_element: intent-local-security-audit-foundation
  entrypoint: tests/integration/security/test_audit_foundation.py::test_end_to_end_non_repudiation_evidence_chain
  runtime_mode: real-app-subprocess

- testcase: sec-e2e-025-audit-integrity-self-healing-lockdown
  intent_element: intent-local-security-audit-foundation
  entrypoint: tests/integration/security/test_audit_foundation.py::test_audit_integrity_self_healing_lockdown
  runtime_mode: real-app-subprocess

- testcase: sec-e2e-027-lease-expiry-active-defense
  intent_element: intent-local-security-audit-foundation
  entrypoint: tests/integration/security/test_audit_foundation.py::test_lease_expiry_blocks_untrusted_rejoin_until_gap_sync
  runtime_mode: real-app-subprocess

- testcase: sec-e2e-028-normal-offline-reconnect-clear-state
  intent_element: intent-local-security-audit-foundation
  entrypoint: tests/integration/security/test_audit_foundation.py::test_normal_offline_reconnect_clears_without_gap_recovery
  runtime_mode: real-app-subprocess

- testcase: sec-e2e-021-prompt-injection-tool-guard-enforced
  intent_element: intent-high-risk-tool-guard
  entrypoint: tests/integration/security/test_audit_foundation.py::test_prompt_injection_cannot_bypass_high_risk_tool_guard
  runtime_mode: real-app-subprocess

- testcase: sec-e2e-029-builtin-rule-line-ending-invariant
  intent_element: intent-builtin-tool-rule-integrity
  entrypoint: tests/unit/security/tool_guard/test_rules_integrity.py::test_builtin_rule_line_ending_invariant
  runtime_mode: unit-harness-with-temporary-rules-directory

- testcase: sec-event-ingestion-v1-accept-legal-event
  intent_element: intent-security-event-ingestion-v1
  entrypoint: tests/integration/security/test_security_event_ingestion.py::test_accepts_legal_event_after_persistence
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: sec-event-ingestion-v1-reject-invalid-config-boundary
  intent_element: intent-security-event-ingestion-v1
  entrypoint: tests/integration/security/test_security_event_ingestion.py::test_rejects_invalid_event_config_boundary
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: sec-event-ingestion-v1-preserve-undefined-payload-fields
  intent_element: intent-security-event-ingestion-v1
  entrypoint: tests/integration/security/test_security_event_ingestion.py::test_preserves_undefined_payload_fields_in_detail_only
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: sec-event-ingestion-v1-enforce-idempotency
  intent_element: intent-security-event-ingestion-v1
  entrypoint: tests/integration/security/test_security_event_ingestion.py::test_enforces_source_event_id_idempotency
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: sec-event-ingestion-v1-render-web-list-and-detail
  intent_element: intent-security-event-inbox-web
  entrypoint: tests/e2e/security_center/test_security_event_inbox.py::test_web_lists_filters_and_opens_event_detail
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: sec-event-ingestion-v1-bound-failure-records
  intent_element: intent-security-event-ingestion-v1
  entrypoint: tests/integration/security/test_security_event_ingestion.py::test_records_failed_receptions_without_business_event_pollution
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: security-center-event-observation-panel-v1-posture-statistics
  intent_element: intent-security-event-observation-panel-v1
  entrypoint: tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_summarizes_current_event_posture
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: security-center-event-observation-panel-v1-alert-scope
  intent_element: intent-security-event-observation-panel-v1
  entrypoint: tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_filters_alerts_by_severity
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: security-center-event-observation-panel-v1-alert-ordering
  intent_element: intent-security-event-observation-panel-v1
  entrypoint: tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_sorts_alerts_by_severity_and_occurred_at
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: security-center-event-observation-panel-v1-failed-receptions-visible
  intent_element: intent-security-event-observation-panel-v1
  entrypoint: tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_shows_failed_receptions_in_raw_records
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: security-center-event-observation-panel-v1-alert-to-raw-traceability
  intent_element: intent-security-event-observation-panel-v1
  entrypoint: tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_links_alert_to_raw_record
  runtime_mode: real-security-center-api-and-web-subprocess

- testcase: security-center-event-observation-panel-v1-time-range-consistency
  intent_element: intent-security-event-observation-panel-v1
  entrypoint: tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_applies_time_range_consistently
  runtime_mode: real-security-center-api-and-web-subprocess

## Critical Non-Explicit Guardrails
- tests/architecture/root-architecture-contracts.test.js guards the presence and cross-reference integrity of the root contracts, including the new security contracts.
- tests/architecture/root-architecture-deliverables.test.js guards that the expected architecture deliverables exist at stable repository paths.
- tests/architecture/validator-bootstrap-traceability.test.js guards the wiring between `package.json` validation commands and bundled validator assets.
- tests/architecture/security-audit-contract-boundaries.test.js guards the frozen boundary between `src/qwenpaw/security`, the explicit security entrypoint zone, the separate Security Center deployment boundary, and the root/runtime/test contracts that reference them.
- tests/architecture/security-explicit-entrypoint-traceability.test.js guards that `sec-e2e-024`, `sec-e2e-025`, `sec-e2e-027`, `sec-e2e-028`, `sec-e2e-021`, and `sec-e2e-029` stay mounted to the read-only explicit entrypoints and that the implementation handoff keeps the same paths plus frozen execution-state traceability for open security gaps.
- tests/architecture/security-event-ingestion-contract-boundaries.test.js guards that Security Event Ingestion V1 stays mounted to `deploy/api`, `deploy/web`, `deploy/config/security-event-contracts.v1.json`, `tests/integration/security/test_security_event_ingestion.py`, `tests/integration/security/security_event_harness.py`, and `tests/e2e/security_center/test_security_event_inbox.py` with expected failing handoff entries until Coding/Repair implements the production behavior.
- tests/architecture/security-event-observation-panel-contract-boundaries.test.js guards that Security Event Observation Panel V1 stays mounted to deploy/api, deploy/web, the protected Security Event harness, six Web e2e entrypoints, and expected failing handoff entries until Coding/Repair implements the production read model and UI.

## Frozen Files For Downstream Coding
- design/KG/SystemArchitecture.json
- design/KG/IntentToImplementationHandoff.json
- design/KG/ImplementationToCodingHandoff.json
- design/KG/test-failure-records.json
- OVERALL_ARCHITECTURE.md
- src/qwenpaw/ARCHITECTURE.md
- src/qwenpaw/security/ARCHITECTURE.md
- src/qwenpaw/cli/ARCHITECTURE.md
- console/ARCHITECTURE.md
- website/ARCHITECTURE.md
- deploy/ARCHITECTURE.md
- deploy/api/ARCHITECTURE.md
- deploy/web/ARCHITECTURE.md
- deploy/config/security-event-contracts.v1.json
- tests/ARCHITECTURE.md
- tests/architecture/ARCHITECTURE.md
- tests/integration/security/ARCHITECTURE.md
- tests/integration/security/harness.py
- tests/integration/security/test_audit_foundation.py
- tests/integration/security/security_event_harness.py
- tests/integration/security/test_security_event_ingestion.py
- tests/e2e/security_center/ARCHITECTURE.md
- tests/e2e/security_center/conftest.py
- tests/e2e/security_center/test_security_event_inbox.py
- tests/contract/security/test_lease_recovery_semantics_contract.py
- tests/architecture/root-architecture-contracts.test.js
- tests/architecture/root-architecture-deliverables.test.js
- tests/architecture/security-audit-contract-boundaries.test.js
- tests/architecture/security-explicit-entrypoint-traceability.test.js
- tests/architecture/security-event-ingestion-contract-boundaries.test.js
- tests/architecture/security-event-observation-panel-contract-boundaries.test.js
- .github/validator/ARCHITECTURE.md

## Integrity Protection Delivery Addendum
- path: extension
  kind: ExtensionAdapterZone
  implements:
    - intent-integrity-protection-delivery
  contract: extension/ARCHITECTURE.md
  role: PRD-scoped adapter and design zone for low-intrusion Integrity Protection Delivery integration.

- path: extension/Intergrity  Protection Design.md
  kind: ImplementationDesignContract
  role: Stable as-built design handoff for persona baseline protection, health-check orchestration, and rule-integrity console exposure (source trust not implemented in this repository).

### Integrity Protection Dependency Direction
- `extension` may hold adapters and design documentation, but product behavior must integrate through stable `src/qwenpaw/security`, `src/qwenpaw/app`, `src/qwenpaw/cli`, and `console` contracts.
- `src/qwenpaw/security` owns backend integrity-protection settings projection and bridges extension adapters; it must not depend on console component internals.
- `console` owns Settings/Security rendering under `console/src/extension/` and consumes backend APIs through `console/src/api/modules/security.ts`.
- `tests/integration/security/test_integrity_protection.py` owns the business-readable acceptance bodies and must call `tests/integration/security/integrity_harness.py` rather than raw HTTP, raw environment, raw filesystem, SQL, Cypher, or GraphQL plumbing.

### Integrity Protection Intent Realization Mapping
- direct implementation: `extension/file_baseline/` plus `src/qwenpaw/security` bridge realizes `intent-persona-baseline-guardian`.
- direct implementation: `extension/health_check/` plus `src/qwenpaw/security/integrity_protection.py` re-export bridge realizes `intent-health-check-orchestrator`.
- direct implementation: `extension/rule_integrity/` realizes built-in rule integrity verify/repair exposure for `intent-builtin-tool-rule-integrity`.
- direct implementation: `console/src/extension/{file_baseline,health_check,rule_integrity}/` realizes `intent-integrity-security-console`.
- not implemented: `intent-source-trust-verifier` (prior demo removed 2026-06-11).
- indirect implementation chain: `thirdparty/clawsec-main/clawsec-main/skills/soul-guardian` carries persona baseline mechanics for `intent-persona-baseline-guardian`.
- indirect implementation chain: `src/qwenpaw/cli/doctor_checks.py`, `doctor_connectivity.py`, and `doctor_fix_runner.py` carry doctor semantics reused by `extension/health_check/projection.py` and `fix.py`.
- as-built health check projection: `extension/health_check/projection.py` builds structured doctor coverage items; `integrity_protection.py` re-exports scan/fix entrypoints without parsing CLI stdout.
- as-built rule integrity: `extension/rule_integrity/` exposes passive check and explicit repair; Console uses `RuleIntegrityPassiveCard` and `RuleIntegrityRepairBanner`.
- direct testcase materialization: `tests/integration/security/test_integrity_protection.py::test_security_i18n_and_healthcheck_progress_carousel` is the read-only explicit entrypoint for `ip-e2e-006-security-i18n-progress-carousel`, freezing English/Simplified Chinese Settings/Security copy, English fallback, Health Check carousel rotation, terminal-state carousel shutdown, and scan-only/no-fix-before-confirmation boundary.
- direct testcase materialization: `tests/integration/security/test_integrity_protection.py::test_healthcheck_full_doctor_coverage_projection` is the read-only explicit entrypoint for `ip-e2e-007-healthcheck-full-doctor-coverage`, freezing default scan-only full doctor coverage projection, grouped structured result fields, carousel candidates sourced from doctor items, English/Simplified Chinese labels, and explicit opt-in deep connectivity via backend API (`deep=true`; Console UI calls `deep=false` only).

### Integrity Protection Explicit Testcase Materialization
- testcase: ip-e2e-001-integrity-security-menu-default-off
  intent_element: intent-integrity-protection-delivery
  entrypoint: tests/integration/security/test_integrity_protection.py::test_integrity_security_menu_default_off
  runtime_mode: business-readable integration harness, currently passing after Coding/Repair implementation

- testcase: ip-e2e-002-persona-drift-alert-restore-accept
  intent_element: intent-persona-baseline-guardian
  entrypoint: tests/integration/security/test_integrity_protection.py::test_file_baseline_drift_alert_restore_accept
  runtime_mode: business-readable integration harness, currently passing after Coding/Repair implementation

- testcase: ip-e2e-003-source-trust-verification-package
  intent_element: intent-source-trust-verifier
  entrypoint: deferred (demo implementation reverted 2026-06-11; see extension/Intergrity  Protection PRD.txt section 二)
  runtime_mode: intent-only until ClawSec guarded_skill_install integration ships

- testcase: ip-e2e-004-health-check-scan-and-confirmed-fix
  intent_element: intent-health-check-orchestrator
  entrypoint: tests/integration/security/test_integrity_protection.py::test_health_check_scan_and_confirmed_fix
  runtime_mode: business-readable integration harness, currently passing after Coding/Repair implementation

- testcase: ip-e2e-005-rule-integrity-entry-visible
  intent_element: intent-builtin-tool-rule-integrity
  entrypoint: extension/rule_integrity/tests/test_integration_entry.py::test_rule_integrity_entry_visible
  runtime_mode: business-readable integration harness, currently passing after Coding/Repair implementation

- testcase: ip-e2e-006-security-i18n-progress-carousel
  intent_element: intent-integrity-security-console
  entrypoint: tests/integration/security/test_integrity_protection.py::test_security_i18n_and_healthcheck_progress_carousel
  runtime_mode: business-readable integration harness, currently passing after Coding/Repair implementation

- testcase: ip-e2e-007-healthcheck-full-doctor-coverage
  intent_element: intent-health-check-orchestrator
  entrypoint: tests/integration/security/test_integrity_protection.py::test_healthcheck_full_doctor_coverage_projection
  runtime_mode: business-readable integration harness; verifies full doctor projection via backend API including explicit `deep=true` (Console UI uses default scan only)

### Integrity Protection Critical Non-Explicit Guardrails
- `extension/run-integrity-delivery-selftest.py` runs wiring, backend, and frontend selftests for rule integrity, persona baseline, and health check slices.

### Integrity Protection Frozen Files For Downstream Coding
- extension/ARCHITECTURE.md
- extension/Intergrity  Protection Design.md
- tests/integration/security/integrity_harness.py
- tests/integration/security/test_integrity_protection.py
- extension/rule_integrity/tests/test_integration_entry.py
