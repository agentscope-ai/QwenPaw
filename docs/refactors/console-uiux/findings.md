# Console UI/UX Finding Ledger

Source findings are defined in the
[2026-10-15 evidence audit](../../audits/2026-10-15-console-uiux-evidence-audit.md).
This ledger records implementation and review state without rewriting the
original evidence.

All F1–F12 are `CLOSED` under their accepted defect contracts. This does not
close the full UI/UX roadmap or the residual enhancements listed below.
Validation-first governs whether a defect enters this ledger; it is not the
completion definition for the broader refactor. Functional linkage, visual
quality, responsive/theme consistency, stability/recovery, runtime log/request
quality, and performance continue through separately authorized vertical work.
The scoped function/state-linkage and visual/page-refinement stage is closed at
`6179f8dea0c34d1ff6ee6aae123cc1f4529850a5`. Stability/recovery and
performance are `DEFERRED TO SEPARATE REFACTOR` and require new authorization.

## Finding-to-commit map

| ID | Severity | Wave | Status | Integration commit(s) | Evidence | Independent verdict |
|---|---|---:|---|---|---|---|
| F1 | P1 | 1 | `CLOSED` | `28109b4cc9e0bd294484a64e68b92216b1fd4e52` | Deferred A/B request test; static agent-scoping confirmation | `APPROVE` at Wave 1 final HEAD |
| F2 | P1 | 1 | `CLOSED` | `8b2317cb64bf535fc2b5e40623b861aa95b1e9f4` | Two-approval targeted fixture; focus isolation | `APPROVE` at Wave 1 final HEAD |
| F3 | P2 | 1 | `CLOSED` | `fe924da8e142254656f5bed7dbfcaa7cc6a8bf45`, `a61c5c64adb9854e317c341c64e626ba18cf3f14` | Browser-runtime geometry at 768/769/820/900/901px | `APPROVE` at Wave 1 final HEAD |
| F4 | P2 | 1 | `CLOSED` | `fd8801b03bf141530e962001c83b4c7ff0a84830`, `cff936b699d5936881be75c47b4b469d08f8bb3b`, `7df8c7819673e815b765cfaa760baad793e1e823` | Accessible-name tests; 390×844 browser-runtime target measurement | `APPROVE` after M2 repair |
| F5 | P2 | 1 | `CLOSED` | `ec5cb20704c454caae327e3628e8af4c9f10f125`, `57676c037c4874226cea42b9cb2995e3858707fb` | Single-owner static chain; lifecycle and polling targeted tests | `APPROVE` after M1 repair |
| F6 | P2 | 2 | `CLOSED` | `1b0ecec92734c424f317c1dc7f2c98b7ee7edc55` | Lazy/bounded formatter targeted tests and static review | `APPROVE` |
| F7 | P2 | 2 | `CLOSED` | `038e811d9ff26d63e3abe9ac0acdba959e43f1c2` | 500/2000 fixture, CSS contract, page targeted tests | `APPROVE` |
| F8 | P2 | 1 | `CLOSED` | `59fdd5041f8b8d0114cf4bcd3cc13b7418feef9e` | Semantic-token static check and theme targeted tests | `APPROVE` at Wave 1 final HEAD |
| F9 | P2 | 2 | `CLOSED` | `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8` | Browser-runtime skip/focus/nested-interactive smoke; targeted tests | `APPROVE` |
| F10 | P2 | 2 | `CLOSED` | `508952dd7f6b9508288195fc5ce86931ce3ce7ad` | 72 treeitems, one Tab stop, Arrow/Home/End runtime smoke; targeted tests | `APPROVE` |
| F11 | P2 | 1 | `CLOSED` | `21e8ff6be08872ceb3b00a4fc642c16e7f17a4bd` | Named-combobox browser runtime and targeted test | `APPROVE` at Wave 1 final HEAD |
| F12 | P3 | 1 | `CLOSED` | `fbdf77bf8cc9f7e81ce7ea6c11c0c30247e76c3a` | Unique provider-action browser runtime and targeted test | `APPROVE` at Wave 1 final HEAD |

Last verification date for this reconciliation: 2026-10-19,
Asia/Shanghai. Wave-level task and review mappings are in the corresponding
[Wave 1](waves/wave-1.md), [Wave 2](waves/wave-2.md), and
[Wave 3](waves/wave-3.md) closeouts and the
[Wave 4 warning record](waves/wave-4.md).

