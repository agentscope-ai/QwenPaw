# Console UI/UX Refactor

This directory is the live source of truth for the Console UI/UX refactor.
It records execution state; it does not replace the product design language or
the original evidence audit.

## Refactor north star

Console UI/UX refactoring is not a defect-patching program. Its product outcome
must combine:

- correct, usable functionality, especially real mouse selection in dropdowns
  and menus and the resulting field/business-state linkage;
- easy, efficient interaction with clear feedback and recovery;
- polished, visually unified pages and components;
- consistent desktop, tablet, and mobile behavior across light and dark themes;
- stability, error recovery, clean runtime logs, healthy request behavior, and
  bounded performance.

Validation-first determines whether a specific defect claim is admitted and
how strongly it is evidenced. A passing validation or a closed Finding does not
end the refactor. Product progress continues across four routes: function and
state linkage, visual system and page refinement, stability/recovery, and
performance. Code is still delivered as small, reviewable vertical packages.

The scoped function/state-linkage and visual/page-refinement program is now
closed. Stability/recovery and performance remain
`DEFERRED TO SEPARATE REFACTOR`; each requires a new handoff and must not be
silently folded into this closeout.

## Current state

| Field | Value |
|---|---|
| Integration branch | `feat/console-uiux-refactor` |
| Current baseline | `6179f8dea0c34d1ff6ee6aae123cc1f4529850a5` |
| Historical branch | `feat/console-uiux-wave1-integration` is retained for audit only and is not a baseline |
| Wave 1 | `CLOSED` at `7df8c7819673e815b765cfaa760baad793e1e823` |
| Wave 2 | `CLOSED` at `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8` |
| Wave 3 | `CLOSED` at `8b5db203f88ff3e24223f6a53f671c693dc61ed9` for the approved stabilization scope |
| Wave 3 implementation | A1 and C1 are `CLOSED` after independent `APPROVE` |
| Open Wave 3 Findings | None in the approved code-Finding scope |
| Wave 4 Ant Design line | `CLOSED`; W2/W5/W6 and `destroyOnClose` integrated/approved and zero in post-merge runtime matrix |
| Sidebar interaction visual polish | `CLOSED` at `f6530ee342cab87f98e913ef1e3a87dae5061e4e`; independent `APPROVE / PASS` |
| Round 5 inventory | `CLOSED`; 19/19 scoped pages, candidate 0, in progress 0, U-only page 0, not inspected 0 |
| Execution status | `CLOSED` for the scoped UI/UX page program; Models explicitly scope-out; U boundaries retained |
| Closeout baseline | `feat/console-uiux-refactor@6179f8dea0c34d1ff6ee6aae123cc1f4529850a5` |
| Push / PR / release | Not requested and not verified |
| Last reconciled | 2026-10-19, Asia/Shanghai |

Wave 3 packages A and C completed as read-only validation/audit work. A1 and
C1 are `CLOSED` after independent `APPROVE`. Package B remains deferred
design-only pending an official APG contract recheck. The Wave 4 warning
governance baseline is complete, and the approved app-owned Ant Design repairs
landed at `48e8ca9575cb1b98bd27757d7382e205dcdc1b19`. W1/W3 remain vendor debt,
and this Console UI/UX refactor will not implement them. W4 `findDOMNode`,
`useForm`, and any additional `bodyStyle` occurrence require evidence of a
user-visible failure before candidate consideration; closing the approved
repair task does not complete the long-term UI/UX roadmap.

Post-merge Chrome validation at `48e8ca9575` completed 6 routes × 2 fresh
contexts: W2, W5, W6, `destroyOnClose`, and `useForm` were zero; page errors,
failed requests, HTTP errors, and mutation attempts were zero. W1=24 and W3=8
remain the already adjudicated non-blocking vendor debt. Chat `findDOMNode`=2 is
an `UNVERIFIED` non-target observation with no pre-merge control or user-visible
failure, so it does not reopen the Ant Design line or create a task.

The closed page program prioritized desktop mouse-driven, high-frequency work.
Keyboard behavior retained only the minimum regression gate required by
existing contracts; keyboard enhancements and keyboard drag-and-drop were not
part of that program. This historical priority is not new implementation
authority.

The first visual-system vertical package is closed: Sidebar interaction states,
selected/hover feedback, and contrast were integrated at `f6530ee342`.
SettingsCenter active-navigation contrast then closed as a separate two-file
package at `85c44a633`; its 14px/500 runtime contrast is 4.746557 in light mode
and 8.298496 in dark mode.

