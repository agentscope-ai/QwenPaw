# Third-party Agent Backend Integration

## Goal

Make a third-party agent runtime a first-class Agent backend while preserving
QwenPaw chats, streaming envelopes, and channels. `harness` remains the
internal adapter-layer name; it is not a user-facing product term.

The first supported harness is Codex. Claude Code and Qoder are discoverable
in the UI as coming-soon providers, but they have no runtime implementation.

## Non-goals

- Do not route coding requests through the ACP delegation tool.
- Do not copy or parse provider OAuth credentials.
- Do not change individual channel implementations.
- Do not add placeholder backend adapters for unavailable harnesses.
- Do not make normal QwenPaw chat depend on a harness installation.

## Module boundaries

All provider-specific code lives below `src/qwenpaw/harnesses/<provider>/`.
Code outside that package may depend only on the common harness interfaces and
event types.

```text
src/qwenpaw/harnesses/
├── base.py              common adapter contract
├── events.py            provider-neutral event and capability models
├── registry.py          adapter factories and static provider catalog
├── runtime.py           per-workspace adapter lifecycle and request routing
└── codex/
    ├── adapter.py       QwenPaw request/event conversion
    └── app_server.py    Codex JSON-RPC process client
```

FastAPI routes expose catalog, status, login, and logout. Agent create/update
APIs persist the backend selection. The frontend never invokes a provider CLI.

## Authentication

Codex owns ChatGPT OAuth and credential refresh through `codex app-server`.
QwenPaw calls the app-server account RPCs, returns only the authorization URL
or device code to the frontend, and observes completion notifications.

QwenPaw never reads `auth.json`, returns tokens through its API, or includes
provider credentials in backups. The default Codex credential store remains
the operating-system keyring when supported by Codex.

## Request routing

Every Agent has an independent `backend`, defaulting to `qwenpaw`.
`Workspace.stream_query` delegates every request to a workspace-scoped
`HarnessRuntime` when that value is `codex`. This applies equally to Chat,
Coding, cron, and Channel entry points and does not inspect Coding Mode.

QwenPaw-backed Agents continue through the existing Runtime unchanged. Codex
receives `backend_project_dir`, falling back to the Agent workspace.

## Events and sessions

Adapters emit provider-neutral `HarnessEvent` values. The runtime converts
assistant text, reasoning, and turn lifecycle into the existing QwenPaw
`Message` and `AgentResponse` envelopes before Channel code observes them.
Tool lifecycle events are normalized at the adapter boundary but remain
internal in this first version.

The minimum event set is:

- assistant text delta
- reasoning delta
- tool start and completion
- turn completion, cancellation, and error

The first Codex integration uses `approvalPolicy: never` together with the
`workspace-write` sandbox. It therefore cannot request elevated execution
through a Channel. An approval event can be added to the common contract when
QwenPaw gains a provider-neutral approval response API.

The Codex thread id is stored per QwenPaw chat id so subsequent turns resume
the same provider conversation. Session metadata stores identifiers only.

## Process lifecycle

Each workspace owns at most one Codex app-server process. The client:

- uses `asyncio.create_subprocess_exec`, never a shell;
- performs the initialize handshake before other RPCs;
- correlates responses by request id;
- dispatches notifications through bounded queues;
- fails pending calls if the process exits;
- terminates the child during workspace shutdown;
- redacts provider payloads from normal logs.

Executable discovery checks an explicit `CODEX_BINARY`, the process `PATH`,
and Codex binaries bundled in `openai.chatgpt-*` VS Code, VS Code Insiders,
Cursor, and VS Code OSS extensions.

## Frontend

Agent Management owns backend selection. Create or edit an Agent, choose
QwenPaw or Codex, and provide a Codex project directory. The same form shows
Codex installation and ChatGPT OAuth state. There is no standalone
third-party Agent settings page and no Coding Mode backend selector.

The UI presents QwenPaw as a native agent and Codex under Third-party agents.
Only native agents load or render QwenPaw model and Skill configuration.
Third-party agents do not query the Provider API, require an active LLM model,
or render the Chat model selector.

Claude Code and Qoder remain catalog-only Coming Soon providers until their
Agent backend adapters are implemented. New UI icons use Lucide React.

## Checklist

- [x] Add common harness models, adapter contract, registry, and runtime.
- [x] Add the Codex app-server client and auth RPCs.
- [x] Convert Codex turn events to QwenPaw envelopes.
- [x] Persist Codex thread ids without persisting credentials.
- [x] Route Agent requests without changing Channel implementations.
- [x] Add harness API routes and Agent backend configuration.
- [x] Add Codex backend and OAuth controls to Agent Management.
- [x] Detect Codex bundled by the ChatGPT editor extension.
- [x] Separate native and third-party agents in Agent Management.
- [x] Bypass QwenPaw model and Skill configuration for third-party agents.
- [x] Add backend unit tests and frontend tests.
- [x] Run targeted tests in the `QwenPaw` conda environment.
- [x] Run frontend type checking and tests.
