# PawApp vNext: Data task adapter

The Data App's `backend/task_bridge` package connects `TaskCoordinator` to
Engine submission protocol 1. It can submit, reconcile, and consume independent
analysis tasks in Direct or Delegated mode. Lifecycle registration, public
dispatch routes, Main Agent tools, and UI are separate gates; importing the
adapter does not enable an action.

## Binding and compatibility

The Host binding supplies:

- An endpoint resolver returning the managed Engine's current `(base_url, token)`.
  Resolve both together per operation; reconnect can discover a changed port.
  Inputs and model output must never choose this endpoint or credential.
- A stable `executor_id` for that Engine database/installation. A port change
  retains the ID. Replacing/resetting the database is not transparent failover.
- `data_action_descriptor()` and an explicit Host authorization callback.
  The descriptor supports `analyze(text, datasource_id)` and both engagements.
  Its permission tags still require production resource-policy mapping.
- Ownership of the adapter's connection pool: call `await adapter.aclose()`
  during shutdown after task consumers stop.

The adapter probes `GET /api/v1/capabilities/submissions` before each operation.
Only protocol version 1 with durable submission and replay support is accepted.
Older Engines and JSON mode cannot fall back to the legacy session/chat POSTs.
`check_compatibility(scope)` is available to the future readiness binding;
unsupported submission raises `unsupported_engine_protocol` before POST.
Rendering a blocked result and an App settings entry still belongs to the Host
readiness/UI gate.

The current verified Engine source is
[`90a374a`](https://github.com/cyruszhang/QwenPaw-Data/commit/90a374ab77b3d6e4de20c8e8f13b30507e914ec1).
This is a development dependency, not a released minimum version. Host and Engine
run in separate dependency environments and communicate only over HTTP/SSE.

## Scope and recovery

`submit`, `query`, and `attach` receive the persisted `TaskSubmission`. Its
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

The coordinator commits projected status, text, cursor, Host event, and delivery
intents together. Direct creates App-session updates. Delegated also creates a
continuation intent for the original Main Chat on terminal transition. These
intents are not yet delivered to the Main Agent scheduler. Clarification requests,
answer/cancel receipts, artifacts, and rich cards are not projected by this slice.

## Verification

Unit tests use HTTP fixtures to cover capability rejection, scoped identities,
lookup uncertainty, text replacement/filtering, terminal mapping, and corrupt
or incomplete replay. The separate-process tests use the real Engine API,
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
accepted response, a fresh Host store/adapter after partial output, and an actual
Engine process kill/restart. This validates the backend protocol, not production
analytics, UI, or Main Agent wake-up.
