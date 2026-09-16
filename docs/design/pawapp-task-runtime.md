# PawApp vNext task runtime

The `qwenpaw.pawapp.tasks` package provides durable Host tasks, authenticated
HTTP dispatch and recovery through the Host lifecycle. Main Chat can discover
granted actions, delegate tasks and follow their progress in Console task cards.
Delegated waiting/terminal updates queue automatic, tool-free summaries in the
originating Main Chat.
The Data
[adapter](../../plugins/apps/qwenpaw-data/backend/task_bridge/adapter.py)
implements this boundary against the Engine's durable submission API. Its
server-owned descriptor matches the [example](pawapp-vnext-data-action.example.json);
neither the descriptor nor adapter registration is a permission grant.

## Host ownership

The Host creates one `TaskStore` at a Host-owned path in its working directory
using `await TaskStore.open(path)`. SQLite owns task facts, action/input snapshots,
submission identities, run mappings, events, replay cursors and delivery receipts.
The file uses schema version 4. Additive migrations retain version 1/2/3 tasks,
add boundary audit records, durable task commands, and backfill pending
continuation jobs from the existing outbox; unsupported versions are rejected. Connections
use WAL, full synchronous commits and short transactions on worker threads.

`app/task_tracker.py` continues to track active Main Chat execution and stream
attachments. `pawapp.task.SSEChannel` remains available to Agent Kanban and other
App-owned streams. The unused in-memory `TaskManager` and its singleton have been
removed; they did not provide durable task endpoints.

## Registration and dispatch

Apps declare `app.task_action(ActionRegistration(...))`. The plugin registry
checks ownership and stores the descriptor, adapter factory and local App settings
entry. Registration does not construct the adapter, probe services or grant access.
The Host owns `app.state.pawapp_tasks`, backed by `<WORKING_DIR>/pawapp/tasks.sqlite3`.
After managed services start, its supervisor reconciles nonterminal tasks and
attaches event consumers. Shutdown cancels consumers and closes adapter pools
before plugin shutdown stops the Engines. Plugin unload/replacement removes the
action from dispatch immediately; the supervisor stops its consumers and closes
the old adapter on its next synchronization. It does not cancel Engine work.

The supervisor permits up to 32 simultaneous consumers, retries unresolved work
with a minimum five-second delay, and pages through recoverable tasks. This is a
single Host process lifecycle; distributed worker leases remain a separate gate.

- Register an `ActionDescriptor` and its `TaskAdapter` on `TaskCoordinator` at
  Host startup. The descriptor contains the App/action IDs, supported engagements,
  JSON Schema 2020-12 input schema, permission tags, effects, output types and
  server-owned adapter reference. Schemas must be self-contained; remote `$ref`
  resolution is prohibited. The Host stores a digest of the descriptor snapshot.
- The coordinator requires an asynchronous `authorize(scope, action, origin, inputs)`
  callback. The Host binding checks explicit grants, input resource constraints
  and ownership of the originating ChatSpec. Scope must
  come from authenticated Host context, not from request JSON or model output.
  There is no default allow policy. Grants pin the complete descriptor digest,
  including permission tags and effects. The callback receives independent descriptor/input
  snapshots so resource checks cannot change the submitted operation.
- `dispatch(scope, action_id, request_id=..., inputs=..., origin=...)` validates
  the registered input schema and persists the task before invoking its adapter.
  A request ID is unique within principal/workspace/App. Retries return the same
  task and submission ID; changing inputs, descriptor or origin yields
  `request_conflict`. Registration snapshots cannot be modified through returned
  descriptions.
- `begin_submission` persists a send intent before external I/O. Only one
  concurrent dispatcher wins this initial transition. An in-flight record after a
  crash means the outcome needs reconciliation; it does not prove acceptance.

## HTTP boundary and operator grants

