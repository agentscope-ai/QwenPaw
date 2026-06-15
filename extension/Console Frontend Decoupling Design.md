# Console Frontend Extension Decoupling Design

## Purpose

Integrity Protection Console code lives under `console/src/extension/`. Host pages (`Settings/Security`, `MainLayout`, `Inbox`) are thin integration shells. Source trust is **not implemented** in this repository.

## Principles

1. **Extension ownership:** Persona baseline, health check, and rule integrity UI/API clients live under `console/src/extension/`.
2. **Backward-compatible imports:** Legacy paths re-export from `@extension/*` where needed (e.g. `pages/.../HealthCheckSection.tsx`).
3. **Dependency direction:** `extension/*` may import `@/api`, `@/pages/Settings/Security/index.module.less`, and i18n keys. Host pages import `@extension/*/index`, not deep `lib/` paths.
4. **As-built UX:** Health Check and Integrity Check strings use `react-i18next` keys in `locales/en.json` and `locales/zh.json`.

## Directory Layout

```
console/src/extension/
├── ARCHITECTURE.md
├── shared/
│   └── inbox/
│       └── inboxEvents.ts          # Generic Inbox changed CustomEvent
├── file_baseline/
│   ├── index.ts
│   ├── api/client.ts
│   ├── components/
│   │   ├── FileBaselineDriftAlertNotifier/
│   │   ├── FileBaselineProtectionSection.tsx
│   │   └── IntegrityProtectionFrame.tsx
│   ├── hooks/useFileBaselineDriftWatch.ts
│   └── lib/
│       ├── alertActions.ts
│       ├── driftDisplay.ts
│       ├── driftAlertItems.ts
│       └── navigation.ts
├── health_check/
│   ├── index.ts
│   ├── api/client.ts
│   ├── components/HealthCheckSection.tsx
│   └── lib/
│       ├── scanUi.ts
│       ├── detailMessages.ts
│       ├── actionLinks.ts
│       ├── fixRisk.ts
│       └── scanSummary.ts
└── rule_integrity/
    ├── index.ts
    ├── api/client.ts
    ├── hooks/useRuleIntegrity.ts
    └── components/
        ├── RuleIntegrityPassiveCard.tsx
        └── RuleIntegrityRepairBanner.tsx
```

Path alias: `@extension/*` → `console/src/extension/*` (Vite + `tsconfig.app.json`).

## Module Responsibilities

| Module | Owns |
|--------|------|
| `file_baseline` | Persona API client, SSE watch, drift alert notifier, Restore/Accept actions, Inbox deep links, Integrity Check persona panel |
| `health_check` | Health scan/fix API client, Health Check tab UI (carousel, grouped table, i18n detail/guidance, sessionStorage, fix confirmations) |
| `rule_integrity` | Rule integrity API client, passive check card, repair banner, polling hook |
| `shared/inbox` | `INBOX_CHANGED_EVENT` bus (used by persona + Sidebar + Inbox) |

## Host Integration (thin shell)

| Host file | Role |
|-----------|------|
| `layouts/MainLayout` | Renders `FileBaselineDriftAlertNotifier` from `@extension/file_baseline` |
| `pages/Settings/Security/index.tsx` | Tabs; `RuleIntegrityRepairBanner`; imports `HealthCheckSection` from extension |
| `pages/Settings/Security/components/IntegrityProtectionSection.tsx` | Composes persona panel + `RuleIntegrityPassiveCard` from extension (no source trust UI) |
| `pages/Settings/Security/components/HealthCheckSection.tsx` | Re-exports `@extension/health_check` |
| `api/modules/security.ts` | Tool Guard / File Guard / etc.; persona + health methods delegate to extension clients |
| `locales/en.json`, `zh.json` | `security.integrityProtection.*`, `security.healthCheck.*`, `security.rulesIntegrity.*` |

## Persona Panel Split

`IntegrityProtectionSection` keeps aggregate settings load via `IntegrityProtectionFrame` and renders:

- `FileBaselineProtectionSwitchRow` + protected paths + drift alerts
- `RuleIntegrityPassiveCard` (manual check button + findings table)

Persona UI compound parts live in `@extension/file_baseline`.

## Health Check UI (as-built)

- Default scan: `runIntegrityHealthCheckScan(false)` only (no Deep scan button).
- API client supports `deep=true`; harness verifies API boundary, not Console Deep button.
- Fix flow: Popconfirm or high-risk Modal → `runIntegrityHealthCheckFix(fixId)`.

## Testing

- Co-located tests under each extension module.
- Manifests: `scripts/file-baseline-selftest.manifest.json`, `scripts/health-check-selftest.manifest.json`.
- Verify: `run-file-baseline-selftest.py`, `run-health-check-selftest.py`, `npm run build`.

## Related Documents

- `extension/ARCHITECTURE.md` — backend extension zone
- `extension/Intergrity  Protection Design.md` — delivery design (as-built)
- `extension/File Baseline Protection Design.md`
- `console/ARCHITECTURE.md` — Settings/Security console contract
