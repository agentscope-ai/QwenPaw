---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: qwenpaw-architecture-guards
element_kind: ArchitectureGuardrailZone
element_path: tests/architecture
---

## Implementation Architecture Contract

### Responsibility
- Hold critical non-explicit tests that guard architecture-deliverable traceability, validator bootstrap integrity, the new security audit boundary, and explicit-entrypoint traceability.

### Children
- path: root-architecture-contracts.test.js
  kind: critical-non-explicit-test
  role: verifies that the root contract and required local contracts remain present and referenced
- path: root-architecture-deliverables.test.js
  kind: critical-non-explicit-test
  role: verifies that the expected architecture deliverables exist at stable repository paths
- path: validator-bootstrap-traceability.test.js
  kind: critical-non-explicit-test
  role: verifies the root npm validation scripts still point to the bundled validator assets and required schema files
- path: security-audit-contract-boundaries.test.js
  kind: critical-non-explicit-test
  role: verifies the new security contract, explicit-entrypoint-zone contract, and protected harness files stay wired together
- path: security-explicit-entrypoint-traceability.test.js
  kind: critical-non-explicit-test
  role: verifies `sec-e2e-024` remains mounted to the declared explicit entrypoint, keeps its real-environment runtime-inspection shape, and preserves failure-record traceability
- path: security-runtime-client-identity-boundary.test.js
  kind: critical-non-explicit-test
  role: verifies sec-e2e-027 still uses one canonical Security Center client id across startup heartbeat, recovery, lockdown, and restored-access projection instead of splitting one live runtime into multiple cloud clients; the complementary live behavior guard lives in ../../tests/contract/security/test_lease_recovery_semantics_contract.py
- path: security-runtime-lease-persistence-boundary.test.js
  kind: critical-non-explicit-test
  role: verifies sec-e2e-027 still freezes lease_ttl_seconds into the Security Center API request contract and durable store instead of allowing overview/timeline to hide zero lease fields through projection-only fallback
- path: security-event-ingestion-contract-boundaries.test.js
  kind: critical-non-explicit-test
  role: verifies Security Event Ingestion V1 explicit entrypoints, config artifact, deploy/api contract, deploy/web contract, protected harness, and ImplementationToCoding expected-failure state remain aligned
- path: security-event-observation-panel-contract-boundaries.test.js
  kind: critical-non-explicit-test
  role: verifies Security Event Observation Panel V1 explicit entrypoints, default latest 24h no-range behavior, failed-reception backend receivedAt range source, deploy/api read-model contract, deploy/web route contract, protected harness, and ImplementationToCoding expected-failure state remain aligned

### Test Guardrails
#### critical_non_explicit_tests
- test_id: root-architecture-contracts
  critical_kind: implementation-traceability
  test_path: root-architecture-contracts.test.js
  execution_entry: root-architecture-contracts.test.js
  guards_elements:
    - ../../OVERALL_ARCHITECTURE.md
    - ../../src/qwenpaw/ARCHITECTURE.md
    - ../../src/qwenpaw/security/ARCHITECTURE.md
    - ../../tests/ARCHITECTURE.md
    - ../../tests/integration/security/ARCHITECTURE.md
  protected_baselines:
    - ARCHITECTURE.md
    - ../../OVERALL_ARCHITECTURE.md
    - ../../src/qwenpaw/security/ARCHITECTURE.md
  rationale: keep root-to-local contract references aligned after the security audit boundary is frozen
  frozen_by_stage: implementationdesign
- test_id: root-architecture-deliverables-presence
  critical_kind: implementation-traceability
  test_path: root-architecture-deliverables.test.js
  execution_entry: root-architecture-deliverables.test.js
  guards_elements:
    - ../../OVERALL_ARCHITECTURE.md
    - ../../design/KG/SystemArchitecture.json
    - ../../design/KG/IntentToImplementationHandoff.json
    - ../../design/KG/ImplementationToCodingHandoff.json
    - ../../design/KG/test-failure-records.json
  protected_baselines:
    - ARCHITECTURE.md
    - ../../OVERALL_ARCHITECTURE.md
  rationale: keep the root architecture delivery set present at stable repository paths once implementation design has materialized it
  frozen_by_stage: implementationdesign
- test_id: validator-bootstrap-traceability
  critical_kind: implementation-traceability
  test_path: validator-bootstrap-traceability.test.js
  execution_entry: validator-bootstrap-traceability.test.js
  guards_elements:
    - ../../.github/validator
  protected_baselines:
    - ARCHITECTURE.md
    - ../../.github/validator/ARCHITECTURE.md
  rationale: keep validator bootstrap assets and root npm script wiring traceable to the declared architecture boundary
  frozen_by_stage: implementationdesign
- test_id: security-audit-contract-boundaries
  critical_kind: architecture-boundary
  test_path: security-audit-contract-boundaries.test.js
  execution_entry: security-audit-contract-boundaries.test.js
  guards_elements:
    - ../../src/qwenpaw/security/ARCHITECTURE.md
    - ../../tests/integration/security/ARCHITECTURE.md
    - ../../tests/integration/security/test_audit_foundation.py
  protected_baselines:
    - ARCHITECTURE.md
    - ../../src/qwenpaw/security/ARCHITECTURE.md
    - ../../tests/integration/security/harness.py
    - ../../tests/integration/security/test_audit_foundation.py
  rationale: keep the sec-e2e-024 owning security boundary and its explicit entrypoint zone stable while implementation moves underneath
  frozen_by_stage: implementationdesign