Routes use the existing Host `AuthMiddleware` and `get_scoped_ctx`. Every supplied
user/channel/App/workspace claim must agree with the resolved scope, including
duplicate query/header claims. Task reads and event replay match all three scope
identities. Origin lookup checks the enabled workspace, ChatSpec owner, console
channel and active chat source. Direct requires App ownership metadata and its
session namespace; Delegated requires a Main Chat. Session return references are
derived by Host, never supplied in the body.

The base path is `/api/pawapps/{app_id}/workspaces/{workspace_id}`:

| Method and suffix | Result |
| --- | --- |
| `GET /actions/{action_id}` | Authorized descriptor and digest for schema injection. |
| `POST /actions/{action_id}/prepare` | Readiness only; creates no task or grant. |
| `POST /actions/{action_id}/tasks` | `202` with a durable task handle, or `200` with a structured blocked result. |
| `GET /tasks/{task_id}` | Scoped task handle and current text snapshot. |
| `POST /tasks/{task_id}/answer` | Persist and deliver an answer for the handle's current typed input request. |
| `POST /tasks/{task_id}/cancel` | Persist cancellation intent and target the original submission/run. |
| `GET /tasks/{task_id}/events?after=0&limit=100` | Ordered replay after the Host event sequence; maximum page size 1000. |

Both POST bodies accept only `request_id`, `chat_id`, `engagement` and `inputs`.
For example, use an existing owned Main Chat ID with:

```json
{
  "request_id": "analysis-request-1",
  "chat_id": "<existing-chat-id>",
  "engagement": "delegated",
  "inputs": {"text": "Analyze revenue", "datasource_id": "sales"}
}
```

Until the grant UI is implemented, the operator provisions
`<WORKING_DIR>/pawapp/task-policy.json`. Missing or invalid policy grants no
access. Replace this file atomically when changing it. A minimal scoped grant is:

```json
{
  "version": 1,
  "grants": [{
    "scope": {
      "principal_id": "alice",
      "workspace_id": "sales",
      "app_id": "qwenpaw-data"
    },
    "action_id": "analyze",
    "descriptor_digest": "<reviewed-action-descriptor-digest>",
    "input_values": {"datasource_id": ["sales"]}
  }]
}
```

Compute the digest offline from the reviewed descriptor using
`ActionDescriptor.model_validate_json(...).descriptor_digest`; the Data fixture
is `docs/design/pawapp-vnext-data-action.example.json`. A changed descriptor
requires a new grant. `input_values` constrains exact string input values;
omitting it grants the action for all input resources in that scope. Policy is
checked on each request and before recovery. It is a temporary explicit operator
policy, not a settings/approval UI or the full Skill/Tool permission bridge.

Host auth-disabled/bootstrap/trusted-host modes retain their existing behavior:
the principal is `default` when middleware supplies no authenticated user. That
identity still requires its own explicit grant and owned chat. These APIs add no
new authentication bypass. Same-process malicious plugin isolation is not claimed.

Data readiness checks durable submission compatibility, the Engine's actual
analysis-model configuration, and presence of the selected datasource in DataBridge.
It makes no provider or SQL query. Missing configuration yields `state: blocked`,
a reason, `setup: unsupported_setup`, and the registered App settings entry.
No task or latent execution is created: the caller explicitly retries after setup.
Readiness is rechecked immediately before each submission attempt. An already
accepted or uncertain request keeps its durable identity even when setup changes.
Readiness is not a connectivity guarantee or an authorization grant.

The `task_audit` table records dispatch intent, blocked outcomes and authorization
denials with scope and request identity, without prompts, credentials or output.
Task creation separately persists the request-to-task mapping and event history.

## Required executor protocol

Only adapters declaring `submission_protocol_version = 1` are accepted:

