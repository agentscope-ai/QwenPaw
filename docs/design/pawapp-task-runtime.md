# PawApp vNext task runtime

The `qwenpaw.pawapp.tasks` package provides durable Host tasks, authenticated
HTTP dispatch and recovery through the Host lifecycle. Main Chat can discover
granted actions, delegate tasks and follow their progress in Console task cards.
The Data
[adapter](../../plugins/apps/qwenpaw-data/backend/task_bridge/adapter.py)
implements this boundary against the Engine's durable submission API. Its
server-owned descriptor matches the [example](pawapp-vnext-data-action.example.json);
neither the descriptor nor adapter registration is a permission grant.

## Host ownership

The Host creates one `TaskStore` at a Host-owned path in its working directory
using `await TaskStore.open(path)`. SQLite owns task facts, action/input snapshots,
submission identities, run mappings, events, replay cursors and delivery receipts.
The file uses schema version 2, with an additive migration from version 1 for
boundary audit records; unsupported versions are rejected. Connections
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
[`89cc1d2`](https://github.com/cyruszhang/QwenPaw-Data/commit/89cc1d2c65983d4c0135b8db6f5f4ba712e2d55e)
on `dev/pawapp-vnext-engine`; no published minimum compatible version is claimed.
See the [Data adapter contract and integration command](pawapp-data-task-adapter.md).

## Main Chat tools and task cards

The Console chat entry point binds four tools to the authenticated principal,
resolved workspace and originating Main Chat:

| Tool | Behavior |
| --- | --- |
| `list_apps(intent="")` | Compact granted action catalog, optionally ranked by intent; no readiness probes or dispatch. |
| `describe_action(app_id, action_id)` | Full granted descriptor and digest, including the input schema and effects. |
| `delegate(app_id, action_id, inputs, request_id)` | Submit an independent delegated task, returning its durable handle or a setup blocker. |
| `get_app_task(app_id, task_id)` | Read status and text for a task delegated from this Main Chat. |

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

Task completion still does not schedule a new Main Agent turn automatically.
Continuation delivery, user answers and cancellation remain separate gates.

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

Delegated waiting/terminal transitions create a continuation intent for the
original Main Chat, in addition to a task update. Direct tasks create only updates
for their App session. Reading pending deliveries does not consume them;
acknowledgment is idempotent and persists separately after the destination has
durably recorded the event identity. These receipts do not promise exactly-once
LLM computation or arbitrary tool side effects.

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
uncertain submissions, Host store reopen, and forced Engine restart. They do
not exercise a live Main Agent, UI, or analytical tools.

`test_task_runtime.py` verifies HTTP authentication, forged scope claims,
cross-user reads, origin/resource denial, blocked setup without latent work,
idempotency, lifecycle recovery, unload and schema migration.
`test_pawapp_task_dispatch.py` verifies authenticated Host HTTP dispatch through
the real separate Engine process for both engagements, with controlled execution
and a fixture datasource catalog. It also exercises Console chat ingress, channel
request conversion, runtime context, bound agent tools and the card status API
against that Engine. A controlled tool caller replaces the LLM; this is not a
live-model or browser end-to-end test.

`test_task_agent_tools.py` covers scoped discovery, schema loading, retries,
blocked setup, grant revocation, invalid App IDs, cross-chat isolation and private
invocation authority. `PawAppTaskCard.test.tsx` covers progress, completion,
recovery, refresh failure/retry, stale responses, newer history snapshots,
unmount cleanup, setup links and handle validation.

Remaining integration includes a grant UI,
durable answer/cancel receipts,
continuation worker leases and destination deduplication, and the Host/public plus
App/private Skill/Tool runtime bridge. These are still P1a gates. Artifact Canvas
and cross-App Exchange are not part of this implementation.
