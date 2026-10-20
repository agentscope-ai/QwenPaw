# Console UI/UX Refactor Plan

## Roadmap

The roadmap serves the complete Console UI/UX product outcome, not only the
Finding ledger. Validation-first is the admission gate for a defect, not the
definition of refactor completion.

| Wave | Scope | Status | Base | Final / target |
|---|---|---|---|---|
| 1 | F1, F2, F3, F4, F5, F8, F11, F12 | `CLOSED` | `c7702cc617690f1d0cd0318827c9aa635b3da3a8` | `7df8c7819673e815b765cfaa760baad793e1e823` |
| 2 | F6, F7, F9, F10 | `CLOSED` | `7df8c7819673e815b765cfaa760baad793e1e823` | `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8` |
| 3 | Stabilization validation and accepted repairs | `CLOSED` | `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8` | `8b5db203f88ff3e24223f6a53f671c693dc61ed9` |
| 4 | Warning governance and approved app-owned Ant Design repairs | `APP-OWNED LINE CLOSED` | `8b5db203f88ff3e24223f6a53f671c693dc61ed9` | `48e8ca9575cb1b98bd27757d7382e205dcdc1b19` |

Wave 3's approved stabilization scope is `CLOSED`. A/C evidence collection is
complete and read-only; A1 and C1 passed integration validation and independent
`APPROVE`. Deferred enhancements and the long-term roadmap remain separate.

Wave 4 warning validation and W1/W3 attribution are complete. The approved
app-owned W2/W5/W6 and `destroyOnClose` repairs passed independent `APPROVE`
and integration validation at `48e8ca9575cb1b98bd27757d7382e205dcdc1b19`.
Remaining warning debt is explicitly outside that repair scope.

## Post-Wave vertical package ledger

| Package | State | Base → task HEAD → integration HEAD | Evidence boundary |
|---|---|---|---|
| Sidebar interaction visual polish | `CLOSED / APPROVE / PASS` | `48e8ca9575` → `0e59e784b` → `f6530ee342` | 5 test files / 73 tests; ESLint 0 errors with 2 pre-existing Hook warnings; Prettier/diff-check passed; light selected/hover contrast 4.703/4.621, dark 8.298/7.230 |
| SettingsCenter active-nav contrast | `CLOSED / APPROVE / PASS` | `f6530ee342` → `ec65049475` → `85c44a633` | Cascade 1/1 and token 3/3; ESLint, Prettier, and diff-check passed; 14px/500 runtime contrast 4.746557 light and 8.298496 dark |
| Cron provider/model mouse selection | `CLOSED / APPROVE / PASS` | `85c44a633` → `892c989311` → `0f909f459` | Two files; real AntD mouse regression, independent review, and independent validation passed |

The Sidebar package changed seven Sidebar/layout/token source and test files.
Merge commit `f6530ee342cab87f98e913ef1e3a87dae5061e4e`
(`merge(console): integrate sidebar interaction polish`) has parents
`48e8ca9575cb1b98bd27757d7382e205dcdc1b19` and
`0e59e784bdb785febf440d3b5d11fe7361549286`. No package, lock, or
documentation file entered the merge. Task branch
`codex/console-uiux-sidebar-interaction-visual-polish` and worktree
`/Users/mazhijian/.codex/worktrees/console-uiux-sidebar-interaction-visual-polish/QwenPawCodex`
remain retained; no push, PR, or cleanup occurred.

SettingsCenter active-navigation contrast was a separate pre-existing candidate:
base and Sidebar head both measured 4.2089367:1 and the production-style
SHA-256 was unchanged, so it was not caused by or blocking the Sidebar package.
The separate two-file repair used task branch
`codex/console-uiux-settingscenter-nav-contrast`, task HEAD `ec65049475`, and
merged at `85c44a633`, whose parents are `f6530ee342` and `ec65049475`.
Runtime verification of the real element at 14px/500 measured 4.746557 in light
mode and 8.298496 in dark mode.

The Chat candidate `chat-cached-session-transition-consistency` is `REJECTED /
NO CODE TASK`. Twelve mouse samples and two rapid switches found a 0/0ms
median/p95 wrong-identity interactive window and zero pointer hits on the wrong
Composer; the old surface became `hidden + inert` at the selected/title switch.
It is an excluded hypothesis, not a Minor, Finding, or backlog item.

## Wave 3 package decisions

| Package | Scope | Decision | Execution state |
|---|---|---|---|
| A `console-mobile-runtime-validation` | 390/480/768px × light/dark validation for Sessions, Chat/Sidebar, and Files | `APPROVED — READ-ONLY` | `COMPLETED / EVIDENCE_ACCEPTED`; thread `01a13eb8-034b-7290-aabc-c40a4f2b8a79`; worktree `/Users/mazhijian/.codex/worktrees/7a18/QwenPawCodex`; no integration event |
| B `console-filetree-typeahead` | Files tree APG typeahead design | `DEFERRED — DESIGN-ONLY` | C evidence is accepted; reconsider only after official APG contract recheck |
| C `console-expanded-tree-performance-audit` | Scale measurement for visible-tree scans and focus restoration | `APPROVED — READ-ONLY` | `COMPLETED / EVIDENCE_ACCEPTED`; thread `01a13eb7-e48e-7400-8e16-14c16a175ed9`; worktree `/Users/mazhijian/.codex/worktrees/deec/QwenPawCodex`; no integration event |
| D `console-uiux-regression-baseline` | Documentation-owned validation matrix | `APPROVED — DOCUMENTATION` | Baseline defined below; accepted A/C evidence incorporated |

Wave 3 is `CLOSED` for its approved stabilization scope. Read-only validation
and documentation approval do not authorize further implementation. No package
may modify business code, package scripts, CI, dependencies, lockfiles, or copy
tests into a new framework without new commander authorization.

## Dependencies and conflict boundaries

- Package A may validate F7 and F9 but must not silently extend into feature
  implementation. A reproduced regression requires a separately scoped repair.