## Wave 3 formal findings

| ID | Severity | Wave | Status | Evidence | Integration | Repair state |
|---|---|---:|---|---|---|---|
| A1 | Minor | 3 | `CLOSED` | Integration validation plus independent 31/31 tests, static checks, and 768/769px geometry review | Source `7d7e24251d0bff46c0e6f06d65892cf8f65bae68`; integration/head `e3e12d98627acd15323c3f2803378d90f1d1aeaf` | Reviewer `01a13e66-462a-7292-a7fe-aafb5d3662d8`: `APPROVE`, no Issues |
| C1 | P2 | 3 | `CLOSED` | Developer and independent targeted/static/performance validation passed | Commit/head `8b5db203f88ff3e24223f6a53f671c693dc61ed9` | Reviewer `01a13e66-462a-7292-a7fe-aafb5d3662d8`: `APPROVE`, no Issues |

## Wave 4 governance repairs

These are governance/compatibility debt repairs, not formal P1/P2 Findings.

| Scope | Status | Task / integration | Evidence | Independent verdict |
|---|---|---|---|---|
| W2 `Spin tip` | `INTEGRATED` | Task `286c724e8`; integration `48e8ca9575` | MainLayout migration; targeted regression included in 5 files / 40 tests | `APPROVE`; no Issues |
| W5 Select `popupClassName` | `INTEGRATED` | Task `286c724e8`; integration `48e8ca9575` | AgentSelector migration and test | `APPROVE`; no Issues |
| W6 Card `bodyStyle` | `INTEGRATED` | Task `286c724e8`; integration `48e8ca9575` | SessionsPage/ChannelCard migrations and tests | `APPROVE`; no Issues |
| Models `destroyOnClose` | `INTEGRATED` | Task `286c724e8`; integration `48e8ca9575` | `destroyOnHidden` migration and test | `APPROVE`; no Issues |

The post-merge gate passed five test files / 40 tests, affected ten-file
ESLint/Prettier checks, and `git diff --check`. The later 6-route × 2
fresh-context matrix observed zero W2/W5/W6, `destroyOnClose`, and `useForm`
events, with zero page/network/write failures; the scoped Ant Design line is
closed.

### A1: 768px Files source tab initially unrecognizable

- Chrome 146 at 768×844, light and dark, reproduced the issue without initial
  horizontal scrolling.
- The tablist measured 209px client width and 317px scroll width. `Knowledge
  Base` was initially 9.9201% visible, became fully visible after scrolling
  108px, and then reported `aria-selected=true` when selected.
- The same tab was fully visible at 390/480px in both themes.
- The fourth entry is difficult for touch users to discover, but horizontal
  scrolling is a reliable workaround; core functionality is not blocked.
- No historical comparison proves a regression.
- Source boundary:
  `FilesWorkspace.module.less:253-255,728-743,984-992` and
  `FilesNavigator.tsx:1147-1166`.
- Minimum fix: constrain changes to the 721–768px navigator/tab layout and keep
  Files data and tree behavior unchanged.
- Required regression: 720/721/767/768/769px × light/dark, four source tabs
  initially recognizable, current tab visible, and no document overflow.
- Task `console-files-tablet-tabs` uses thread
  `01a13ee7-f13a-76e2-9dff-2f165c4b36a1`, worktree
  `/Users/mazhijian/.codex/worktrees/2a4a/QwenPawCodex`, and base
  `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8`. Its file owner is
  `FilesWorkspace.module.less`; only a failing direct test may justify minimally
  touching FilesNavigator/page code.
- Source commit `7d7e24251d0bff46c0e6f06d65892cf8f65bae68` was
  cherry-picked without an extra merge commit as
  `e3e12d98627acd15323c3f2803378d90f1d1aeaf`.
- Long-lived-branch validation was reported passing: three Vitest files / 31
  tests, ESLint, Prettier check, and `git diff --check`.
- Chrome 146 headless touch simulation with route mocks confirmed all four tabs
  were initially and after-selection 100% visible at 720/721/767/768px in both
  themes, with correct selected state and no document or tablist overflow.
- At 769px the unchanged desktop contract intentionally retained horizontal
  scrolling: `Knowledge Base` was initially 0% visible, then 100% visible and
  selected after scroll/click, with no document overflow. This is not claimed
  as a four-tabs-initially-visible pass.
