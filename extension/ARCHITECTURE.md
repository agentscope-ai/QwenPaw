---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: qwenpaw-extension-adapters
element_kind: ExtensionAdapterZone
element_path: extension
---

## Implementation Architecture Contract

### Responsibility
- Own PRD-scoped extension design notes and low-intrusion adapters for optional security deliveries.
- Keep Integrity Protection Delivery adapters decoupled from core runtime internals while integrating through stable `src/qwenpaw/security`, `src/qwenpaw/app`, `src/qwenpaw/cli`, and `console` contracts.
- Treat `extension/Intergrity  Protection PRD.txt` as business evidence and `extension/Intergrity  Protection Design.md` as the implementation-stage adapter design for this slice.

### Out Of Scope
- Owning backend router composition, runtime security semantics, or console rendering.
- Duplicating ClawSec soul-guardian, qwenpaw doctor, or built-in rule integrity behavior beyond stable adapters.
- Source trust verification for skill pool secure import (`extension/skill_sign/`); broader source-trust verifier remains future work.
- Owning console i18n implementation details or Health Check carousel rendering mechanics; those remain under the `console` contract.

### Children
- path: Intergrity  Protection PRD.txt
  kind: business-prd-evidence
  role: as-built integrity-protection requirements for file baseline drift, health check, rule integrity, and console placement (source trust removed from as-built scope)
- path: File Baseline Protection Design.md
  kind: implementation-design-contract
  role: file baseline protection slice design (supersedes File Baseline Protection Design.md)
- path: File Baseline Protection Design.md
  kind: implementation-design-contract
  role: superseded historical reference for runtime semantics pre-v1.0 rename
- path: Intergrity  Protection Design.md
  kind: implementation-design-contract
  role: adapter-level implementation design and as-built constraints for Integrity Protection Delivery
- path: file_baseline/
  kind: extension-module
  role: superseded — rename to file_baseline/ per File Baseline Protection Design.md
- path: file_baseline/
  kind: extension-module
  role: file baseline protection business logic and host_bridge wiring for inbox/push/SSE
- path: health_check/
  kind: extension-module
  role: doctor projection (projection.py), scan orchestration (scanner.py), confirmed fix (fix.py), fix allowlist (constants.py)
- path: rule_integrity/
  kind: extension-module
  role: built-in tool guard rule integrity verify/repair, API routes, startup polling, and acceptance harness/tests
- path: skill_sign/
  kind: extension-module
  role: Ed25519 skill ZIP verification, sign tool, and secure pool import bridge
- path: Skill Secure Import Design.md
  kind: implementation-design-contract
  role: skill pool secure import and sign-tool design
- path: Console Frontend Decoupling Design.md
  kind: implementation-design-contract
  role: console/src/extension module layout and re-export boundary

### Dependency Direction
- `extension` adapters may depend inward on stable QwenPaw backend, CLI, console API, and thirdparty ClawSec capabilities.
- `src/qwenpaw/security` and `console` must not depend on incidental extension implementation details that are not promoted through explicit backend or API contracts.
- Verification assets under `tests/integration/security` observe Integrity Protection through harness abstractions, not by importing extension adapter internals directly.

### Explicit Testcase Entrypoints
- tests/integration/security/test_integrity_protection.py::test_integrity_security_menu_default_off
- tests/integration/security/test_integrity_protection.py::test_file_baseline_drift_alert_restore_accept
- tests/integration/security/test_integrity_protection.py::test_health_check_scan_and_confirmed_fix
- extension/rule_integrity/tests/test_integration_entry.py::test_rule_integrity_entry_visible
- tests/integration/security/test_integrity_protection.py::test_security_i18n_and_healthcheck_progress_carousel
- tests/integration/security/test_integrity_protection.py::test_healthcheck_full_doctor_coverage_projection

### Current Evidence
- PRD and Design documents describe as-built behavior aligned with current code.
- Grouped doctor coverage lives in `extension/health_check/projection.py` with re-exports from `src/qwenpaw/security/integrity_protection.py`.
- Console UI lives under `console/src/extension/{file_baseline,health_check,rule_integrity}/`.
- Source trust is not implemented; prior demo verifier was removed.
- Acceptance entrypoints pass through production behavior behind `tests/integration/security/integrity_harness.py`.