- Package B is not an approved implementation. Its proposed contract covers
  visible items in DOM order, prefix buffering, repeated-character cycling,
  wrap, focus-only movement, modifier/input/IME exclusion, and omission of
  collapsed nodes. The W3C APG Tree View URL returned HTTP 429 during the
  design check, so the official contract remains `待验证假设` until rechecked.
- Package C completed as read-only measurement. The current design-lead
  conversation completed C1 diagnosis and repair design without code changes.
  The authorized read-only segmented measurement completed in the current
  design-lead conversation. It excludes A/B and recommends C; the commander
  approved the separate coding gate for option C only.
  Virtualization remains unauthorized. Do not create a Sub-agent.
- Package D changes documentation only. CI or script changes require separate
  commander authorization.
- Shared files, global layout, registry changes, or overlapping test fixtures
  require an explicit ownership decision before worktrees are created.

## Regression baseline (Package D)

### Fast gate

Use only the entries relevant to the changed scope. Run from `console/` with
the repository's existing local binaries; do not add package scripts.

| Contract | Existing targeted-test entry |
|---|---|
| F1 agent-scoped tools | `src/api/modules/tools.test.ts`, `src/pages/Agent/Tools/useTools.test.ts` |
| F2 approval queue | `src/pages/Chat/components/ApprovalQueueOverlay.test.tsx` |
| F4 composer actions | `src/pages/Chat/components/ComposerAccessibilityLabels.test.tsx`, `src/pages/Chat/components/WhisperSpeechButton/index.test.tsx`, `src/pages/Chat/sdkHostIntegration.test.tsx`, `src/pages/Chat/index.module.test.ts` |
| F5 polling ownership | `src/components/ConsolePollService/index.test.tsx`, `src/os/DesktopPollingServices.test.tsx`, `src/os/useOsNotifyPoller.test.tsx`, `src/layouts/Sidebar.render.test.tsx` |
| F6 bounded Raw display | `src/components/Chat/ToolCards/shared/ToolCardShell.test.tsx`, `src/components/Chat/ToolCards/shared/rawToolDisplay.test.ts` |
| F7 mobile Sessions | `src/pages/Control/Sessions/index.test.tsx` |
| F8 semantic queue tokens | `src/pages/Chat/components/MessageQueuePanel.test.tsx`, `src/pages/Chat/components/BackgroundTaskPanel.test.tsx` |
| F9 Sidebar semantics | `src/components/SessionGroupDnd/SessionGroupDnd.test.tsx`, `src/components/SessionItem/SessionItem.test.tsx`, `src/layouts/MainLayout/MainLayout.accessibility.test.tsx` |
| F10 Files tree | `src/features/files-workspace/FilesNavigator.interaction.test.tsx` |
| F11 language name | `src/pages/SettingsCenter/GeneralSettings.language.test.tsx` |
| F12 provider actions | `src/pages/Settings/Models/components/cards/ProviderCloseButton.test.tsx` |

F3 remains browser-geometry coverage at 768/769/820/900/901px; there is no
dedicated targeted-test entry evidenced in the closed-Wave commit map.

Command form:

```text
./node_modules/.bin/vitest run <targeted test files>
./node_modules/.bin/eslint <changed TS/TSX files>
./node_modules/.bin/prettier --check <changed supported files>
git diff --check <base>..<head>
git status --short
```

### Extended gate

- Package A viewport/theme matrix at 390/480/768px and light/dark.
- Sessions: no horizontal overflow; initial 20 rows; load to 40; filter resets
  the visible window.
- Chat/Sidebar: skip link; row plus menu as two stops; no nested interactive
  nodes.
- Files: one tree Tab stop; Arrow keys, Home, End, and Enter.
- Pointer/touch automation must be labeled simulation, never true-device pass.
- Package C measures 100/500/2,000 visible nodes and conditionally 10,000,
  separating cold/warm runs and reporting median/p95, Long Tasks, and DOM count.
  Heap is a proxy only. A repeated interaction or Long Task above 50ms is a
  formal performance-problem candidate, not automatic proof of root cause.
- F5 extended coverage includes foreground/background recovery and single
  in-flight behavior.

Package A used route mocks or an isolated context and created no real
business data. Existing E2E initialization can create repository-local report
directories, so outputs must be isolated (for example under `/tmp`) or run in
its isolated worktree. A used an independent BrowserContext, wrote evidence
under `/tmp`, and reported resource release. C then used the exclusive browser
and CPU measurement window and also reported clean resource release.

### Package A accepted evidence

- Evidence directory: `/tmp/qwenpaw-console-mobile-validation.Ia4heA/`.
- Environment: Chrome `146.0.7680.80`; six 390/480/768px × light/dark cases;
  independent BrowserContext per case; mocked routes and no real business data.
- Method boundary: Playwright pointer/touch simulation, not a physical-device
  pass.
- Returned result: the six-cell core matrix ran successfully; failed requests,
  HTTP responses at or above 400, and business console errors were reported as
  zero. Development-mode warnings remain separately classified.
- At discovery, formal Finding A1 was `Minor / OPEN / browser-runtime`: at
  768px in `/files`,
  the `Knowledge Base` source tab was initially 9.9201% visible, became 100%
  visible after 108px horizontal scrolling, and remained selectable. Light and
  dark reproduced it; 390/480px in both themes rendered the tab 100% visible.
  No historical comparison exists, so this is not described as a regression.
- Resource handoff: A reported browser/Vite/validation subprocess cleanup; port
  55176 had no listener during documentation reconciliation. C subsequently
  completed formal timing and released its resources.
- Evidence integrity:
  - `matrix-results.json` SHA-256
    `12919b60ab98ce108956fe1b4ea9c18475e36023bd2523bcda962a13d304128d`.
  - `files-tab-visibility.json` SHA-256
    `244ea821b5edd5d179cced21b014bdde0c06051cada74e922e92f15ac6d18814`.

#### A1 repair boundary

- Planned task name: `console-files-tablet-tabs`.
- Execution: `CLOSED`; thread
  `01a13ee7-f13a-76e2-9dff-2f165c4b36a1`; worktree
  `/Users/mazhijian/.codex/worktrees/2a4a/QwenPawCodex`.
