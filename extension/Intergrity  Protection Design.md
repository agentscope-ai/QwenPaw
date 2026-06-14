# Integrity Protection Delivery Implementation Design

## Stable Boundary
- Root delivery slice: `intent-integrity-protection-delivery`.
- Runtime owner: `src/qwenpaw/security/ARCHITECTURE.md`.
- Console owner: `console/ARCHITECTURE.md`.
- Extension adapter owner: `extension/ARCHITECTURE.md`.
- Acceptance owner: `tests/integration/security/ARCHITECTURE.md`.

Integrity Protection default-off semantics (per sub-feature, as-built):
- `persona_protection_enabled=false`: no protected-file monitoring, no startup scan, no drift alerts, write hook no-op.
- Health Check: Settings/Security **Health Check** tab and scan/fix APIs are always available; `health_check_enabled` is a settings projection field defaulting to `false` and does **not** gate routes or UI visibility.
- Rule integrity: `rule_integrity_check_passive=true` by default; status may be polled or checked manually; repair requires an explicit user action.
- Source trust verification: **not implemented** in this repository (prior demo removed 2026-06-11).

## Layering
- `extension` owns PRD-scoped adapter design and low-intrusion glue.
- `src/qwenpaw/security` owns integrity-protection settings projection, persona baseline bridge, and re-exports for health-check scan/fix.
- `src/qwenpaw/app` owns HTTP/SSE routing via `integrity_protection_routes.py` and must not redefine security semantics.
- `src/qwenpaw/cli` owns existing `qwenpaw doctor` and `qwenpaw doctor fix`; health-check orchestration wraps these as scan-only then confirmed-fix phases.
- `console` owns Settings/Security UI placement and API client calls under `console/src/extension/`.
- `thirdparty/clawsec-main/clawsec-main` remains a reused capability source, not a copied implementation mirror.

## Interface Contracts
- Persona baseline protection exposes enablement, protected path listing, drift alert observation, Restore, and Accept through backend APIs consumed by console UI (`console/src/extension/persona_baseline/`).
- Source trust verification (original PRD section 二): **not implemented** in this repository.
- Health Check exposes scan progress and suggested repairs separately from confirmed fix execution. A scan request is read-only. A fix request requires a second explicit user confirmation and targets one selected repair from `CONSOLE_FIX_IDS`.
- Health Check doctor coverage is a structured projection with `group`, `id`, `label`, `status`, `detail`, `risk`, `recommendation`, `fix_id`, and `deep_only` for each check item. Status values: `ok`, `risk`, `suggestion`, `skipped`. Projection is generated from qwenpaw doctor helper semantics in `extension/health_check/projection.py`, not by parsing `click.echo` output.
- Default Health Check scan uses `deep=false` and omits channel connectivity and local LLM deep probes. `deep=true` is accepted on the scan API and extension API client; the Console UI currently calls only `deep=false` (no Deep scan button).
- Rule integrity reuses the dangerous-shell-rules integrity backend in `extension/rule_integrity/` and exposes passive check plus explicit repair through Integrity Check (`RuleIntegrityPassiveCard`) and the Security page top banner (`RuleIntegrityRepairBanner`).
- Console i18n routes Integrity Check and Health Check operator-visible strings through `react-i18next` with English and Simplified Chinese keys in `console/src/locales/en.json` and `console/src/locales/zh.json`; unsupported configured languages fall back to English.
- Health Check progress exposes a localized current-check carousel sourced from visible doctor-derived check items while loading. Completion, failure, cancellation, and interruption stop carousel rotation without running any doctor fix.

## As-built Health Check Specification

### Backend modules
- `extension/health_check/projection.py` — doctor-derived check items
- `extension/health_check/scanner.py` — read-only scan orchestration
- `extension/health_check/fix.py` — confirmed doctor fix via `run_doctor_fix`
- `extension/health_check/constants.py` — `CONSOLE_FIX_IDS`, `HIGH_RISK_FIX_IDS`
- `src/qwenpaw/security/integrity_protection.py` — bridges extension health_check imports

### API
- `GET  /config/security/integrity-protection/settings`
- `POST /config/security/integrity-protection/health-check/scan` — body `{ deep: bool }`, default `false`
- `POST /config/security/integrity-protection/health-check/fix` — body `{ fix_id, selected_repair }`

### Scan response fields
`scan_id`, `read_only`, `progress`, `check_items[]`, `risk_summary[]`, `repair_suggestions[]`, `mutated_files[]`

