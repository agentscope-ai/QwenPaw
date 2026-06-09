# QwenPaw CLI TUI — design

Status: **Phase 1 implemented** (relocation + ACP-subprocess transport).
Audience: QwenPaw contributors extending or maintaining the terminal UI.

## 1. Goal

Give `qwenpaw` a first-class, interactive terminal chat experience — the same
UX previously shipped as the standalone `paw` CLI — launched simply by running
`qwenpaw` with no subcommand. The design must accommodate frequent future
additions (model-provider config, skills config, memory viewer, MCP config)
without protocol churn.

## 2. Architecture: the transport seam

The single most important property of this UI is that **the widgets never know
how the agent is reached.** The UI layer consumes a small, normalized event
union (`TuiEvent`) produced by an implementation of the `TuiTransport`
protocol. ACP is *one* such implementation, not a UI-level dependency.

```
  widgets/ + app.py  ──consumes──►  TuiEvent (normalized union, §4.2)
        │                                  ▲
        │                          TuiTransport protocol (§4.1)
        │                          ╱                    ╲
        │            AcpTransport (Phase 1)        InProcessTransport (future)
        │            spawn `qwenpaw acp`           drive workspace runner
        │                  │                            in-process
        ▼                  ▼
   Textual App      ACP/stdio JSON-RPC ──► QwenPawACPAgent ──► Workspace.runner
```

Because the seam exists, the Phase 1 → future-transport switch is a one-line
default change in `launch.py`, not a UI rewrite.

## 3. Module layout

```
src/qwenpaw/cli/tui/
├── __init__.py          # package doc; re-exports __version__
├── __version__.py       # TUI version (independent of backend version)
├── launch.py            # build transport + run app; `tui` click command
├── app.py               # PawApp (Textual App): the whole UI/controller
├── events.py            # TuiEvent union — the UI's stable contract (§4.2)
├── normalize.py         # ACP session_update -> TuiEvent translation
├── paths.py             # self-owned state dir (logs); honors PAW_STATE_DIR
├── themes.py            # theme gallery + palette generation
├── transport/
│   ├── base.py          # TuiTransport protocol (§4.1)
│   └── acp.py           # AcpTransport: spawns `qwenpaw acp`, drives ACP/stdio
└── widgets/             # Textual widgets (messages, tool panel, status bar, …)
```

Tests live in `tests/cli/tui/` and run against a fake ACP agent
(`tests/cli/tui/_fake_acp_agent.py`) — no heavy backend required.

## 4. Contracts

### 4.1 `TuiTransport` (`transport/base.py`)

An async protocol that drives one conversation and yields `TuiEvent`s:
`start`, `send`, `interrupt`, `list_sessions`, `load_session`, `events`,
`resolve_permission`, `close`. Any object satisfying this protocol can back the
UI. `AcpTransport` is the Phase 1 implementation.

### 4.2 `TuiEvent` (`events.py`)

The normalized union the UI consumes: `Connected`, `BackendWarmed`,
`SessionTitle`, `TextDelta`, `ThoughtDelta`, `ToolCall` (+ `FileLink`),
`PlanUpdate`, `Usage`/`TokenUsage`, `PermissionRequest`, `AvailableCommands`,
`PushMessage`, `UserTurn`, `TurnEnded`, `TransportError`. Transports translate
their wire format *into* this union; widgets render *from* it. New UI
capabilities are added by extending this union plus the producing transport —
never by leaking a wire format into the widgets.

### 4.3 Extensions (server-initiated)

`AcpTransport`'s client implements the ACP `ext_notification` / `ext_method`
hooks. Proactive server pushes (`qwenpaw/push_message`) become `PushMessage`
events. Unknown extension methods degrade gracefully (ignored). This is the
channel for backend-initiated UI signals that don't fit the request/response
turn model.

## 5. CLI integration (`launch.py`, `cli/main.py`)

- The root group is `invoke_without_command=True`; bare `qwenpaw` calls
  `run_tui()` (the TUI), while every other entry point is an explicit
  subcommand. `--help`/`--version` are handled by Click before the callback.
- `qwenpaw tui [--agent | --resume]` is the explicit form.
- The transport command is `[sys.executable, "-m", "qwenpaw", "acp"]`, so the
  TUI always drives the *same* install/venv it ships in — no reliance on
  `qwenpaw` being on `PATH`. (`AcpTransport` still accepts a custom `command`
  for a future remote/dev escape hatch; it is simply not exposed on the CLI.)

## 6. Why ACP-subprocess for Phase 1

The chat loop is already exposed over ACP by `QwenPawACPAgent`
(`agents/acp/server.py`) and is also consumed by external IDEs (Zed, etc.), so
it is proven and maintained. Spawning it as a subprocess gives full feature
parity (tools, memory, permissions, slash commands, model switching, session
resume) for free, plus process isolation: a UI crash can't take down the
backend, and the heavy backend imports don't slow UI startup. It is also fully
testable without model keys via the fake ACP agent.

The alternative — an in-process transport that drives `Workspace.runner`
directly — is attractive for deep integration but, on the agentscope-2.0
branch, the in-process envelope→event translation in the ACP server
(`_EnvelopeTracker`) is minimal (text/thought/tool/usage only); a full-parity
in-process transport would have to re-derive permissions, file links, plans,
and command advertising from raw `stream_query` envelopes, and can't be
verified on the lean dev setup. It is therefore deferred (see §7), behind the
unchanged seam.

## 7. Future phases & extensibility

Configuration/inspection features should **not** be routed through the agent
prompt or ACP. They become native TUI screens backed by a thin service layer
over QwenPaw internals — additive, no wire-protocol versioning:

| Future screen        | Backed directly by                               |
| -------------------- | ------------------------------------------------ |
| Model/provider config| `providers/provider_manager.py` + config I/O     |
| Skills config        | `agents/skill_system/` hub                       |
| Memory viewer        | memory managers (`agents/memory/`)               |
| MCP config           | `config.py` `MCPConfig` + `app/mcp/manager.py`   |

These pair naturally with a future `InProcessTransport`, which would give the
screens typed, in-process access to those subsystems. Adding one is "a screen +
a service call," and the transport seam means it can land without disturbing the
chat UI.

## 8. Testing

`tests/cli/tui/` exercises normalize, the app (Textual test harness), the
AcpTransport end-to-end against the fake ACP agent, the status bar, the welcome
banner, and launch wiring. The suite needs only light deps
(`textual`, `agent-client-protocol`, `click`, …) — see the project memory note
"TUI dev/test setup" for the lean-venv recipe.