- Creation gate: satisfied after C evidence acceptance and resource release.
- Creation base: the latest verified `feat/console-uiux-refactor` HEAD at task
  creation time, recorded as
  `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8`.
- File boundary: `FilesWorkspace.module.less`; touch `FilesNavigator.tsx`, the
  Files page, or direct responsive/browser tests only when the failing
  regression requires the minimum additional surface.
- Scope: only the 721–768px Files navigator/source-tab layout. Do not change
  tree keyboard behavior, tree performance, or typeahead.
- Minimum repair: keep all four source tabs initially recognizable, or provide
  clear overflow/automatic-visibility behavior, without changing Files data or
  tree logic.
- Preferred direction: align the Files mobile-layout boundary with the shared
  768px breakpoint and reuse the existing `workspaceEmpty` full-width navigator
  semantics where applicable.
- Regression boundary: at 720/721/767/768px × light/dark, assert all four tabs
  are initially and after-selection fully visible, selected state is correct,
  and neither the document nor tablist overflows. At 769px, preserve the desktop
  horizontal-scroll layout; require the selected tab to become fully visible
  after scroll/click and keep document overflow false.
- Source commit: `7d7e24251d0bff46c0e6f06d65892cf8f65bae68`.
- Integration: cherry-picked without an extra merge commit at
  `2026-10-15 17:38:45 +08:00`; integration commit and `integration_head` are
  both `e3e12d98627acd15323c3f2803378d90f1d1aeaf`.
- Integrated range:
  `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8..e3e12d98627acd15323c3f2803378d90f1d1aeaf`.
- Long-lived-branch targeted validation was reported passing: three Vitest
  files / 31 tests, ESLint, Prettier check, and `git diff --check`.
- Browser evidence: Chrome 146, headless touch simulation with route mocks.
  The 720/721/767/768px light/dark cases met the mobile contract. The 769px
  cases preserved desktop horizontal scrolling: `Knowledge Base` was initially
  0% visible and became 100% visible and selected after scroll/click, with no
  document overflow. Evidence file
  `/tmp/qwenpaw-a1-integration-results.json`; SHA-256
  `0ac6955e30da6f3fbe61934bcd31544099976b2a7ad192bcb702cef38434eff9`.
- Independent review: thread `01a13e66-462a-7292-a7fe-aafb5d3662d8`
  returned `APPROVE` for the fixed range with no Critical, Important, or Minor
  Issues. It independently ran 3 files / 31 tests, ESLint, Prettier,
  `git diff --check`, and current-theme 768/769px browser geometry checks.
- Closure: all A1 integration, validation, and review gates are satisfied at
  `e3e12d98627acd15323c3f2803378d90f1d1aeaf`; A1 is `CLOSED`.
- Review boundary: 721–768px non-empty preview/workspace drawer states were not
  independently exercised one by one. Static review found no contract violation
  or actual failure evidence. macOS received runtime sampling; Linux/Windows are
  CSS-only static low-risk conclusions.

### Package C accepted evidence

- Evidence directory: `/tmp/qwenpaw-tree-perf.WejBM5/`.
- Environment: Apple M4, 16 GiB RAM, macOS 26.3.2, Playwright 1.60.0,
  Chrome 146.0.7680.80, headless with `document.visibilityState=visible`;
  workspace API route mocks and no business-data mutations.
- C1 was originally recorded as `P2 / OPEN / performance-data-confirmed`:
  end-to-end tree
  refresh, React commit, and active-focus recovery measured median/p95 19.05 /
  33.3ms at 100 visible nodes, 62.3 / 66.4ms at 500, and 242.6 / 275.1ms at
  2,000. All ten 500- and 2,000-node samples exceeded 50ms; 2,000 nodes also
  produced eight 50–54ms Long Tasks.
- Conditional 10,000-node data measured 1402.3 / 1631.0ms and 25 Long Tasks,
  maximum 358ms. It is scale evidence, not a required baseline tier.
- Reachability: normal 200-entry pagination can produce 500/2,000 visible
  treeitems. Refresh preserves loaded pages, replaces only the active path, and
  keeps the other visible keys stable.
- Correctness boundary: focus recovery remained correct and no data loss was
  observed. Four keyboard operations stayed at p95 1.2–1.4ms for 2,000 nodes
  and 4.6–6.6ms for the conditional 10,000-node run, so keyboard scanning is
  not a confirmed performance defect.
- Causality boundary: `FilesNavigator.tsx:930-949` performs a full
  `querySelectorAll` plus active-item scan in a `MutationObserver`, but the
  original evidence confirmed only combined end-to-end latency. The later
  segmented measurement rejects the observer scan as the primary cause and
  identifies unnecessary full-tree React work as the dominant class. Exact
  per-component attribution remains medium confidence. Vite/dev startup time
  and Chromium heap proxy data are non-findings.
- Design status: the current design-lead conversation completed the C1
  diagnosis and repair design and the authorized read-only `/tmp` segmented
  measurement without a Sub-agent or code changes. Measurement is complete;
  option C implementation and local validation are complete at
  `8b5db203f88ff3e24223f6a53f671c693dc61ed9`; independent review returned
  `APPROVE`.
- Required regression contract: the same 200-entry fixture at 100/500/2,000
  visible nodes, 100% focus recovery, refresh p95 below 50ms, no refresh Long
  Task, and unchanged keyboard behavior/single Tab stop.
- Evidence integrity:
  - `report.md` SHA-256
    `7045e251f1073f0af506adb5a9ea5a37e93d53c454a07577be554a9722334bf7`.
  - `results-minimal-churn.json` SHA-256
    `86d0680c87ce72b6842f95bf449eca685e5f1590094efca56950ede1f6b88f7b`.
  - `results-10000.json` SHA-256
    `adada9e30c2e432a6f5b3e48cdd65d9df2f61be4eb06e2410f127691b78480f1`.
  - `measure_tree.py` SHA-256
    `f685916bf1dfc448c64e7114593fc80b4cfa4ef0c2951a7684ce4d2231dfe3c5`.
- Package C completed cleanly, released its resources, and produced no commit;
  its integration status is `no merge applicable`.

### C1 diagnosis and repair design

#### Confirmed data flow and causality boundary