The mandatory double gate is complete for the 19-page Round 5 inventory.
Closure is scoped: code packages are reachable from the integration HEAD;
no-code pages closed on exact-base evidence; Market closed only for its
read-only browse boundary. Models is excluded by instruction.

| Task | Type | State | Boundary |
|---|---|---|---|
| A SettingsCenter active-nav contrast | Independent code vertical package | `CLOSED / APPROVE / PASS` at `85c44a633` | Two-file repair; cascade 1/1, token 3/3, ESLint, Prettier, and diff-check passed |
| Round 4 code packages | Code-producing vertical packages | `CLOSED / APPROVE / PASS` | All recorded candidate commits are reachable from `6179f8dea`; package-specific browser/static/test boundaries remain explicit in the plan |
| Round 5 code pages | Security and Debug | `CLOSED / APPROVE / PASS` | Security `123d90ae5` → `0362e7a5e`; Debug `50c772132` → `6179f8dea`; independent real-browser and static/test gates passed |
| Round 5 no-code pages | Agent Config, Checkpoints, Agent Stats | `CLOSED / NO CODE` | Exact-base real-browser matrices and focused tests passed; no product diff or integration event |
| Round 5 Market | `READ-ONLY` | `CLOSED` for browse boundary only | Browse/search/filter/internal detail passed in real browser; install/update/uninstall/publish/external navigation remain `U` |
| Models | Scope decision | `SCOPE-OUT` | Excluded by user instruction; not counted as open or uninspected work |

SettingsCenter used branch `codex/console-uiux-settingscenter-nav-contrast`,
worktree
`/Users/mazhijian/.codex/worktrees/settingscenter-nav-contrast/QwenPawCodex`,
and task HEAD `ec65049475e565ad56093ff8f2ab362f44554b15`. Cron P1 task
HEAD `892c989311788943c569e7ba56d9448693636a6c` merged as
`0f909f459061c5de3af72269eb8908201a9e9b07`; its branch/worktree were not
reported. Push and PR remain unauthorized.

Closed F1–F12 contracts did not automatically reopen under this page-level
re-audit. A closed Finding reopens only when new evidence proves its accepted
contract is violated again. Stability/recovery and performance remain the next
separate handoff; they were not silently absorbed into this closeout.

C1 diagnosis and repair design was completed directly in the design-lead
conversation without a Sub-agent or code changes. The first proposed stage is
read-only segmented measurement with `/tmp` output; it completed with 12 valid
samples per tier and no invalid samples. Observer options A/B were excluded;
stable entry identity and memoized rows (C) were approved for direct
implementation in the current design-lead conversation. Commit
`8b5db203f88ff3e24223f6a53f671c693dc61ed9` is present on the long-lived branch
and passed the targeted and browser gates. Independent review is complete;
no push or PR occurred. Reviewer thread
`01a13e66-462a-7292-a7fe-aafb5d3662d8` returned `APPROVE` with no Critical,
Important, or Minor Issues, closing C1 at that commit.

| Package | Delivery type | Execution status | Task thread | Worktree |
|---|---|---|---|---|
| A `console-mobile-runtime-validation` | `READ-ONLY` | `COMPLETED / EVIDENCE_ACCEPTED` | `01a13eb8-034b-7290-aabc-c40a4f2b8a79` | `/Users/mazhijian/.codex/worktrees/7a18/QwenPawCodex` |
| C `console-expanded-tree-performance-audit` | `READ-ONLY` | `COMPLETED / EVIDENCE_ACCEPTED` | `01a13eb7-e48e-7400-8e16-14c16a175ed9` | `/Users/mazhijian/.codex/worktrees/deec/QwenPawCodex` |

Both tasks use base `9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8`.
They produce evidence, not integration events or merge records.

A returned its evidence under
`/tmp/qwenpaw-console-mobile-validation.Ia4heA/`; the design lead accepted the
evidence package and confirmed formal Finding A1. A released its browser, Vite
server, port 55176, and validation subprocess resources before C entered formal
timing.

C returned accepted evidence under `/tmp/qwenpaw-tree-perf.WejBM5/` and closed
cleanly with its measurement resources released. The data originally
established C1 (`P2 / OPEN / performance-data-confirmed`):
refresh-plus-React-commit-plus-focus
recovery exceeds 50ms at 500 and 2,000 visible nodes, while recovery remains
correct and keyboard navigation stays below the budget. Package C is read-only,
so it records `no merge applicable`; the evidence does not authorize C1 code.

