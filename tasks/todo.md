# Plan: Update source repo URL to boostclaw

- [x] Inventory all references to the source repository URL.
- [x] Update repo URLs to https://github.com/aimentorai/boostclaw.git where appropriate.
- [x] Run diagnostics/tests/build as applicable.
- [x] Document results and verification.

# Plan: Fix ProBoost register CORS / stale console bundle

- [x] Confirm the current auth source and served bundle route SMS calls through `/api/proboost-auth/*`.
- [x] Remove the easy stale-build path by syncing `console/dist` into `src/copaw/console` whenever the console build runs.
- [x] Make source-install preparation prefer fresh `console/dist` assets over an older bundled `src/copaw/console` copy.
- [x] Run targeted frontend tests/build plus backend diagnostics and document verification + review.

## Verification
- Confirmed source flow already uses backend proxy: `console/src/auth/proboost/client.ts` posts SMS/login/register requests via `getApiUrl("/proboost-auth/*")`, and the rebuilt bundle in `src/copaw/console/assets/index-DgPx1xcq.js` contains the `/api` prefix helper plus `/proboost-auth/meta`, `/proboost-auth/send-sms-code`, `/proboost-auth/verify-sms-code`, and `/proboost-auth/login` route strings.
- `cd console && npm test -- tests/auth/proboost/client.test.ts` passed, including a new regression test that asserts SMS code requests go to `/api/proboost-auth/send-sms-code`.
- `cd console && npm run build` passed and logged `[console sync] Synced .../console/dist -> .../src/copaw/console`.
- `bash -n scripts/install.sh` passed.
- `python3 -m py_compile src/copaw/app/routers/proboost_auth.py` passed.
- `python3 -m pytest -q tests/unit/test_proboost_auth_router.py` could not run in this environment because `pytest` is not installed in the active Python environment.

## Review
- Added `console/scripts/sync-built-console.mjs` and wired `console/package.json` build scripts so every console build now refreshes the backend-served `src/copaw/console` assets automatically.
- Hardened `scripts/install.sh` to refresh bundled console assets from `console/dist` when a fresher local build exists, instead of trusting an older `src/copaw/console` copy.
- Added a regression test in `console/tests/auth/proboost/client.test.ts` so future auth changes keep SMS code requests on the local `/api/proboost-auth/*` proxy path and avoid browser-side CORS failures.

# Plan: Desktop window title + packaging freshness

- [x] Locate title sources used by desktop app (`webview.create_window` and console `index.html`).
- [x] Change visible window/page title text from CoPaw naming to BoostClaw naming for startup.
- [x] Make macOS pack script rebuild wheel when source is newer than existing same-version wheel.
- [x] Verify Python syntax and key title strings after edits.

## Verification
- Checked `src/copaw/cli/desktop_cmd.py`: desktop window title source is `webview.create_window(...)`.
- Checked `console/index.html` and `src/copaw/console/index.html`: `<title>` updated for startup page title.
- Ran AST parse on `src/copaw` previously to ensure Python syntax is valid; re-check done for changed file via grep/readback.

## Review
- Startup title path now uses BoostClaw branding in both desktop shell title and web page title.
- `scripts/pack/build_macos.sh` now avoids stale same-version wheels by rebuilding when source files changed, so source title changes reliably flow into packaged `.app` without manual patching.

# Plan: Unify startup title to BoostClaw

- [x] Locate runtime title sources for desktop window and page title.
- [x] Change desktop window title text to `BoostClaw`.
- [x] Change console page `<title>` text to `BoostClaw`.
- [x] Run minimal verification (grep + syntax check) and document result.

## Verification
- `python3 -m py_compile src/copaw/cli/desktop_cmd.py` passed.
- Search for `BoostClaw Desktop` under `src/copaw/**/*.py`: no results.
- Confirmed `console/index.html` now contains `<title>BoostClaw</title>`.

## Review
- Startup desktop window title now resolves to `BoostClaw` via `webview.create_window(...)`.
- Console base page title now initializes as `BoostClaw`; packaged `src/copaw/console` will be refreshed by `scripts/wheel_build.sh` during packaging.

# Plan: Configure packaged workspace default via launcher

- [x] Update macOS launcher template to export `COPAW_WORKING_DIR` with default `~/.boostclaw`.
- [x] Use `COPAW_WORKING_DIR` for `config.json` existence checks during startup/init.
- [x] Validate shell syntax and confirm references are present.