- Browser evidence: `/tmp/qwenpaw-a1-integration-results.json`, SHA-256
  `0ac6955e30da6f3fbe61934bcd31544099976b2a7ad192bcb702cef38434eff9`.
- Independent reviewer thread `01a13e66-462a-7292-a7fe-aafb5d3662d8`
  returned `APPROVE` with no Critical, Important, or Minor Issues. It ran three
  files / 31 tests, ESLint, Prettier, `git diff --check`, and current-theme
  768/769px geometry checks.
- Closure conditions are satisfied at
  `e3e12d98627acd15323c3f2803378d90f1d1aeaf`; A1 is `CLOSED`.
- Non-blocking boundary: the reviewer did not independently exercise every
  non-empty preview/workspace drawer state at 721–768px. Static review found no
  contract violation or actual failure evidence.
- Cross-platform boundary: macOS received runtime sampling; Linux and Windows
  are static CSS low-risk conclusions only.

### C1: Large expanded-tree refresh focus recovery exceeds 50ms

- Package C measured the full refresh-to-React-commit-to-active-focus-recovery
  interaction using normal 200-entry pagination and workspace route mocks.
- Median/p95 was 19.05/33.3ms at 100 visible nodes, 62.3/66.4ms at 500, and
  242.6/275.1ms at 2,000. Every 500- and 2,000-node sample exceeded the 50ms
  interaction budget; 2,000 nodes produced eight 50–54ms Long Tasks.
- A conditional 10,000-node run measured 1402.3/1631.0ms and 25 Long Tasks,
  maximum 358ms. It strengthens scale evidence but is not a required baseline.
- The user path is reachable: normal pagination can expose 500/2,000 treeitems,
  and refreshing an active path preserves loaded pages while replacing that
  path. The remaining visible keys stay stable.
- Focus recovery was 100% correct and no data loss was observed, so the issue is
  P2 rather than a blocking correctness or data-integrity failure.
- Four keyboard operations stayed at p95 1.2–1.4ms for 2,000 nodes and
  4.6–6.6ms for 10,000. Keyboard scanning is therefore not part of C1.
- Static candidate `FilesNavigator.tsx:930-949` performs a full visible-item
  query and active scan from a `MutationObserver`. Segmented evidence rejects
  that scan as the primary cause: callback p95 was 1.2ms and direct DOM scan p95
  was 0.5ms at 2,000 nodes.
- Diagnosis/repair design is complete in the current design-lead conversation;
  it used no Sub-agent and made no code changes. The authorized read-only `/tmp`
  measurement completed with 12 valid samples per tier and zero invalid samples.
- Client p50/p95 was 11.1/19.2ms at 100, 30.55/35.3ms at 500, and
  109.9/112.3ms at 2,000 nodes. At 2,000, pre-observer was 49.4/51.0ms,
  callback 0.75/1.2ms, tail 59.05/60.6ms, and 15 Long Tasks occurred across 12
  samples; network was separate at 94.4/116.5ms.
- Root-cause class is unnecessary full-tree React work with high confidence;
  exact component share is medium confidence. A/B are excluded. C was selected
  and implemented with the narrower boundary recorded below.
- Implementation, virtualization, keyboard changes, and typeahead remain
  outside the measured conclusion. The commander authorized only option C:
  complete-field stable entry identity, memoized workspace leaf rows, and a
  stable toggle callback across the four owned Files source/test files.
  Virtualization, keyboard changes, and typeahead remain unauthorized.
- Implementation completed directly on the long-lived branch as commit
  `8b5db203f88ff3e24223f6a53f671c693dc61ed9`, touching only the four authorized
  Files source/test files. Focused Vitest passed 2 files / 36 tests; ESLint,
  Prettier check, and `git diff --check` passed.
- The commit uses six-field complete equality for entry identity reuse,
  memoizes `WorkspaceFileRow` for root and nested workspace leaves, and
  stabilizes the directory toggle callback. It does not change observer,
  keyboard, ARIA, DOM, style, DnD, or protocol behavior, and does not implement
  A/B, virtualization, or a `DirectoryNode` comparator.
- Full post-commit p95 was 20.2/24.6/33.2ms at 100/500/2,000 nodes, with zero
  Long Tasks, zero invalid samples, 100% Tab-stop recovery, and 1/3/10 requests.
  The 2,000-node control delta was +14.469%, so it was not treated as reliable
  alone. A 20+20 confirmation measured median/p95 13.7/28.1ms, zero Long Tasks,
  zero invalid samples, 20/20 recovery, ten requests, and −4.155% delta.
