# A small App on the durable PawApp contract

Use a managed handler for bounded work that can run in the Host process. Use a
`ManagedTaskAdapter` for an external engine or independently running service.
Both produce the same TaskHandle, questions, experience, project and artifact
contracts. Neither registration grants permission to execute.

## Minimal backend

```python
from qwenpaw.pawapp import PawApp
from qwenpaw.pawapp.tasks import ActionDescriptor, ActionResult, TaskExecution

app = PawApp("Word counter", app_id="word-counter")

@app.action(
    ActionDescriptor(
        app_id="word-counter",
        action_id="count",
        summary="Count words in supplied text.",
        engagements=("direct", "delegated"),
        adapter_ref="word-counter.count.v1",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 10000}},
            "required": ["text"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 0}},
            "required": ["count"],
            "additionalProperties": False,
        },
    ),
    recovery="replay_safe",
)
async def count(ctx: TaskExecution):
    count = len(ctx.inputs["text"].split())
    return ActionResult(summary=f"Found {count} words.", data={"count": count})
```

The normal plugin manifest points to this backend and its frontend. The Host
registers the action; the user enables its exact descriptor in App access for
the selected workspace. Main Chat then discovers and delegates it through the
existing generic tools and renders its task card. No Main Chat or Host branch
for the App ID is needed. Discovery in Main Chat excludes direct-only actions.
Optional descriptor `guidance` explains action selection and stays untrusted
metadata, separate from permission/effect grants.

For an expected business failure such as a stale document revision, use
`await ctx.fail("revision-conflict", text="The document changed. Review it first.")`.
This persists a failed task and stops the handler; the deliberate public text
survives retries. An optional `project=ProjectRef(...)` keeps the destination
available for review. Do not pass raw exception messages, credentials or
internal diagnostics as public text. Unexpected exceptions remain sanitized.

## Frontend

```javascript
const paw = window.QwenPaw.paw.forApp("word-counter");
const workspaceId = paw.host.getSelectedAgentId();
// Persist this intent and its inputs BEFORE sending. Retry the same ID after
// an ambiguous failure; generate another ID for a new user intent.
const requestId = paw.tasks.newRequestId();
const dispatched = await paw.tasks.dispatch("count", { text: "hello world" }, {
  requestId, workspaceId, appSessionId: "document-one",
});
if (dispatched.state === "accepted") {
  const task = await paw.tasks.wait(dispatched.task.task_id, { workspaceId });
  console.log(task.result_data);
}
```

`wait` returns on a terminal or waiting state, including setup and questions.
Pass an AbortSignal to stop observation when a view closes; this does not cancel
execution. `tasks.answer`, `cancel`, `get`, `events`, and `open` use the same
scoped API. Save the accepted task ID to restore progress after reload. Changing
inputs or App session while reusing an accepted request ID is a conflict.
`appSessionId` is an App context key; the Host creates and validates its Direct
origin. Apps do not construct ChatSpec or caller-supplied principal IDs.

`paw.setup.request(actionId, inputs, {requestId, workspaceId, entryId})`, `get`,
`open` and `cancel` coordinate declared setup entries. App backends complete
setup with a typed SetupResult after saving configuration; frontend callers
cannot assert that a prerequisite is satisfied. `paw.artifacts.list` and `read`
return authorized references and content. Navigation returned by task/setup
open is validated before being exposed by the SDK.

Authenticated backend routes use `Depends(get_scoped_ctx)` from
`qwenpaw.pawapp`, then `ctx.tasks`, `ctx.setup`, or `ctx.artifacts`. Legacy
`get_ctx` does not receive these durable clients. Task execution itself receives
`TaskExecution`, with trusted `scope`, immutable submission identity, `inputs`,
`report(key, ...)`, `request_input(request)`, and `publish(...)`.

## Questions, artifacts and recovery

For missing app settings, register `SetupRequirement` checks and
`SetupEntryRegistration` handlers with an `app_entry` presentation. Reference
the requirement IDs on the action. A blocked submission then gets a Main Chat
configuration button automatically. Its handler returns a `SetupOpenAction`
pointing to the appropriate screen inside the App; credentials stay in that
screen. Return a setup receipt after saving. Preflight setup still requires an
explicit task retry; it does not silently authorize execution. See the
[setup lifecycle](pawapp-task-runtime.md) for scoping and recovery rules.

Use typed TaskInputRequest/TaskAnswer, TaskExperienceDefinition/Update and
ProjectRef from `qwenpaw.pawapp.contracts`. Text is a human summary; `result_data`
is a JSON object validated against the descriptor's result_schema and bounded
to 64 KiB. When a result schema is declared, a successful handler must return
matching data. Larger deliverables belong in artifacts. Declare `qwenpaw:file`
in output_types before calling `ctx.publish(source_id=..., name=...,
media_type=..., content=...)`. An artifact source ID identifies immutable bytes
for that submission; reuse with different bytes is rejected.

The Host journals submissions, sequenced events, questions, answers and command
receipts in the task database. The default `recovery="interrupt"` never silently
reruns potentially effectful code after process loss. The recovered task becomes
interrupted. Opt into `replay_safe` only for read-only handlers or handlers that
deduplicate every external effect using `ctx.submission_id`. After restart the
coroutine runs again; stable report keys, question IDs and artifact source IDs
must describe identical checkpoints. Finished task results are replayed without
executing the handler. Cancellation is cooperative; it cannot undo effects
already committed by a handler or background thread.

The Host manages async orchestration, not CPU isolation or distributed worker
leases. Move blocking work off the event loop; use an external adapter for long
jobs requiring independent lifecycle, sandboxing, or worker coordination.

## Scope and compatibility

Artifact creation records the producing task/session as provenance. Access is
scoped by authenticated user, workspace and App, so another session in that
scope can reuse it. Another App needs an explicit Host grant to the exact
artifact version, such as an authorized handoff. A copied reference or task ID
is not a grant. Task commands and delegated continuation still validate the
original chat ownership.

Python is the model source of truth. Regenerate the JSON Schema bundle and TS
types using `python scripts/generate-pawapp-contracts.py`; CI runs `--check`.
Frontend SDK validation covers the generated schema subset; state transitions
and cross-field invariants remain authoritative on the Host. Existing external
protocol-1 adapters may retain detail-based events, or adopt typed event fields.
Do not send conflicting typed and legacy payloads. Optional artifact translation
is documented by ArtifactMaterializingAdapter in `tasks.binding`.

See [implementation status](pawapp-contract-progress.md) for the tested Engine
pairing, migration rules and remaining production validation.