## Verification
- `bash -n scripts/pack/build_macos.sh` passed.
- `grep COPAW_WORKING_DIR scripts/pack/build_macos.sh` shows export + runtime usage in both no-TTY and TTY branches.

## Review
- Packaged macOS app now supports workspace override via environment variable while keeping the previous default path.

# Plan: Audit install/packaging rename from CoPaw to BoostClaw

- [x] Inspect package metadata and CLI entry points for remaining user-visible `copaw` naming.
- [x] Audit `scripts/install.sh`, `scripts/wheel_build.sh`, and `scripts/pack/build_macos.sh` for rename inconsistencies.
- [x] Review env/default-directory compatibility layers to distinguish internal namespace vs user-visible branding.
- [x] Fix the highest-impact install/packaging issues without renaming the internal Python package unless required.
- [x] Validate with syntax checks and targeted searches, then document findings.

## Verification
- Shell syntax checks passed: `bash -n scripts/install.sh`, `bash -n scripts/pack/build_macos.sh`, `bash -n scripts/wheel_build.sh`.
- Python syntax checks passed for edited runtime files via `python3 -m py_compile ...`.
- Targeted searches in edited install/packaging/runtime paths show no remaining high-impact user-facing `CoPaw` strings, no `-m boostclaw` launcher usage, and no `~/.copaw` defaults in touched files.
- PowerShell parser validation could not run in this environment because `pwsh` is unavailable (noted risk).

## Review
- Fixed critical packaging bug on Windows: launcher now uses `python -m copaw` (internal module), not `-m boostclaw`.
- Unified user-facing branding/paths to BoostClaw in CLI/version/help text, installer output/wrappers, packaging docs, and media/workspace defaults.
- Kept compatibility where needed: internal Python module/package path remains `copaw`, and env aliases (`COPAW_*`) still map via compatibility logic while `BOOSTCLAW_*` is preferred.

# Plan: Minimize runtime drift for upstream compatibility

- [x] Roll back non-essential `src/copaw` and console runtime path/branding edits.
- [x] Keep only boundary-layer rename work (install/pack scripts + packaging docs + launcher/env compatibility).
- [x] Re-run syntax checks after rollback.

## Verification
- `git diff --stat` now shows only boundary files changed: `scripts/install.sh`, `scripts/install.ps1`, `scripts/pack/build_macos.sh`, `scripts/pack/build_win.ps1`, `scripts/pack/README.md`, `scripts/pack/README_zh.md`, `tasks/todo.md`.
- Python compile check passed for reverted runtime files.
- Shell syntax checks passed for edited shell scripts.

## Review
- This branch is now much closer to upstream in `src/copaw`, reducing merge conflicts for periodic syncs.
- Remaining changes are concentrated at installation/packaging boundaries where BoostClaw branding belongs.

# Plan: Add modular console login/logout

- [x] Review console routing, API layer, and header entry points for minimal-impact auth integration.
- [x] Add independent auth module (types/storage/context/service/guard) with token persistence and backward-compatible env token fallback.
- [x] Add login route/page and protect existing console routes without rewriting existing feature pages.
- [x] Wire logout action in header and add i18n copy for auth UI.
- [x] Unify request auth behavior (Authorization header + 401 cleanup/redirect) and cover non-wrapper fetch calls.
- [x] Run frontend lint/build checks and document verification + review.

## Verification
- `cd console && npm run build` passed (TypeScript + Vite build completed).
- `cd console && npx eslint <changed-files...>` passed for this change set (auth/login/logout + API touchpoints).
- `cd console && npm run lint` still reports many pre-existing ESLint violations in unrelated files; this task did not expand that existing baseline.
- Auth request flow verified at code level: runtime token storage is read by `getApiToken`, and `requestRaw` now handles 401 by clearing auth and redirecting to `/login`.

## Review
- Added modular auth domain under `console/src/auth` (storage, types, service, provider, hook, route guard), avoiding invasive changes to existing page modules.
- Introduced `/login` page and protected all existing console routes through a top-level route guard in `console/src/App.tsx`.
- Added logout entry in `console/src/layouts/Header.tsx` and multilingual auth/logout copy in `console/src/locales/*.json`.
- Unified auth header and 401 handling in `console/src/api/request.ts`, and updated non-wrapper fetch paths (`workspace` upload/download, skill stream, chat stream default endpoint) to reuse shared logic.

