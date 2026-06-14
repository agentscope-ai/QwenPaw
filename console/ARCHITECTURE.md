---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: qwenpaw-console
element_kind: OperatorConsole
element_path: console
---

## Implementation Architecture Contract

### Responsibility
- Own the operator-facing console frontend and Tauri-oriented packaging assets.
- Materialize pages, hooks, stores, layouts, and API client code for the browser or desktop console surface.

### Out Of Scope
- Owning Python backend runtime behavior.
- Owning public documentation and marketing content under website/.

### Stable Subdirectories
- src/api
- src/pages
- src/layouts
- src/stores
- src/tauri

### Dependency Direction
- The console depends on backend APIs and shared runtime contracts, but the runtime must not depend on console implementation details.

### Children
- path: src
  kind: frontend-source
  role: React application source for operator workflows
- path: src-tauri
  kind: desktop-shell
  role: Tauri bootstrap and desktop packaging assets
- path: public
  kind: static-assets
  role: static assets served with the console bundle

### Notes
- Integrity Protection console slice is covered by explicit entrypoints listed in the Integrity Protection Delivery Addendum below and verified through `tests/integration/security/integrity_harness.py` plus extension frontend selftests.

## Integrity Protection Delivery Addendum

### Responsibility
- Own the Settings/Security Integrity Check submenu and Health Check submenu that serve `intent-integrity-security-console`.
- Keep Integrity Check and Health Check visually and navigationally peer-level with Tool Guard and File Guard.
- Present persona protection Switch, protected-path lists, drift Restore/Accept, rule-integrity passive check card, Security page top repair banner, health-check progress, risk summaries, and confirmed-fix actions.
- Localize Integrity Check and Health Check operator-visible strings through `react-i18next` and `console/src/locales/en.json` / `console/src/locales/zh.json` (`security.healthCheck.*`, `security.integrityProtection.*`), with English fallback for other configured languages.
- Show a Health Check scan progress carousel that rotates localized current-check text while loading and stops on completion, failure, cancellation, or interruption without running a fix.
- Project Health Check scan and final results from backend structured doctor coverage items (not a hardcoded two-item list).
- Display doctor groups, check item ids, status, detail, risk or recommendation, and mapped fix affordance when present. Default scan in UI uses `deep=false` and remains read-only; `deep=true` is supported on the API/client only (no Deep scan button in Console).

### Out Of Scope
- Owning persona baseline, source trust, doctor scan/fix, or rule-integrity backend semantics.
- Running package installation, package execution, file restoration, baseline acceptance, rule repair, or doctor fix without an explicit backend action initiated by the user.

### Dependency Direction
- `console/src/api/modules/security.ts` is the stable client module for security settings and Integrity Protection API calls.
- Console components may call backend APIs and display state, but must not import Python runtime code, parse `qwenpaw doctor` CLI text, or duplicate doctor/ClawSec verification logic.

### Explicit Testcase Entrypoints
- ../tests/integration/security/test_integrity_protection.py::test_integrity_security_menu_default_off
- ../tests/integration/security/test_integrity_protection.py::test_persona_drift_alert_restore_accept
- ../tests/integration/security/test_integrity_protection.py::test_health_check_scan_and_confirmed_fix
- ../extension/rule_integrity/tests/test_integration_entry.py::test_rule_integrity_entry_visible
- ../tests/integration/security/test_integrity_protection.py::test_security_i18n_and_healthcheck_progress_carousel
- ../tests/integration/security/test_integrity_protection.py::test_healthcheck_full_doctor_coverage_projection

### Current Evidence
- `console/src/api/modules/security.ts` covers Tool Guard, File Guard, Skill Scanner, and delegates persona/health/rule-integrity calls to extension clients.
- Health Check UI: `console/src/extension/health_check/components/HealthCheckSection.tsx` (grouped table, carousel, i18n detail/guidance, sessionStorage, Issues only/All, cross-tab links, high-risk fix Modal).
- Legacy re-export: `console/src/pages/Settings/Security/components/HealthCheckSection.tsx` exports from `@extension/health_check`.
- Integrity Check: `console/src/pages/Settings/Security/components/IntegrityCheckSection.tsx` composes `@extension/persona_baseline` and `@extension/rule_integrity` (`RuleIntegrityPassiveCard`). No source-trust UI (not implemented).
- Rule integrity banner: `RuleIntegrityRepairBanner` on `pages/Settings/Security/index.tsx` with `useRuleIntegrity` 5s polling.
- Locales: `en.json` and `zh.json` define full `security.healthCheck.groups.*` and `security.healthCheck.scanItems.*` coverage for doctor projection items.
- Acceptance: `tests/integration/security/integrity_harness.py` verifies i18n, carousel, and full doctor coverage against these as-built paths.