The A1 repair task `console-files-tablet-tabs` started at base
`9d575bf8b576d54a0d45d8d383dddb2ac9eda7b8` in thread
`01a13ee7-f13a-76e2-9dff-2f165c4b36a1` and worktree
`/Users/mazhijian/.codex/worktrees/2a4a/QwenPawCodex`. Source commit
`7d7e24251d0bff46c0e6f06d65892cf8f65bae68` was cherry-picked as
`e3e12d98627acd15323c3f2803378d90f1d1aeaf`; targeted tests, static checks, and
the integration browser matrix passed. Independent reviewer thread
`01a13e66-462a-7292-a7fe-aafb5d3662d8` returned `APPROVE` with no
Critical/Important/Minor Issues, so A1 is `CLOSED`.

## Document map

- [Roadmap and governance](plan.md)
- [Finding ledger](findings.md)
- [Current handoff](handoff.md)
- [Decision records](decisions/README.md)
- [Wave 1 closeout](waves/wave-1.md)
- [Wave 2 closeout](waves/wave-2.md)
- [Wave 3 closeout](waves/wave-3.md)
- [Wave 4 warning governance baseline](waves/wave-4.md)
- [Original evidence audit](../../audits/2026-10-15-console-uiux-evidence-audit.md)
- [QwenPaw design language](../../../design.md)

The audit is an evidence snapshot from 2026-10-15. Its original findings and
unchecked implementation checklist are not rewritten as implementation state.
The design language is a governing design contract, not a progress ledger.

## Governing inputs

- `design.md`: tracked repository design contract.
- User-provided `AGENTS.md` instructions: conversation-provided `always_on`
  governance; no repository-root `AGENTS.md` was found during reconciliation.
- `Console UIUX 实用性巡检规范`: conversation-provided governing
  specification; repository path unavailable during reconciliation.
- Git objects: authoritative for local branch, commit, parent, and diff facts.
- Targeted validation records and explicit independent-review verdicts:
  authoritative only for the scope and environment they name.

Local Git facts do not prove a push, pull request, merge, deployment, or
release. Those states must remain `not requested` or `not verified` unless
independently evidenced.

## Role and branch governance

| Role | Responsibility | Thread |
|---|---|---|
| Commander | Authorize scope and close tasks/Findings | `01a13e14-b9df-71f2-bd3c-1198d5ba7813` |
| Design lead | Own design, decomposition, task-branch integration, and long-lived-branch integration | `01a13e1d-d252-7813-aaad-cf4a94a63dd0` |
| Validator | Execute tests and capture raw evidence; does not issue the independent verdict | `01a13f1a-c9e9-7002-852a-b4d6f1de5140` |
| Independent reviewer | Evaluate the fixed range and issue the independent verdict | `01a13e66-462a-7292-a7fe-aafb5d3662d8` |
| Documentation owner | Maintain this SSOT and reconcile status/evidence without changing code | Current documentation task |

The authoritative long-lived baseline is
`feat/console-uiux-refactor@6179f8dea0c34d1ff6ee6aae123cc1f4529850a5`.
`feat/console-uiux-wave1-integration` is retained only as historical audit
evidence and must not be used as a task base.

Every authorized code task follows this lifecycle:

1. Record the exact current `feat/console-uiux-refactor` HEAD as
   `TASK_BASE_SHA`, create a dedicated task development branch from that SHA,
   and perform development in an independent worktree. The primary workspace
   remains on the long-lived branch; direct development there is prohibited.
2. The design lead may create parallel worktrees from the task branch baseline
   for mutually exclusive subtasks. Every accepted subtask result is first
   integrated into the same task development branch.
3. Complete combined targeted validation on the task development branch, then
   freeze the independent review range as `TASK_BASE_SHA..TASK_DEV_HEAD`.
4. Apply review fixes to the same task development branch and repeat validation
   and review as required. Do not integrate into the long-lived branch before
   the independent reviewer returns `APPROVE`.
5. After `APPROVE`, merge the task development branch into
   `feat/console-uiux-refactor`. If that branch advanced after `TASK_BASE_SHA`,
   first synchronize the task branch, rerun the scoped validation, and request
   a new review when synchronization causes a substantive code change.
6. On the resulting long-lived-branch integration HEAD, run the scoped
   regression and record `TASK_DEV_HEAD` reachability plus the final
   `integration_head`.