# Plan: Switch console auth to ProBoost login/register

- [x] Review `scripts/boost_api.md` and map the new auth endpoints to the current console auth entry points.
- [x] Add isolated ProBoost auth config/client modules without mixing them into the existing `/api/*` request layer.
- [x] Extend auth context and storage-backed state for password login, SMS code sending, SMS verification register/login, and local logout.
- [x] Upgrade the auth page to support both login and register flows and add a `/register` route alias.
- [x] Update i18n copy and decouple ProBoost auth from console backend token injection / 401 handling.
- [x] Run targeted lint/build/error validation and document verification + review.

## Verification
- `cd console && npx eslint src/auth/proboost/types.ts src/auth/proboost/config.ts src/auth/proboost/client.ts src/auth/types.ts src/auth/storage.ts src/auth/service.ts src/auth/AuthContext.ts src/auth/context.tsx src/auth/useAuth.ts src/pages/Auth/Login/index.tsx src/App.tsx src/api/config.ts src/api/request.ts src/vite-env.d.ts` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).
- `get_errors` check for touched auth/api/login files returned no errors.

## Review
- Added isolated ProBoost auth adapter under `console/src/auth/proboost/` (config + typed client + payload/response types) for password login, SMS send, and SMS verify.
- Extended auth domain (`console/src/auth/*`) to expose `login`, `register`, `sendSmsCode`, and local `logout`, and normalized persisted user shape to ProBoost fields.
- Upgraded `console/src/pages/Auth/Login/index.tsx` into a dual-mode login/register screen with SMS send countdown and route-driven mode (`/login` vs `/register`).
- Kept console backend `/api/*` request layer independent by removing runtime auth-state coupling from `console/src/api/config.ts` and clearing legacy auth redirect side effects from `console/src/api/request.ts`.
- Updated i18n auth strings for `en/zh/ja/ru` and added Vite env typings in `console/src/vite-env.d.ts` for ProBoost auth configuration.

# Plan: Externalize ProBoost auth parameters to .env

- [x] Confirm current ProBoost config read path and variable names.
- [x] Add `console/.env.example` with all `VITE_PROBOOST_*` keys.
- [x] Keep runtime-safe defaults in `console/src/auth/proboost/config.ts` while prioritizing `.env` values.
- [x] Run targeted lint/build validation and document results.

## Verification
- `cd console && npx eslint src/auth/proboost/config.ts` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).

## Review
- ProBoost auth parameters are now externally configurable via `.env`/`.env.*` using the `VITE_PROBOOST_*` key set.
- Added `console/.env.example` so environments can copy-and-tune config without touching source code.
- `console/src/auth/proboost/config.ts` now trims/normalizes env input and still preserves safe defaults for backward compatibility.

# Plan: Fix wheel build PEP 668 failure

- [x] Identify why `scripts/wheel_build.sh` fails with `externally-managed-environment`.
- [x] Update wheel build script to avoid system-wide `pip install` and use isolated build tooling.
- [x] Validate script syntax and document behavior.

## Verification
- `bash -n scripts/wheel_build.sh` passed.

## Review
- `scripts/wheel_build.sh` now creates/uses an isolated venv at `.wheelshim/build-venv` (override via `WHEEL_BUILD_VENV`) and runs `pip/build` inside it.
- This removes the system `python3 -m pip install build` step that triggers PEP 668 on Homebrew-managed Python.

# Plan: Fix Mattermost default media_dir branding path

- [x] Locate Mattermost default media directory definitions in backend config/runtime and console form placeholder.
- [x] Replace legacy `~/.copaw/media/mattermost` default with `~/.boostclaw/media/mattermost` in source defaults.
- [x] Add focused unit tests to lock the new default values.
- [x] Run targeted tests and syntax checks for changed files.

## Verification
- `pytest -q tests/unit/channels/test_mattermost_defaults.py` failed in this environment (`pytest: command not found`).
- `python3 -m py_compile src/copaw/config/config.py src/copaw/app/channels/mattermost/channel.py tests/unit/channels/test_mattermost_defaults.py` passed.

