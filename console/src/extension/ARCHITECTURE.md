---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: console-integrity-extension
element_kind: ConsoleExtensionZone
element_path: console/src/extension
---

## Responsibility

- Own Console UI and client code for Integrity Protection extensions: persona baseline, health check, and rule integrity.
- Keep host pages (`Settings/Security`, `MainLayout`, `Inbox`) as thin integration shells.

## Out Of Scope

- Tool Guard, File Guard, Skill Scanner (remain under `console/src/pages/Settings/Security`).
- Source trust (not implemented).
- Backend semantics outside thin host routers and bridges (`src/qwenpaw/security`, `extension/*`).

## Children

- `shared/inbox/` — generic Inbox change event utilities
- `file_baseline/` — persona protection UI, API client, SSE watch
- `health_check/` — health scan UI, API client, lib helpers (`scanUi`, `detailMessages`, `actionLinks`, `fixRisk`, `scanSummary`)
- `rule_integrity/` — rule integrity API client, passive check card, repair banner, polling hook
- `skill_sign/` — skill pool secure import API client, hook, and header button component

## Dependency Direction

- Extension modules may import `@/api`, `@/pages/Settings/Security/index.module.less`, and i18n keys.
- Host code imports `@extension/file_baseline`, `@extension/health_check`, and `@extension/rule_integrity` public `index.ts` exports only.

## As-built Notes

- Deep scan: API/client supports `deep=true`; `HealthCheckSection` UI uses `deep=false` only.
- Rule integrity: `GlobalRuleIntegrityRepairBanner` on MainLayout below Header (SSE + 60s poll fallback) + `RuleIntegrityPassiveCard` in Integrity Check tab.
- Health Check: sessionStorage key `qwenpaw.healthCheck.lastScan.v1`; carousel interval 1800ms.

## Delivery test contracts (file baseline)

These are **regression guards** — not product behavior. They fail when host wiring or the drift notifier UI is removed accidentally:

| Guard | Location |
|-------|----------|
| Extension files + bridge routes exist | `extension/selftest/file-baseline-wiring.test.js` |
| `MainLayout` mounts `FileBaselineDriftAlertNotifier` | wiring test + `hostIntegration.contract.test.ts` |
| Public `index.ts` exports notifier + alert actions | wiring test + `hostIntegration.contract.test.ts` |
| Notifier Restore/Accept UI contract | `FileBaselineDriftAlertNotifier/notifierUi.contract.test.ts` |
| Full slice net | `python extension/run-integrity-delivery-selftest.py --delivery file-baseline` |

Scenario IDs: `FB-SUI-NOTIFIER` (notifier UI), `FB-SUI-HOST` (host/public surface).

See also: `extension/Console Frontend Decoupling Design.md`, `console/ARCHITECTURE.md`