7. Do not push, create a PR, delete a branch, or remove a worktree without
   separate authorization. Every role sends a structured completion, failure,
   blocker, or decision-needed report to the commander before ending its task.

## State model

Wave states:

`PLANNED → ACTIVE → TASK_VALIDATED → IN_REVIEW → REVIEWED → INTEGRATED → CLOSED`

Exceptional states are `BLOCKED` and `SUPERSEDED`.

- `PLANNED`: scope or technical design has been commissioned; implementation
  has not started.
- `ACTIVE`: authorized implementation is running.
- `TASK_VALIDATED`: combined validation passed on the task development branch.
- `IN_REVIEW`: the fixed commit range has been sent for independent review.
- `REVIEWED`: an independent verdict exists, but closure conditions may remain.
- `INTEGRATED`: an approved task development HEAD is reachable from the
  long-lived integration branch.
- `CLOSED`: for a code-producing task, the source task commit and every review
  follow-up commit are reachable from `feat/console-uiux-refactor`, the
  integration commit and new `integration_head` are recorded, targeted
  regression has passed on the long-lived branch, required independent review
  returned `APPROVE`, and evidence/residual risks are recorded. A clean child
  worktree, task tests, or task-level review alone never satisfies `CLOSED`.

Finding states:

`OPEN / IMPLEMENTED / VERIFIED / CLOSED / DEFERRED / REOPENED`

Closing an audit Finding means the accepted defect contract was repaired and
approved. It does not mean every recommended refactor, enhancement, or
unverified path has been completed.

Evidence status and method are recorded separately.

Claim status:

- `已复现`: the failure or behavior was reproduced.
- `运行通过`: the named runtime path passed in the stated environment.
- `静态确认`: source or Git structure proves only the stated static claim.
- `性能数据确认`: repeatable quantitative performance data exists.
- `不可验证`: environment, fixture, permission, or instrument was unavailable.
- `待验证假设`: evidence is insufficient for a finding or completion claim.

Evidence method:

- `browser-runtime`: observed in the named running browser environment.
- `targeted-test`: a bounded test or static-check command was executed.
- `static-confirmation`: source or Git structure supports the conclusion.
- `unavailable`: the required environment, fixture, permission, or instrument
  was unavailable.
- `hypothesis`: evidence is insufficient for a finding or completion claim.

## Update rules

1. Reconcile branch, HEAD, working-tree state, commits, tests, and reviewer
   verdict before updating status.
2. Record task thread, worktree, base SHA, file ownership, and acceptance
   criteria when implementation is authorized.
3. Follow the branch lifecycle above: validate and independently review the
   fixed `TASK_BASE_SHA..TASK_DEV_HEAD` range before integrating the approved
   task branch into `feat/console-uiux-refactor`. Record task base/head,
   integration sequence/time, integration commit/head, and branch/status
   evidence. Preserve one Finding per commit where practical.
4. Read-only tasks with no commit record `no merge applicable`. Any repair
   derived from their evidence is a separate code-producing task with the full
   integration and closure gate. A/C currently use `no merge applicable`; A1
   passed the full integration and independent-review closure gate.
5. Do not change a Wave to `CLOSED` on `APPROVE WITH FIXES` or
   `REQUEST CHANGES`.
6. Preserve old evidence and append its superseding evidence; do not silently
   turn a static conclusion into a runtime result.
7. Update `handoff.md` before ownership changes. Keep closed-Wave detail in the
   Wave file and only the current summary here.
8. Record a real architectural or product decision before changing the plan;
   do not invent retrospective ADRs for choices that were never decided.
9. Documentation tracking/commit timing is a commander decision. Code tasks
   must not incidentally add these documentation files to their commits.

## Record templates

Finding record:

```text
id | severity | source | wave | status | integration_sequence |
task_branch | task_base_sha | task_dev_head | review_range | integrated_at |
integration_commit | integration_head | task_thread | worktree |
implementation_evidence | reviewer_verdict | residual_risk | last_verified_at
```

Wave record:

```text
goal | scope | base_sha | task_branches | final_sha | commits |
task_threads/worktrees | task_validation | review_ranges |
integration_validation | reviewer_thread | verdict | returned_fixes |
unverified_items | rollback_boundary | status | closed_at
```

ADR record:

```text
context | options | decision | rationale | consequences |
rollback_condition | evidence | decided_by | date | status
```