- Independent reviewer thread `01a13e66-462a-7292-a7fe-aafb5d3662d8`
  returned `APPROVE` with no Critical, Important, or Minor Issues for
  `e3e12d98627acd15323c3f2803378d90f1d1aeaf..8b5db203f88ff3e24223f6a53f671c693dc61ed9`.
  It independently passed 2 files / 36 tests, four-file ESLint/Prettier,
  `git diff --check`, and a 2,000-node 10/10 rerun at median/p95 13.8/19.4ms,
  zero T2–T5 Long Tasks, ten requests per sample, one Tab stop and correct focus
  in 10/10 runs, and zero invalid samples.
- The independent rerun's −38.368% instrumented/control delta exceeds the ±10%
  comparability band. This is an instrumentation/control limitation, not a
  product defect or blocker: the developer 20+20 confirmation had −4.155% delta,
  28.1ms p95, 20/20 recovery, and zero Long Tasks, while the independent
  instrumented samples again stayed well below the 50ms task target.
- Performance and review closure gates passed. The 50ms value remains a task
  target, not an existing product contract. C1 is `CLOSED` at
  `8b5db203f88ff3e24223f6a53f671c693dc61ed9`.
- Evidence directory: `/tmp/qwenpaw-c1-implementation-e3e12d9/`; hashes are
  recorded in `plan.md`. No push or PR occurred.
- Required regression: the same 200-entry fixture at 100/500/2,000 visible
  nodes, 100% recovery, refresh p95 below 50ms, no refresh Long Task, and
  unchanged keyboard behavior/single Tab stop.
- Evidence: `/tmp/qwenpaw-tree-perf.WejBM5/`; package C completed cleanly,
  released its resources, produced no commit, and records
  `no merge applicable`.

## Current-stage formal findings

| Scope | Severity | Status | Evidence | Repair boundary |
|---|---|---|---|---|
| Cron provider/model mouse selection | P1 | `CLOSED / APPROVE / PASS` at `0f909f459` | Browser runtime reproduced a visible provider popup/listbox whose dialog ancestor computed to `pointer-events:none`; `elementFromPoint` reached the underlying form, provider did not change, and model stayed disabled | Task HEAD `892c989311` repaired the popup host fallback and added a real AntD mouse regression; independent review/validation passed and the two-file package merged |
| Cron DurationWheel drawer overflow | Minor | `CLOSED / APPROVE / PASS` at `000bc87af6` | The read-only C audit reproduced horizontal drawer overflow caused by the DurationWheel negative margin | Synchronized candidate `d34465a049` passed its gates and is reachable from final integration |
| Security rule-modal selector width | Minor | `CLOSED / APPROVE / PASS` at `0362e7a5e` | Exact-base real browser measured clipped 37px/76.39px Select controls; post-fix controls remained fully visible across 1280/820/390 × light/dark | Candidate `123d90ae5` changed two Security files; independent browser plus 32-test/static gates passed |
| Debug intermediate-width toolbar | Minor | `CLOSED / APPROVE / PASS` at `6179f8dea` | At 820px the search width was 47.78px and updated text wrapped to three lines; post-fix layout uses two logical rows without overflow | Candidate `50c772132` changed two Debug files; independent browser plus 35-test/static gates passed |

The P1 violates the accepted Cron creation contract: after creating a task and
choosing the reply target, a mouse user must be able to select a provider and
thereby enable model selection. The reachable runtime path opens the provider
popup, but `SettingsDrawer.tsx` supplies its container through
`ConfigProvider.getPopupContainer` under a non-interactive dialog. The current
`ExecutionModelSelect` unit test mocked a native select, so it could not
exercise the real AntD popup or catch the disabled-model consequence. Task HEAD
`892c989311788943c569e7ba56d9448693636a6c` now selects the desktop overlay
root, mobile drawer, or `body` fallback as appropriate. Its real AntD mouse
regression asserts option hitability, provider change, enabled model selection,
and no click-through. Independent review returned `APPROVE`, independent
validation returned `PASS`, and merge `0f909f459061c5de3af72269eb8908201a9e9b07`
integrated the two changed files.