- `refreshCurrent` only increments `directoryRevision`
  (`FilesNavigator.tsx:853-863`).
- On revision change, `useDirectoryListing.ts:38-80` reloads the number of pages
  recorded in `previous.pages` and calls `setListing` once with the rebuilt
  entries.
- Root-entry replacement causes `FilesNavigator` to map all `displayEntries`;
  each treeitem's `tabIndex` depends on `activeTreeItemPath` or `defaultPath`.
- After commit, the subtree `MutationObserver` queries all treeitems and scans
  for the active path. If absent, it selects the first item and causes a second
  render.
- The confirmed defect is total client recovery latency, not a unique observer
  root cause. React element creation/reconciliation, DOM commit/layout, observer
  delivery, and the second active-path render may all contribute. Keyboard code
  performs a similar full query plus `indexOf` yet stays below 7ms at 10,000
  nodes, so keyboard changes are not justified by current evidence.

#### Completed read-only segmented measurement

The commander authorized this stage for direct execution in the current
design-lead conversation without a Sub-agent. It completed with evidence only
under `/tmp`; it changed no tracked source or documentation and created no
commit, push, or PR. It used fixed baseline
`feat/console-uiux-refactor@e3e12d98627acd15323c3f2803378d90f1d1aeaf`, the
200-entry pagination fixture, 100/500/2,000 visible nodes, and 12 valid samples
per tier on Chrome 146 / Apple M4. Invalid samples were zero. Each refresh
replaced exactly one active path while keeping the other N−1 keys stable.

| Marker | Meaning |
|---|---|
| T0 | Refresh click/dispatch |
| T1 / T2 | First request start / final page route-fulfill completion |
| T3 / T4 | First / last tree `childList` mutation; React DOM-commit window proxy |
| T5 | Unique `tabIndex=0` restored and active path equals the first item |

Before document startup, wrap the `MutationObserver` constructor only to record
callback begin/end, delivery count, and record count while preserving original
semantics. Capture Chrome `devtools.timeline`, `PerformanceObserver` Long Tasks,
and `FunctionCall`, `UpdateLayoutTree`, `Layout`, and `Paint` events.

Derived metrics are `T2−T0` network/reload, `T3−T2` state-to-first-mutation,
`T4−T3` DOM-commit proxy, summed observer callback duration, `T5−T4` recovery
tail, and `T5−T2` client total. Report median, p95, and percentage contribution
per tier. Network/reload is excluded from the frontend repair budget. T3/T4
must remain labeled a proxy; if trace attribution is insufficient, request
minimal temporary instrumentation instead of claiming a root cause.
The 50ms value is the current acceptance target, not a proven product contract.

| Visible nodes | Client p50 / p95 | Pre-observer p50 / p95 | Observer p50 / p95 | Tail p50 / p95 | Long Tasks |
|---:|---:|---:|---:|---:|---:|
| 100 | 11.1 / 19.2ms | 3.75 / 5.0ms | 0.0 / 0.1ms | 6.7 / 15.1ms | 0 |
| 500 | 30.55 / 35.3ms | 13.7 / 14.5ms | 0.2 / 0.3ms | 16.85 / 20.5ms | 0 |
| 2,000 | 109.9 / 112.3ms | 49.4 / 51.0ms | 0.75 / 1.2ms | 59.05 / 60.6ms | 15 across 12 samples |

At 2,000 nodes, median client-recovery shares were 45.19% before observer
delivery, 0.68% inside the observer callback, and 54.12% after it. Network was
separate at 94.4ms median / 116.5ms p95. A DOM-only probe measured the full
missing-path query/scan at 0.5ms p95. Therefore the observer primary-cause
hypothesis is rejected. Unnecessary full-tree React work on both sides of the
request is the dominant client-side class with high confidence; its exact
per-component split remains medium confidence because React Profiler was not
injected into the production bundle.

Evidence integrity:

- `/tmp/qwenpaw-c1-segmented.DMZ8kc/report.md` SHA-256
  `082ebaa2002f1befe21bd6bf9ffbc337902fd0a6ada14d0463c79064e350c8c0`;
- `results.json` SHA-256
  `2ff838108b6fa30c5f95066df343dc0a4af2eb5314947a47383fe49c090d01ff`;
- `measure_segmented.py` SHA-256
  `b2aeb87d5b71d21ce9eca4f44a200fcd37ae335dbe54b80d8f0f7246ff44aac8`;
- `dom-query-probe.json` SHA-256
  `c9d529abf942645ac1dbceeebdad90a7f81c16348b18b3dcb0b4c67d0976104b`.

#### Repair decision tree

| Option | Minimum design | Selection gate | Primary risk |
|---|---|---|---|
| A | Coalesce observer recovery per commit; use current-path targeted lookup plus first-item fallback | Observer callback p95 ≥15ms or ≥25% of client total, with more than one delivery | Selector escaping, scheduling, or transient zero/two Tab stops; recovery must complete before paint |
| B | Callback-ref registry mapping visible path to element and visible order | Observer scan dominates, but A's targeted lookup is insufficient; PoC must beat A | N ref mount/unmount operations, nested-order maintenance, DnD/Profile/Memory complexity |
| C | Reuse shallow-equal N−1 entries by path and memoize rows with explicit active/selected booleans | DOM commit/reconciliation dominates and observer is below 25% | Stale fields/props and nested expansion or selection regressions |

The completed measurement excludes A because the callback is below 1% of median
client recovery and has one delivery per sample. It excludes B because it would
replace a sub-millisecond scan with lifecycle bookkeeping without addressing the
hotspot. C was selected: reuse fully equal entries, memoize workspace leaf rows,
and stabilize the directory toggle callback. The implemented minimum deliberately
does not add a `DirectoryNode` comparator. Virtualization, keyboard handler
changes, and typeahead remain unauthorized.

#### Authorized implementation and closure gate

Hotspot contribution, root-cause confidence, and the A/B/C selection have been
reported. The commander authorized option C for direct implementation in the
current design-lead conversation without a Sub-agent. The exact code boundary
is limited to four Files source/test files:

