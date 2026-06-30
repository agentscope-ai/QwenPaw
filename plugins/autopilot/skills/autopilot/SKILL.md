# Autopilot — Multi-Phase Autonomous Execution

You are operating in **Autopilot mode**: a fully autonomous pipeline that takes a brief and delivers working code through structured phases.

## Phases

### 1. Expansion
- Analyze the brief
- Identify scope, dependencies, and risks
- Produce a high-level plan
- Save phase to `.qwenpaw/loop_state/autopilot-state.json`: `{"phase": "expansion"}`

### 2. Planning
- Break down into detailed tasks
- Define acceptance criteria for each task
- Identify the implementation order
- Update phase: `{"phase": "planning"}`

### 3. Execution
- Implement each task according to the plan
- Write code, create files, run commands
- Update phase: `{"phase": "execution"}`

### 4. QA
- Run tests for all implemented changes
- Fix any failing tests
- Verify code style and linting
- Update phase: `{"phase": "qa"}`

### 5. Validation
- Review all changes holistically
- Use `spawn_subagent` for independent review
- Verify the brief is fully addressed
- Update phase: `{"phase": "validation"}`

### 6. Complete
- Output a comprehensive summary
- List all files changed
- Report test results
- Update phase: `{"phase": "complete"}`

## Rules

- **Follow the phases in order.** Do not skip phases.
- **Update the state file at every phase transition.**
- **If execution hits a blocker**, escalate in the summary rather than silently skipping.
- **In QA phase**, actually run the tests. Do not assume they pass.
- **In Validation phase**, use `spawn_subagent` for an independent review.

## State File

Path: `.qwenpaw/loop_state/autopilot-state.json`

The loop exits when `phase === "complete"`.
