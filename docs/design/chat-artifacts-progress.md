# Chat Workspace Artifacts Progress

This checklist is the implementation ledger for Issue #6083. Update it whenever
a task changes state or new verification evidence is produced.

## Current status

- Phase: 3 - automated and end-to-end validation
- Overall: 6 of 9 milestones complete
- Branch: `fix/desktop-artifacts-6083`
- Base: `origin/main` at `6f8e52a4`
- Workspace opener migration: `4e9e7f8a`
- Last updated: 2026-08-03

## Success criteria

- [x] A turn that creates or modifies user files emits one manifest-backed card.
- [x] Shell/Python-created files are detected without parsing assistant text.
- [x] Refreshing the chat restores the same artifact card and agent identity.
- [x] Preview, download, Desktop open, and Desktop reveal enforce workspace bounds.
- [ ] XLSX end-to-end creation produces a usable WorkBuddy-style experience.
- [ ] Focused backend, frontend, Rust, and end-to-end checks pass or have explicit
      environment limitations recorded.

## Milestones

### 1. Baseline and branch

- [x] Inspect tracked and untracked workspace state.
- [x] Fetch the current upstream `main`.
- [x] Create `fix/desktop-artifacts-6083` from upstream.
- [x] Migrate the existing workspace opener implementation.
- [x] Preserve all pre-existing untracked files and directories.

Evidence:

- Upstream base: `6f8e52a4`
- Migration commit: `4e9e7f8a`
- Conflicts were limited to Tauri capability and module registration; both kept
  upstream registrations plus `open-workspace`.

### 2. Design contract

- [x] Record goals and non-goals.
- [x] Define manifest v1.
- [x] Define two-source discovery and lifecycle.
- [x] Define security and cross-platform boundaries.
- [x] Define UI behavior and test matrix.

### 3. Backend artifact discovery

- [x] Add immutable artifact and snapshot models.
- [x] Add cross-platform relative-path normalization.
- [x] Add exclusions and bounded workspace scanning.
- [x] Add before/after snapshot diffing.
- [x] Add explicit file registration and deterministic merge.
- [x] Add unit tests in the base Python environment.

Evidence:

- Focused suite: `9 passed`.
- Formatting: base Python Black check passed for 8 files.
- The default Windows pytest temp root is ACL-blocked in this environment;
  validation used a task-local writable `--basetemp` and disabled cache writes.
- CSV and Markdown MIME types are explicitly normalized for cross-platform
  manifest stability.

### 4. Turn integration and persistence

- [x] Locate the single shared completion boundary for chat turns.
- [x] Capture the initial snapshot before tool execution.
- [x] Capture and merge the final snapshot after execution.
- [x] Emit one `workspace_artifacts` event when changes exist.
- [x] Preserve agent, chat, and turn identity in stored history.
- [x] Verify scan failures do not alter the assistant response.

Evidence:

- `WorkspaceArtifactsHook` is registered by both app and ACP bootstrap paths.
- Runtime captures before `PRE_DISPATCH`, collects before final envelope close,
  and appends a versioned `RESULT` message to the same response output.
- Artifact focused suite: `10 passed`; AST parse: `AST_OK`.
- Bytecode compile was attempted but existing repository `__pycache__` ACLs
  prevented writes; no-write AST validation passed.

### 5. Secure file operations

- [x] Reuse or extend backend file preview/download endpoints.
- [x] Reject traversal, workspace escape, cross-agent access, and directories.
- [x] Add Desktop system-open command.
- [x] Add Desktop file-manager reveal command.
- [x] Register minimal Tauri permissions.
- [x] Add focused Rust tests.
- [ ] Run focused Rust tests.

Evidence:

- Agent-scoped `/workspace/artifacts/{path}` endpoint uses `safe_join`, rejects
  non-regular files, limits downloads to 250 MB, and preserves MIME metadata.
- Tauri open/reveal commands resolve relative paths under the manifest agent's
  configured workspace and canonicalize before operating.
- Windows reveal uses one `/select,<path>` argument; macOS uses `open -R`; Linux
  opens the containing directory with `xdg-open`.
- Rust toolchain is not installed in the current environment, so Rust formatting
  and focused tests remain an explicit verification gap.

### 6. Chat artifact UI

- [x] Add manifest parser and version fallback.
- [x] Register `workspace_artifacts` for live and replay adapters.
- [x] Build compact WorkBuddy-style artifact group.
- [x] Build all-artifacts and all-changes views.
- [x] Reuse file preview support.
- [x] Add download, system-open, and reveal actions.
- [x] Add responsive, keyboard, loading, empty, and error states.
- [x] Use Lucide React only for new icons.

Evidence:

- Compact summary shows up to four files with type, size, and change state.
- Drawer views expose all artifacts, all changes, and supported previews.
- Historical actions and previews use the manifest `agent_id`, not current UI
  selection.

### 7. Automated validation

- [x] Backend unit tests pass 100% for changed Python code.
- [x] Relevant frontend Vitest command exits successfully.
- [x] TypeScript validation passes.
- [x] ESLint and Prettier checks pass for changed frontend files.
- [ ] Rust formatting and focused tests pass.
- [x] `git diff --check` passes.

### 8. End-to-end validation