| Operation | Contract |
| --- | --- |
| `submit(TaskSubmission)` | Durably deduplicate `submission_id`, including concurrent retries and executor restarts; return the original `ExecutorRunRef`. |
| `query(TaskSubmission)` | Use its durable submission ID and trusted scope; return `accepted` with the original run, authoritative `not_found`, or `unknown`. Losing a response or acceptance history is `unknown`, not `not_found`. |
| `attach(TaskSubmission)` | Use its bound run and saved cursor; emit new events in executor sequence order, followed by explicit terminal status. |
| `command(TaskSubmission, TaskCommand)` | Apply the Host-persisted answer/cancel identity to the original run and return a durable outcome. |
| `query_command(TaskSubmission, TaskCommand)` | Reconcile the same command ID as `accepted`, `rejected`, authoritative `not_found`, or `unknown`. |

All three calls receive the persisted submission so query/replay can recover
the same scope after Host restart, without an adapter-local identity cache.
`attach` returns an async generator; the coordinator closes it on terminal
commit, cancellation, or error so its HTTP stream is released promptly.

Acceptance/deduplication records must remain queryable for the lifetime of the
Host task. An expired record cannot justify creating another execution.
`reconcile` queries the same identity. It may retry that identity only after
`not_found` and only if the Host has never recorded acceptance. A missing known
run stays unresolved. Changed descriptors block recovery until the compatible
registration is restored. Query failures preserve task state and recorded output.

