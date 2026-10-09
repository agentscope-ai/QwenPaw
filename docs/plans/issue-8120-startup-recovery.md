# Issue #8120: recovery before React starts

## Agreed scope

The user approved extending recovery to the Console startup stage. The reported
Windows 2.2.2b1 sequence is: first launch stays on `LOADING CONSOLE`; closing and
reopening shows the page error; manually refreshing restores access.

On macOS Chrome, controlled failures of the production entry, an entry
dependency, and entry execution all preserve the static loading placeholder.
This proves a recovery gap, but does not identify the Windows first-install
trigger. Do not describe controlled Chrome failures as a Windows reproduction.

Install a small independent monitor before module execution. Capture startup
resource/runtime failures and a 30-second startup timeout. Keep diagnostics
available without React, with collapsed details above copy and refresh buttons.
Only module resource failures may automatically refresh, using the existing
per-build, per-tab session guard. Runtime failures and timeouts allow manual
recovery. Stop monitoring when React replaces the loading placeholder.

The monitor is compiled and inlined by Vite, so it does not require another
successful resource request or depend on React, UI vendors, or lazy routes.
Use existing translated diagnostics/actions and complete new startup strings
for all seven locales. Preserve the existing diagnostic storage schema and
URL redaction. A resource recheck is a later observation, not the original cause.

## Checklist

- [x] Agree on the startup scope and verify the existing gap.
- [x] Add the independent startup monitor and production/development injection.
- [x] Add startup messages for all seven locales and preserve the fallback layout.
- [x] Test failures, timeout, successful startup cleanup, and the shared reload guard.
- [x] Check types, lint, formatting, and the production build.
- [x] Verify entry/dependency/runtime failures, recovery, clipboard, and layout in Chrome.

## Verification

- 82 tests passed across startup monitoring, recovery, diagnostics, lazy routes,
  the React error boundary, and language loading.
- Type checking and ESLint passed. The production build, Monaco CSS check,
  precompression, and initial bundle check passed.
- Nine Chrome cases passed using the actual production build: normal mounting,
  a transient missing entry, persistent entry/dependency 404s, an HTML response,
  a runtime exception, offline status, blocked session storage, and an actual
  30-second timeout followed by late successful rendering.
- Startup recovery and the route recovery helper share the same session guard:
  after one successful automatic refresh, route recovery cannot refresh again.
- Manual refresh recovers after restoring an entry or removing the injected
  runtime fault. Persistent failures do not loop. Clipboard contents match the
  saved diagnostic; the 375px layout stays within the viewport, with details
  collapsed above copy and refresh. Desktop and expanded mobile screenshots
  were visually inspected.
- Evidence: `startup-recovery-verification.json`, `startup-error-centered.png`,
  and `startup-error-mobile-details.png` in the task's `issue8120` artifacts.
- After removing the obsolete eager build identifier, all 54 startup/recovery/
  diagnostic tests passed again. The final production build, ESLint, Prettier,
  and diff checks passed. Chrome revalidated normal mounting and the shared
  one-refresh guard against that final build (`startup-recovery-final-check.json`).
- At `http://localhost:5173/agent-config`, Chrome also verified normal startup,
  recovery after a transient entry failure, and no reload loop for a persistent
  entry failure. Requests included Vite's actual hot-update timestamp, rather
  than assuming the entry URL has no query (`startup-dev-verification.json`).

## Verification limits

The local host is macOS. The user supplied Windows first-install observations;
the local checks validate recovery behavior, not that platform-specific trigger.
Do not clear the user's profile or configuration. No GitHub Actions enablement
or dispatch is included in this change.