- `console/src/features/files-workspace/FilesNavigator.tsx`;
- `console/src/features/files-workspace/useDirectoryListing.ts`;
- `console/src/features/files-workspace/FilesNavigator.interaction.test.tsx`;
- `console/src/features/files-workspace/useDirectoryListing.test.tsx`;
- a browser performance harness under `/tmp`, never committed.

Do not touch `FilesWorkspace.module.less`, A1, global components, package or
lockfiles, keyboard semantics, typeahead, or virtualization. Acceptance requires
100/500/2,000-node runs with 100% recovery, client-total refresh p95 below 50ms,
zero refresh Long Tasks, one restored Tab stop, first-item fallback when the old
path disappears, unchanged Arrow/Home/End/Enter behavior, and no pagination,
request-order, retry, nested-expanded-refresh, or existing Files-test regression.
Use targeted Vitest, affected-file ESLint/Prettier, `git diff --check`, and same-
machine Chrome data. The 10,000-node tier is observation-only.

The one-commit rule is satisfied; diagnostic scripts remain in `/tmp`. The
commit landed directly on `feat/console-uiux-refactor`, the long-lived-branch
gate passed, and independent incremental review returned `APPROVE`. No push or
PR occurred. C1 is `CLOSED`; the rollback boundary is that single commit.

Implementation completed as the single commit
`8b5db203f88ff3e24223f6a53f671c693dc61ed9`
(`perf(console): reduce files tree refresh work`) directly on
`feat/console-uiux-refactor`, parented by
`e3e12d98627acd15323c3f2803378d90f1d1aeaf`. Only the four authorized Files
source/test files changed; docs, package files, and lockfiles were excluded.

The final implementation reuses entry identity only when all six
`DirectoryEntry` fields are equal; memoized `WorkspaceFileRow` covers root and
nested workspace leaves; and the directory toggle callback is stable. It does
not change observer behavior, keyboard semantics, ARIA, DOM structure, styling,
DnD, or protocols, and it does not implement A, B, virtualization, or a
`DirectoryNode` comparator.

Post-commit validation:

- focused Vitest: 2 files / 36 tests passed;
- ESLint, Prettier check, and `git diff --check`: passed;
- full 12-sample run: p95 20.2ms at 100, 24.6ms at 500, and 33.2ms at 2,000;
  all Long Task counts were zero, invalid samples were zero, Tab-stop recovery
  was 100%, and request counts were 1/3/10;
- the full 2,000-node control delta was +14.469%, above the reliability line and
  therefore not hidden or used alone;
- a 20+20 confirm run measured median/p95 13.7/28.1ms, zero Long Tasks, zero
  invalid samples, 20/20 recovery, ten requests, and −4.155% control delta;
  therefore the performance acceptance gate passed.

Post-commit evidence directory:
`/tmp/qwenpaw-c1-implementation-e3e12d9/`.

- `results-8b5db203f.json` SHA-256
  `00fcac4e6ccd0d1d8c61eea093689166cdb3527d1f856232431bf0e7f4215f25`;
- `results-8b5db203f-2000-confirm.json` SHA-256
  `848f064692bdd585f04b6c89f41fe6ce418f72c523464ad448cea9eaa8217842`;
- `evidence-binding.json` SHA-256
  `90006f4965ca6031ab5dcec26300a1d143731153ba3b231e8e2867c1dd094e10`;
- `validation-report.md` SHA-256
  `840bc58910f58a5a353d93133a5d39aa6133275e37b2fe8210157d4013bd3c9e`.

Fixed independent-review range:
`e3e12d98627acd15323c3f2803378d90f1d1aeaf..8b5db203f88ff3e24223f6a53f671c693dc61ed9`.
Reviewer thread `01a13e66-462a-7292-a7fe-aafb5d3662d8` returned `APPROVE` with
no Critical, Important, or Minor Issues. Its independent 2,000-node rerun had
10/10 valid samples, median/p95 13.8/19.4ms, zero T2–T5 Long Tasks, ten requests
per sample, one Tab stop and correct focus in 10/10 runs, and zero invalid
samples. The −38.368% instrumented/control delta exceeds the ±10% comparability
band and is recorded only as an instrumentation/control limitation, not a
product defect. Developer-side 20+20 confirmation remained reliable at −4.155%
delta, 28.1ms p95, 20/20 recovery, and zero Long Tasks. C1 is `CLOSED` at
`8b5db203f88ff3e24223f6a53f671c693dc61ed9`.

### Wave 4 warning-governance validation

Task `wave4-warning-governance-baseline` completed as validation-only/read-only
at `feat/console-uiux-refactor@8b5db203f`. Chrome 146 on macOS ran six routes
twice in fresh contexts at 1440×900/light, for 12 clean loads; `/tools` also had
two deterministic interactions. There were no mutation attempts, new
non-warning errors, uncaught exceptions, failed requests, or HTTP errors.

The [Wave 4 evidence record](waves/wave-4.md) contains exact owner, reason, and
expiry/removal conditions. Current results are W1 vendor-only/high (24), W2
`MainLayout` candidate/high (12), W3 dependency-design vendor debt/high (8), W4
`ChatActionGroup` ref-boundary candidate/high (2), W5 `AgentSelector`
candidate/high (12), and W6 `SessionsPage`/`ChannelCard` candidate/high (4).
Fresh-context target-hover evidence attributes W3 centrally to the
`@agentscope-ai/design` Button/Tooltip wrapper; business routes are consumers.

`destroyOnClose` was a separate ModelsPage candidate/high with two events.
Unconnected `useForm` is stale/not reproduced with zero events; that absence is
not proof of safety. No signal is allowlisted or promoted to a formal P1/P2
Finding. Historical and current counts are not treated as a delta because their
scenarios differ.

The follow-up vendor matrix found no published chat/design version or official
`main@64d95f2` snapshot with a complete W1/W3 fix. Design 2 beta only fixes the
IconButton ref and requires AntD 6. Current disposition is wait/retain vendor
debt. This Console UI/UX refactor abandons W1/W3 implementation: no upgrade,
`patch-package`, route-level workaround, broad suppression, or code task. A
future dependency program would require separate commander authorization and
must not be inferred from this record. GitHub REST 403 prevented non-main
history verification; exact official main was checked through Git ref plus
codeload, while non-main historical fixes remain Unverified.