Data's legacy `EngineClient.create_chat` remains the existing chat path. The
task adapter uses `POST /api/v1/submissions` and requires the Engine's explicit
protocol-1 capability probe. The verified development Engine is
[`183bca7`](https://github.com/cyruszhang/QwenPaw-Data/commit/183bca7)
on `dev/pawapp-vnext-engine`; no published minimum compatible version is claimed.
See the [Data adapter contract and integration command](pawapp-data-task-adapter.md).

## Main Chat tools and task cards

The Console chat entry point binds six tools to the authenticated principal,
resolved workspace and originating Main Chat:

| Tool | Behavior |
| --- | --- |
| `list_apps(intent="")` | Compact granted action catalog, optionally ranked by intent; no readiness probes or dispatch. |
| `describe_action(app_id, action_id)` | Full granted descriptor and digest, including the input schema and effects. |
| `delegate(app_id, action_id, inputs, request_id)` | Submit an independent delegated task, returning its durable handle or a setup blocker. |
| `get_app_task(app_id, task_id)` | Read status and text for a task delegated from this Main Chat. |
| `answer_task(app_id, task_id, command_id, request_id, answers)` | Answer the exact typed request currently pending on a task delegated from this chat. |
| `cancel_task(app_id, task_id, reason="")` | Request cancellation and return the task's durable command receipt. |

Action schemas are loaded on demand, rather than injected as a separate top-level
tool for every App action. Caller identity, workspace and return chat are captured
by the Host; the model cannot pass them as tool arguments. An in-memory private
request attribute carries this authority from Console ingress to agent assembly.
JSON requests and serialized history cannot create it. App sessions, archived
chats, other channels and subagents do not receive these tools. Legacy Console
identities that differ from the authenticated user remain usable for chat but do
not acquire task authority.

The tools use the standard permission wrapper and recheck the Host action grants
and input restrictions on invocation. Delegation namespaces the model's request
ID by the originating chat: retrying the same intent and inputs returns the same
task, while another chat's identical request ID is independent. Acceptance means
queued, not completed. Setup blockers create no latent work; after configuration,
the user must explicitly retry.

Both Console chat renderers use `PawAppTaskCard` for `delegate` and `get_app_task`.
The card validates the persisted handle and refreshes it through the authenticated
task API, explicitly retaining the task's workspace when the selected workspace
changes. It polls every two seconds until an authoritative terminal status, uses
event sequences to reject stale snapshots, and aborts pending reads on unmount or
a handle change. Refresh failures preserve the last output and offer a manual
retry. Recovery and partial output never imply successful completion. Setup links
are constructed from the App ID, not from a tool-supplied external URL. English
and Chinese labels are included; malformed results use the generic tool card.

Delegated waiting/terminal transitions schedule an assistant summary using
the workspace's configured model and language. The summary is appended to the
originating Main Chat when it becomes idle. This worker calls the model without
tools or runtime hooks. The next Main Chat turn can use the separately bound
answer/cancel tools; arbitrary follow-on action execution remains a separate gate.

## Events and recovery

Executor and Host event sequences are distinct. An executor event includes its
run identity, sequence, opaque cursor, optional status, optional complete text
snapshot and structured detail. Host-created events also advance the Host
sequence. Replayed source events are deduplicated; changed content under the same
source identity is rejected. Out-of-order source events and replacement runs are
rejected. Adapters must preserve source order and reconnect for replay when needed.

Task status, text result, replay cursor, source sequence, event and delivery
intents commit in one transaction. Success requires a persisted text result
(possibly supplied by an earlier event). Terminal states cannot be overwritten.
EOF and transport failure record recovery state without inferring success or
interruption. Only an authoritative executor event can establish interruption.

An `ask_user_question` tool call projects a bounded `input_request` onto the task
and ends that attachment at an intentional waiting boundary. The Host validates
answer question identities, option labels and selection cardinality against this
snapshot before persisting a command. Waiting tasks are not polled until a
command exists; replay after an answer clears the request when the matching tool
result arrives.

The Host records each answer/cancel meaning under a stable command ID before
external I/O. Same-ID retries return the same receipt; changed answer content is
`command_conflict`. A stale answer is rejected, while cancellation before
submission terminalizes locally without dispatch. Once a run exists, terminal
executor state wins cancellation races and its partial output remains available.
Uncertain sends are reconciled through the executor receipt rather than assigned
a new identity.

Delegated waiting/terminal transitions create a continuation intent for the
original Main Chat, in addition to a task update. Direct tasks create only updates
for their App session. Reading pending deliveries does not consume them;
acknowledgment is idempotent and persists separately after the destination has
durably recorded the event identity. These receipts do not promise exactly-once
LLM computation or arbitrary tool side effects.

## Durable Main Chat summaries

`ContinuationWorker` starts after the Host task runtime and stops before it.
Each continuation job snapshots the App/action/task IDs, actual status and up
to 16,000 characters of text. The prompt treats these fields as untrusted data
and reports truncation. It does not forward an App's private history or tools.
Queued waiting prompts are suppressed if the task has since changed status.

Workers claim jobs with expiring tokens, renew leases while generating and
recheck ownership before every durable write. Pending jobs serialize per
principal/workspace/return session. The existing `TaskTracker` also serializes
them with ordinary user turns: a busy chat defers the summary without attaching
a subscriber or invoking the model. Authorization, chat ownership and workspace
availability are checked before generation and again before session commit.

Prepared assistant messages are persisted before delivery, so retries reuse
the same message and stable run ID. The session appends the message and its
receipt atomically under its path lock while the SQLite transaction fences
other delivery workers. If the Host crashes after the session write but before
outbox acknowledgment, the receipt prevents another append. Ordinary session
saves preserve these receipts outside model context and compaction. Cancellation
waits for an in-progress session transaction before releasing the chat lock.
Only committed messages enter the live SSE stream; reconnect/reload reads the
durable session. Transport delivery and model computation are not exactly once.

Model generation has a 120-second timeout and at most three attempts per event.
A user stop or exhausted attempts halts that job without blocking later updates;
the task result remains readable in its card and `get_app_task`. There is no
summary retry UI yet. Authority/configuration/storage failures defer delivery.
The initial worker supports the `qwenpaw` backend with `SafeJSONSession`; other
backends and unmigrated legacy-memory sessions defer delivery. Continuation
workers have durable fences, but ordinary Chat execution still assumes one Host
process. This is not distributed fencing for all chat writers or unrestricted
Main Agent tool continuation.

## Scoped runtime capabilities

PawApps declare their runtime imports in the typed top-level `pawapp` manifest
section. `host_tools` and `host_skills` name capabilities already enabled in the
selected Host workspace. `local_tools` and `local_skills` declare App-private
registrations created with `@app.local_tool(...)` and `app.local_skills(...)`;
they are never added to the Host agent's global catalogs. Skill declarations
carry explicit `tool_refs`, and a Skill with a missing dependency remains visible
but blocked with `skill_dependency_unavailable`.

`ctx.tools.list/describe/invoke` and `ctx.skills.list/load` resolve only this
App/workspace/principal scope. Host-public tool calls are reconstructed through
`PolicyGuardedTool`, so the normal governance decision runs before execution.
Capability IDs include their ownership boundary (`host/tool/...`,
`app/tool/...`, `host/skill/...`, or `app/skill/...`); name collisions receive
stable `host__` and `app__` runtime names. Every describe denial, invocation,
and Skill load writes a metadata-only JSONL audit record without inputs, outputs,
or bearer tokens.

Independent Engine submissions receive a signed callback envelope containing
only protocol version, Host endpoint, and a token bound to the durable task's
principal/workspace/App/session identity. The Engine must advertise
`scoped_host_capabilities: true`. During agent construction it fetches the
scoped catalog once, exposes remote tools through AgentScope `FunctionTool`, and
materializes Skill files under the Engine workspace with path, encoding, count,
and size checks. The Engine cannot widen scope from request text or model output;
unknown and cross-scope capability IDs fail closed at the Host.

## Validation and remaining P1a integration

`tests/unit/pawapp/test_task_store.py` exercises concurrent request retries,
scope denial, SQLite rollback on injected outbox failure, event replay, result
retention, terminal immutability, origin-specific delivery and durable receipts.
A labelled executor simulator exercises Host recovery before acceptance, after
acceptance but before confirmation, after partial output and after terminal commit
but before destination acknowledgment. This verifies the Host implementation;
it is not a real Data engine or Main Chat end-to-end test.

`tests/integration/test_pawapp_data_tasks.py` additionally runs the adapter and
coordinator against a separate Engine process with real HTTP/SSE, SQL receipt
creation, and startup recovery. Its executor emits controlled text without a
provider call. The tests verify both engagements, concurrent delegation,
uncertain submissions, Host store reopen, forced Engine restart, a real
clarification pause/answer/resume, idempotent command receipts, and cancellation
that retains partial output. They do not exercise a live Main Agent, UI, or
analytical tools.

`test_task_runtime.py` verifies HTTP authentication, forged scope claims,
cross-user reads, origin/resource denial, blocked setup without latent work,
idempotency, lifecycle recovery, unload and schema migration.
`test_pawapp_task_dispatch.py` verifies authenticated Host HTTP dispatch through
the real separate Engine process for both engagements, with controlled execution
and a fixture datasource catalog. It also exercises Console chat ingress, channel
request conversion, runtime context, bound agent tools and the card status API
against that Engine, then delivers the result into the originating Main Chat
session through the continuation worker. Controlled tool calling and summary
generation replace model calls; this is not a live-model or browser end-to-end
test.

`test_task_continuation.py` covers busy-chat serialization, concurrent claims,
expired-worker fencing, prepared-result replay, a crash between session commit
and acknowledgment, transcript/receipt preservation, authority revocation,
shutdown, user stop, bounded model retries, schema migration, stale waiting
prompts, and publishing only committed output to live subscribers.

`test_task_agent_tools.py` covers scoped discovery, schema loading, retries,
blocked setup, grant revocation, invalid App IDs, cross-chat isolation and private
invocation authority. `PawAppTaskCard.test.tsx` covers progress, completion,
recovery, refresh failure/retry, stale responses, newer history snapshots,
unmount cleanup, setup links and handle validation.

Remaining integration includes a grant UI and general Main Agent continuation
with follow-on tools. Artifact Canvas and cross-App Exchange are not part of this
implementation.
