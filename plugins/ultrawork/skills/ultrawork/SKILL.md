<!--
  Based on oh-my-claudecode (https://github.com/nicobailon/oh-my-claudecode)
  Adapted for QwenPaw loop plugin infrastructure.
  License: MIT — see original project for full terms.
-->
---
name: ultrawork
description: Parallel execution engine for high-throughput task completion
argument-hint: "<task description with parallel work items>"
level: 4
---

<Purpose>
Ultrawork is a parallel execution engine and execution protocol for independent work. It emphasizes intent grounding, parallel context gathering, dependency-aware task graphs for non-trivial work, and concise evidence-backed execution summaries. It is a component, not a standalone persistence mode — it provides parallelism and routing guidance, but not persistence, verification loops, or long-lived state management.
</Purpose>

<Use_When>
- Multiple independent tasks can run simultaneously
- User says "ulw", "ultrawork", or wants parallel execution
- You need to delegate work to multiple agents at once
- Task benefits from concurrent execution but the user will manage completion themselves
</Use_When>

<Do_Not_Use_When>
- Task requires guaranteed completion with verification — use `ralph` instead (ralph includes ultrawork)
- Task requires a full autonomous pipeline — use `autopilot` instead (autopilot includes ralph which includes ultrawork)
- There is only one sequential task with no parallelism opportunity — delegate directly
- User needs session persistence for resume — use `ralph` which adds persistence on top of ultrawork
</Do_Not_Use_When>

<Why_This_Exists>
Sequential task execution wastes time when tasks are independent. Ultrawork enables firing multiple agents simultaneously and routing each to the right model tier, reducing total execution time while controlling token costs. It is designed as a composable component that ralph and autopilot layer on top of.
</Why_This_Exists>

<Execution_Policy>
- Fire all independent agent calls simultaneously — never serialize independent work
- Use `run_in_background: true` for operations over ~30 seconds (installs, builds, tests)
- Run quick commands (git status, file reads, simple checks) in the foreground
- Resolve intent and uncertainty before implementation; explore first, ask only when still blocked
- For non-trivial tasks, produce a dependency-aware plan with parallel waves before execution
- Keep delegated-task reports concise: short summary, files touched, verification status, blockers
- Manual QA is required for implemented behavior, not just diagnostics
</Execution_Policy>

<Steps>
1. **Ground intent first**: Confirm whether the request is implementation, investigation, evaluation, or research; do not code before that is clear
2. **Gather context in parallel**:
   - Direct tools for quick reads/searches
   - Exploration agents for broad context
3. **Classify tasks by independence**: Identify which tasks can run in parallel vs which have dependencies
4. **Create a task graph for non-trivial work**:
   - Parallel Execution Waves
   - Dependency Matrix
   - Acceptance criteria and verification steps per task
5. **Route to correct tiers**:
   - Simple lookups/definitions: lightweight model
   - Standard implementation: standard model
   - Complex analysis/refactoring: powerful model
6. **Fire independent tasks simultaneously**: Launch all parallel-safe tasks at once
7. **Run dependent tasks sequentially**: Wait for prerequisites before launching dependent work
8. **Background long operations**: Builds, installs, and test suites use `run_in_background: true`
9. **Verify when all tasks complete** (lightweight):
   - Build/typecheck passes
   - Affected tests pass
   - Manual QA completed for implemented behavior
   - No new errors introduced
</Steps>

<Examples>
<Good>
Three independent tasks fired simultaneously at appropriate tiers.
Why good: Independent tasks at appropriate tiers, all fired at once.
</Good>

<Good>
Correct use of background execution: Long build runs in background while short task runs in foreground.
Why good: Maximizes parallelism by not blocking on long operations.
</Good>

<Bad>
Sequential execution of independent work.
Why bad: These tasks are independent. Running them sequentially wastes time.
</Bad>

<Bad>
Using the most powerful model for a trivial fix like adding a missing semicolon.
Why bad: Overkill for a trivial fix. Use a lightweight model instead.
</Bad>
</Examples>

<Escalation_And_Stop_Conditions>
- When ultrawork is invoked directly (not via ralph), apply lightweight verification only — build passes, tests pass, no new errors
- For full persistence and comprehensive verification, recommend switching to `ralph` mode
- If a task fails repeatedly across retries, report the issue rather than retrying indefinitely
- Escalate to the user when tasks have unclear dependencies or conflicting requirements
</Escalation_And_Stop_Conditions>

<Final_Checklist>
- [ ] All parallel tasks completed
- [ ] Build/typecheck passes
- [ ] Affected tests pass
- [ ] No new errors introduced
</Final_Checklist>

## Relationship to Other Modes

```
ralph (persistence wrapper)
 \-- includes: ultrawork (this skill)
     \-- provides: parallel execution only

autopilot (autonomous execution)
 \-- includes: ralph
     \-- includes: ultrawork (this skill)
```

Ultrawork is the parallelism layer. Ralph adds persistence and verification. Autopilot adds the full lifecycle pipeline.

## State File

Path: `.qwenpaw/loop_state/{sessionId}/ultrawork-state.json`

The loop exits automatically when all todos are cleared.
