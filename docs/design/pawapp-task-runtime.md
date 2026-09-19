# PawApp vNext task runtime

The `qwenpaw.pawapp.tasks` package provides durable Host tasks, authenticated
HTTP dispatch and recovery through the Host lifecycle. Main Chat can discover
granted actions, delegate tasks and follow their progress in Console task cards.
Delegated waiting/terminal updates queue automatic, scoped Main Agent turns in
the originating Main Chat.
The Data
[adapter](../../plugins/apps/qwenpaw-data/backend/task_bridge/adapter.py)
implements this boundary against the Engine's durable submission API. Its
server-owned descriptor matches the [example](pawapp-vnext-data-action.example.json).
Creator's public delegated workflow is captured by the exact
[`create-video` descriptor](pawapp-vnext-creator-create-video-action.example.json).
The existing [storyboard](pawapp-vnext-creator-storyboard-action.example.json) and
[video](pawapp-vnext-creator-video-action.example.json) descriptors are App-private
implementation actions. Neither a descriptor nor adapter registration is a
permission grant.

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
Registration metadata also declares `exposure` (`host_public` or `app_private`)
and disjoint eager/deferred requirement IDs. Private actions are absent from
catalog, description and grant management, and reject new external dispatch,
while their bindings remain available to reconcile and terminally deliver tasks
accepted before an action became private. Grants remain descriptor/action scoped:
a public `create-video` grant never authorizes either private media action.
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
| `POST /tasks/{task_id}/open` | Mint a local authenticated handoff for the task's published project reference. |
| `POST /tasks/{task_id}/answer` | Persist and deliver an answer for the handle's current typed input request. |
| `POST /tasks/{task_id}/cancel` | Persist cancellation intent and target the original submission/run. |
| `GET /tasks/{task_id}/events?after=0&limit=100` | Ordered replay after the Host event sequence; maximum page size 1000. |
| `POST /setup-requests/{request_id}/open` | Resolve one linked setup request to a validated local App path. |

Action preparation and task submission accept only `request_id`, `chat_id`,
`engagement` and `inputs`. For example, use an existing owned Main Chat ID with:

```json
{
  "request_id": "analysis-request-1",
  "chat_id": "<existing-chat-id>",
  "engagement": "delegated",
  "inputs": {"text": "Analyze revenue", "datasource_id": "sales"}
}
```

The operator manages grants under **Settings → App access** for the selected
agent/workspace. The authenticated Host route lists only live registered action
descriptors; updates name an App/action and optional exact string input limits.
The browser cannot supply a descriptor digest, permission list, effect list, or
principal. Host resolves those values from the current registration, pins the
complete digest, applies optimistic policy revisions, writes atomically, and
audits enable/revoke changes. The PawApp SDK and task execution APIs expose no
policy mutation.

The durable policy remains `<WORKING_DIR>/pawapp/task-policy.json`, so an operator
can also provision it offline. Missing or invalid policy grants no access. A
minimal scoped grant is:

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
`ActionDescriptor.model_validate_json(...).descriptor_digest`; public fixtures are
`docs/design/pawapp-vnext-data-action.example.json` and
`docs/design/pawapp-vnext-creator-create-video-action.example.json`. The Creator
storyboard/video descriptor fixtures document App-private implementation actions
and cannot receive new external grants. A changed descriptor requires a new grant. `input_values` constrains exact string input values; omitting
it grants the action for all input resources in that scope. Policy is checked on
each request and before recovery. Granting an action does not configure its
provider, satisfy readiness, approve a future prompt, or expand the separate Host
Tool/Skill capability policy.

Host auth-disabled/bootstrap/trusted-host modes retain their existing behavior:
the principal is `default` when middleware supplies no authenticated user. That
identity still requires its own explicit grant and owned chat. These APIs add no
new authentication bypass. Same-process malicious plugin isolation is not claimed.

Data readiness checks durable submission compatibility, the Engine's actual
analysis-model configuration, and presence of the selected datasource in DataBridge.
It makes no provider or SQL query. Apps can declare typed requirements and register
bounded readiness checks plus setup entry handlers. Actionable blockers yield
`setup: required`; undeclared legacy blockers retain `setup: unsupported_setup`.

