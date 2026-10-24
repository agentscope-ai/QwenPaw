# Record & Replay architecture

Record & Replay is an optional macOS 14+ plugin that records minimized desktop
events, lets the user review the evidence, and turns an approved recording into
a reusable QwenPaw Skill. The first release is events-only: screenshots and
video are not part of the recording artifact.

## Component boundaries

```text
Record & Replay frontend
        |
        v
plugin HTTP API -> Recording/Learning services -> Agent workspace
        |
        v
EventStream client -> HostRuntime capability -> QwenPaw Computer Use Helper
                                              |-- Computer Use contract
                                              `-- EventStream contract
```

- The plugin owns feature enablement, HTTP routes, recording review, model
  consent, Skill materialization, and frontend state.
- The Python recording service owns the durable workspace session and imports
  only sealed Helper artifacts.
- HostRuntime owns Helper discovery, launch, authentication, and capability
  lifetime. Optional plugins do not launch their own Helper.
- The Helper owns native permissions, the physical-device coordinator, the
  recording activity indicator, emergency stop, capture, and temporary staging.
- Computer Use remains a separate optional plugin. It shares the Helper but is
  not required to record or generate a Skill. A Skill that automates the desktop
  requires Computer Use when it is executed.

## Recording flow

1. The frontend starts a recording for the authenticated Agent workspace.
2. Python acquires an authenticated EventStream connection from HostRuntime.
3. The Helper takes the process-wide recording lease and starts the native
   input listener. Computer Use mutations fail fast while this lease is held;
   read-only observation remains available.
4. Native enrichment projects only allowlisted application, window, control,
   pointer, scroll, modifier, and key-class metadata. It never reads typed key
   content, clipboard data, AX text values, or screenshots.
5. Rust applies the capture-time privacy policy before writing JSONL to a
   private staging directory.
6. Stop seals the artifact and returns an opaque reference. Python opens it
   beneath the authenticated staging root, validates ownership and shape,
   applies an independent privacy guard, normalizes actions, and commits the
   result atomically to the Agent workspace.
7. Python releases the temporary Helper artifact after the durable commit.

Pause flushes the current sequence barrier before acknowledging the paused
state. Cancel, connection loss, emergency stop, Helper failure, and backend
shutdown release native resources and leave an explicit terminal workspace
state.

## Learn and replay flow

1. The user selects a completed recording and reviews the local semantic event
   timeline.
2. Python builds a bounded evidence envelope containing only redacted,
   allowlisted fields and shows the exact transfer preview.
3. One-time consent authorizes one model generation request.
4. The returned structured draft must account for every evidence event and may
   not change its grounded locator or action.
5. The user reviews the generated Markdown and explicitly approves writing it
   as a workspace Skill.
6. QwenPaw reloads the Agent. Later execution uses the normal Skill and tool
   system; there is no Record-specific replay engine or DSL.

## Security invariants

- One signed Helper identity owns desktop permissions; plugins never receive
  its authentication secret.
- Record and Computer Use share one process-wide device coordinator.
- EventStream is request/response plus sealed file handoff, not a Python-to-Rust
  callback channel.
- Native capture minimization and Python import validation are separate trust
  boundaries and intentionally duplicate critical privacy checks.
- Paths, user identities, raw recordings, screenshots, absolute coordinates,
  key contents, and clipboard contents are excluded from model evidence.
- Feature disable and plugin unload stop only the plugin's own recording and do
  not delete recordings, generated Skills, or another plugin's state.

## Storage

The Helper uses a private, instance-owned staging root with explicit ownership,
sealing, release, and expiry. The Agent workspace is the durable source of
truth and contains versioned session metadata, minimized `events.jsonl`, and a
completion summary. A staged artifact is never treated as a completed
recording.

## Compatibility

The authenticated wire envelope, Computer Use contract, EventStream contract,
native ABI, workspace session schema, and event schema are versioned
independently. A client must negotiate the contract it uses, and incompatible
versions fail before any desktop action or capture starts.

## Verification

Maintained regression coverage consists of:

- Rust unit tests for contracts, coordination, lifecycle, staging, privacy, and
  Helper installation;
- Python unit and integration tests for protocol handling, import validation,
  normalization, persistence, consent, grounding, and Skill materialization;
- frontend tests for controls, review, consent, and plugin surfaces;
- packaging checks for the signed nested Helper and native runtime.

Machine-specific permission experiments and one-off validation transcripts are
not kept as product source or unit-test dependencies.
