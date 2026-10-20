# Console UI/UX Wave 4 Warning Governance Baseline

## Validation status

| Field | Value |
|---|---|
| Task | `wave4-warning-governance-baseline` |
| Type | `VALIDATION-ONLY / READ-ONLY` |
| Status | Validation `COMPLETED`; approved app-owned Ant Design line `CLOSED` |
| Baseline | `feat/console-uiux-refactor@8b5db203f88ff3e24223f6a53f671c693dc61ed9` |
| Validator | `01a13f1a-c9e9-7002-852a-b4d6f1de5140` |
| Repository changes | None from validation |
| Push / PR / allowlist / service restart | None |
| Completed on | 2026-10-15, Asia/Shanghai |

The baseline established warning ownership and removal conditions without
creating a formal P1/P2 Finding or allowlist. A later scoped task repaired the
approved app-owned Ant Design call sites; its integration record appears below.

## Matrix and integrity

- Environment: Chrome 146.0.7680.80 on macOS, development server, desktop
  light at 1440×900.
- Routes: `/sessions`, `/chat`, `/files`, `/channels`, `/models`, and `/tools`.
- Sampling: two fresh isolated BrowserContexts per route, for 12 clean loads;
  `/tools` also opened its first visible configuration control twice.
- Network boundary: only GET/HEAD/OPTIONS were allowed. There were no mutation
  attempts, new non-warning console errors, page errors/uncaught exceptions,
  failed requests, or HTTP responses at or above 400.
- Binding: the live frontend exposed the A1 and C1 target-only sentinels. The
  backend binding combined repository module resolution, workspace cwd, and the
  matching `2.2.2b6` version response; it was not inferred from ports alone.
- Limits: dark/narrow viewports, production builds, Linux/Windows, physical
  touch, assistive technology, and minified production stacks were not tested.

## Warning ledger

| ID | Baseline result | Classification / confidence | Owner | Reason | Expiry / removal condition |
|---|---|---|---|---|---|
| W1 `forwardRef` arity | 24; 12/12 loads | `vendor-only` / high | `@agentscope-ai/chat` `ActionButton2`; `@agentscope-ai/design` `SparkAnchor` | Both vendor components pass a one-argument render function to `forwardRef` | Pinned vendor upgrade/patch, followed by zero events in two clean loads of every baseline route |
| W2 AntD `Spin tip` | 12; 12/12 loads | app defect candidate / high | `MainLayout / ChunkRecoverySuspense` fallback | Shared lazy-route fallback supplies `tip` outside nested/fullscreen Spin usage | Supported fallback props and zero events in two clean cold loads of every route |
| W3 Tooltip `overlayClassName` | 8; Chat/Sessions/Models/Tools 8/8 | dependency-design vendor debt / high | `@agentscope-ai/design` Button/Tooltip | Button always mounts Tooltip; an absent tooltip class becomes `overlayClassName=""` and reaches AntD | Upstream or authorized exact-version central patch; zero fresh-context events on all four routes |
| W4 `findDOMNode` | 2; Chat 2/2 | app/vendor ref-boundary candidate / high | `ChatActionGroup` and design `IconButton` boundary | Tooltip child lacks the DOM ref required by `SingleObserver`, causing fallback | DOM-ref-forwarding child/vendor component; zero twice plus tooltip interaction coverage |
| W5 Select `popupClassName` | 12; 12/12 loads | app defect candidate / high | `AgentSelector` | Shared sidebar Select passes the deprecated compatibility prop | Migrate to `classNames.popup.root`; zero twice on every route |
| W6 Card `bodyStyle` | 4; Sessions/Channels 4/4 | app defect candidate / high | `SessionsPage`; `ChannelCard` | Both route-owned Cards pass deprecated `bodyStyle` | Migrate to `styles.body`; zero twice on Sessions and Channels |

The follow-up owner-attribution task proved a shared W3 dependency owner. A
fresh context plus targeted host-button hover reproduced one warning on each of
Sessions, Chat, Models, and Tools. AntD `warningOnce` still hides mounted
offender counts, but Fiber and installed-source evidence consistently reaches
the unconditional `@agentscope-ai/design` Button → Tooltip wrapper. The four
business routes are consumers, not four independent remediation owners.

Historical Package A counts were W1 60, W2 30, W3 24, W4 12, W5 12, and W6
12. The historical traversal and current clean-load matrix differ; no baseline
delta is claimed.

Confirmed source boundaries are `console/src/layouts/MainLayout/index.tsx:86`
for W2, `console/src/pages/Chat/components/ChatActionGroup/index.tsx:24` for
W4, `console/src/components/AgentSelector/index.tsx:505` for W5,
`console/src/pages/Control/Sessions/index.tsx:417` and
`console/src/pages/Control/Channels/components/ChannelCard.tsx:52` for W6.
W3 retains four business-route reachability points, but its remediation owner
is the shared design dependency rather than those route call sites.