- test_id: security-explicit-entrypoint-traceability
  critical_kind: explicit-entrypoint-correctness
  test_path: security-explicit-entrypoint-traceability.test.js
  execution_entry: security-explicit-entrypoint-traceability.test.js
  guards_elements:
    - ../../design/KG/SystemArchitecture.json
    - ../../design/KG/ImplementationToCodingHandoff.json
    - ../../design/KG/test-failure-records.json
  protected_baselines:
    - ARCHITECTURE.md
    - ../../tests/integration/conftest.py
    - ../../tests/integration/security/test_audit_foundation.py
    - ../../tests/integration/security/harness.py
  rationale: keep sec-e2e-024 pointed at one read-only entrypoint, freeze the real-app runtime-inspection assertions plus readable startup-failure surface that make the testcase harder to bypass, and preserve the first expected-failure signal handed to Coding/Repair
  frozen_by_stage: implementationdesign
- test_id: security-runtime-client-identity-boundary
  critical_kind: implementation-traceability
  test_path: security-runtime-client-identity-boundary.test.js
  execution_entry: security-runtime-client-identity-boundary.test.js
  guards_elements:
    - ../../src/qwenpaw/security/audit_foundation.py
    - ../../deploy/api/store.py
    - ../../design/KG/ImplementationToCodingHandoff.json
  protected_baselines:
    - ARCHITECTURE.md
    - ../../src/qwenpaw/security/ARCHITECTURE.md
    - ../../deploy/api/ARCHITECTURE.md
  rationale: keep the static identity boundary frozen while the complementary live supporting contract proves that one online runtime must not surface as multiple canonical terminals or a false DIVERGED fork for sec-e2e-027
  frozen_by_stage: implementationdesign
- test_id: security-runtime-lease-persistence-boundary
  critical_kind: implementation-traceability
  test_path: security-runtime-lease-persistence-boundary.test.js
  execution_entry: security-runtime-lease-persistence-boundary.test.js
  guards_elements:
    - ../../deploy/api/app.py
    - ../../deploy/api/store.py
    - ../../design/KG/ImplementationToCodingHandoff.json
  protected_baselines:
    - ARCHITECTURE.md
    - ../../deploy/api/ARCHITECTURE.md
    - ../../tests/contract/security/test_lease_recovery_semantics_contract.py
  rationale: keep the lease-persistence boundary frozen so Coding/Repair must carry lease_ttl_seconds through the HTTP contract into the durable Security Center store rather than masking zero lease fields with projection-only read-model fallback
  frozen_by_stage: implementationdesign
- test_id: security-event-ingestion-contract-boundaries
  critical_kind: explicit-entrypoint-correctness
  test_path: security-event-ingestion-contract-boundaries.test.js
  execution_entry: security-event-ingestion-contract-boundaries.test.js
  guards_elements:
    - ../../design/KG/SystemArchitecture.json
    - ../../design/KG/ImplementationToCodingHandoff.json
    - ../../OVERALL_ARCHITECTURE.md
    - ../../deploy/api/ARCHITECTURE.md
    - ../../deploy/web/ARCHITECTURE.md
    - ../../deploy/config/security-event-contracts.v1.json
    - ../../tests/integration/security/test_security_event_ingestion.py
    - ../../tests/integration/security/security_event_harness.py
    - ../../tests/e2e/security_center/test_security_event_inbox.py
  protected_baselines:
    - ARCHITECTURE.md
    - ../../deploy/api/ARCHITECTURE.md
    - ../../deploy/web/ARCHITECTURE.md
    - ../../deploy/config/security-event-contracts.v1.json
    - ../../tests/integration/security/test_security_event_ingestion.py
    - ../../tests/integration/security/security_event_harness.py
    - ../../tests/e2e/security_center/test_security_event_inbox.py
  rationale: keep the six Security Event Ingestion V1 acceptance baselines executable, business-readable, and expected-failing until Coding/Repair implements the production API/Web behavior
  frozen_by_stage: implementationdesign
- test_id: security-event-observation-panel-contract-boundaries
  critical_kind: explicit-entrypoint-correctness
  test_path: security-event-observation-panel-contract-boundaries.test.js
  execution_entry: security-event-observation-panel-contract-boundaries.test.js
  guards_elements:
    - ../../design/KG/SystemArchitecture.json
    - ../../design/KG/ImplementationToCodingHandoff.json
    - ../../OVERALL_ARCHITECTURE.md
    - ../../deploy/ARCHITECTURE.md
    - ../../deploy/api/ARCHITECTURE.md
    - ../../deploy/web/ARCHITECTURE.md
    - ../../tests/ARCHITECTURE.md
    - ../../tests/integration/security/security_event_harness.py
    - ../../tests/e2e/security_center/ARCHITECTURE.md
    - ../../tests/e2e/security_center/test_security_event_observation_panel.py
  protected_baselines:
    - ARCHITECTURE.md
    - ../../deploy/api/ARCHITECTURE.md
    - ../../deploy/web/ARCHITECTURE.md
    - ../../tests/integration/security/security_event_harness.py
    - ../../tests/e2e/security_center/ARCHITECTURE.md
    - ../../tests/e2e/security_center/test_security_event_observation_panel.py
  rationale: keep the six Security Event Observation Panel V1 acceptance baselines executable, business-readable, and expected-failing until Coding/Repair implements the production read model and Web panel, including default latest 24h and failed-reception backend receivedAt time-range semantics
  frozen_by_stage: implementationdesign