The Host persists setup requests in `setup.sqlite3`, scoped by principal, workspace,
and App. `POST .../actions/{action_id}/setup-requests` reauthorizes the origin,
reruns readiness, binds the idempotency key to the action inputs by digest, and
creates no task. `GET .../setup-requests/{request_id}`, `POST .../open`, and
`POST .../cancel` expose the request lifecycle. The registered App backend opens
the presentation and completes it with a typed, scoped receipt; browsers cannot
submit completion receipts. Raw action inputs and credentials are not stored in
the setup database; optional setup suggestions are explicitly non-secret.

Creator exposes two public delegated actions. `create-project` intentionally
creates and returns an empty workspace. `create-video` accepts the bounded
intent-level schema in its [descriptor fixture](pawapp-vnext-creator-create-video-action.example.json),
atomically creates the Project, Session, Conversation, initial Goal and initial
Message, and then lets Creator's existing Agent/work-graph runtime plan and
execute the work. It accepts no project, target, timeline, element, work-node,
provider-job, credential, source-upload, template or preauthorization IDs.

The v1 mapping normalizes line endings, strips only outer whitespace, applies
defaults before hashing, and persists the normalized input, mapping version,
submission identity and exact rendered-goal digest. Its immutable text is:

```text
[creator-video-workflow@1]
Submission: <submission_id>

Brief:
<brief>

User script:
<script, or "Not provided; create a script from the brief.">

Production constraints:
- project_name: <resolved name>
- description: <description, or "Not provided.">
- scenario: <scenario>
- aspect_ratio: <aspect_ratio>
- resolution: <resolution>
- content_type: <content_type, or "Not specified.">
- duration_seconds: <integer, or "Not specified.">
- language: <language>
- completion: publish one final composed video
```

When `name` is absent, Creator uses the first non-empty brief line, normalized to
at most 96 characters, then appends `-` and the first 12 hexadecimal characters
of `sha256(submission_id)`. An explicit duplicate name is a durable business
failure. Replay uses the stored v1 meaning; changing this rendering requires a
new mapping version and adapter reference.

Creator's LLM requirement is eager. If unavailable, dispatch returns the existing
blocked/setup result and creates no task, Project or workflow; the caller retries
the same request after setup. Image and video requirements are deferred until
their earliest actionable work stages, image first when both are observed. A
`waiting_for_setup` handle links exactly one Host request with its input digest
and monotonic attempt. The Console or `open_task_setup` asks Host for the local
App path; neither caller constructs it. A saved setup result is rechecked rather
than treated as ready. If still unready, Host advances the attempt and creates or
reuses the next deterministic request. Cancelled setup cancels the workflow;
failed, expired or unrecoverable setup fails it. Setup never grants approval or
starts a provider call.

A correlated pending execution authorization becomes a typed
`waiting_for_approval` request with `Approve once` and `Do not run`. It shows the
immutable operation, semantic target, provider/model, candidate count, duration,
resolution, aspect ratio and other billing-relevant arguments without tokens or
internal references. Answering uses Creator's existing authorization
compare-and-set. Readiness and the authorization fingerprint are rechecked
immediately before dispatch; changed configuration or inputs require a new
approval.

The workflow derives one graph snapshot and observes only the receipt's exact
goal/run/round/task chain. Ready or regeneration-ready nodes remain owned by the
Creator runtime. Success requires exactly one live non-snapshot narrative
timeline whose selected, non-stale `final_video` is an indexed `video/*` file,
whose compose node is `DONE`, and whose selections/read set/fingerprint are
current. Zero or multiple live timelines fail when no explicit recovery state can
resolve them; the multiple-timeline result tells the user to open Creator, leave
one live timeline and start again without exposing timeline IDs.

Publication stores a verified Creator source receipt separately from a
source-bound Host publication intent and completed `ArtifactRef`. The receipt
keeps the graph compose fingerprint distinct from the executor/render request
fingerprint and verifies the durable dispatch key that binds them. Bytes are read
through Creator's verified asset store. Before terminal success, the workflow
rereads the Project under its lock and republishes if the canonical source was
superseded. Success returns non-empty text, the latest `creator-project`
`ProjectRef`, and exactly one bound Host artifact. A Creator run, completed shots
or script completion alone is nonterminal.

The workflow lock linearizes cancellation and publication. Cancellation before a
publication intent wins, expires only correlated authorization, stops only
correlated active work and preserves the Project and partial outputs. Once the
intent is durable, publication reconciliation determines eventual success or a
proven unrecoverable publication failure; cancellation cannot produce a cancelled
terminal result. An ambiguous publish remains `publishing` and reuses the same
intent after restart.