## Review
- Updated Mattermost backend defaults in `src/copaw/config/config.py` and `src/copaw/app/channels/mattermost/channel.py` to use `~/.boostclaw/media/mattermost`.
- Updated console channel form placeholder in `console/src/pages/Control/Channels/components/ChannelDrawer.tsx` to match the backend default.
- Added regression coverage in `tests/unit/channels/test_mattermost_defaults.py` to prevent default-path drift back to `~/.copaw`.

# Plan: Add debug logs for login/register

- [x] Inspect the console auth flow to find the minimal safe place(s) to log login/register activity.
- [x] Add debug-oriented logs for login/register attempts/results without printing passwords, SMS codes, or tokens.
- [x] Run targeted diagnostics/build validation for changed auth files.
- [x] Document verification and review results.

## Verification
- `get_errors` check for `console/src/auth/context.tsx` returned no errors.
- `cd console && npx eslint src/auth/context.tsx` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).

## Review
- Added centralized debug logs in `console/src/auth/context.tsx` for `login` and `register` start/success/failure paths so both `/login` and `/register` routes are covered.
- Logs only include masked phone numbers, country code, and non-sensitive result/error metadata; passwords, SMS codes, and tokens are not logged.

# Plan: Persist login/register debug events into backend logs

- [x] Add a minimal frontend API method to report auth debug events to backend.
- [x] Update auth context to send non-blocking sanitized login/register events to backend logs.
- [x] Add backend `/console/auth-debug-events` endpoint with strict field allowlist and sensitive-key filtering.
- [x] Add focused unit tests for backend sanitization behavior.
- [x] Run targeted lint/build/tests and document verification + review.

## Verification
- `get_errors` checks returned no errors for changed frontend/backend files.
- `cd console && npx eslint src/auth/context.tsx src/api/modules/console.ts` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).
- `python3 -m pytest -q tests/unit/test_console_auth_debug.py` failed in this environment (`No module named pytest`).
- `python3 -m py_compile src/copaw/app/routers/console.py tests/unit/test_console_auth_debug.py` passed.

## Review
- Added `consoleApi.reportAuthDebugEvent` in `console/src/api/modules/console.ts` with typed `AuthDebugEventPayload`.
- Updated `console/src/auth/context.tsx` to send fire-and-forget backend auth debug events for login/register start/success/failed, while keeping local `console.debug` output.
- Added backend endpoint `POST /console/auth-debug-events` in `src/copaw/app/routers/console.py`.
- Backend now sanitizes payloads via allowlist + sensitive field drop + value length cap before logging.
- Added focused unit tests in `tests/unit/test_console_auth_debug.py` for sensitive-field filtering and truncation behavior.


# Plan: Fix ProBoost auth CORS in console TS flow

- [x] Inspect current ProBoost frontend request path and identify the direct cross-origin call causing the preflight failure.
- [x] Route ProBoost auth requests through a same-origin dev proxy using TypeScript/Vite-only changes.
- [x] Validate the edited TS files for diagnostics and run a frontend build to confirm the auth client still compiles.
- [x] Document verification and review notes for the CORS fix.

## Verification
- `get_errors` returned no diagnostics for `console/src/auth/proboost/client.ts` and `console/vite.config.ts` after the edits.
- `cd console && npx eslint src/auth/proboost/client.ts vite.config.ts` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).

## Review
- Updated `console/src/auth/proboost/client.ts` so login, send-SMS, and verify-SMS requests use same-origin `/api/proboost-auth/*` paths during Vite local development, avoiding browser CORS preflights against the external domain while preserving the existing direct ProBoost URLs outside dev mode.
- Confirmed the current Python backend does not register a `/api/proboost-auth/*` router, so a fully same-origin solution for the `127.0.0.1:8088` hosted console cannot be completed with TS-only changes.
- Added a Vite dev proxy in `console/vite.config.ts` for `/api/proboost-auth` so local frontend development avoids browser CORS preflights against the external ProBoost domain.


# Plan: Implement backend ProBoost auth proxy + clean console auth dead code

- [x] Review current ProBoost auth frontend/backend code and map the documented ProBoost endpoints to backend `/api/proboost-auth/*` routes.
- [x] Implement backend proxy handlers for login, send-sms-code, and verify-sms-code, and register the router under the existing `/api` mount.
- [x] Simplify the console ProBoost client/config to always use the backend proxy and remove no-longer-used frontend direct-call/env code.
- [x] Run focused diagnostics/build/syntax verification for the changed Python and TypeScript files, and document the outcome.

