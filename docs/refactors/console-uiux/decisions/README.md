# Console UI/UX Architecture and Design Decisions

This directory records decisions made after the documentation baseline was
established. It does not reconstruct retrospective decisions from commit
history or chat summaries.

## Decision index

No ADR has been created yet.

## Closure and evidence index

| Scope | State | Decision / evidence boundary | Authoritative record |
|---|---|---|---|
| A1 Files source tabs | `CLOSED` | 720–768px requires four tabs initially visible; 769px preserves desktop split layout and local horizontal tab scrolling | [Finding ledger](../findings.md) and [Wave 3 plan](../plan.md) |
| C1 expanded-tree refresh | `CLOSED` | Option C committed, validated, and independently approved at `8b5db203` | [Wave 3 closeout](../waves/wave-3.md) and [Finding ledger](../findings.md) |
| Wave 4 app-owned AntD deprecations | `CLOSED` | W2/W5/W6 and `destroyOnClose` migrated/approved and zero in the 6-route × 2 post-merge matrix | [Wave 4 evidence record](../waves/wave-4.md#post-merge-runtime-closure) |
| W1/W3 dependency warnings | `OUT OF CONSOLE SCOPE / NON-BLOCKING VENDOR DEBT` | This refactor abandons implementation; no upgrade, patch package, route workaround, broad suppression, or code task | [Wave 4 vendor attribution](../waves/wave-4.md#w1w3-vendor-attribution-decision) |
| Page-program interaction priority | `CLOSED / RETAINED AS GOVERNANCE` | Desktop mouse high-frequency tasks came first; keyboard was limited to existing-contract regression, with no keyboard enhancement or keyboard DnD priority | [Current plan](../plan.md#closed-page-program-interaction-priority) |
| Refactor north star and delivery model | `ACCEPTED` | Not a defect-only program; maintain function/linkage, visual refinement, stability/recovery, and performance, delivered as small vertical packages | [SSOT north star](../README.md#refactor-north-star) and [four-route model](../plan.md#four-route-delivery-model) |
| Current-stage route priority | `CLOSED` | The scoped page program closed at `6179f8dea0`; stability/recovery and performance remain separate, unauthorized handoffs | [Current plan](../plan.md#four-route-delivery-model) |
| Core-interaction discovery gate | `ACCEPTED / MANDATORY` | Core paths and controls are enumerated before execution; historical reports are MUST-TEST; real UI mouse evidence and zero core NOT TESTED are required for a completed zero-Finding claim | [Discovery gate](../plan.md#core-interaction-discovery-gate) |
| All-page gate re-audit | `CLOSED` | 19/19 scoped pages closed: 15 code, 3 no-code, and 1 read-only; Models is excluded; scoped inventory has zero uninspected pages | [Round 5 ledger](../plan.md#round-5-final-inventory) |
| 2026-10-16 focused execution window | `CLOSED / SUPERSEDED` | Interim counts and checkpoints were superseded by the frozen Round 5 final ledger and must not be used as current status | [Round 5 ledger](../plan.md#round-5-final-inventory) |
| Sidebar interaction visual polish | `CLOSED / APPROVE / PASS` | Integrated at `f6530ee342`; contrast and regression gates passed; SettingsCenter was kept separate | [Vertical package ledger](../plan.md#post-wave-vertical-package-ledger) |
| SettingsCenter active-nav contrast | `CLOSED / APPROVE / PASS` | Separate two-file package integrated at `85c44a633`; 14px/500 light and dark contrast and targeted gates passed | [Vertical package ledger](../plan.md#post-wave-vertical-package-ledger) |
| Cron provider/model mouse selection | `P1 / CLOSED / APPROVE / PASS` | `SettingsDrawer` now resolves desktop overlay root, mobile drawer, then `body`; task `892c989311` added a real AntD mouse regression and merged at `0f909f459` | [Current-stage formal findings](../findings.md#current-stage-formal-findings) |
| Cron DurationWheel drawer overflow | `MINOR / CLOSED / APPROVE / PASS` | Candidate `d34465a049` merged at `000bc87af6`; the formerly frozen `209f8a3` snapshot is historical only | [Current-stage formal findings](../findings.md#current-stage-formal-findings) |
| Round 4 final packages | `CLOSED / MERGED` | Every final package from DurationWheel through Channels is merged; all recorded candidate heads are reachable from `6179f8dea0` | [Vertical package ledger](../plan.md#post-wave-vertical-package-ledger) |
| Round 5 closure classification | `CLOSED` | 15 code closures, no-code Agent Config/Checkpoints/Agent Stats, and read-only Market; Models is out of scope | [Round 5 ledger](../plan.md#round-5-final-inventory) |
| Market read-only boundary | `CLOSED / READ-ONLY` | Actual-browser browse/search/filter/internal detail passed; install/update/uninstall/publish/external navigation/remote effects remain `U` | [Round 5 ledger](../plan.md#round-5-final-inventory) |
| Security and Debug | `CLOSED / MERGED` | Security candidate `123d90ae5b` merged at `0362e7a5e0`; Debug candidate `50c7721322` merged at final `6179f8dea0`; browser and static/test evidence remain separately labeled | [Finding ledger](../findings.md#round-5-closeout-evidence) |
| Evidence semantics | `ACCEPTED / MANDATORY` | Actual-browser PASS, static/test PASS, and `U` are distinct; one must never be promoted into another | [SSOT overview](../README.md) |
| Next work boundary | `NOT AUTHORIZED` | Stability/recovery and performance require separate baselines, inventories, gates, and handoffs | [Four-route model](../plan.md#four-route-delivery-model) |
| Chat cached-session transition | `REJECTED / NO CODE TASK` | Independent mouse evidence found no wrong-identity interactive window or pointer hit | [Rejected candidates](../findings.md#rejected-candidates) |

A1 closure uses integration head
`e3e12d98627acd15323c3f2803378d90f1d1aeaf` and independent reviewer thread
`01a13e66-462a-7292-a7fe-aafb5d3662d8`, which returned `APPROVE` with no
Critical, Important, or Minor Issues. This index records the accepted contract
and evidence location; it is not a retrospective ADR.

C1's conditional design was accepted and implemented as commit `8b5db203` after
the read-only `/tmp` measurement. Observer coalescing and a visible-path registry
were excluded by sub-millisecond scan evidence. Six-field entry identity reuse,
memoized workspace leaf rows, and a stable toggle callback were implemented. No
`DirectoryNode` comparator, virtualization, keyboard change, typeahead, push, or
PR was included. Independent review returned `APPROVE` with no Issues, closing
C1. The review's −38.368% instrumented/control delta is retained as a
comparability limitation rather than a product defect; developer 20+20
confirmation remained within the reliability band.

Wave 4 began as an evidence record rather than a formal P1/P2 Finding. Its
subsequent scoped app-owned repair passed independent review and integration
gates. This does not turn W1/W3 vendor debt, W4, `useForm`, or extra
`bodyStyle` occurrences into formal Findings or authorized tasks.

W1/W3 require vendor/dependency-layer action and cannot be solved locally
without an upgrade, patch package, route workaround, or suppression. This
Console UI/UX refactor will not implement those options. Any future revisit is
a separately authorized dependency program, not a continuation or automatic
follow-up of Wave 4.

Fresh-context verification remains closure evidence for the integrated repair,
and the scoped post-merge matrix passed. Residual W1/W3 events do not derive a
new task. Chat `findDOMNode` is `UNVERIFIED` because there is no pre-merge
control or user-visible failure. Any W4, `useForm`, or additional `bodyStyle`
candidate first requires evidence of a user-visible failure.

## Cron discovery-miss responsibility record

The original `audit_chat_sessions_cron_files` execution missed the real-mouse
provider/model failure. The design-lead v2 discovery gate also failed to catch
that omission before accepting the audit result. The commander owns final
acceptance responsibility. This record does not assign discovery-stage
responsibility to fixed-range reviewers or validators: their commissioned
scope began after candidate discovery and did not include an open-ended page
audit.

The prevention decision is the mandatory discovery gate above. Executor
delivery is followed by row-by-row design-lead audit; every P1 core path is then
sampled independently with the real UI. Reports must disclose all uncovered
items, and no unexecuted matrix cell may be reported or inferred as `PASS`.

Create `ADR-NNNN-short-title.md` only when a product, architecture, ownership,
compatibility, or rollback choice is explicitly decided and will affect later
work.

## ADR template

```markdown
# ADR-NNNN: <decision title>

- Status: proposed / accepted / superseded / reverted
- Date: YYYY-MM-DD, Asia/Shanghai
- Decided by: <role or authority>
- Evidence: <repository paths, tests, measurements, or review records>

## Context

<What verified constraint or problem requires a decision?>

## Options

1. <Option and trade-offs>
2. <Option and trade-offs>

## Decision

<Chosen option and exact scope.>

## Rationale

<Why the evidence favors this option.>

## Consequences

<Expected benefits, costs, dependencies, and residual risks.>

## Rollback condition

<Observable condition and safe rollback boundary.>
```

An ADR must link to the relevant Wave plan and must not contain credentials,
unsanitized logs, or unsupported claims.
