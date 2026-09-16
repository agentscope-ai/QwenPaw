# PawApp vNext task runtime

The internal `qwenpaw.pawapp.tasks` package implements the Host storage and
adapter boundary for P1a. It is not registered with the application lifecycle,
HTTP routes, Main Agent tools or Data Console yet. The Data action
[example](pawapp-vnext-data-action.example.json) is a validated contract fixture,
not an enabled action or a permission grant.

## Host ownership

The Host creates one `TaskStore` at a Host-owned path in its working directory
using `await TaskStore.open(path)`. SQLite owns task facts, action/input snapshots,
submission identities, run mappings, events, replay cursors and delivery receipts.
The file uses schema version 1; unsupported versions are rejected. Connections
use WAL, full synchronous commits and short transactions on worker threads.

`app/task_tracker.py` continues to track active Main Chat execution and stream
attachments. `pawapp.task.SSEChannel` remains available to Agent Kanban and other
App-owned streams. The unused in-memory `TaskManager` and its singleton have been
removed; they did not provide durable task endpoints.

## Registration and dispatch

- Register an `ActionDescriptor` and its `TaskAdapter` on `TaskCoordinator` at
  Host startup. The descriptor contains the App/action IDs, supported engagements,
  JSON Schema 2020-12 input schema, permission tags, effects, output types and
  server-owned adapter reference. Schemas must be self-contained; remote `$ref`
  resolution is prohibited. The Host stores a digest of the descriptor snapshot.
- The coordinator requires an asynchronous `authorize(scope, action, origin, inputs)`
  callback. The production binding must check Host policy, datasource/resource
  permissions and ownership of the referenced originating session. Scope must
  come from authenticated Host context, not from request JSON or model output.
  There is no default allow policy. The example's permission tags still need a
  production policy mapping. The callback receives independent descriptor/input
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

## Required executor protocol

Only adapters declaring `submission_protocol_version = 1` are accepted:

| Operation | Contract |
| --- | --- |
| `submit(TaskSubmission)` | Durably deduplicate `submission_id`, including concurrent retries and executor restarts; return the original `ExecutorRunRef`. |
| `query(submission_id)` | Return `accepted` with the original run, authoritative `not_found`, or `unknown`. Losing a response or acceptance history is `unknown`, not `not_found`. |
| `attach(run_ref, cursor)` | Replay events after the saved cursor in monotonically increasing executor sequence order; then stream live events with explicit terminal status. |

Acceptance/deduplication records must remain queryable for the lifetime of the
Host task. An expired record cannot justify creating another execution.
`reconcile` queries the same identity. It may retry that identity only after
`not_found` and only if the Host has never recorded acceptance. A missing known
run stays unresolved. Changed descriptors block recovery until the compatible
registration is restored. Query failures preserve task state and recorded output.

The current Data `EngineClient.create_chat` and engine request model do **not**
implement this protocol. They are not adapted by pretending Host-side deduplication
is sufficient. A compatible engine release must be implemented and verified before
enabling the Data action or choosing a minimum compatible version.

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

Remaining integration includes authenticated routes and origin/resource binding,
policy and denial auditing, readiness/blocked responses, the real Data adapter and
engine protocol, task cards and Main Agent tools, durable answer/cancel receipts,
continuation worker leases and destination deduplication, and the Host/public plus
App/private Skill/Tool runtime bridge. These are still P1a gates. Artifact Canvas
and cross-App Exchange are not part of this implementation.