The accepted contract is that drawer content remains within its horizontal
viewport during the reachable Cron DurationWheel interaction. The C audit
reproduced the violation on that real path and isolated the negative margin as
the cause. Final candidate `d34465a0499660355745378dd91d3f29937904ba`
is reachable through merge `000bc87af6471970e5223b413c3694037b0bdf3a`.

## Round 5 closeout evidence

- Final integration: `6179f8dea0c34d1ff6ee6aae123cc1f4529850a5`.
- Inventory: 19 scoped pages, all `CLOSED`; candidate 0, in progress 0,
  U-only page 0, and not inspected 0. Models is scope-out.
- Closure types: 15 code, 3 no-code, and 1 read-only.
- Market actual-browser `PASS` is limited to browse, search, filter, and
  internal detail. Install, update, uninstall, publish, external navigation,
  and real remote effects remain `U`.
- Agent Config, Checkpoints, and Agent Stats are no-code closures backed by
  exact-base actual-browser evidence and focused tests.
- Security and Debug are code closures with independent Reviewer `APPROVE`,
  independent Validator browser `PASS`, focused static/test `PASS`, merge
  reachability, and post-merge targeted gates.
- Round 5 ledger:
  `/tmp/qwenpaw-round5-cf088ce5/REMAINING_MATRIX.md`, SHA-256
  `056a135daa34266439ebd6cd0818225d1cf005754b55c6563db025dbb8f95d8c`.

## Integration chronology

The historical commits form a linear sequence. `integration_head` is the HEAD
immediately after that integration event. Times are Git committer timestamps.

