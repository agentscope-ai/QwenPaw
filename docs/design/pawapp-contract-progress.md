# PawApp contract implementation status — 2026-10-20

The contract now supports managed small Apps and existing external adapters on
one Host task model. The Host branch now includes upstream main through
`210f5aaac`, including the merged Data app 1.0.3 release (#8266). The Engine
pairing below includes Data #85 merged with its latest main. Earlier browser
acceptance and hosted CI evidence is dated separately below.

| Area | Implementation |
| --- | --- |
| Public contract | Python export surface, generated JSON Schema and TS types, SDK response validation, typed executor event fields with legacy normalization |
| Results | Schema-checked structured result beside human summary, artifact refs and project; bounded continuation projection |
| Small Apps | `app.action` / handler registration, Host-owned submission/event/command journal, explicit restart policy |
| Scoped SDKs | Python task/setup/artifact clients; frontend task/setup/artifact namespaces; Host-managed Direct origin; explicit request IDs |
| Main Chat | Generic task labels and action guidance; delegated-only discovery; existing task continuation, questions and handoffs retained |
| Data scope | Legacy session route ownership checks, owner-filtered list pagination in SQL and JSON stores, body/form checks, Host compatibility gate |
| Example migration | File Browser `browse-directory` uses a managed handler, structured result and frontend SDK |
| Compatibility | Published Engine commit pinned by revision, preparation script, schema drift check and contract CI workflow |

## Tested pairing

The machine-readable source is
[`tests/fixtures/pawapp-compatibility.json`](../../tests/fixtures/pawapp-compatibility.json).
The Engine is fork revision `a7fdc606c6bb73efdb688389380dd7ec6f24c783`,
which includes scoped-session ownership and per-run Host model bindings. CI checks out and verifies
that exact revision. No compatibility patch is required. Run
`scripts/prepare-pawapp-engine.py <checkout>` to verify the pairing locally.

The Host requires the Engine's `scoped_sessions` capability before exposing
legacy session APIs. Protocol version 1 alone is insufficient. An older Engine
fails closed, including the previous unpatched base.

## Migration and scope invariants

Existing descriptors without result_schema keep their prior grant digest.
Guidance is not authorization material. Typed shared event fields normalize to
the old replay meaning, preserving durable event receipts. The SQLite v4 task
store gains additive managed journal tables; existing adapters/tasks remain on
their original protocol and identities. Data's previous native chat origin IDs
are retained behind the shared origin helper.

File Browser's old `list-directory` descriptor and adapter remain App-private to
recover tasks already accepted. The new `browse-directory` action has a new
schema and requires its own grant in App access; old grants are retained and
are not silently widened. Saved task pointers can still display legacy JSON
text results. New requests use structured results and persist an intent before
sending, so uncertain retries keep the same request ID.

Artifact access remains user/workspace/App scoped, with exact-version grants
for cross-App handoffs. Sessions provide provenance, not a blanket isolation
boundary within that scope. The Engine's Host-supplied identity encodes user and
workspace; its legacy routes now enforce the same ownership as submissions.

## Main synchronization — 2026-10-20

- Preserve Main Chat's session transition/retry changes inside the PawApp task
  surface, and preserve failed-plugin inventory/removal alongside explicit App
  activation.
- Keep the released model-configuration HTTP 409 errors and map them to blocked
  task readiness; unrelated HTTP errors retain their original failure behavior.
- Data uses the vNext SDK's native per-service environment factory. The stable
  launcher's Windows PID/lifecycle fixes and regression tests are also retained.
- Verify the updated pairing with 22 separate-process Host–Engine tests,
  1,036 Console task/SDK/chat tests, 412 platform contract tests (one skip),
  and the Data UI tests/build. Full-suite collection requires separate runs
  because the repository has integration and unit files named `test_backup.py`.
- The full unit run passed 17,721 tests with 24 skips. Its only failure was the
  unchanged upstream epoch-format test under the local Pacific timezone; all 23
  tests in that module passed when rerun with `TZ=UTC`. Console production build,
  CSS verification and bundle-size checks passed.
- No services were redeployed, and live-provider acceptance was not repeated.

## Verification and limits

The suites cover descriptor/event compatibility, generic task lifecycle,
questions and command receipts, restart interruption and replay, project and
experience projection, artifact publication and scope isolation, Direct SDK
origin creation and retry, frontend validation and workspace pinning. Real
Host–Engine tests use separate processes, HTTP/SSE, SQLite and controlled
execution; both Engine storage implementations have owner-pagination coverage.

Local verification results:

| Check | Result |
| --- | --- |
| Host/PawApp/plugin and selected Creator/File Browser tests | 1,000 passed, 7 skipped (Host/plugins/config/CLI); 192 Creator and 49 Console/boundary tests passed |
| Engine session stores and affected API suites | 126 passed |
| Separate-process Host–Engine integration | 16 passed |
| Console SDK/task API/task card tests | 72 passed (including 6 plugin-loader tests) |
| Data UI tests | 3 passed |
| Console/Data UI TypeScript, generated contract drift, Python lint, new SDK ESLint, diff checks | Passed |

The direct setup test was also rerun after adding SDK-route coverage. The managed stream race regression forces a terminal commit between reads;
the consumer must receive and persist that final event. The seven Host/plugin skips are environment-dependent tests.

The live Creator preflight on 2026-10-15 failed because its saved credential
could not be decrypted. It made zero provider submissions. A usable credential
is required before live-provider acceptance can pass. Browser acceptance and
hosted CI results will be recorded separately from these local tests. Managed
handlers run within the Host process and must explicitly opt into replay-safe
execution. Setup completion and policy grants remain Host/backend operations.

For the integration recipe, see the [App quickstart](pawapp-app-quickstart.md).
For the underlying architecture, see [task runtime](pawapp-task-runtime.md) and
[Data adapter](pawapp-data-task-adapter.md).

Acceptance fixes on 2026-10-15: managed streams now read run state before the
event snapshot, preventing a concurrent completion from being dropped. CLI
module validation accepts the same `app` export as the runtime loader, allowing
PawApps to pass installation validation. Console production build and its
bundle/CSS checks passed.

## Browser acceptance — 2026-10-15

The production Console and real Host ran on loopback in an isolated acceptance
working directory. File Browser was installed through the CLI/API and activated
through its normal App route. Browser checks verified:

- Ungranted listing is rejected with the App access link.
- `browse-directory` accepts an exact directory grant saved in Settings.
- The granted listing renders its structured result (`acceptance.txt`, 35 B).
- Reload restores the completed task without a duplicate run.
- The parent directory remains forbidden under that exact grant.
- Saving the default and omitting the input produces the same authorized result.

Cold App navigation exposed late installation of Host hooks. The loader now
installs the SDK before executing any App script; a regression test covers the
ordering. The corrected production build passed the browser flow without a new
render error. The broader Creator UI check also exposed three old whole-film
fixtures that used `timeline_render`; they now explicitly use `final_video`,
matching the canonical-film contract. All six tests in that file passed.

Restart acceptance also uncovered repeated rewriting of workspace paths when a
custom working directory lived below `~/.copaw`. Normalization now preserves
paths already inside the current root and requires a directory boundary for
legacy prefixes. All 58 config utility tests pass. After repairing the isolated
fixture's already-rewritten path, the existing listing was readable again with
no additional managed task and no browser errors.

The Engine cron test now waits for its terminal event as well as completed chat
state: those are separate durable writes. The updated exact Engine pin includes
that deterministic test fix. Hosted Creator and Console/website format checks passed.
[Contract conformance passed](https://github.com/cyruszhang/QwenPaw/actions/runs/38765983418)
against the updated Engine pin. Full-repository lint cleanup was then applied;
all changed files pass pre-commit, and the full-repository mypy check passes.

A further restart without repairing any state confirmed both original tasks
remain accessible with HTTP 200 and `succeeded`, exactly two managed runs, and
an unchanged workspace path. The acceptance runtime is isolated from the normal
Host installation; this is local deployment evidence, not a production rollout.

The final cleanup applies repository formatting to the earlier acceptance
scripts, corrects the capability-builder input annotation and Console queue
narrowing, and documents Pylint limitations for isolated plugin module names and
dynamic callable classes. Lifecycle complexity exceptions are scoped to the
specific state-machine functions/guards. No global lint rule was weakened.

Live-provider acceptance remains the only credential-dependent gate. Restore
the Creator Wan credential in its settings, then run the bounded acceptance
recipe in [real-provider acceptance](pawapp-real-provider-acceptance.md).
The failed preflight made zero provider submissions.


## Workspace model settings preview — 2026-10-15

Data now defaults to the selected Host workspace model. Analysis, lightweight
summaries, and DataBridge each have an explicit inherited, Host override, or
app-local source. The embedded settings page shows the resolved model and
configuration errors. Provider credentials for inherited/Host overrides are
resolved server-side; the saved choices contain only references and a revision.
A stale editor receives HTTP 409 instead of overwriting newer choices.
The page also shows the main-chat default when Data has an override. Readiness
refreshes after saving, navigation, and returning to the app; an older probe
cannot restore a warning after a newer settings check.

New submissions snapshot model connections at acceptance. The Engine uses the
snapshot for analysis and background summaries; existing agent memory is retained
when a later turn selects a different model. DataBridge receives the run's model
through a private service-authenticated header. MCP clients are session-specific,
and Context keeps the binding request-local. Model credentials are excluded from
submission serialization, digests, and durable stores. Replaying an accepted
Engine submission retains the original run even after model settings change.

The Data settings page separates model choices from supported Engine behavior
controls. Existing app-specific connections remain under Advanced. Embeddings
retain a separate service/index connection and vector dimension; they do not
follow chat-model changes. The embedding save action explicitly says that it
rebuilds the index. Context model settings now use the authenticated App gateway,
fixing the previous root-level 404 responses.

Bound analysis currently supports OpenAI-compatible and DashScope chat models.
It inherits provider/model identity and connection credentials; Engine generation
and agent behavior remain independently configured. Other Host model protocols
fail with a configuration message. Model choices grant no datasource or task
permissions. The marketplace package is unchanged; this is a local development
preview on the paired branches.

Verification: 139 Host adapter/configuration/gateway tests; 11 console provenance
tests; 132 embedded-console tests; 760 Engine/Context suite tests with three skips,
plus concurrent MCP-to-REST and session-memory model-switch regressions. TypeScript and both Data UI builds
passed. Browser checks cover the inherited settings view, missing-provider message,
override/reset controls, and saving the supported behavior settings. Live API
checks confirm saving unchanged choices and rejecting stale revisions with 409.
The readiness follow-up passed 16 model-settings/provenance tests and a browser
save-and-return check: a missing inherited model shows the warning, then saving a
configured override clears it without a reload. No live model inference or
embedding rebuild was performed.


## Native chat datasource selection fix — 2026-10-15

Native Data chat now accepts the Console's null datasource selection. Host
normalizes it to an omitted optional input for `analyze-session`; the Engine
advertises `optional_session_datasource` and accepts it only for an owned,
existing session. Delegated `analyze` still requires a datasource. Named-source
grant constraints still reject unscoped inputs, and existing grant digests must
be refreshed for the changed Direct action. Admission reports an actionable
App access error when that grant is absent or stale.

Validation: 84 Host adapter/policy tests, 41 Engine submission tests, and 19
separate-process Host–Engine integration tests passed. Native chat cases cover
selected/no source, retries, clarification, cancellation and session ownership.
The controlled Engine fixture also accepts the runtime model-binding arguments.

Live acceptance: the installed app accepted an unscoped native turn. Its first
execution exposed stopped local Colima; after starting the existing runtime,
a second turn completed with `Connection OK`, and the Host task reached
`succeeded`. The already enabled unrestricted Direct grant was re-saved for the
new descriptor with the same constraints; other grants were preserved.


## DataBridge discovery in native sessions — 2026-10-15

Session-scoped AgentScope MCP clients no longer lose workspace-wide legacy
registrations. The Engine supplies those declarations through `default_mcps`,
so each session gets its own client and transient model headers. Explicit
per-session entries, including an empty list, still take precedence. Docker
defaults receive the same host-alias and authentication handling as legacy
clients; the saved host MCP file is unchanged.

The Host restores the persisted active datasource after starting its gateways,
without waiting for someone to open the Context console. Local acceptance also
required configuring the existing Neo4j connection and selecting the GAAP demo
datasource; those instance credentials are not part of the source changes.

Validation: 736 Engine tests passed with three skips; 30 Host datasource and
service-lifecycle tests passed. A real Docker workspace discovered all 20
DataBridge MCP tools with session-scoped clients.

Live native-chat acceptance with no explicit datasource selection found
`DemoProduct → dws_gaap_di` and executed `SELECT 1 AS connection_ok`, returning
`[[1]]` with successful SQL execution. The Host task reached `succeeded`.


## Dataset reload and selected analysis context — 2026-10-15

The embedded Console requested `/api/v1/datasets`, which the OSS Engine did
not implement; reload therefore repeated a 404. The Engine now loads the
semantic dataset catalog with the OSS `datasource_id` filter, authenticated
requests, validated pagination, and explicit upstream errors. The Cloud-only
`source_datasource` parameter is not used because OSS would ignore it.

Native `analyze-session` also accepts bounded `dataset_names`. The Engine
advertises `dataset_context`, persists names with the chat in SQL/JSON stores,
returns them on history reads, preserves them on forks, and includes them in
the agent's analysis context. Names participate in submission idempotency;
omitted/empty names preserve older submission digests. Selection is an
analysis focus, not a database authorization or hard query filter. Existing
source grants and session ownership still apply. Older Engines are blocked
before selected-dataset submissions are sent.

Validation: the full Engine suite passed (749 tests, three skips), including
catalog pagination and filtering, submission persistence and idempotency.
Host adapter tests passed (56), and 12 separate-process integration cases
passed, including dataset
selection, retries, clarification and cancellation. The local app was
reinstalled and activated. Its existing unrestricted Direct analysis grant
was refreshed with the same constraints for the updated descriptor.

Live browser acceptance: selecting `Demo PG - GAAP use case` populated
`dws_gaap_di`. A selected-dataset turn inspected metadata and successfully ran
`SELECT COUNT(*) AS row_count FROM dws_gaap_di`, returning **475** rows.
The completed result remains in the verification session. A request for an
unrelated datasource returned an empty catalog.

## Main Chat story writing and Creator handoff — 2026-10-20

The bilingual bundled `story-writing` skill develops the full story in Main
Chat, then uses granted Creator actions to prepare, revise and produce one
film. `prepare-production` deterministically imports a versioned story package
and exact Markdown script without invoking a model. Both are published as Host
artifacts and the task opens the populated Creator project.

`revise-story` preserves history, checks the preceding digest and project ETag,
rejects active Runtime work, and invalidates script approval even for changes
only to character details or agreed decisions. `produce-video` resumes the
same project with explicit media-generation permissions, setup and spending
gates. Its admission recovers after a crash without duplicating the goal;
stale requests become visible failed tasks rather than indefinite recovery.
Ownership is user/workspace/App scoped, so another chat can reuse the project.

The shared SDK adds `ctx.fail` for deliberate public business failures while
unexpected exceptions remain sanitized. Generic handoff context now falls back
to the completed task result when no text input exists. The Host contains no
story-schema or Creator routing logic.

Validation: 145 focused Creator tests and 799 Host/skill tests passed. The broad
unit run reported 17,721 passed and 24 skipped, plus the existing local-timezone
failure in `TestFormatTimestamp.test_formats_epoch`; all 23 tests in that
unchanged module passed with `TZ=UTC`. Both packaged skill languages resolve.
The default whole-repository pytest command still has the existing duplicate
`test_backup.py` collection issue.

Reference URIs and notes are preserved, but their binary files are not copied.
No live media-provider generation is claimed. Contract, recovery details and limits:
[Creator story handoff](pawapp-creator-story-handoff.md).

### Local workflow acceptance — 2026-10-20

The local service on port 8088 now runs this branch with rebuilt Console and
Creator assets. Existing service settings and the Creator installation were
backed up before switching the LaunchAgent from the release checkout. The
default workspace imported/enabled `story-writing` and explicitly enabled the
three new action grants.

Using the configured Main Chat model, the browser flow wrote the 12-second
Chinese film **一盏灯**, then delegated `prepare-production`. Creator opened the
populated script-stage project. The exact three-scene Markdown was preserved;
the saved JSON matched the delegated package and its digest. Two characters,
eight decisions and twelve constraints, including the silent ending, were
carried over. JSON and Markdown artifacts were published. A service restart
restored the completed task unchanged and the same project remained readable.

A subsequent Main Chat `revise-story` added one no-brand-logo constraint.
Revision 2 retained the same project, original script bytes and all other
story fields, with both versions retained. Neither import admitted a production
goal or generated media.

Production preflight exposed undecryptable saved Creator credentials being
counted as configured. Setup readiness now rejects retained encrypted values,
including inherited LLM keys; keyless SGLang remains supported. All 16 setup
tests and changed-file pre-commit checks pass. After redeployment, the public
`produce-video/prepare` endpoint correctly returned `needs_configuration`
without dispatching production. Creator credentials still need repair before
live generation; this acceptance does not validate rendered output.

### Main Chat setup response serialization — 2026-10-20

A subsequent Main Chat production attempt exposed a separate Host transport
bug: `delegate` passed a nested `PrepareResult` directly to the strict JSON
serializer. The earlier HTTP preflight succeeded because that route already
encoded contract models. The three failed chat attempts were audited as
`creator_llm_model_missing`, with no task created for their request ID; the
serialization exception then hid that setup result.

All task-tool responses now use the same JSON-compatible encoding as HTTP,
including nested setup contracts. Durable request/event serialization and
identity digests remain unchanged. A regression test reproduced the exact
exception before the fix. Tests cover all five non-ready setup states, no
latent execution on repeated blocked requests, and exactly one task when the
same request is retried after configuration becomes ready.

Validation: 64 focused Host tests and changed-file pre-commit checks passed;
12 optional Engine integration cases were skipped because their external
checkout/interpreter variables were not supplied. The local service restarted
healthy. Its current production preflight was round-tripped through the Main
Chat response encoder and still reports `needs_configuration`, now as valid
structured JSON. This check did not dispatch production or run another model
turn. The existing project remains at generation 2; credential repair and
live media generation remain outstanding.

### App-owned setup prompts before task creation — 2026-10-20

The live Main Chat retry confirmed the serialization fix but exposed the next
UX gap: an eager setup blocker only linked to the App home page. Blocked
submissions now return typed `setup_prompts`, grouped by the App's registered
configuration entry. Main Chat renders those prompts as buttons and resolves
their scoped request IDs through the Host before navigating. Creator's planning
model prompt opens its LLM settings directly. No credential is requested or
entered in Main Chat, and no model-supplied navigation URL is trusted.

Active prompts are reused for repeated submissions. A subsequent explicit
retry renews expired or closed prompts atomically while preserving old receipts.
Unavailable/unknown checks produce no configuration requests. Read-only prepare
calls create neither prompts nor tasks. Saving preflight configuration does
not start production; a retry rechecks readiness under the original task intent.
Setup after task acceptance retains the existing linked-task resume behavior.

Validation: 508 Host tests and 23 focused Console tests pass. The Console build
and generated-contract drift check pass. Tests cover grouping multiple missing
requirements, prompt reuse and renewal, principal isolation, registered paths,
no task before setup, and one task after configuration and an explicit retry.
Live Main Chat now renders “Configure the Creator planning model.” on the
blocked card. The current saved Creator planning/image credentials still fail
decryption, despite the App's presence-based configured badge. The relevant
App settings screen was opened for repair; no production task or media was
created for the original request, and the revision-2 story remains intact.

### Existing-story production progress recovery — 2026-10-20

After repairing the local credentials, LLM, image and video connection probes
passed and `produce-video` was accepted. Its first progress event failed because
the shared video experience mapper parsed the story-reference request as a
`create-video` brief. The Host retained the accepted task in recovery rather
than receiving its planning status.

Progress context now reads the workflow's persisted normalized input, shared by
both entry actions. This preserves the admitted resolution, aspect ratio and
duration without reinterpreting action-specific request schemas during replay.
The regression test reopens the Host journal and adapter after acceptance,
consumes the progress events, and verifies repeated reconciliation preserves
the same run, project, story and single production message. All 96 focused
Creator story/video and Host experience tests and changed-file pre-commit checks
passed.

The local Creator backend was updated and the Host restarted. The previously
accepted task recovered to `running` / `plan`, with executor sequence 2 and its
original task, submission and project identities. The Creator agent is active;
final video generation and rendering are not yet validated by this check.