## Verification
- `get_errors` reported no errors for `src/copaw/app/routers/proboost_auth.py`, `src/copaw/app/routers/__init__.py`, `console/src/auth/proboost/client.ts`, `console/src/auth/proboost/config.ts`, and `tests/unit/test_proboost_auth_router.py` after the edits. (`console/src/vite-env.d.ts` still shows a pre-existing IDE warning that `ImportMetaEnv` is unused.)
- `python3 -m py_compile src/copaw/app/routers/proboost_auth.py src/copaw/app/routers/__init__.py tests/unit/test_proboost_auth_router.py` passed.
- `python3 tests/unit/test_proboost_auth_router.py` passed (`Ran 4 tests ... OK`).
- `cd console && npx eslint src/auth/proboost/client.ts src/auth/proboost/config.ts vite.config.ts src/vite-env.d.ts` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).

## Review
- Added `src/copaw/app/routers/proboost_auth.py` as a dedicated backend proxy for the documented ProBoost auth endpoints, forwarding login, send-SMS, and verify-SMS requests to `https://proboost.microdata-inc.com/pb_api/insight/v3/...` with the required auth/language/origin/referer headers.
- Registered the new router in `src/copaw/app/routers/__init__.py`, so the endpoints are now available under `/api/proboost-auth/*` via the existing `/api` app mount.
- Simplified `console/src/auth/proboost/client.ts` so the console always calls the backend proxy (`/api/proboost-auth/*`) instead of maintaining direct external fetch logic.
- Removed unused frontend ProBoost direct-call config from `console/src/auth/proboost/config.ts`, `console/src/vite-env.d.ts`, and `console/.env.example`, keeping only the still-used website/language/country settings.
- Added focused regression coverage in `tests/unit/test_proboost_auth_router.py` for route exposure, URL normalization, and proxy header construction.


# Plan: Add selectable auth country code

- [x] Inspect the auth form and current default-country config to identify the smallest change for selectable `countryCode` support.
- [x] Add supported country-code options (`+86`, `+1`, `+81`, `+39`) to the auth config and wire the selected value through login, register, and send-code actions.
- [x] Update auth i18n copy for the new selector and preserve a safe default when env config is unsupported.
- [x] Run targeted diagnostics/lint/build validation and document the result.

## Verification
- `get_errors` returned no diagnostics for `console/src/auth/proboost/config.ts` and `console/src/pages/Auth/Login/index.tsx` after the edits.
- `cd console && npx eslint src/auth/proboost/config.ts src/pages/Auth/Login/index.tsx` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).

## Review
- Added `SUPPORTED_COUNTRY_CODES` in `console/src/auth/proboost/config.ts` with `+86`, `+1`, `+81`, and `+39`, and normalized the env-driven default country code back to `+86` if an unsupported value is configured.
- Updated `console/src/pages/Auth/Login/index.tsx` to render a selectable `countryCode` field and pass the chosen value into password login, SMS send, and SMS verification/register flows.
- Added selector copy to `console/src/locales/zh.json`, `console/src/locales/en.json`, `console/src/locales/ja.json`, and `console/src/locales/ru.json`.


# Plan: Refine auth country-code selector UI

- [x] Inspect the current auth country-code selector implementation and identify the smallest UI-only refinement for inline layout + country names.
- [x] Show country names alongside `+86`, `+1`, `+81`, and `+39` in the selector while keeping the existing supported-code list.
- [x] Arrange the country-code selector and phone input on one row in the auth form without breaking validation.
- [x] Run targeted diagnostics/lint/build validation and document the result.

## Verification
- `get_errors` returned no diagnostics for `console/src/pages/Auth/Login/index.tsx` and the edited locale JSON files.
- `cd console && npx eslint src/pages/Auth/Login/index.tsx src/auth/proboost/config.ts` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).

## Review
- Refined `console/src/pages/Auth/Login/index.tsx` so the country-code selector now displays localized country names for China, United States, Japan, and Italy.
- Placed the `countryCode` selector and phone input on the same row in the auth form for a more compact login/register layout.
- Added localized country-label strings under `auth.countryCodeOptions` in `console/src/locales/en.json`, `console/src/locales/zh.json`, `console/src/locales/ja.json`, and `console/src/locales/ru.json`.


# Plan: Move ProBoost website/language config to backend proxy