### Doctor groups (default scan)
`environment`, `config`, `agents`, `channels`, `mcp-clients`, `skills`, `browser-playwright`, `security-baseline`, `memory-embedding`, `workspace-hygiene`, `cron`, `startup-paths`, `console-static-files`, `web-authentication`, `providers`, `per-agent-models`, `api-target`

### Deep-only items (`deep=true` scan only)
- `enabled-channel-connectivity` (group `channels`)
- `qwenpaw-local-llm-deep` (group `active-llm`)

### CONSOLE_FIX_IDS (console repair allowlist)
`ensure-working-dir`, `ensure-workspace-dirs`, `validate-all-jobs-json`, `reconcile-workspace-skills`, `seed-missing-agent-json`, `reset-invalid-agent-json`, `rebuild-console-npm`

### Console UX (`console/src/extension/health_check/components/HealthCheckSection.tsx`)
- Session persistence: `sessionStorage` key `qwenpaw.healthCheck.lastScan.v1`
- Views: Segmented **Issues only / All**
- Collapse: environment OK items under `ENVIRONMENT_INFO_ITEM_IDS`
- Hidden placeholders: `web-authentication` and reserved ids in `HIDDEN_PLACEHOLDER_ITEM_IDS`
- Cross-tab links: `actionLinks.ts` → `toolGuard`, `fileGuard`, `skillScanner`
- High-risk fixes: `HIGH_RISK_FIX_IDS` → confirmation Modal before fix
- Carousel: `CAROUSEL_DISPLAY_DURATION_MS=1800`; terminal states in `TERMINAL_SCAN_STATES` stop rotation

## Testcase Entrypoints
- `tests/integration/security/test_integrity_protection.py::test_integrity_security_menu_default_off`
- `tests/integration/security/test_integrity_protection.py::test_persona_drift_alert_restore_accept` (P2)
- `tests/integration/security/test_integrity_protection.py::test_health_check_scan_and_confirmed_fix`
- `extension/rule_integrity/tests/test_integration_entry.py::test_rule_integrity_entry_visible`
- `tests/integration/security/test_integrity_protection.py::test_security_i18n_and_healthcheck_progress_carousel`
- `tests/integration/security/test_integrity_protection.py::test_healthcheck_full_doctor_coverage_projection`

These tests are business-readable acceptance contracts verified through `tests/integration/security/integrity_harness.py` against the as-built production paths above.

## Persona Baseline Sub-Slice

Persona drift protection (PRD section 一) is specified in detail in `extension/Persona Baseline Guardian Design.md` (v0.6.7), including enable gate, scenario tests with **SOUL.md pilot default**, **P2 Restore/Accept**, and PB-S20 user journey (§18.8).

## Key Implementation Mapping
- Direct: `extension/persona_baseline/` + security bridge realizes `intent-persona-baseline-guardian`.
- Direct: `extension/health_check/` + security bridge realizes `intent-health-check-orchestrator`.
- Direct: `extension/rule_integrity/` realizes built-in rule integrity verify/repair exposure.
- Direct: `console/src/extension/{persona_baseline,health_check,rule_integrity}/` realizes `intent-integrity-security-console`.
- Not implemented: `intent-source-trust-verifier`.
- Indirect: `thirdparty/clawsec-main/clawsec-main/skills/soul-guardian` carries persona baseline mechanics.
- Indirect: `src/qwenpaw/cli/doctor_cmd.py`, `doctor_checks.py`, `doctor_connectivity.py`, and `doctor_fix_runner.py` carry doctor scan/fix semantics reused by projection and fix adapters.

## Coding/Repair Constraints
- Do not modify `design/KG/SystemArchitecture.json` in Coding/Repair.
- Do not make persona protection enablement default-on.
- Do not auto-restore, auto-accept, auto-repair, install, execute, or fix anything before explicit user action.
- Do not put raw HTTP, environment, SQL, GraphQL, or filesystem plumbing into `tests/integration/security/test_integrity_protection.py`.
- Do not copy ClawSec logic into an unrelated implementation when a stable adapter or extracted verification primitive can reuse it.
- Health Check carousel rotation must stop after completed, failed, cancelled, or interrupted states and must not trigger fix from carousel state.
- Do not satisfy doctor coverage by parsing CLI stdout from `qwenpaw doctor`.
- Do not enable deep connectivity by default; deep-only items must be absent from default scan and present only when `deep=true` on the scan API.