#### Approved app-owned repair integration

The authorized repair task used base
`8b5db203f88ff3e24223f6a53f671c693dc61ed9`, task branch
`codex/console-uiux-w4-antd-deprecation-repair`, and task development HEAD
`286c724e8e2006592609a0fbc789eec462e4b1c0`. It migrated:

- W2: removed the unsupported `Spin tip` route fallback combination;
- W5: replaced AgentSelector `popupClassName` with
  `classNames.popup.root`;
- W6: replaced SessionsPage and ChannelCard `bodyStyle` with `styles.body`;
- the independent ModelsPage signal: replaced `destroyOnClose` with
  `destroyOnHidden`.

Independent review returned `APPROVE` with no Critical, Important, or Minor
Issues. Merge commit `48e8ca9575cb1b98bd27757d7382e205dcdc1b19` made
`TASK_DEV_HEAD` reachable from the long-lived branch. Post-merge validation
passed five test files / 40 tests, affected ten-file ESLint and Prettier checks,
and `git diff --check`. No package, lock, or documentation file entered the
code merge. The task branch and worktree remain retained; no push, PR, or
cleanup occurred.

Post-merge Chrome validation at `48e8ca9575` completed two fresh contexts on
each of six routes. W2, W5, W6, Models `destroyOnClose`, and disconnected
`useForm` were zero; page errors, failed requests, HTTP responses at or above
400, and mutation attempts were zero. This closes the scoped app-owned Ant
Design repair line.

W1=24 and W3=8 remain non-blocking vendor debt outside this Console UI/UX
implementation scope and do not derive repairs. Chat `findDOMNode`=2 is an
`UNVERIFIED` non-target observation: no pre-merge control or user-visible
failure proves a regression. It does not upgrade to a task. Any future W4
`findDOMNode`, `useForm`, or additional `bodyStyle` candidate first requires
evidence of user-visible failure and separate authorization. The runtime result
must not automatically create another AntD repair task.

Runtime evidence:
`/tmp/qwenpaw-wave4-postmerge-runtime-20261016-082932-48e8ca957/`;
`MANIFEST.sha256` SHA-256
`944611f681c04ec270f249d910df38f1322bd3883537908bfd1dff6063f7bb61`.
The manifest's full file checksum verification passed.

### Warning allowlist

- New errors: zero allowed.
- New warnings: zero allowed unless explicitly accepted before integration.
- An existing warning is allowed only with exact signature, owner, reason, and
  expiry date. A broad pattern or permanent waiver is invalid.
- A warning count is evidence only for the captured command/environment; it is
  not a product-wide pass.

### Evidence vocabulary

Every result records one claim status — `已复现`, `运行通过`, `静态确认`,
`性能数据确认`, `不可验证`, or `待验证假设` — plus its evidence method,
environment, commit SHA, command/scenario, and boundary. Planned checks must
not be written as results.

## Acceptance design requirements

Every authorized implementation package must define:

1. Exact `TASK_BASE_SHA`, dedicated task branch/worktree, and owned files.
2. User-visible contract and non-goals.
3. Targeted tests or a minimal reproducible measurement.
4. Browser/runtime checks where static tests cannot prove the contract.
5. Rollback boundary and residual risk.
6. One-purpose commit strategy.
7. Independent review scope and fixed `TASK_BASE_SHA..TASK_DEV_HEAD` range.

Each code-producing task starts from the exact current
`feat/console-uiux-refactor` HEAD on a dedicated task development branch in an
independent worktree. The primary workspace remains on the long-lived branch;
direct development there is prohibited. The plan does not require per-Wave Git
branches. Read-only tasks do not create a merge record.

### Code-producing task completion gate

A design-lead task that produces code is not complete merely because one child
worktree is clean or its tests pass. All of the following are required:

1. Record `TASK_BASE_SHA` from the exact current long-lived HEAD, create a
   dedicated task development branch and independent worktree, and record file
   ownership. The design lead may distribute mutually exclusive subtasks from
   that task baseline into parallel worktrees.
2. Integrate every accepted subtask and review-follow-up commit into the same
   task development branch, preserving one Finding per commit where practical.
3. Run combined scoped validation on the task development branch and freeze the
   independent review range as `TASK_BASE_SHA..TASK_DEV_HEAD`.
4. Keep all review fixes on that branch and repeat validation/review until the
   independent reviewer returns `APPROVE`; do not integrate earlier.
5. If `feat/console-uiux-refactor` advanced, synchronize the task branch and
   rerun scoped validation. A substantive synchronized diff requires a new
   independent review before integration.
6. Merge the approved task development branch into the long-lived branch, run
   the scoped integration regression, and record the integration commit,
   sequence/time, `integration_head`, and `TASK_DEV_HEAD` reachability.
7. Mark the task/Finding `CLOSED` only after the integration regression passes
   and evidence, residual risks, and the final `APPROVE` are recorded.

Every integration record includes `git branch --show-current`, `git rev-parse
HEAD`, and `git status --short` evidence. Documentation remains outside code
task commits unless the commander separately authorizes its incorporation.

An `APPROVE WITH FIXES` follow-up commit remains on the task development branch
and is subject to the same combined validation and independent review before
long-lived-branch integration.

Do not push, create a PR, delete a branch, or remove a worktree without separate
authorization. The commander authorizes and closes work; the design lead owns
design, decomposition, and integration; validator thread
`01a13f1a-c9e9-7002-852a-b4d6f1de5140` executes tests and captures raw
evidence; the independent reviewer issues the verdict; the documentation owner
maintains this SSOT. Every role reports completion, failure, blockers, or needed
decisions to the commander before ending its task.

Read-only tasks with no commit record `no merge applicable`. A and C currently
have that status. Their later repair tasks are tracked independently; in
particular, A1 passed this gate and is closed at
`e3e12d98627acd15323c3f2803378d90f1d1aeaf`.

No full `npm run build`, `npm run format`, or `npm run test` is permitted
without explicit user authorization. Targeted tests and checks remain allowed.

## Long-term route from the audit