- [x] Audit current frontend and backend ownership of ProBoost `webSiteId`, `language`, and default `countryCode`.
- [x] Update the backend ProBoost proxy to inject `webSiteId` and backend-owned default `language` for upstream requests.
- [x] Simplify the frontend ProBoost config/types/service/client/env surface so only UI-level country-code defaults remain.
- [x] Extend verification coverage and run focused Python/TypeScript validation for the ownership shift.

## Verification
- `python3 -m py_compile src/copaw/app/routers/proboost_auth.py tests/unit/test_proboost_auth_router.py` passed.
- `python3 tests/unit/test_proboost_auth_router.py` passed (`Ran 5 tests ... OK`).
- `cd console && npx eslint src/auth/proboost/config.ts src/auth/proboost/types.ts src/auth/proboost/client.ts src/auth/service.ts src/pages/Auth/Login/index.tsx` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).
- `get_errors` was re-run on edited files; Python files were clean, while JetBrains still reported stale frontend import diagnostics inconsistent with the successful ESLint + TypeScript build after the symbol rename.

## Review
- Backend proxy ownership now includes ProBoost `webSiteId` and default `language` in `src/copaw/app/routers/proboost_auth.py`; the browser no longer needs to send either value.
- Frontend ProBoost payload types and service calls were simplified to remove `webSiteId`, and `console/src/auth/proboost/client.ts` no longer adds a frontend-managed `language` header.
- `console/src/auth/proboost/config.ts` is now UI-only: it keeps `SUPPORTED_COUNTRY_CODES`, `DEFAULT_COUNTRY_CODE`, and the normalized `defaultCountryCode` export used by the auth form.
- `console/src/vite-env.d.ts` and `console/.env.example` were trimmed to remove obsolete frontend env keys for ProBoost `websiteId` and `language`.
- `tests/unit/test_proboost_auth_router.py` now covers backend payload injection for `webSiteId` in addition to route exposure and header defaults.


# Plan: Document backend ProBoost proxy configuration

- [x] Review the current backend ProBoost proxy ownership and choose the best existing doc location for operator-facing notes.
- [x] Document local proxy routes, backend-owned ProBoost config/env vars, and frontend/backend responsibility boundaries.
- [x] Add a minimal inline code comment if it helps prevent future config drift.
- [x] Verify the documentation against the current router/client implementation and record the result.

## Verification
- Read back the top section of `scripts/boost_api.md` to confirm it now documents local `/api/proboost-auth/*` routes, backend-owned config, and `BOOSTCLAW_*` env overrides.
- `get_errors` reported no diagnostics for `src/copaw/app/routers/proboost_auth.py` after the inline comment update.
- Read back `src/copaw/app/routers/proboost_auth.py` to confirm the inline comments match actual runtime ownership (`language` header + injected `webSiteId`).

## Review
- Added a new “BoostClaw 集成说明（后端代理）” section near the top of `scripts/boost_api.md` so operators can see the local proxy route mapping and backend environment variables in the same place as the upstream ProBoost API contract.
- Documented the post-migration ownership split explicitly: frontend only supplies user-entered auth fields, while backend owns upstream connection settings and default request parameters.
- Added concise inline comments in `src/copaw/app/routers/proboost_auth.py` to make backend ownership of transport defaults and `webSiteId` injection obvious in the source of truth.


# Plan: Add backend-driven ProBoost auth metadata

- [x] Audit the current static country-code config in the console and decide the minimal backend metadata contract.
- [x] Add `GET /api/proboost-auth/meta` in the backend proxy with normalized default/supported country-code values.
- [x] Update the auth UI to consume backend metadata with safe static fallback when the request is unavailable.
- [x] Extend regression coverage and run focused Python/TypeScript verification for the new metadata flow.

## Verification
- `python3 -m py_compile src/copaw/app/routers/proboost_auth.py tests/unit/test_proboost_auth_router.py` passed.
- `python3 tests/unit/test_proboost_auth_router.py` passed (`Ran 7 tests ... OK`).
- `cd console && npx eslint src/auth/proboost/config.ts src/auth/proboost/types.ts src/auth/proboost/client.ts src/auth/service.ts src/pages/Auth/Login/index.tsx` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).
- `get_errors` returned no diagnostics for the edited backend/frontend/doc files after the final pass.