The App-private `generate-storyboard` and `generate-video` adapters continue to
reconcile previously accepted tasks, but cannot be newly listed, described,
granted or externally dispatched. Their existing-project IDs stay internal to
Creator. Registering any action does not grant it; the Host policy must contain a
matching public descriptor grant.

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

The Console chat entry point binds eight tools to the authenticated principal,
resolved workspace and originating Main Chat:

| Tool | Behavior |
| --- | --- |
| `list_apps(intent="")` | Compact granted public-action catalog, optionally ranked by intent; no readiness probes or dispatch. For Creator video intent, choose `create-video`; use `create-project` only for an explicitly empty workspace and never ask for Creator internal IDs. |
| `describe_action(app_id, action_id)` | Full granted public descriptor and digest, including the input schema and effects. |
| `delegate(app_id, action_id, inputs, request_id)` | Submit an independent delegated task, returning its durable handle or an eager setup blocker. |
| `get_app_task(app_id, task_id)` | Read status and text for a task delegated from this Main Chat. |
| `open_app(app_id, task_id)` | Ask Host to mint a local authenticated handoff for the task's project reference. |
| `open_task_setup(app_id, task_id)` | Ask Host to resolve the task's active linked setup request to a validated local App path. |
| `answer_task(app_id, task_id, command_id, request_id, answers)` | Answer the exact typed input or approval request currently pending on a task delegated from this chat. |
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
retry. Recovery and partial output never imply successful completion. A linked
setup button calls the Host open endpoint and accepts only a validated local path
under that App. Typed input and approval requests render from the generic question
schema; answer submission preserves one command ID across uncertain retries and
refreshes immediately. Project handoffs and final artifacts use generic controls,
with no interpretation of Creator element, timeline, work or provider IDs. English
and Chinese labels are included; malformed results use the generic tool card.

Delegated waiting/terminal transitions schedule a server-created Main Agent turn
in the originating Chat when it becomes idle. The turn passes through the normal
Runtime, so the agent receives its standard governed tools plus the task tools
bound to that principal, workspace and Chat. A Host-owned system instruction
treats every task-event field as untrusted data. Follow-on work is allowed only
when the user's existing request and current policy already authorize it; the App
result does not grant new authority.

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
and ends that attachment at an intentional waiting boundary. The same request is
legal for `waiting_for_approval`, allowing an App adapter to project an immutable
external authorization as ordinary typed questions. The Host validates request
identity, exact question text, option labels and selection cardinality before
persisting a command. Waiting tasks are not polled until a command exists; replay
after an answer clears the request when the matching tool result arrives.

A `waiting_for_setup` event may carry exactly one bounded requirement ID, stable
reason code and user-facing reason. The task atomically stores one opaque setup
request ID and monotonic attempt. Setup and approval are independent: neither
transition grants, answers or mutates the other, and neither changes action grants.

The Host records each answer/cancel meaning under a stable command ID before
external I/O. Same-ID retries return the same receipt; changed answer content is
`command_conflict`. A stale answer is rejected, while cancellation before
submission terminalizes locally without dispatch. For ordinary adapters, terminal
executor state wins cancellation races and partial output remains available. An
adapter with a durable publication intent may define a stricter cutoff: Creator's
`create-video` rejects cancellation after that intent and reconciles publication
to success or a proven publication failure. Uncertain sends are reconciled through
the executor receipt rather than assigned a new identity.

Delegated waiting/terminal transitions create a continuation intent for the
original Main Chat, in addition to a task update. Direct tasks create only updates
for their App session. Reading pending deliveries does not consume them;
acknowledgment is idempotent and persists separately after the destination has
durably recorded the event identity. These receipts do not promise exactly-once
LLM computation or arbitrary tool side effects.

## Durable Main Chat continuation

`ContinuationWorker` starts after the Host task runtime and stops before it.
Each continuation job snapshots the App/action/task IDs, actual status and up
to 16,000 characters of text. The Host injects a trusted continuation policy
into the Main Agent system prompt; the structured event remains untrusted user
data. It does not forward an App's private history or private tools. Queued
waiting prompts are suppressed if the task has since changed status.

Workers claim jobs with expiring tokens, renew leases while generating and
recheck ownership before every durable write. Pending jobs serialize per
principal/workspace/return session. The existing `TaskTracker` also serializes
them with ordinary user turns: a busy chat defers the continuation without
attaching a subscriber or invoking the model. Authorization, chat ownership and
workspace availability are checked before generation and again before session
commit.

