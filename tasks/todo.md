# Plan: Update source repo URL to boostclaw

- [x] Inventory all references to the source repository URL.
- [x] Update repo URLs to https://github.com/aimentorai/boostclaw.git where appropriate.
- [x] Run diagnostics/tests/build as applicable.
- [x] Document results and verification.

## Verification
- LSP diagnostics: clean for updated TS/TSX files (Header.tsx, Sidebar.tsx, Nav.tsx, QuickStart.tsx, config.ts). Note: TypeScript hints report deprecated `Github` icon usage (pre-existing).
- Tests: `python scripts/run_tests.py -u` failed (python not found). `python3 scripts/run_tests.py -u` failed (pytest not installed). Attempted venv install with `python3 -m venv .venv && . .venv/bin/activate && python -m pip install -e ".[dev,full]"` failed due to Python 3.14.3 not in supported range (<3.14,>=3.10).

## Review
- Updated source repo URLs to https://github.com/aimentorai/boostclaw(.git) across install scripts, console, website config/components, docs, READMEs, contributing guides, and release notes.

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