- [x] Start backend and Desktop application from an agent workspace.
- [x] Ask the agent to create an XLSX and Markdown summary.
- [x] Confirm a single artifact group appears after the turn.
- [ ] Confirm metadata and change labels are correct.
- [ ] Confirm Markdown preview and browser download.
- [ ] Confirm XLSX opens in the default Desktop application.
- [x] Confirm reveal selects or locates the correct file.
- [ ] Refresh and confirm historical restoration.
- [ ] Switch agents and confirm the historical card still uses its original agent.
- [ ] Attempt traversal and cross-agent access and confirm rejection.

### 8.2 Historical artifact restoration fix

- [x] Diagnose the missing card after chat switch, agent switch, or restart.
- [x] Read manifests from the persisted `agent` state module.
- [x] Keep compatibility with a legacy root-level manifest field.
- [x] Add regression tests for both persisted layouts.
- [ ] Re-run Desktop/source end-to-end restoration checks.

Root cause: `SessionSaveHook` persists the manifest in the `agent` state
module, while the history API previously read only the outer session object.
The live response therefore showed a card, but history replay reconstructed no
workspace tool pair after a chat switch or application restart.

Desktop evidence exposed an internal-state false positive: a turn that created
`test.xlsx` and `work.md` also reported `chats.json`, `skill.json`, and a
32-character hexadecimal session `.jsonl` file.

### 8.1 Internal-state false-positive fix

- [x] Reuse the repository's QwenPaw root-state path policy in artifact scans.
- [x] Exclude root session `.jsonl` files with 32 hexadecimal stems.
- [x] Keep user-authored nested `chats.json` and ordinary `.jsonl` files.
- [x] Apply the same exclusions to explicit artifact registration.
- [x] Add snapshot and collector regression tests.
- [x] Re-run backend, frontend, formatting, and type validation.
- [ ] Rebuild Desktop and confirm the same prompt reports exactly two files.

### 9. Delivery

- [x] Review the final scoped diff against upstream.
- [x] Update this document with exact commands and pass counts.
- [ ] Commit only scoped files.
- [ ] Push the branch to the fork.
- [ ] Prepare an upstream PR description with limitations and verification steps.

## Known limitations and risks

- Full-workspace scanning must remain bounded for large repositories.
- Timestamp and size comparison can miss an unusual in-place rewrite that keeps
  both values unchanged; explicit file-tool registration covers common cases.
- Symlink and Windows junction behavior needs platform-specific tests.
- Office in-app rendering is deliberately deferred from the MVP.
- Existing untracked workspace content is user-owned and excluded from commits.

## Validation log

| Date | Command or check | Result |
| --- | --- | --- |
| 2026-08-03 | Fetch `origin/main` | Passed; advanced from `044b505e` to `6f8e52a4` |
| 2026-08-03 | Create implementation branch | Passed |
| 2026-08-03 | Cherry-pick workspace opener | Passed after two minimal registration conflicts |
| 2026-08-03 | Artifact discovery focused pytest | Passed; 9 tests |
| 2026-08-03 | Black check for artifact slice | Passed; 8 files unchanged |
| 2026-08-03 | Runtime artifact integration tests | Passed; 10 focused tests and AST validation |
| 2026-08-04 | Backend artifact, history, security, and file-tool regression | Passed; 61 tests |
| 2026-08-04 | TypeScript `tsc --noEmit` | Passed |
| 2026-08-04 | Focused ESLint and Prettier | Passed |
| 2026-08-04 | Focused Vitest parser command | Exit 0; terminal did not print test count |
| 2026-08-04 | Rust toolchain lookup | Blocked; `cargo` and `rustfmt` unavailable |
| 2026-08-04 | Full console build | Incomplete; Vite emitted no completion summary and Monaco CSS verification failed |
| 2026-08-04 | TypeScript `tsc -b --noEmit` after CI fixes | Passed |
| 2026-08-04 | Focused frontend Prettier check after CI fixes | Passed |
| 2026-08-04 | Base-environment focused mypy | Passed |
| 2026-08-04 | Pre-commit for all 19 CI-fix files | Passed; all applicable hooks |
| 2026-08-04 | Backend artifact regression after CI fixes | Passed; 61 tests in 13.01 seconds |
| 2026-08-04 | Desktop XLSX/Markdown creation and Explorer reveal | Partial pass; reveal selected `test.xlsx`, but three QwenPaw state files were false positives |
| 2026-08-04 | Internal-state filter red tests | Expected failure; 2 failed and 9 passed before implementation |
| 2026-08-04 | Internal-state filter focused tests | Passed; 11 tests |
| 2026-08-04 | Artifact, history, security, file-tool, and path-policy regression | Passed; 64 tests in 7.90 seconds |
| 2026-08-04 | Focused base-environment mypy and Black | Passed |
| 2026-08-05 | Historical manifest persistence regression | Passed; 7 tests in 0.64 seconds |
| 2026-08-05 | Historical manifest API Black and mypy | Passed |
| 2026-08-04 | Base Python AST parse | Passed; 8 changed Python files |
| 2026-08-04 | Focused pylint after line-ending normalization | Passed; 10.00/10 |
| 2026-08-04 | TypeScript `tsc -b --noEmit` after state-filter fix | Passed |
| 2026-08-04 | Checkpoint regression | Environment-blocked; 117 passed, 24 Git-ref ACL failures, 3 skipped |
| 2026-08-04 | Isolated pre-commit | Hooks reached mypy/Black/flake8 pass; cache manifest was later removed by the environment |