The worker durably prepares a stable agent-turn identity before invoking the
Runtime. Session save writes the complete agent state, continuation receipt and
outbox acknowledgment as one fenced operation under the session path lock. If
the Host crashes after the session write but before SQLite commit, the receipt
lets a retry acknowledge the event without rerunning the agent or its tools.
Ordinary session saves preserve these receipts outside model context and
compaction. The synthetic event stays in model context but is tagged and omitted
from the visible user transcript. Live SSE is buffered until commit;
reconnect/reload reads the durable session.

Generation has at most three attempts per event. A user stop or exhausted
attempts halts that job without blocking later updates; the task result remains
readable in its card and `get_app_task`. There is no continuation retry UI yet.
Authority/configuration/storage failures defer delivery. PawApp delegation from
a continuation derives its submission identity from the continuation, action
and inputs, so a model retry cannot create a duplicate downstream App task.
Other tool side effects retain their normal governance and idempotency semantics;
a process crash during an uncommitted non-idempotent tool call remains subject to
that tool's recovery contract. The worker supports the `qwenpaw` backend with
`SafeJSONSession`; other backends and unmigrated legacy-memory sessions defer
delivery. Prepared tool-free summaries from older Host versions remain replayable.
Continuation workers have durable fences, but ordinary Chat execution still
assumes one Host process rather than distributed Chat writers.

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

## Static installation and explicit activation

An App with `type: "app"` and a versioned top-level `pawapp` section installs as
an inert package. Local, URL and upload installs copy the package and validate its
typed manifest, Host version range and declared entry points. They do not install
dependencies, import the backend, run lifecycle hooks or execute the frontend.
Legacy plugins and Apps without the typed section retain their existing hot-load
behavior.

The plugin and PawApp catalogs read manifests from disk and expose an inactive
App with `activation_status: "installed"`. Console startup does not load its
frontend bundle. Opening that App explicitly calls the authenticated activation
endpoint; the Host then installs dependencies, imports and registers the backend,
runs post-load integration and only afterward records activation. Console executes
the frontend entry after that request succeeds.

Activation is stored outside the package in a private marker bound to the parsed
manifest digest. A matching marker permits startup to activate the same package.
A force replacement clears the marker and unloads prior runtime registrations, so
the replacement remains inert until it is opened again. Failed activation unloads
the partial runtime and leaves no marker. Uninstall removes both package files and
the marker.

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
cross-user reads, origin/resource denial, digest-pinned grant updates, resource
constraint validation, concurrent policy revisions, revocation, blocked setup
without latent work, idempotency, lifecycle recovery, unload and schema migration.
`test_pawapp_task_dispatch.py` verifies authenticated Host HTTP dispatch through
the real separate Engine process for both engagements, with controlled execution
and a fixture datasource catalog. It also exercises Console chat ingress, channel
request conversion, runtime context, bound agent tools and the card status API
against that Engine, then delivers the result into the originating Main Chat
session through the continuation worker. A controlled legacy summary path
replaces the provider call in this integration fixture; unit coverage exercises
the full Runtime turn, scoped task tools and atomic agent-state receipt. This is
not a live-model or browser end-to-end test.

`test_task_continuation.py` covers busy-chat serialization, concurrent claims,
expired-worker fencing, prepared-result replay, a crash between session commit
and acknowledgment, transcript/receipt preservation, authority revocation,
shutdown, user stop, bounded model retries, schema migration, stale waiting
prompts, and publishing only committed output to live subscribers.

`test_task_agent_tools.py` covers scoped discovery, schema loading, retries,
blocked setup, Host-resolved linked setup, grant revocation, invalid App IDs,
cross-chat isolation and private invocation authority. `PawAppTaskCard.test.tsx`
and `pawappTasks.test.ts` cover progress, recovery, stale snapshots, validated
setup navigation, typed approval/input submission, stable retry IDs, project
handoff and artifact preview without App-specific IDs.

Creator's workflow suites cover exact input/mapping snapshots, atomic bootstrap,
crash recovery, correlation/precedence collisions, independent setup and approval,
saved-but-unready retries across restart, canonical-selector parity, verified
publication and supersession, all cancellation/publication orderings, and private
action migration/grant isolation. The final validation gate is the isolated
fake-provider real-App acceptance: Main Chat delegation, task-card reload,
Creator execution, canonical artifact access and Main Chat continuation, with a
hard failure if any real provider is selected. The separate limited real-provider
runner remains opt-in and requires fresh confirmation before any billable call.
Cross-App Exchange is not part of this implementation.
