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
- `persona_baseline/` — persona protection UI, API client, SSE watch
- `health_check/` — health scan UI, API client, lib helpers (`scanUi`, `detailMessages`, `actionLinks`, `fixRisk`, `scanSummary`)
- `rule_integrity/` — rule integrity API client, passive check card, repair banner, polling hook

## Dependency Direction

- Extension modules may import `@/api`, `@/pages/Settings/Security/index.module.less`, and i18n keys.
- Host code imports `@extension/persona_baseline`, `@extension/health_check`, and `@extension/rule_integrity` public `index.ts` exports only.

## As-built Notes

- Deep scan: API/client supports `deep=true`; `HealthCheckSection` UI uses `deep=false` only.
- Rule integrity: `RuleIntegrityRepairBanner` on Security page top (5s poll) + `RuleIntegrityPassiveCard` in Integrity Check tab.
- Health Check: sessionStorage key `qwenpaw.healthCheck.lastScan.v1`; carousel interval 1800ms.

See also: `extension/Console Frontend Decoupling Design.md`, `console/ARCHITECTURE.md`
