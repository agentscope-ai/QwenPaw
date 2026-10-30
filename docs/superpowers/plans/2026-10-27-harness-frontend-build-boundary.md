# Harness frontend build boundary repair

> 测试维护更新（2026-10-28）：本文保留历史实施/验收记录；旧测试路径、行号和命令不再是当前入口。当前四个核心测试、构建及手工验收边界以[精简方案](../specs/2026-10-28-harness-test-slimming.md)为准。

> **For agentic workers:** Use superpowers:subagent-driven-development; production/config and test work have separate authors as requested by the user.

**Goal:** Fix the reported Desktop Windows frontend compile failure while keeping optional Harness source out of Console production compilation and preserving all six cross-plugin test assertions.

**Architecture:** Move `console/src/plugins/vendorHarnessSettings.test.tsx` byte-for-byte to `console/tests/plugins/vendorHarnessSettings.test.tsx`. Register an exact `@qwenpaw/plugin-sdk` alias pointing to `../src/qwenpaw/plugins/frontend/index.js` inside `test.alias` in `console/vite.config.ts`. Keep production resolution, TypeScript scope, runtime bundles and plugin dependencies unchanged.

**Spec:** User approved the previous diagnosis and this two-file solution in chat. Failed run: https://github.com/Luohh5/QwenPaw/actions/runs/40300314670/job/121496293154 (commit 6e84471). Clean scratch reproduction confirmed missing SDK/JSX modules; moving the test and adding the test-only public SDK alias made TypeScript and six tests pass.

## Global Constraints

- Reuse current `refactor/plugin_harness`; BASE `309279420202b196de27b23361e0c4deb1b17f51`. No push/merge/publish, remote workflow rerun, 9099/account/global environment changes.
- Production agent owns only functional/config changes; test agent owns only the test relocation and independent verification. Neither edits the other's files or dispatches agents.
- Preserve original test content and assertions exactly; do not skip tests, mock away the public SDK or relax TypeScript checks.
- Console clean build and six-test phase must have no node_modules in either plugin directory, and no hidden plugin SDK installation in Console dependencies.
- Build plugins independently in separate clean staging directories using declared dependencies and the real public SDK package. Do not borrow plugin node_modules from the checkout or require both plugins during Console build.
- Keep changes concise and colocated. No new runtime work, synchronous backend IO, dependencies, source JSX rewrites or ZIP changes are required.

## Review Focus

- Moved test remains auto-discovered by normal Vitest commands and retains its six assertions/cases unchanged.
- Relative component imports continue to resolve after relocation.
- Public SDK alias is exact and test-only; production Vite configuration must not resolve optional plugin modules via it.
- Full `npm run build:prod` includes TypeScript, Vite, Monaco CSS, precompression and initial-bundle verification; report actual final exit status.
- Each plugin builds from its own manifest/config and public SDK in isolation, without changing the other plugin or the checkout.

### Task 1: Separate production compilation from cross-plugin tests

- [x] Independent test author records original-file hash, relocates it byte-for-byte, and establishes RED from missing SDK resolution before production config changes.
- [x] Production author adds the exact alias in `test.alias`, preserving existing production/test aliases and compiler settings.
- [x] Independent test author verifies six cross-plugin tests and file-byte identity in a clean core staging directory with both plugin node_modules absent.
- [x] Run Console full production build in that clean directory and validate actual build guards.
- [x] Independently build Codex and Qoder frontends in separate fresh dependency environments, using the actual public SDK.
- [x] Review complete scoped diff for specification compliance and code quality; run relevant formatting/lint and actual commit hooks.
- [x] Record evidence and save a concrete local result without pushing or merging.
