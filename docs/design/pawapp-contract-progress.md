# PawApp contract implementation status — 2026-10-21

PR #7874 delivers the shared PawApp SDK/control plane and Creator integration.
The Data App adapter, native Console task routing, adapter tests, external Engine
pairing and Host–Engine CI suite are extracted into
[Data integration #8363](https://github.com/agentscope-ai/QwenPaw/pull/8363).
The existing released Data App remains at the upstream main implementation.
File Browser is also extracted into its own dependent example-app PR. Neither
app integration is required to run the SDK conformance suite.

| Area | Implementation |
| --- | --- |
| Public contract | Python export surface, generated JSON Schema and TS types, response validation and typed executor events |
| Results | Schema-checked structured results, summaries, artifact refs and project references |
| Small Apps | `app.action`, Host-owned execution journal and explicit restart policy |
| Scoped SDKs | Python and frontend task/setup/artifact clients, Host-managed Direct origins and explicit request IDs |
| Main Chat | Generic action discovery, task cards, setup guidance and durable continuation |
| Creator | Story-writing handoff, prepare/revise/produce actions and verified final-film publication |
| Small-App example | App-independent word-counter quickstart and managed-handler conformance tests |
| Conformance | Generated schema drift checks and Host/frontend tests without an external Data Engine checkout |

## Migration and scope invariants

Existing descriptors without result_schema retain their prior authorization
digest. Guidance is not authorization material. Shared typed event fields retain
legacy replay meaning. SQLite v4 adds managed execution journals without changing
accepted task or submission identities.

Creator actions require action-specific grants. Setup completion does not grant
execution or approve media spending. File Browser action migration is documented
with its separate App implementation.

Artifacts remain user/workspace/App scoped. Sessions record provenance and do
not prevent reuse within that scope. Cross-App access requires an explicit grant
to the exact artifact version.

## Data integration split

The follow-up contains `analyze` and Direct-only `analyze-session`, the Data
adapter and event mapping, native Console dispatch/commands, App-local tool and
skill registration, and the exact Engine compatibility pin. Its implementation
depends on this SDK and the Engine changes in QwenPaw-Data #85.

Host runtime and task-store tests now use an App-independent descriptor. The
contract CI workflow no longer checks out or installs the external Data Engine.
Data-specific docs, fixtures and integration tests move with the adapter.

## File Browser integration split

The complete File Browser App is delivered separately: its managed directory
listing, App-owned default-directory setup, frontend SDK client, persistence,
private legacy recovery adapter and App tests move together. The SDK retains
its word-counter quickstart and generic managed-handler, setup and authorization
tests. No shared runtime code imports the File Browser implementation.

## Validation boundaries

After both App extractions, 617 standalone Host/PawApp/plugin/CLI/config tests
passed. Generated-contract drift and changed-file pre-commit checks passed.

The standalone Host/PawApp/plugin/CLI/config conformance suite runs without
installing or importing either extracted App implementation. Generated-contract
checks and the frontend contract suite remain in the SDK workflow. Each App
integration carries its own focused CI workflow.

The SDK tests cover authorization, scoped resources, idempotence, commands,
setup, artifacts, restart recovery and continuation receipts. Creator retains
its workflow and final-film tests. See the [App quickstart](pawapp-app-quickstart.md),
[task runtime](pawapp-task-runtime.md) and [Creator story handoff](pawapp-creator-story-handoff.md).

The dated Creator entries below record the state observed at each checkpoint;
earlier configuration blockers are historical, not a statement of current local
service readiness. No service restart or live-provider execution is part of the
App PR extractions.

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

### Creator model reasoning disabled — 2026-10-20

The recovered production run later exhausted the 600-second model-turn limit.
Subsequent local retries streamed roughly 49–51 thousand reasoning characters
without completing a tool call. Creator's planning and vision clients forced
`thinking_enable=True` independently of Main Chat settings and supplied no
reasoning budget.

Both clients now explicitly disable thinking on the DashScope/OpenAI-compatible
path. Four request-level regression cases exercise both clients and protocols
through the real SDK with a mock HTTP transport, asserting the serialized JSON
contains `enable_thinking: false` and retains tool definitions. All 142
model-client/runtime tests and changed-file pre-commit checks passed.

A live probe using the configured `qwen3.8-max` model captured that same flag,
returned a `read_project` tool call in 2.08 seconds, and emitted zero reasoning
characters. The probe executed no tools. The installed Creator backend was
updated and the Host restarted; this verifies model-request behavior, not a
completed production or rendered video.