The original audit proposed measurement and guardrails, surgical P1/P2 fixes,
shared components/token governance, information-architecture convergence, and
continuous performance/accessibility budgets. Wave 1 and Wave 2 closed the
formal F1–F12 defect set, but did not complete that broader roadmap.

### Closed page-program interaction priority

The completed Console UI/UX page program prioritized frequent desktop mouse
tasks. Its first-pass evidence covered:

- click target size, hit accuracy, and accidental activation;
- overlay/popover obstruction, click-through, stacking, and dismissal;
- actual dropdown/menu option selection and resulting business state;
- hover, pressed, loading, selected, and disabled feedback;
- residual UI or state after close/cancel;
- drag initiation/drop behavior and the resulting persisted or submitted
  business state.

Keyboard coverage is limited to the minimum regression gate already required by
existing contracts. Keyboard enhancements and keyboard drag-and-drop are not
priorities for that stage. This historical priority does not authorize another
page package; any later code change requires a separately authorized task and
the full branch, validation, and review lifecycle.

Current execution is `CLOSED` for the scoped Console UI/UX page program at
`feat/console-uiux-refactor@6179f8dea0c34d1ff6ee6aae123cc1f4529850a5`.
Round 5 accounts for 19/19 scoped pages: candidate 0, in progress 0, U-only
page 0, and not inspected 0. Models is explicitly scope-out. Push and PR remain
unauthorized.

### Evidence vocabulary for closeout

- `BROWSER PASS`: the named behavior was exercised in an actual browser with
  the stated input, viewport/theme, hit-testing, state, and side-effect bounds.
- `STATIC/TEST PASS`: source inspection or focused automated checks passed; it
  is not a browser claim.
- `U`: deliberately unexercised, unsafe, external, or not durably evidenced.
  `U` is never rewritten as `PASS`.
- Integration reachability proves delivery identity only. It does not broaden
  package-specific browser or test evidence.

### Round 4 merged-package ledger

Every candidate below is an ancestor of final integration `6179f8dea`. The
ledger records delivery identity; browser/static/test claims remain limited to
each package's Reviewer/Validator evidence.

| Package | Candidate → integration | Final gate |
|---|---|---|
| Cron DurationWheel | `d34465a049` → `000bc87af6` | `APPROVE / PASS / REACHABLE` |
| Sidebar tooltip pointer | `9d31b45deb` → `79c4179ba7` | `APPROVE / PASS / REACHABLE` |
| Imports scanning state | `d248cc3adb` → `0359036ba3` | `APPROVE / PASS / REACHABLE` |
| Settings search/mobile selector | `dfe943fbc9` → `d4cc1cf3f5` | `APPROVE / PASS / REACHABLE` |
| Token Usage mobile range | `13e7d78d90` → `5f9eea427f` | `APPROVE / PASS / REACHABLE` |
| ACP canonical route | `a872374bd4` → `40193ee5bc` | `APPROVE / PASS / REACHABLE` |
| Security option deduplication | `4958cf74a6` → `b5e6d20dc0` | `APPROVE / PASS / REACHABLE` |
| Sessions tablet layout | `4c14bfcff9` → `1ff5b3a049` | `APPROVE / PASS / REACHABLE` |
| Inbox tablet toolbar | `b8e29002c3` → `b2e5843f4b` | `APPROVE / PASS / REACHABLE` |
| Skills tag-filter escape | `e18b012e75` → `1b00f3d3fc` | `APPROVE / PASS / REACHABLE` |
| Settings responsive coverage | `674f78ef10` → `d9eb1a1bc2` | `STATIC/TEST PASS / REACHABLE` |
| Chat history recovery | `95b2a6c79c` → `31d0c486a5` | `APPROVE / PASS / REACHABLE` |
| Sessions recovery states | `d0d428d455` → `fe64a939f9` | `APPROVE / PASS / REACHABLE` |
| ACP load guards | `c674d6e587` → `a09c62efe8` | `APPROVE / PASS / REACHABLE` |
| Heartbeat load guards | `2866b86da2` → `d13f2df009` | `APPROVE / PASS / REACHABLE` |
| Voice load guards | `f86229d6d2` → `37f9acadc5` | `APPROVE / PASS / REACHABLE` |
| Imports mobile gutter | `e1b59c15e8` → `844f56acc4` | `APPROVE / PASS / REACHABLE` |
| Files mobile workspace | `e162fc2294` → `e810241e28` | `APPROVE / PASS / REACHABLE` |
| Inbox recovery states | `08dca18be0` → `76e4e595c9` | `APPROVE / PASS / REACHABLE` |
| Tools recovery states | `bee50a6ac5` → `99ab3700bf` | `APPROVE / PASS / REACHABLE` |
| Imports detection recovery | `76ed026bb8` → `e1816583d3` | `APPROVE / PASS / REACHABLE` |
| Backups recovery states | `e711abd10a` → `b7c8ff96d5` | `APPROVE / PASS / REACHABLE` |
| MCP recovery guards | `ffb0292968` → `bd6a46b316` | `APPROVE / PASS / REACHABLE` |
| Skills ownership guards | `9c96064785` → `d0fb040c6c` | `APPROVE / PASS / REACHABLE` |
| Channels ownership guards | `c6302f6b45` → `cf088ce570` | `APPROVE / PASS / REACHABLE` |

### Round 5 final inventory

