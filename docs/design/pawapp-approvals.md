# App approvals in Main Chat

Apps own their approval policy. The Host displays an App's proposal, records the
user's decision, and delivers it to the original task. An action grant, model
configuration, ordinary agent answer, or successful setup does not approve an
operation. Main Chat never changes an App's YOLO policy.

## Contract

An executor emits `ExecutorEvent(status="waiting_for_approval",
approval_request=ApprovalRequest(...))`. The request is distinct from
`TaskInputRequest` and contains:

| Field | Meaning |
| --- | --- |
| `request_id` | Immutable proposal identity; use a new ID when any proposal field changes. |
| `kind` | `execution` for authorization, `review` for content acceptance. |
| `subject_digest` | SHA-256 binding to the exact operation, content revision, or App decision token. Hash sensitive material; never expose tokens or credentials. |
| `title`, `summary`, `effects` | Bounded plain text describing what the user is deciding. No executable instructions or arbitrary navigation URLs. |
| `choices` | Stable `approve_once`, `reject`, or `request_changes` IDs with independent display labels and optional required feedback. Apps advertise only supported choices. |
| `cost` | Optional informational amount/currency and description. Missing estimates are unknown, not free. This is not a budget grant. |
| `expires_at` | Optional UTC epoch deadline. New decisions and delivery attempts after the deadline are rejected. |
| `subject` | Optional bounded object label, operation, operation count, revision and target labels. Counts describe the scope of this decision, not the number of approval requests. |
| `inspection` | Optional button label and opaque App-owned target ID. The Host issues an authenticated handoff; the App resolves the ID to its authoritative review UI. No App-supplied URL is accepted. |
| `decision_surface` | `chat` by default; `app` requires an inspection entry and disables Host decisions on the server as well as in the card. |

## Approval progress and inspection

`ExecutorEvent.approval_progress` projects mutable task-wide counts into
`TaskHandle.approval_progress`: `completed` counts handled decisions (including
rejections), and `pending` includes the currently displayed proposal. These
count approval requests, not shots, candidates, or individual changed fields.
`future` counts additional approvals after the currently pending requests.
Its `forecast` must be `exact` or `estimated` when a number is supplied, and
`unknown` when no number is known. Apps own this projection; the Host does not
infer a fixed total from an agent's narrative. A forecast does not authorize work.

Progress is separate from the immutable proposal and its digest. Updating counts
does not invalidate a displayed decision or discard its receipt. Changing the
operation, content, or approval scope still requires a new proposal identity.

To inspect a particular approval, POST `{ "request_id": "…",
"subject_digest": "sha256:…" }` to the existing scoped `/tasks/{task_id}/open`
endpoint. The Host checks the current proposal and scope and places the proposal
in `TaskContext.approval_request`. The frontend SDK exposes the same operation as
`paw.tasks.open(taskId, { approval: { request_id, subject_digest } })`.
Ordinary opens of a task with an inspectable approval share the same handoff.
The App must check that the destination is still pending at the requested
revision; it must not silently substitute a different pending review.

The scoped UI endpoint is `POST /tasks/{task_id}/decide` under the usual
`/api/pawapps/{app_id}/workspaces/{workspace_id}` prefix:

```json
{
  "command_id": "user-decision-1",
  "decision": {
    "request_id": "proposal-1",
    "subject_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "decision_id": "approve_once",
    "comment": null
  }
}
```

The Host derives the actor from authenticated scope; clients cannot supply an
actor in the body. `answer_task` cannot answer an approval wait. There is no
agent approval tool. User-interface provenance identifies the authenticated API
boundary; it does not claim to prove a physical human gesture against arbitrary
code holding that user's credentials.

The Host persists the command before delivery. Reuse its ID and identical body
following a lost response. Changed retries conflict; a second command for the
same proposal conflicts even if sent from another tab. `TaskHandle` carries an
`approval_receipt` with the recorded decision, actor and delivery state, so a
reload does not offer fresh approval buttons. Accepted delivery means the App
accepted the decision, not that the task succeeded.

The executor must independently validate its authoritative proposal/version,
apply the decision atomically, and implement `query_command` plus idempotent
command replay. It must reconcile decisions made inside the App as well. Stale,
expired, superseded, or cancelled proposals cannot authorize new work. The Host
checks scope and the action grant again before delivering a command. Policy
changes therefore cannot be bypassed using an old pending card.

The original task remains pending during approval. App events clear the request
when work resumes, finishes, or is cancelled; replacing a pending proposal
updates the card and wakes the delegated chat. Decisions never create a second
project or resubmit the original action.

## Small App example

```python
from qwenpaw.pawapp.tasks import ApprovalChoice, ApprovalRequest
from qwenpaw.pawapp.tasks.contracts import content_digest

proposal = ApprovalRequest(
    request_id="export-revision-7",
    kind="execution",
    subject_digest="sha256:" + content_digest({
        "dataset_version": 7,
        "destination": "user-download",
    }),
    title="Export this dataset?",
    summary="Create one downloadable export of revision 7.",
    effects=("Create an export artifact in this workspace.",),
    choices=(
        ApprovalChoice(decision_id="approve_once", label="Export once"),
        ApprovalChoice(decision_id="reject", label="Do not export"),
    ),
)
answer = await ctx.request_approval(proposal)
if answer.decision_id != "approve_once":
    await ctx.fail("export-declined", text="Export declined.")
# Recheck the dataset revision, then execute using submission_id for deduplication.
```

This example illustrates the generic SDK; it does not add a Data App integration.
Managed handlers must explicitly honor rejection and choose a replay-safe
implementation before enabling restart replay. The frontend SDK offers
`paw.tasks.decide(taskId, decision, commandId, options)` for an App's own UI.
Complex content inspection can use the existing authorized task/project entry;
the approval contract does not accept arbitrary App-supplied URLs.

## Creator adaptation

Generation authorization projects the existing immutable execution request into
an execution approval. The card shows provider/model and bounded generation
parameters; unknown provider cost is explicit. Approval applies Creator's
existing authorization compare-and-set, with a fresh subject check. Actual
provider dispatch still performs Creator's configuration/fingerprint checks.

Correlated pending content reviews produce a review card instead of appearing
as `planning`. New review cards show the candidate revision and operation count
and require inspection and a decision in Creator, where the actual content,
diffs, and individual decisions are available. Generation requests can still be
approved in Main Chat and offer an inspection entry to the exact authorization.
Creator focuses that authorization or review in its decision tray, with a stale
destination message instead of displaying an unrelated decision. The App's
existing UI accepts, undoes, or requests changes with feedback.
The App's existing review token, compensating commits, decision journal and
follow-up mechanism perform the work. Tokens and private review snapshots remain
in Creator. Exact command receipts survive reload and uncertain delivery.

Creator counts correlated authoritative authorizations and reviews, including
decisions made in its own UI. Expired or superseded proposals do not count as
completed approvals. Future approvals remain unknown because the workflow can
create additional generation, review, or revision work. Already-offered legacy
proposals retain their original payload and behavior until resolved.

Legacy persisted generation events retain their original `input_request` wire
payload and replay digest. Their existing user-interface answer path remains
readable. Newly emitted events use typed approvals. Ordinary agent/backend
answers cannot approve either representation. No configuration or permission is
silently upgraded during migration.
