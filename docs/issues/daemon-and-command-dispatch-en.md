# [Feature] Daemon and command dispatch (two-phase implementation)

## Summary

Introduce command dispatch at the Runner layer so that system/daemon commands are handled without creating a CoPawAgent. Add daemon built-in commands (status, restart, reload-config, version, logs) and share the same execution layer with the `copaw daemon` CLI. Implementation is split into two phases: Phase 1 adds the dispatch, two mixins, and the five daemon subcommands; Phase 2 adds a DaemonAgent with F12-style behavior (self-diagnosis, self-healing, and optional evolution logging).

## Component(s) Affected

- [x] Core / Backend (app, agents, config, providers, utils, local_models)
- [ ] Console (frontend web UI)
- [ ] Channels (DingTalk, Feishu, QQ, Discord, iMessage, etc.)
- [ ] Skills
- [x] CLI
- [x] Documentation (website)
- [x] Tests
- [ ] CI/CD
- [ ] Scripts / Deploy

## Problem / Motivation

- Today, command branching happens inside `CoPawAgent.reply()`, so every request goes through the heavy path (create Agent, load session). Even command requests create a full CoPawAgent, which is costly and semantically wrong.
- There is no unified way to perform ops tasks (restart, status, recent logs, hot-reload config) from either chat or CLI.
- A future DaemonAgent (F12 mode: no uncaught errors, self-diagnosis, self-healing, evolution) needs a clear command-dispatch and daemon-command layer first.

## Proposed Solution

**Overall:** At the entrance of `AgentRunner.query_handler`, treat the last user message as a command when it starts with `/`. If it is a command, run the command path (no CoPawAgent) and yield events; otherwise keep the current agent flow. Replies still go back through the same stream to the channel.

**Two-phase implementation:**

### Phase 1

- **Dispatch:** At the start of `query_handler`, detect commands (conversation + daemon) by the leading `/` and route to `run_command_path(request, msgs, runner)`. Yield events and return without creating an agent.
- **Two mixins:**
  - **ConversationCommandHandlerMixin:** Handles existing conversation commands (`/compact`, `/new`, `/clear`, `/history`, `/compact_str`, `/await_summary`, `/start`). The set of commands and their behavior are unchanged in this phase; only the design moves them into a mixin used on the light path (session/memory/formatter/memory_manager).
  - **DaemonCommandHandlerMixin:** Handles daemon commands: parses `/daemon <sub>` or short names (e.g. `/restart` ≡ `/daemon restart`) and calls the shared daemon execution layer.
- **Daemon execution layer** (new `app/runner/daemon_commands.py`): `run_daemon_status`, `run_daemon_restart`, `run_daemon_reload_config`, `run_daemon_version`, `run_daemon_logs`. Used by both in-chat and CLI; context injects `load_config`, `memory_manager`, etc.
  - **Logs:** Tail the last N lines from a fixed log file under the working dir: **`WORKING_DIR / "copaw.log"`**. The app will add a `FileHandler` to this path when running (e.g. in `setup_logger` or app startup) so that all CoPaw logs are also written there and `/daemon logs` (and `copaw daemon logs`) can tail it.
  - **Restart:** The app is run with **uvicorn**. Concrete trigger:
    - **Single worker (default, `workers=1`):** From the daemon restart handler, schedule process exit (e.g. `os._exit(0)`) after the HTTP response is sent. The process exits; when run under systemd/supervisor/docker, the process manager restarts it. So “restart” = “exit this process so the manager restarts it.”
    - **Multiple workers (`workers>1`):** Uvicorn’s main process can restart workers on **SIGHUP**. Optionally write the main process PID to a file (e.g. `WORKING_DIR / "copaw.pid"`) at startup so that the daemon restart handler (or CLI) can send `SIGHUP` to that PID to trigger a graceful worker restart. If not implemented in Phase 1, document that full restart with multiple workers is “run under a process manager and use single worker for `/daemon restart`” or “send SIGHUP to the uvicorn main process manually.”
- **CLI:** New `copaw daemon` group with subcommands `status`, `restart`, `reload-config`, `version`, `logs` (optional `-n` for line count). Each subcommand calls the same execution layer.
- **Command dispatcher:** New `app/runner/command_dispatch.py` that composes both mixins, checks daemon first then conversation, calls the appropriate `handle_*`, and converts results to the existing Event stream.
- Conversation command set and behavior are **unchanged** in this phase; only daemon commands are new.

### Phase 2

- **DaemonAgent:** A simplified ReAct-based agent in F12 mode (top-level try/except, no uncaught errors, structured diagnostic output).
- Restricted tools (read-only / allowlist) and a dedicated system prompt (e.g. `DAEMON_SOUL.md`).
- Self-diagnosis: on failure, run diagnostic steps (logs, config, dependencies). Self-healing: retry, rollback, or suggest `/daemon restart`.
- Evolution: first version only “record outcomes” (e.g. append to `DAEMON_RULES.md` or a small store) for future diagnosis.
- In the command path, when the subcommand is `diagnose` or `agent`, create the DaemonAgent, run one ReAct loop, and return the result as events.

**Naming:** Daemon supports both `/daemon <sub>` and short names (e.g. `/restart`). The `/daemon xxx` form is kept for future use when the daemon agent is invoked as the query target.

Detailed design: `docs/design/daemon-and-command-dispatch.md`.

## Alternatives Considered

- Keeping dispatch inside the agent: does not avoid creating a full agent for commands.
- Daemon only via CLI (no in-chat): would split the ops entry point; a single execution layer for both is simpler.

## Additional Context

- Commands docs: https://copaw.agentscope.io/docs/commands
- Design doc: `docs/design/daemon-and-command-dispatch.md`
- App entry: `uvicorn.run("copaw.app._app:app", ...)` in `src/copaw/cli/app_cmd.py` (default `workers=1`).

## Willing to Contribute

- [ ] I am willing to open a PR for this feature (after discussion).