| Page | Closure type | Evidence boundary and retained U |
|---|---|---|
| Chat | `CLOSED — code` | Package gates passed; send, attachment, and deterministic Stop remain `U` |
| Sessions | `CLOSED — code` | Package gates passed; save/archive/delete/batch writes remain `U` |
| Inbox | `CLOSED — code` | Package gates passed; real message/approval writes remain `U` |
| Files | `CLOSED — code` | Package gates passed; upload and UI Git remain `U` |
| Imports | `CLOSED — code` | Package gates passed; final real import lifecycle remains `U` |
| Channels | `CLOSED — code` | Package gates passed; real shared-backend writes remain `U` |
| Heartbeat | `CLOSED — code` | Package gates passed; instruction-file fixture gap remains `U` |
| Skills | `CLOSED — code` | Package gates passed; real install/import/delete remain prohibited `U` |
| Tools | `CLOSED — code` | Scoped recovery and safe toggle path closed |
| MCP | `CLOSED — code` | Scoped CRUD/recovery path closed |
| ACP | `CLOSED — code` | Scoped route/recovery path closed; runner launch remains `U` |
| Backups | `CLOSED — code` | Recovery UI closed; real create/import/restore/delete jobs remain `U` |
| Voice | `CLOSED — code` | Scoped UI/load path closed; Whisper provider/API remains `U` |
| Security | `CLOSED — code` | Candidate `123d90ae5` merged at `0362e7a5e`; actual-browser and static/test `PASS`; backend persistence/scanning `U` |
| Debug | `CLOSED — code` | Candidate `50c772132` merged at `6179f8dea`; actual-browser and static/test `PASS`; production backend content `U` |
| Agent Config | `CLOSED — no code` | Exact-base actual-browser mouse/write-failure/retry and 27 focused tests `PASS`; writes were intercepted |
| Checkpoints | `CLOSED — no code` | Exact-base actual-browser menu/preview/cancel and 25 focused tests `PASS`; destructive writes `U` |
| Agent Stats | `CLOSED — no code` | Exact-base actual-browser hover/date-query/visual matrix and 3 focused tests `PASS`; Chrome/macOS runtime only |
| Market | `CLOSED — read-only` | Actual-browser browse/search/filter/internal detail and 71 focused tests `PASS`; install/update/uninstall/publish/external navigation remain `U` |

Models is scope-out and is not counted as open, U-only, or uninspected work.
The authoritative Round 5 ledger is
`/tmp/qwenpaw-round5-cf088ce5/REMAINING_MATRIX.md`, SHA-256
`056a135daa34266439ebd6cd0818225d1cf005754b55c6563db025dbb8f95d8c`.

### Core-interaction discovery gate

This gate is mandatory for every page audit, validation task, and page-level
completion claim:

1. Before execution, list the page's core user journeys and the controls used
   by each journey. Every historical user report in scope is `MUST-TEST` and
   must appear explicitly in that checklist.
2. For every core `Select` or `Dropdown`, use a real mouse against the real UI
   implementation to complete option selection. Record the controlled-value
   change, downstream field or business-state linkage, and absence of pointer
   penetration into adjacent fields.
3. For every popup or overlay involved in a core journey, record its resolved
   container, computed `pointer-events`, and `elementFromPoint` result at the
   intended click coordinate.
4. A test that replaces the UI control with a native `select` mock proves only
   data-flow logic. It is never evidence that the production component is
   mouse-usable.
5. Every matrix cell uses exactly `PASS`, `FAIL`, `UNAVAILABLE`, or
   `NOT TESTED`. An unexecuted check cannot be inferred as `PASS`, and the
   report must list every uncovered item explicitly.
6. A page may be reported as `COMPLETED / 0 FORMAL FINDINGS` only when core
   `NOT TESTED` equals zero and every observed P1/P2 candidate has been
   adjudicated. Otherwise its state is `PARTIAL`, even when executed rows pass.
7. After the executor reports, the design lead audits every checklist row and
   disposition. The independent validator samples every P1 core path with the
   real interaction; fixed-scope review or validation does not replace the
   discovery-stage gate.

Round 5 applied this gate to all 19 in-scope pages and closed the inventory with
candidate 0, in progress 0, and not inspected 0. Models remained scope-out.
Closure preserves every `U` boundary and does not imply full-function PASS.
This governance pass did not automatically reopen closed F1–F12; reopening
still requires new evidence of a violated accepted contract.

### Four-route delivery model

All four routes remain part of the long-term north star. The first two are
closed for the scoped page program; the other two require separate handoffs:

| Route | Current status | Outcome | Typical evidence |
|---|---|---|---|
| Function and linkage | `CLOSED FOR SCOPED PAGE PROGRAM` | Controls perform the intended action within each recorded boundary; dangerous or external paths remain `U` | Round 4/5 package gates and Round 5 inventory |
| Visual system and page refinement | `CLOSED FOR SCOPED PAGE PROGRAM` | Scoped responsive/theme and page-polish contracts passed their recorded evidence gates | Package-specific browser/static/test evidence |
| Stability and recovery | `NEXT SEPARATE HANDOFF / NOT STARTED` | Failures are contained and recoverable; logs and requests remain clean and intentional | New scope, measurements, and authorization required |
| Performance | `NEXT SEPARATE HANDOFF / NOT STARTED` | Frequent interactions remain responsive and payload/work bounds are explicit | New scope, measurements, and authorization required |

Roadmap concurrency does not mean one large implementation. Deliver code as
small vertical packages around one user journey or interaction boundary. Each
package selects only the applicable checks from the four routes, owns a narrow
file set, and passes the task-branch validation/review/integration lifecycle.
Closing one package or passing one validation does not close the other routes.
Any later page package must not absorb stability/recovery or performance scope.

The following remain roadmap candidates rather than approved implementation:

- production-like performance baselines and bounded trace datasets —
  `DEFERRED TO SEPARATE REFACTOR`;
- true touch-device and VoiceOver/NVDA validation;
- shared component and warning-debt work beyond the accepted Findings;
- canonical URL and information-architecture convergence;
- Desktop OS, Hub, and embedded-app coverage unavailable in the audit setup.

## Update triggers

- Commander confirms Wave or package: update scope and status.
- Task/worktree created: record owner, `TASK_BASE_SHA`, task branch, files, and
  transition to `ACTIVE`.
- Combined task-branch validation passed: record `TASK_DEV_HEAD` and transition
  to `TASK_VALIDATED`.
- Review dispatched: freeze `TASK_BASE_SHA..TASK_DEV_HEAD` and transition to
  `IN_REVIEW`.
- Verdict received: record issues and transition to `REVIEWED` or return work.
- Final `APPROVE`: integrate the approved task branch, verify reachability and
  scoped long-lived-branch regression, then transition through `INTEGRATED` to
  `CLOSED` and record residuals.
- Scope, architecture, or rollback decision: add an ADR before updating this
  plan.
