# PawApp vNext: Data task adapter

## Delivery and prerequisites

This integration is delivered separately from the shared SDK/Creator work in
[QwenPaw #7874](https://github.com/agentscope-ai/QwenPaw/pull/7874). It requires
that SDK plus the Engine implementation in
[QwenPaw-Data #85](https://github.com/agentscope-ai/QwenPaw-Data/pull/85).
The Data-only branch is based on main so its diff contains only this integration;
it must be rebased after #7874 merges before it is independently runnable.

It adds public `analyze` and Direct-only `analyze-session`, native Console task
submission and commands, scoped Engine event/result mapping, App-local tools
and skills, and native SDK managed-service registration. Existing released
model settings and Data UI behavior are preserved.

The generic SDK and Creator adaptation remain in #7874. File Browser is a
separate example-app PR; neither App integration depends on the other.
App-owned typed setup-entry migration is a separate follow-up: this adapter
retains its existing readiness checks and generic App settings link.

## Tested Engine pairing

[`tests/fixtures/pawapp-compatibility.json`](../../tests/fixtures/pawapp-compatibility.json)
is the machine-readable pairing. It pins Engine revision
`a7fdc606c6bb73efdb688389380dd7ec6f24c783` from `cyruszhang/QwenPaw-Data`.
Run `python scripts/prepare-pawapp-engine.py /path/to/engine` to verify it.
The dedicated `PawApp Data Integration` workflow installs isolated Host/Engine
environments and checks the adapter, HTTP/SSE recovery and both session stores.
Before release, reconcile the pin with the merged Engine revision and choose
the Data App release version; this extraction does not bump or publish a version.

## Adapter boundary

The Data App's `backend/task_bridge` package connects `TaskCoordinator` to
Engine submission protocol 1. It can submit, reconcile, and consume independent
analysis tasks in Direct or Delegated mode. The Data App declares its action
through `PawApp.task_action`; Host owns adapter lifecycle, scoped HTTP dispatch,
grants, readiness and recovery. Main Chat tools and Console task cards now use
this boundary; see the [Host task runtime](pawapp-task-runtime.md). A durable
Host worker resumes the originating Main Agent through its normal Runtime and
governed tools after the Chat becomes idle.

## Binding and compatibility

The Host binding supplies:

- An endpoint resolver returning the managed Engine's current `(base_url, token)`.
  Resolve both together per operation; reconnect can discover a changed port.
  Inputs and model output must never choose this endpoint or credential.
- A stable `executor_id` for that Engine database/installation. A port change
  retains the ID. Replacing/resetting the database is not transparent failover.
- `data_action_descriptor()` and an explicit Host authorization callback.
  The descriptor supports `analyze(text, datasource_id)` and both engagements.
  The Host grant pins its descriptor digest and can constrain datasource IDs.
- Ownership of the adapter's connection pool: call `await adapter.aclose()`
  during shutdown after task consumers stop.
- A deterministic, signed capability envelope bound to the submitted Host task.
  Engines must advertise `scoped_host_capabilities: true`; the adapter refuses
  older engines before it sends a submission containing this envelope.
- A Host-owned immutable artifact store. Engines must advertise
  `artifact_handoff: true`; registered files are copied and verified before
  their references enter the durable task.

The adapter probes `GET /api/v1/capabilities/submissions` before each operation.
Only protocol version 1 with durable submission, replay, and artifact handoff
support is accepted.
Answer/cancel operations additionally require `durable_commands: true`.
Older Engines and JSON mode cannot fall back to the legacy session/chat POSTs.
`check_compatibility(scope)` is available to the Host readiness binding;
unsupported submission raises `unsupported_engine_protocol` before POST.
`readiness(scope, inputs)` additionally requires
`GET /api/v1/capabilities/analysis` readiness version 1, checks the Engine's
analysis model configuration, then finds the requested source in
`GET /api/v1/datasources`. Older readiness endpoints block explicitly. These
read-only checks do not invoke a model or execute SQL. The Engine checks the same
local Agent Configuration/environment fallback used by independent runs; the
DataBridge semantic model is a separate configuration.

Host returns blocked setup with `/apps/qwenpaw-data` as the App settings entry
and creates no task until explicit retry succeeds. The entry opens the existing
Data Console, whose Agent Configuration and datasource pages own setup in P1a.
There is no Host-native setup form yet. See the
[runtime routes and operator grant contract](pawapp-task-runtime.md).

The compatible Engine must include the `artifact_handoff` submission capability
and digest-bound artifact reads. This is a development dependency, not yet a
released minimum version. Host and Engine run in separate dependency
environments and communicate only over HTTP/SSE.

## Scope and recovery

`submit`, `query`, `attach`, `command`, and `query_command` receive the persisted
`TaskSubmission`. Its
trusted principal/workspace/App scope is hashed into a stable Engine
`X-User-Id` namespace. The adapter holds no task→scope/run map in memory, so a
fresh adapter can reconcile an existing task. The Engine header is a business
stamp under service-token authentication, not independent tenant authorization.
Host must authenticate the caller, resolve scope, authorize resources and origin
ownership, and keep the token out of the browser.

`submit` sends the Host's existing `submission_id`; retries preserve it.
`query` returns `not_found` only for the explicit protocol response matching
that ID. Timeouts, HTTP errors (including 404), malformed responses, and failed
capability checks are `unknown`. A known accepted run whose data is unavailable
retains its original identity; replay fails rather than creating a replacement.

Before replay, `attach` queries the scoped receipt and verifies that its
session/run IDs equal Host's persisted mapping. The stable `executor_id` must
also match. Endpoint redirects are not followed and HTTP errors do not include
response bodies or credentials.

## Event projection

### Explicit analysis experience (2026-09-23)

Engines advertising `analysis_experience: true` emit `analysis.progress`
with an App-owned stage: `read_data`, `confirm_scope`, `analyze`, or
`publish_report`. The adapter translates these into generic TaskExperience
step IDs; the Host renderer does not understand SQL or Data-specific events.
Replay retains the last declared stage across ordinary text/file events.
Waiting for input and terminal success still take precedence. Event counts
and file creation are not evidence of analytical progress.

The Engine's private `report_analysis_progress` and
`publish_analysis_artifact` tools let its domain agent declare progress and
select deliverables. Each artifact can carry the shared presentation contract
(`schema_version`, `role`, `kind`, `visibility`, `preview`, `rank`). New Engine
automatic file discovery explicitly emits diagnostic/app-only artifacts;
only intentional publication selects reports/charts for Main Chat. Valid
explicit metadata overrides filename heuristics. Legacy events without
metadata retain the compatibility classifier; this is not a new-app contract.
Presentation is not authorization: all downloads still require scoped access.

The Data Console consumes `paw_view=evidence` as its artifacts workspace and
`paw_view=diagnostics` as its trace workspace. Unknown hints open the ordinary
turns view; hints cannot select arbitrary URLs or transfer interaction ownership.

### Native Console admission

The native Console's chat POST now enters the same Host coordinator through
the Direct-only `analyze-session` action. It requires an explicit grant, a
stable `X-Request-Id`, and Engine `session_submissions: true`. The submission
retains the existing Engine session, attachment IDs and artifact comments.
Its datasource selector is optional: Console `null` becomes an omitted input.
An unselected datasource requires Engine `optional_session_datasource: true`;
model and session readiness still apply. The delegated action continues to
require a named datasource, and datasource-restricted grants reject unscoped
Direct inputs. Upgrading this Direct schema changes its grant digest.
Scoped `submission-readiness` checks reject legacy/unavailable or busy sessions
before task creation; the Engine transaction rechecks ownership and concurrency.
The Host stamps Engine calls with the authenticated principal/workspace
namespace and records a deterministic, App-owned ChatSpec as the Direct origin.
Completion stays in the App; it does not wake Main Chat.

Native clarification and cancellation resolve the scoped persisted run mapping
and use durable task commands. Raw browser submission endpoints are denied;
uncertain admission must be retried with the same request ID, never through
legacy chat creation. This does not make every legacy Engine read API tenant
isolated: the Engine remains a trusted service behind the Host.

Upgrade constraints: legacy sessions created under the unscoped Engine identity
are not silently adopted. Start a new scoped session (or perform a separately
reviewed migration). Legacy unmanaged runs cannot use durable task commands.
Nonempty dataset filters and disabled clarification are rejected explicitly,
not silently discarded. Existing `analyze` grants do not automatically grant
the new `analyze-session` descriptor; enable it in App access.

Each complete SSE frame must contain a matching SSE ID, session/run identity,
and contiguous numeric source sequence. Malformed JSON, mismatched identities,
sequence gaps, truncated frames, or events over 4 MiB fail the attachment. EOF
without an explicit terminal response leaves the task in recovery.

Only `assistant` messages with Engine type `message` contribute text. Per-block
deltas append; full content/message snapshots replace earlier content. Messages
are combined in Engine message order with blank lines between them. Reasoning,
tool arguments/results, and user echoes are excluded. A terminal event contains
the complete available prose, including an explicit empty string if none was
emitted. Metadata includes a digest of the source frame; raw non-prose payloads
and provider error messages are not copied into Host delivery events.

A completed `ask_user_question` plugin call is projected as
`waiting_for_input` with its call ID, title, bounded questions, options and
selection mode. Malformed clarification payloads fail replay instead of being
silently skipped. The attachment returns at this deliberate boundary. After the
Host sends a durable answer, replay rebuilds the same projection, observes the
matching plugin output, clears the pending request, and continues the original
run.

An `artifact.registered` frame must carry the exact session/run identity,
normalized relative path, media type, byte size, and SHA-256 digest. The adapter
requests that path with the expected digest under the task's Engine identity.
The Engine rejects another identity and rejects a file that changed after the
event. Host then verifies the bytes again and publishes a content-addressed,
immutable `ArtifactRef`. Replay of the same source artifact returns the same
reference; a later registration of the same logical path creates a new version.

The adapter maps response outcomes as follows:

| Engine response | Host status |
| --- | --- |
| `created`, `in_progress` | `running` |
| `completed` | `succeeded` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |
| `cancelled` with `error.details.reason = executor_restarted` | `interrupted` |

On reconnect, the adapter currently reads from Engine sequence zero to rebuild
message/block state, verifies the text snapshot at Host's committed cursor, and
emits only events after that cursor. This avoids losing text prefixes or counting
full snapshots twice without storing a second projection database. The cost is
linear replay of historical events on each attachment; projection checkpoints
can optimize this later. Engine's watermark is never used to skip unconsumed
events.

The coordinator commits projected status, text, typed input request, output
references, cursor, Host event, and delivery intents together. Direct creates
App-session updates.
Delegated also creates a continuation job for the original Main Chat on waiting
and terminal transitions. The Host's
leased worker runs a scoped Main Agent continuation after the chat becomes idle,
with atomic transcript receipts and stable downstream delegation identity.
Answer/cancel commands use the
Engine's scoped durable receipt endpoints. The task card lists artifact versions,
downloads authorized content, and previews text/Markdown or sandboxed HTML.

The first projected event also binds the Engine session as a `ProjectRef`.
Opening the task asks the Host to persist a bounded `TaskContext` and returns a
local App path containing only an opaque handoff ID. The target App resolves
that ID through its authenticated principal, workspace, and App scope; a copied
ID has no independent authority. Repeating the same task/context revision
returns the same handoff. QwenPaw Data then opens the existing Engine session
through its `session_id` route without submitting another run. The handoff
contains the task goal, scope, project/ref revisions, exact artifact refs, and a
resume ref, but no full chat transcript or principal identity.

When a handoff targets another App, Host grants only the artifact versions in
that persisted snapshot. The grant retains the originating principal and
workspace scope and is rechecked on every artifact read; possession of an
`ArtifactRef` or handoff ID alone does not grant access.

Protocol 1 permits at most 64 MiB per artifact, 128 artifact versions, and
256 MiB of referenced bytes per task. Published versions follow task retention;
there is no automatic deletion in this slice. Host reads always revalidate the
stored digest and return the same not-found response for missing and inaccessible
references. Read attempts are audited without storing artifact content.

## Session ownership compatibility gate

The Host requires `scoped_sessions: true` from the Engine before proxying its
legacy session APIs. Session listing filters by the Host-supplied identity before
pagination; session paths and body/form references validate ownership before
reads, mutation or streaming. Host identities encode user and workspace.
Artifacts remain reusable across sessions in the same authorized scope.
See the [tested pairing](#tested-engine-pairing) for the pinned Engine revision
containing the ownership changes.

## Verification

Extraction validation on 2026-10-21 used a temporary combined checkout of the
SDK split commit `ead389a87` plus this Data-only patch. All 324 Data App unit and
Host/Engine integration tests passed, including the real separate-process
HTTP/SSE cases. The exact Engine pin check and changed-file pre-commit/workflow
lint passed. These checks used controlled execution without live model calls.
Standalone main does not yet contain the required SDK; rebase after #7874 merges.

Unit tests use HTTP fixtures to cover capability rejection, scoped identities,
lookup uncertainty, text replacement/filtering, clarification boundaries,
terminal mapping, and corrupt or incomplete replay. The separate-process tests use the real Engine API,
SQLite stores, event writer/envelope, and startup recovery with a controlled
executor, without model or datasource calls.

Run the integration tests from this Host checkout with a compatible Engine
checkout and its installed virtual environment:

```bash
QWENPAW_TEST_ENGINE_SOURCE=/path/to/QwenPaw-Data \
QWENPAW_TEST_ENGINE_PYTHON=/path/to/engine-venv/bin/python \
PYTHONPATH=src python -m pytest -q \
  tests/integration/test_pawapp_data_tasks.py \
  tests/integration/test_pawapp_task_dispatch.py
```

These tests create isolated temporary stores, bind an ephemeral loopback port,
and terminate only the Engine processes they start. Without the two Engine
variables they skip explicitly. Coverage includes Direct/Delegated output and
delivery intents, concurrent submissions, a failure before acceptance, a lost
accepted response, a fresh Host store/adapter after partial output, an actual
Engine process kill/restart, clarification answer/resume, and cancellation with
retained partial output. This validates the backend protocol, not production
analytics or UI. `tests/integration/test_pawapp_task_dispatch.py` additionally
tests authenticated Console ingress through the real Engine into a persisted
Main Chat continuation, using a controlled provider substitute.


## Model bindings

`DataTaskAdapter(model_resolver=...)` resolves server-owned model connections for
new submissions. The resolver receives the trusted `TaskScope`, never model IDs,
endpoints, or credentials from action inputs. Bound submissions require the
Engine's `runtime_model_bindings` capability and an updated Context service.
Inherited analysis uses the workspace's saved default, falling back to the global
Host default; a main-chat request override does not alter this choice.

`GET/PUT /api/qwenpaw-data/model-settings` exposes reference-only choices scoped
to the authenticated principal, workspace, and App. A revision prevents stale
writes. Analysis defaults to the workspace model; summaries and DataBridge default
to analysis. Explicit app-local choices resolve the same scoped Engine preferences
used by the native console, while a local DataBridge connection remains managed
by the Context service. No selection mutates the main-chat model or widens grants.

The private Engine submission field `runtime_models` is transient. The Engine
snapshots it before launching a run and excludes it from persisted requests and
idempotency digests. Local analysis and summary choices are resolved at admission. An explicitly local
DataBridge connection remains governed by the service configuration. DataBridge model
headers are sent only to the recognized Context MCP endpoint, and browser-supplied
binding headers are not forwarded by the Host gateway. Embedding/index configuration
is independent of these per-run chat roles.