## Review
- Added backend-driven auth metadata in `src/copaw/app/routers/proboost_auth.py` via `GET /api/proboost-auth/meta`, including normalization for default and supported country codes and env overrides for both values.
- Extended `tests/unit/test_proboost_auth_router.py` to cover the new metadata route and normalization behavior in addition to the existing proxy header/payload checks.
- Updated `console/src/auth/proboost/client.ts` and `console/src/pages/Auth/Login/index.tsx` so the auth page fetches backend metadata once, uses it for country-code options/defaults, and safely falls back to static defaults if the route is unavailable.
- Kept frontend fallback config minimal in `console/src/auth/proboost/config.ts`, and clarified in `console/.env.example` that `VITE_PROBOOST_COUNTRY_CODE` is now fallback-only.
- Updated `scripts/boost_api.md` to document `/api/proboost-auth/meta` and the backend-owned country-code metadata env vars.


# Plan: Move country label mapping into backend auth metadata

- [x] Audit the current `/api/proboost-auth/meta` contract and frontend country-label mapping to identify the minimal ownership shift.
- [x] Extend backend auth metadata so it includes ordered country-code options with backend-owned label keys.
- [x] Remove the auth page’s hardcoded country-code label map and render selector labels directly from backend metadata with raw-code fallback.
- [x] Update tests/docs and rerun focused Python/TypeScript verification.

## Verification
- `python3 -m py_compile src/copaw/app/routers/proboost_auth.py tests/unit/test_proboost_auth_router.py` passed.
- `python3 tests/unit/test_proboost_auth_router.py` passed (`Ran 7 tests ... OK`).
- `cd console && npx eslint src/auth/proboost/config.ts src/auth/proboost/types.ts src/auth/proboost/client.ts src/auth/service.ts src/pages/Auth/Login/index.tsx` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).
- `get_errors` returned no diagnostics for the edited backend/frontend/doc files after the final pass.

## Review
- Extended `src/copaw/app/routers/proboost_auth.py` so `/api/proboost-auth/meta` now returns `countryCodeOptions` with backend-owned `labelKey` entries, keeping ordering and label mapping in one place.
- Updated `tests/unit/test_proboost_auth_router.py` to assert the enriched metadata payload for both default and custom country-code normalization cases.
- Removed the hardcoded `COUNTRY_CODE_LABEL_KEYS` map from `console/src/pages/Auth/Login/index.tsx`; the auth page now renders labels directly from backend metadata and falls back to the raw code if no `labelKey` is provided.
- Expanded the frontend metadata contract/fallback handling in `console/src/auth/proboost/types.ts`, `console/src/auth/proboost/config.ts`, and `console/src/auth/proboost/client.ts`.
- Updated `scripts/boost_api.md` to document the richer `/api/proboost-auth/meta` response structure including `countryCodeOptions`.


# Plan: Add regression tests for modified ProBoost auth code

- [x] Review current backend/frontend test capabilities for the recently modified ProBoost auth flow.
- [x] Extend backend router tests to cover env-driven metadata normalization edge cases.
- [x] Add lightweight frontend unit tests for ProBoost auth config normalization and metadata parsing/fetch behavior.
- [x] Run the new tests plus targeted existing validation and document the results.

## Verification
- `python3 tests/unit/test_proboost_auth_router.py` passed (`Ran 8 tests ... OK`).
- `cd console && npm test` passed with the new Vitest suite (`2` files, `6` tests).
- `cd console && npx eslint src/auth/proboost/config.ts src/auth/proboost/types.ts src/auth/proboost/client.ts src/auth/service.ts src/pages/Auth/Login/index.tsx tests/auth/proboost/config.test.ts tests/auth/proboost/client.test.ts` passed.
- `cd console && npm run build` passed (`tsc -b && vite build`).
- `get_errors` returned no diagnostics for the new backend/frontend test files and the updated `console/package.json`.

## Review
- Extended `tests/unit/test_proboost_auth_router.py` with an env-driven metadata normalization case that verifies deduplication and missing-`labelKey` fallback for unknown country codes.
- Added a lightweight frontend unit-test harness to `console` by introducing `vitest` and a `test` script in `console/package.json`.
- Added `console/tests/auth/proboost/config.test.ts` to cover `normalizeSupportedCountryCodes`, `normalizeCountryCode`, and `FALLBACK_AUTH_META`.
- Added `console/tests/auth/proboost/client.test.ts` to cover `parseAuthMeta`, successful `fetchAuthMeta`, and failed metadata request handling.