| Sequence | Finding / purpose | Integrated at | Integration commit | Integration head |
|---:|---|---|---|---|
| 1 | F1 | 2026-10-15 15:01:19 +08:00 | `28109b4cc9e0bd294484a64e68b92216b1fd4e52` | `28109b4cc9e0bd294484a64e68b92216b1fd4e52` |
| 2 | F5 Classic Console | 2026-10-15 15:01:19 +08:00 | `ec5cb20704c454caae327e3628e8af4c9f10f125` | `ec5cb20704c454caae327e3628e8af4c9f10f125` |
| 3 | F11 | 2026-10-15 15:01:19 +08:00 | `21e8ff6be08872ceb3b00a4fc642c16e7f17a4bd` | `21e8ff6be08872ceb3b00a4fc642c16e7f17a4bd` |
| 4 | F12 | 2026-10-15 15:01:19 +08:00 | `fbdf77bf8cc9f7e81ce7ea6c11c0c30247e76c3a` | `fbdf77bf8cc9f7e81ce7ea6c11c0c30247e76c3a` |
| 5 | F3 | 2026-10-15 15:01:19 +08:00 | `fe924da8e142254656f5bed7dbfcaa7cc6a8bf45` | `fe924da8e142254656f5bed7dbfcaa7cc6a8bf45` |
| 6 | F3 test formatting | 2026-10-15 15:01:19 +08:00 | `a61c5c64adb9854e317c341c64e626ba18cf3f14` | `a61c5c64adb9854e317c341c64e626ba18cf3f14` |
| 7 | F4 accessible names | 2026-10-15 15:01:19 +08:00 | `fd8801b03bf141530e962001c83b4c7ff0a84830` | `fd8801b03bf141530e962001c83b4c7ff0a84830` |
| 8 | F8 | 2026-10-15 15:01:19 +08:00 | `59fdd5041f8b8d0114cf4bcd3cc13b7418feef9e` | `59fdd5041f8b8d0114cf4bcd3cc13b7418feef9e` |
| 9 | F2 | 2026-10-15 15:01:19 +08:00 | `8b2317cb64bf535fc2b5e40623b861aa95b1e9f4` | `8b2317cb64bf535fc2b5e40623b861aa95b1e9f4` |
| 10 | F4 SDK lifecycle | 2026-10-15 15:01:19 +08:00 | `cff936b699d5936881be75c47b4b469d08f8bb3b` | `cff936b699d5936881be75c47b4b469d08f8bb3b` |
| 11 | F5 M1 repair | 2026-10-15 15:42:09 +08:00 | `57676c037c4874226cea42b9cb2995e3858707fb` | `57676c037c4874226cea42b9cb2995e3858707fb` |
| 12 | F4 M2 repair | 2026-10-15 15:43:17 +08:00 | `7df8c7819673e815b765cfaa760baad793e1e823` | `7df8c7819673e815b765cfaa760baad793e1e823` |
| 13 | F6 | 2026-10-15 16:13:48 +08:00 | `1b0ecec92734c424f317c1dc7f2c98b7ee7edc55` | `1b0ecec92734c424f317c1dc7f2c98b7ee7edc55` |
| 14 | F7 | 2026-10-15 16:13:48 +08:00 | `038e811d9ff26d63e3abe9ac0acdba959e43f1c2` | `038e811d9ff26d63e3abe9ac0acdba959e43f1c2` |
| 15 | F10 | 2026-10-15 16:13:48 +08:00 | `508952dd7f6b9508288195fc5ce86931ce3ce7ad` | `508952dd7f6b9508288195fc5ce86931ce3ce7ad` |
| 16 | F9 | 2026-10-15 16:13:48 +08:00 | `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8` | `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8` |
| 17 | A1 | 2026-10-15 17:38:45 +08:00 | `e3e12d98627acd15323c3f2803378d90f1d1aeaf` | `e3e12d98627acd15323c3f2803378d90f1d1aeaf` |
| 18 | C1 | 2026-10-15 18:04:38 +08:00 | `8b5db203f88ff3e24223f6a53f671c693dc61ed9` | `8b5db203f88ff3e24223f6a53f671c693dc61ed9` |
| 19 | Wave 4 app-owned AntD deprecations | 2026-10-16 08:25:11 +08:00 | `48e8ca9575cb1b98bd27757d7382e205dcdc1b19` | `48e8ca9575cb1b98bd27757d7382e205dcdc1b19` |
| 20 | Sidebar interaction visual polish | 2026-10-16 11:18:37 +08:00 | `f6530ee342cab87f98e913ef1e3a87dae5061e4e` | `f6530ee342cab87f98e913ef1e3a87dae5061e4e` |
| 21 | SettingsCenter active-nav contrast | 2026-10-16 12:01:02 +08:00 | `85c44a633cd70dec15c56b3fc9d46fb8e88ae61c` | `85c44a633cd70dec15c56b3fc9d46fb8e88ae61c` |
| 22 | Cron provider/model mouse selection | 2026-10-16 13:24:32 +08:00 | `0f909f459061c5de3af72269eb8908201a9e9b07` | `0f909f459061c5de3af72269eb8908201a9e9b07` |
| 23 | Cron DurationWheel overflow | 2026-10-16 13:44:57 +08:00 | `000bc87af6471970e5223b413c3694037b0bdf3a` | `000bc87af6471970e5223b413c3694037b0bdf3a` |
| 24 | Sidebar tooltip pointer | 2026-10-16 14:04:57 +08:00 | `79c4179ba75ae494d0ef519bb3e62f525092f057` | `79c4179ba75ae494d0ef519bb3e62f525092f057` |
| 25 | Imports scanning state | 2026-10-16 14:36:38 +08:00 | `0359036ba3bad3f67d186480b053ed8fe62bd1e8` | `0359036ba3bad3f67d186480b053ed8fe62bd1e8` |
| 26 | Settings search mobile polish | 2026-10-16 15:29:12 +08:00 | `d4cc1cf3f5b07ce2b8b9a2754e6b62c29c5ce257` | `d4cc1cf3f5b07ce2b8b9a2754e6b62c29c5ce257` |
| 27 | Token Usage mobile range | 2026-10-16 16:01:46 +08:00 | `5f9eea427f096279a8b79895ad636ab5f3321baf` | `5f9eea427f096279a8b79895ad636ab5f3321baf` |
| 28 | ACP canonical route | 2026-10-16 16:06:11 +08:00 | `40193ee5bc10a5d2b59f99503a1e0deeba08f3cc` | `40193ee5bc10a5d2b59f99503a1e0deeba08f3cc` |
| 29 | Security option deduplication | 2026-10-16 16:15:06 +08:00 | `b5e6d20dc0451c9f9878b5de625cad93ec36c4ef` | `b5e6d20dc0451c9f9878b5de625cad93ec36c4ef` |
| 30 | Sessions tablet layout | 2026-10-16 18:05:13 +08:00 | `1ff5b3a049a5635ec629f1bb9adbe6159eab713b` | `1ff5b3a049a5635ec629f1bb9adbe6159eab713b` |
| 31 | Inbox tablet toolbar | 2026-10-16 18:54:37 +08:00 | `b2e5843f4bffeb8cdeba7b8c1c6dc501b1fc2dde` | `b2e5843f4bffeb8cdeba7b8c1c6dc501b1fc2dde` |
| 32 | Skills tag-filter escape | 2026-10-17 19:04:07 +08:00 | `1b00f3d3fcb1fdb89d6954c210b05c41c907a504` | `1b00f3d3fcb1fdb89d6954c210b05c41c907a504` |
| 33 | Settings responsive coverage | 2026-10-19 08:26:46 +08:00 | `d9eb1a1bc25739aa8476c9d2187bc8ef97941f9c` | `d9eb1a1bc25739aa8476c9d2187bc8ef97941f9c` |
| 34 | Chat history recovery | 2026-10-19 09:33:30 +08:00 | `31d0c486a581691c274f5e4c0a877bd54b8b9ab6` | `31d0c486a581691c274f5e4c0a877bd54b8b9ab6` |
| 35 | Sessions recovery states | 2026-10-19 09:45:20 +08:00 | `fe64a939f9f183aeaf718cbe7ce86fc7f966fac2` | `fe64a939f9f183aeaf718cbe7ce86fc7f966fac2` |
| 36 | ACP load guards | 2026-10-19 09:52:39 +08:00 | `a09c62efe8077a6e43fa9a42e401abc7eb6984f3` | `a09c62efe8077a6e43fa9a42e401abc7eb6984f3` |
| 37 | Heartbeat load guards | 2026-10-19 10:04:16 +08:00 | `d13f2df00917653fbbfa78b53f0f50d01553c6a0` | `d13f2df00917653fbbfa78b53f0f50d01553c6a0` |
| 38 | Voice load guards | 2026-10-19 10:14:06 +08:00 | `37f9acadc50e72d346ba6cb799a8279ef75daac5` | `37f9acadc50e72d346ba6cb799a8279ef75daac5` |
| 39 | Imports mobile gutter | 2026-10-19 10:26:33 +08:00 | `844f56acc469d6048775ed7090be7693b4a1b989` | `844f56acc469d6048775ed7090be7693b4a1b989` |
| 40 | Files mobile workspace | 2026-10-19 10:34:23 +08:00 | `e810241e28a6ce4834bd76d048b477a4c7a2e33c` | `e810241e28a6ce4834bd76d048b477a4c7a2e33c` |
| 41 | Inbox recovery states | 2026-10-19 10:44:40 +08:00 | `76e4e595c91c8f9c6685dac2e3476291b51eae1e` | `76e4e595c91c8f9c6685dac2e3476291b51eae1e` |
| 42 | Tools recovery states | 2026-10-19 10:54:28 +08:00 | `99ab3700bf3e313c3edd46804d01f23d041d4a2a` | `99ab3700bf3e313c3edd46804d01f23d041d4a2a` |
| 43 | Imports detection recovery | 2026-10-19 10:58:54 +08:00 | `e1816583d39e5214a3a3df5ce98db36fb3c857d9` | `e1816583d39e5214a3a3df5ce98db36fb3c857d9` |
| 44 | Backups recovery states | 2026-10-19 11:04:04 +08:00 | `b7c8ff96d551965a01d86337ab78d0d743e4cd1a` | `b7c8ff96d551965a01d86337ab78d0d743e4cd1a` |
| 45 | MCP recovery guards | 2026-10-19 11:10:23 +08:00 | `bd6a46b316df93b5150a6d81788c37b67bc33ff7` | `bd6a46b316df93b5150a6d81788c37b67bc33ff7` |
| 46 | Skills ownership guards | 2026-10-19 11:46:51 +08:00 | `d0fb040c6cb9e76814f378f320bc3b18fcd702ac` | `d0fb040c6cb9e76814f378f320bc3b18fcd702ac` |
| 47 | Channels ownership guards | 2026-10-19 11:52:42 +08:00 | `cf088ce570ae227e00eb5f4b7a84674a45b2620b` | `cf088ce570ae227e00eb5f4b7a84674a45b2620b` |
| 48 | Security rule-modal selector width | 2026-10-19 12:42:08 +08:00 | `0362e7a5e0fb076a361d5b15c3ec936af19bd486` | `0362e7a5e0fb076a361d5b15c3ec936af19bd486` |
| 49 | Debug intermediate-width toolbar | 2026-10-19 12:53:13 +08:00 | `6179f8dea0c34d1ff6ee6aae123cc1f4529850a5` | `6179f8dea0c34d1ff6ee6aae123cc1f4529850a5` |

