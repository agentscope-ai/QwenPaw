# PawApp vNext: Data task adapter

The Data App's `backend/task_bridge` package connects `TaskCoordinator` to
Engine submission protocol 1. It can submit, reconcile, and consume independent
analysis tasks in Direct or Delegated mode. The Data App declares its action
through `PawApp.task_action`; Host owns adapter lifecycle, scoped HTTP dispatch,
grants, readiness and recovery. Main Chat tools and Console task cards now use
this boundary; see the [Host task runtime](pawapp-task-runtime.md). A durable
Host worker delivers automatic, tool-free summaries to the originating Main
Chat. General Main Agent continuation with follow-on tools remains separate.

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
leased worker delivers a tool-free summary after the chat becomes idle, with
prepared-result replay and destination receipts. Answer/cancel commands use the
Engine's scoped durable receipt endpoints. The task card lists artifact versions,
downloads authorized content, and previews text/Markdown or sandboxed HTML.

Protocol 1 permits at most 64 MiB per artifact, 128 artifact versions, and
256 MiB of referenced bytes per task. Published versions follow task retention;
there is no automatic deletion in this slice. Host reads always revalidate the
stored digest and return the same not-found response for missing and inaccessible
references. Read attempts are audited without storing artifact content.

## Verification

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
PYTHONPATH=src python -m pytest -q tests/integration/test_pawapp_data_tasks.py
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
Main Chat summary, using controlled tool calling and summary generation.