## W1/W3 vendor attribution decision

Task `wave4-tooltip-vendor-attribution` completed read-only at the same baseline
without service restart or repository changes. Its compatibility matrix found
no directly upgradable artifact that repairs the complete W1/W3 target set:

| Artifact | Result |
|---|---|
| Current/newest chat beta | ActionButton `forwardRef` arity remains unfixed |
| Design latest `1.0.32` and beta `1.0.33-beta` | SparkAnchor, IconButton ref, and Tooltip targets remain partially or wholly unfixed |
| Design `2.0.0-beta` | Fixes only IconButton ref; retains SparkAnchor/W3 defects and requires AntD 6 |
| Official `main@64d95f2f1ed8f8e0502408dfad93e674015c5804` | No complete ActionButton, SparkAnchor, IconButton, or Tooltip fix |

Current decision: retain W1/W3 as non-blocking vendor debt and abandon their
implementation in this Console UI/UX refactor. Console cannot resolve them
independently without a dependency upgrade, exact-version `patch-package`,
route-level workaround, or suppression. None is authorized. Any future action
belongs to a separately authorized dependency program, not Wave 4 follow-up.

GitHub REST history/tree access returned 403. The validator used the official
Git ref and codeload archive to inspect the exact `main` snapshot. Published
artifacts and that SHA are verified; whether a non-main or inaccessible
historical upstream change contains a fix remains Unverified.

## Independent signals

- AntD Modal `destroyOnClose`: reproduced twice in two clean `/models` loads.
  Classification was app defect candidate, high confidence. Owner is the
  `ModelsPage` variant-selection Modal at
  `console/src/pages/Settings/Models/index.tsx:666`. Removal requires migration
  to `destroyOnHidden` and zero events in two clean Models loads. The code
  migration is integrated below; the browser zero-event condition has not been
  rerun. It remains separate from W1–W6 and is not allowlisted.
- Unconnected `useForm`: stale/not reproduced, zero across 12 clean loads and
  two deterministic Tools interactions. Candidate owners remain Tools
  `ToolConfigModal`, `WebSearchConfigModal`, and the Sidebar account form. This
  matrix did not recover the historical interaction path, so zero is not proof
  of safety and is not an allowlist basis. Retain the historical fact until the
  original path is identified or targeted form-lifecycle coverage closes it.

## Severity and repair boundary

No evidence-backed P1/P2 candidate was produced. The baseline signals are
development-warning governance debt and upgrade-compatibility repair
candidates; this matrix observed no user-visible functional failure.

The approved app-owned repair task covered W2, W5, W6, and `destroyOnClose`.
It did not cover W1/W3 vendor debt, W4 `findDOMNode`, or `useForm`, and it did
not authorize an allowlist or dependency change.

## App-owned repair integration

| Field | Value |
|---|---|
| Task base | `8b5db203f88ff3e24223f6a53f671c693dc61ed9` |
| Task branch | `codex/console-uiux-w4-antd-deprecation-repair` |
| Task worktree | `/Users/mazhijian/.codex/worktrees/w4-antd-deprecation-repair/QwenPawCodex` |
| Task development HEAD | `286c724e8e2006592609a0fbc789eec462e4b1c0` |
| Fixed review range | `8b5db203f88ff3e24223f6a53f671c693dc61ed9..286c724e8e2006592609a0fbc789eec462e4b1c0` |
| Independent reviewer / verdict | `01a13e66-462a-7292-a7fe-aafb5d3662d8`; `APPROVE`, no Critical, Important, or Minor Issues |
| Integration commit / HEAD | `48e8ca9575cb1b98bd27757d7382e205dcdc1b19` |
| Integrated on | 2026-10-16 08:25:11 +08:00 |
| Post-merge validation | 5 test files / 40 tests; ten-file ESLint and Prettier; `git diff --check` passed |
| Excluded from merge | package, lock, and documentation files |
| External state | No push or PR; task branch/worktree retained |

The task integrated four surgical migrations: supported route-loading fallback
without `Spin tip`, AgentSelector `classNames.popup.root`, SessionsPage and
ChannelCard `styles.body`, and ModelsPage `destroyOnHidden`. Ten source/test
files changed, with no dependency surface.

The post-merge evidence proves targeted tests and static checks at the new
long-lived HEAD. The runtime closure below additionally satisfies the scoped
fresh-context zero-event gate for W2/W5/W6 and `destroyOnClose`.

## Post-merge runtime closure