Sequences 1–16 occurred while the branch was named
`feat/console-uiux-wave1`. The same local branch is now named
`feat/console-uiux-refactor`; later integration events use the current name and
commit history was not rewritten.

## Rejected candidates

| Candidate | Decision | Evidence | Reopen condition |
|---|---|---|---|
| `chat-cached-session-transition-consistency` | `REJECTED / NO CODE TASK`; not a Minor, Finding, or backlog item | 12/12 mouse samples and two rapid switches; wrong-identity interactive window median/p95 0/0ms; zero wrong Composer pointer hits; old surface synchronously `hidden + inert` at selected/title switch | A sample simultaneously shows target URL and selected row, old message identity, visible/non-inert surface, enabled Composer, and a real pointer hit |

Evidence directory: `/tmp/qwenpaw-chat-cache-consistency-48e8ca957/`.
`MANIFEST.sha256` hash:
`1a21d99266fabf50724428b290016ea630d25754d9543084e585b48ae2f95444`;
the full checksum list passed.

## Residual enhancements and unavailable validation

| Related scope | Classification | State | Boundary |
|---|---|---|---|
| F6 | Residual performance risk | `DEFERRED TO SEPARATE REFACTOR` | Budgeted values still format synchronously on the main thread; current limits are 100,000 characters, 2,000 nodes, and 100 levels |
| F7 | Runtime validation follow-up | Wave 3 package A completed; evidence accepted | Chrome 146 Playwright pointer/touch simulation returned a passing 390/480/768 × light/dark core matrix; this is not physical-device evidence |
| F9 | Enhancement | Not part of closed Finding | Existing mouse/touch DnD was preserved; keyboard drag-and-drop was not introduced |
| F10 | Enhancement | Wave 3 package B deferred/design-only | APG typeahead was explicitly outside Wave 2 scope; implementation is not approved |
| F10 | Residual performance follow-up | C1 `CLOSED`; remaining work `DEFERRED TO SEPARATE REFACTOR` | Full-tree React work is the high-confidence dominant class; exact per-component share remains medium confidence |
| Wave 4 warnings | Governance / compatibility debt | App-owned Ant Design line `CLOSED`; no formal P1/P2 | Post-merge matrix cleared W2/W5/W6, `destroyOnClose`, and `useForm`; W1/W3 remain non-blocking vendor debt; Chat `findDOMNode` is `UNVERIFIED` non-target observation; no task derivation |
| SettingsCenter active navigation | Closed visual repair | `CLOSED / APPROVE / PASS` at `85c44a633` | Real element at 14px/500 measured 4.746557 light and 8.298496 dark; cascade 1/1, token 3/3, ESLint, Prettier, and diff-check passed |
| Round 5 scoped inventory | Page-level double gate | `CLOSED`; 19/19 scoped pages | Candidate 0, in progress 0, U-only page 0, not inspected 0; Models scope-out |
| Market | Read-only closure | `CLOSED` for browse boundary | Actual browser browse/search/filter/internal detail passed; install/update/uninstall/publish/external navigation and remote effects remain `U` |
| Dangerous or external mutations | Retained validation boundary | `U`; not PASS | Chat send/attachment/Stop, Sessions writes, Inbox writes, Files upload/UI Git, Imports final lifecycle, Skills install/import/delete, ACP runner, Backups jobs, Voice provider/API, Security persistence/scanning, and production Debug content remain scoped as recorded |
| Stability and recovery | Next program | `NOT STARTED / SEPARATE HANDOFF` | Requires separately authorized scope, observability, recovery contracts, and regression plan |
| Performance | Next program | `NOT STARTED / SEPARATE HANDOFF` | Requires separately authorized budgets, datasets, measurements, and regression plan |
| Audit environment | Unavailable | Open roadmap item | True touch hardware, VoiceOver/NVDA, Hub mode, Desktop OS/PawApp samples, and production-like tracing were unavailable or outside scope |
| Information architecture | Design roadmap | Not implemented as part of F1–F12 | Canonical URLs and six-domain navigation remain separate product/design decisions |

Residual rows do not reopen F1–F12 unless new evidence proves that an accepted
defect contract is again violated.
