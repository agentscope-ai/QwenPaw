## Description

Implement Mission Mode — an autonomous iterative agent system for complex, long-running tasks.

Inspired by [snarktank/ralph](https://github.com/snarktank/ralph) (MIT License), Anthropic's [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) design patterns, and Claude Code's verification agent mechanism.

Core philosophy: **code-level control + prompt guidance + independent verification**. Reliability-critical paths (iteration, tool restrictions, PRD validation, max iterations) are guaranteed by code; judgment-requiring paths (task decomposition, scheduling, error recovery) are guided by prompts; each story's acceptance is verified by an independent **adversarial verification agent**, not the worker itself.

**Related Issue:** N/A

**Security Considerations:**
- In Phase 2, Mission Mode disables the master agent's implementation tools (shell/write/edit) via the Toolkit group mechanism, preventing self-implementation
- Verifier agent is strictly read-only — prohibited from modifying any project files

## Type of Change

- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation
- [ ] Refactoring

## Component(s) Affected

- [x] Core / Backend (app, agents, config, providers, utils, local_models)
- [x] Console (frontend web UI)
- [ ] Channels (DingTalk, Feishu, QQ, Discord, iMessage, etc.)
- [ ] Skills
- [x] CLI
- [ ] Documentation (website)
- [ ] Tests
- [ ] CI/CD
- [ ] Scripts / Deploy

## Change Summary

### New Files (8)

| File | Description |
|---|---|
| `src/qwenpaw/agents/mission/__init__.py` | Module init with snarktank/ralph copyright notice |
| `src/qwenpaw/agents/mission/handler.py` | `/mission` command parser, session-bound state initialization |
| `src/qwenpaw/agents/mission/prompts.py` | Master/Worker/Verifier prompt templates |
| `src/qwenpaw/agents/mission/mission_runner.py` | Two-phase execution engine: code-level iteration loop + Toolkit group tool restriction |
| `src/qwenpaw/agents/mission/state.py` | File-based state management (prd.json, progress.txt, loop_config.json, task.md) |
| `src/qwenpaw/app/runner/mission_dispatch.py` | Runner integration layer with session-scoped automatic follow-up routing |
| `src/qwenpaw/cli/mission_cmd.py` | CLI entry points (`qwenpaw mission start/status/list`) |

### Modified Files (7)

| File | Description |
|---|---|
| `src/qwenpaw/app/runner/runner.py` | Integrate Ralph two-phase dispatch, auto-routing for follow-up messages + lightweight context refresh |
| `src/qwenpaw/cli/main.py` | Register `ralph` CLI subcommand group |
| `console/src/locales/{en,zh,ja,ru}.json` | Add i18n description for `/mission` slash command |
| `console/src/pages/Chat/index.tsx` | Register slash command suggestions in frontend |

### Architecture

```
User: /mission Implement user authentication
        │
        ▼
   handler.py ── parse command ──▶ create loop_dir + state files
        │                          write loop_config.json (phase=prd_generation)
        │                          inject MASTER_PROMPT into agent messages
        ▼
   mission_dispatch.py ──▶ return {mission_phase:1, loop_dir, max_iterations}
        │
        ▼
   runner.py ── detect mission_info ──▶ dispatch to mission_runner
        │
        ▼
   mission_runner.py
        ├── Phase 1 (run_mission_phase1)
        │     Agent generates prd.json → code validates schema → report to user
        │     User confirms → agent writes current_phase=execution_confirmed
        │     Code detects signal → seamless transition to Phase 2
        │
        └── Phase 2 (run_mission_phase2)
              Code: set_phase2_tool_restrictions() — disable impl tools
              Code: for-loop (max_iterations)
                Master dispatches current batch:
                  Worker(s) ──implement──▶ Verifier(s) ──adversarial──▶ VERDICT
                  PASS → Master updates prd.json passes=true
                  FAIL → Master retries worker (with error context)
                Code checks prd.json stories.passes
                all pass → done ✅
                else → inject continuation msg → next iteration
              Code: finally → restore_tools()
```

### Worker → Verifier Pipeline

Each story follows this completion flow:

```
┌─────────┐     ┌──────────┐     ┌─────────────┐
│  Master  │────▶│  Worker  │────▶│  Verifier   │
│(control) │     │(implement)│     │(adversarial)│
└─────────┘     └──────────┘     └─────────────┘
                     │                   │
                     │ implements story   │ VERDICT: PASS/FAIL/PARTIAL
                     │ runs quality checks│ with command evidence
                     │ does NOT set passes│ Master updates prd.json
                     ▼                   ▼
```

**Key design decisions:**
- Worker **no longer self-grades** (`passes: true`) — eliminates "judge and player" problem
- Verifier is an **adversarial role** — its goal is to "try to break the implementation"
- Verifier is **strictly read-only** — prohibited from modifying project files
- Each check must include **Command run + Output observed** — reading code alone does not count as PASS
- Verifier prompt inspired by Claude Code's `verificationAgent.ts`

### Code-Level Guarantees (Not Prompt-Dependent)

| Dimension | Implementation |
|---|---|
| Iteration loop | `for` loop in `mission_runner.py`; agent stops → code checks prd.json → injects continuation |
| Tool restriction | Phase 2 disables shell/write/edit via `Toolkit.update_tool_groups("mission_impl", active=False)` |
| PRD validation | `validate_prd()` checks schema before Phase 1→2 transition |
| Max iterations | Hard code limit, not LLM self-discipline |
| Phase transition | Agent writes loop_config signal → code detects and executes transition |
| Session binding | loop_config stores session_id, preventing cross-session interference |
| Verification isolation | Worker and Verifier are separate sessions; Verifier is read-only |

### User Experience

- First message uses `/mission` to trigger; subsequent messages auto-route to the active mission
- Supports `/mission status` and `/mission list` subcommands
- Supports `--verify <command>` to specify verification command (e.g. `pytest`), passed to Verifier
- CLI: `qwenpaw mission start "task description"`
- Agent automatically matches the user's input language

## Checklist

- [x] I ran `pre-commit run --all-files` locally and it passes
- [x] If pre-commit auto-fixed files, I committed those changes and reran checks
- [ ] I ran tests locally (`pytest` or as relevant) and they pass
- [ ] Documentation updated (if needed)
- [x] Ready for review

## Testing

1. **Basic flow**: Input `/mission Create a simple TODO app` → verify Phase 1 generates prd.json → confirm to enter Phase 2 auto-iteration
2. **Worker→Verifier pipeline**: After worker completes, Master should auto-dispatch Verifier → Verifier outputs VERDICT → Master updates prd.json accordingly
3. **Worker no self-grading**: After worker finishes, `passes` in prd.json should still be `false`
4. **Verifier read-only**: Verifier session should NOT modify any project files
5. **Tool restriction**: In Phase 2, master agent should NOT directly execute shell commands or write files
6. **Session binding**: A different session should not interfere with the active Ralph Loop
7. **Auto-routing**: Second message without `/mission` prefix should be correctly routed
8. **Subcommands**: `/mission status` and `/mission list` return correct status info
9. **CLI**: `qwenpaw mission start "test task"` triggers correctly
10. **--verify**: `qwenpaw mission start "task" --verify pytest` should pass `pytest` to Verifier prompt

## Local Verification Evidence

```bash
pre-commit run --all-files
# Passed (all hooks green)

pytest
# TODO: Ralph Loop unit tests to be added
```

## Additional Notes

- Prompt templates adapted from [snarktank/ralph](https://github.com/snarktank/ralph) (MIT License), copyright attributed in `__init__.py`
- Verifier prompt inspired by [Claude Code](https://github.com/anthropics/claude-code)'s `verificationAgent.ts` design
- Design document available at `design/agentic-ralph-loop.md` (not included in this commit)