Chrome 146 on macOS loaded `/sessions`, `/chat`, `/files`, `/channels`,
`/models`, and `/tools` twice each in fresh 1440×900/light contexts at
`feat/console-uiux-refactor@48e8ca9575cb1b98bd27757d7382e205dcdc1b19`.
All 12 cases returned HTTP 200 with the expected route and main content.

| Signal | Total | Closure classification |
|---|---:|---|
| W2 `Spin tip` | 0 | Fixed target clear in scoped matrix |
| W5 `popupClassName` | 0 | Fixed target clear in scoped matrix |
| W6 `bodyStyle` | 0 | Fixed target clear in scoped matrix |
| Models `destroyOnClose` | 0 | Fixed target clear in scoped matrix |
| Disconnected `useForm` | 0 | Stale/not reproduced; does not prove every form path safe |
| W1 `forwardRef` | 24 | Adjudicated non-blocking vendor debt; no repair derivation |
| W3 Tooltip API | 8 | Adjudicated non-blocking vendor debt; no repair derivation |
| Chat `findDOMNode` | 2 | `UNVERIFIED / non-target`; no pre-merge control or visible failure |

Page errors, failed requests, HTTP responses at or above 400, and mutation
attempts were all zero. The scoped app-owned Ant Design repair line is closed.
The residual signals do not automatically derive another repair task.

Taxonomy note: this SSOT keeps W4 assigned to `findDOMNode`; the runtime
report's local “W4 useForm” label refers to the independent disconnected
`useForm` signal and does not renumber the governance ledger.

The evidence package is
`/tmp/qwenpaw-wave4-postmerge-runtime-20261016-082932-48e8ca957/`.
Its `MANIFEST.sha256` file has SHA-256
`944611f681c04ec270f249d910df38f1322bd3883537908bfd1dff6063f7bb61`,
and the full checksum list verified successfully.

## Follow-up admission rule

- Fresh-context validation may close or qualify the evidence for the integrated
  repair; it does not authorize implementation work by itself.
- W1/W3 stay outside this Console UI/UX implementation scope as non-blocking
  vendor debt.
- W4, `useForm`, and additional `bodyStyle` occurrences are not current repair
  candidates. They may be proposed only after reproducible evidence connects
  them to a user-visible failure and the commander separately authorizes scope.

## Evidence

Directory:
`/tmp/qwenpaw-wave4-warning-governance-20261015-184506-8b5db203f/`.

| File | SHA-256 |
|---|---|
| `manifest.json` | `1954dc2a5f34dc852648d5119c73dd330fc1106e93d47367df1b0a582890b748` |
| `report.md` | `103fa5a73e3ba814e5f0b1de1aa93a69eca6f75da0051b399e52e66a22c3a8d3` |
| `classification.json` | `fe56a962a5ea34ad1a8c0fa9fb3d4cfaf3bedb4bf027567808f40a876b4103d3` |
| `results.json` | `057723c187e3a0d227fad91bc82c86cfecdb7988a762747b915eb1dc29f822c0` |
| `console.json` | `b8cbb6af971ff9e3c69db267d99f36796c560c343405e6c1a0c9eb554e8a55ea` |
| `network.json` | `be56faf06dadc97b75ae58a5d274f9b01ca97e1a242e46028def9d7db24ac28a` |
| `service-binding.json` | `ccfeeb7eae6a1cf93ab7da9e58b593af3eb6604765351534c8d154604de5cc73` |
| `fiber-props.json` | `71e43298bffd020b1ff48ed7652b960a8cf23ce2fc406905621a0a6a3af22857` |
| `capture_warnings.py` | `98d626abdbc69ac932083842d85b5b7d63e2a4289aaa9974743634abf713fef0` |
| `probe_fibers.py` | `566b53a4d94b68f603ac033267c25a0cec7a117ca96362801e966d8eb3846439` |

Vendor-attribution directory:
`/tmp/qwenpaw-wave4-tooltip-vendor-20261015-191010-8b5db203f/`.

| File | SHA-256 |
|---|---|
| `report.md` | `df658cfd031e52a88c244ab52c954798f528c41f118bb22a498934cc7c2bce36` |
| `compatibility-matrix.json` | `e5a839d7e00e7ce697a2b15cdca866e2d02aea288eee928d24369bcb20821a8e` |
| `w3/owner-attribution.json` | `e4c5331ca06e1d78639a3e5bf05b62cb3af4215648e6028a035b754b44939911` |
| `manifest.json` | `da71684c31d99d963401f9795f5462ef913d1659a6d37c71eabac0fd2dc7aaa8` |

The evidence lives in `/tmp` and can be removed by system cleanup. The hashes
prove integrity only while the original files remain available.
