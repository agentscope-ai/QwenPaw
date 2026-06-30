<!--
  Based on oh-my-claudecode (https://github.com/nicobailon/oh-my-claudecode)
  Adapted for QwenPaw loop plugin infrastructure.
  License: MIT — see original project for full terms.
-->
---
name: ralph
description: PRD-driven persistence loop until task completion with verification
argument-hint: "<task description>"
level: 4
---

[RALPH + ULTRAWORK - ITERATION {{ITERATION}}/{{MAX}}]

Your previous attempt did not output the completion promise. Continue working on the task.

<Purpose>
Ralph is a PRD-driven persistence loop that keeps working on a task until ALL user stories in prd.json have passes: true and are reviewer-verified. It wraps ultrawork's parallel execution with session persistence, automatic retry on failure, structured story tracking, and mandatory verification before completion.
</Purpose>

<Use_When>
- Task requires guaranteed completion with verification (not just "do your best")
- User says "ralph", "don't stop", "must complete", "finish this", or "keep going until done"
- Work may span multiple iterations and needs persistence across retries
- Task benefits from structured PRD-driven execution with reviewer sign-off
</Use_When>

<Do_Not_Use_When>
- User wants a full autonomous pipeline from idea to code — use `autopilot` instead
- User wants to explore or plan before committing — use planning skill instead
- User wants a quick one-shot fix — delegate directly
- User wants manual control over completion — use `ultrawork` directly
</Do_Not_Use_When>

<Why_This_Exists>
Complex tasks often fail silently: partial implementations get declared "done", tests get skipped, edge cases get forgotten. Ralph prevents this by:

1. Structuring work into discrete user stories with testable acceptance criteria (prd.json)
2. Iterating story-by-story until each one passes
3. Tracking progress and learnings across iterations (progress.txt)
4. Requiring fresh reviewer verification against specific acceptance criteria before completion
</Why_This_Exists>

<PRD_Mode>
By default, ralph operates in PRD mode. A scaffold `prd.json` is auto-generated when ralph starts if none exists. Active transient PRD state is session-scoped at `.qwenpaw/loop_state/{sessionId}/prd.json`.

**Startup gate:** Ralph always initializes and validates `prd.json` at startup.
</PRD_Mode>

<Execution_Policy>
- Fire independent agent calls simultaneously — never wait sequentially for independent work
- Use `run_in_background: true` for long operations (installs, builds, test suites)
- Deliver the full implementation: no scope reduction, no partial completion, no deleting tests to make them pass
</Execution_Policy>

<Steps>
1. **PRD Setup** (first iteration only):
   a. Check the active PRD file in the Ralph loop state directory (`.qwenpaw/loop_state/{sessionId}/prd.json`).
   b. If no legacy PRD exists, auto-generate a scaffold at the active PRD path.
   c. **CRITICAL: Refine the scaffold.** The auto-generated PRD has generic acceptance criteria. You MUST replace these with task-specific criteria:
      - Analyze the original task and break it into right-sized user stories
      - Write concrete, verifiable acceptance criteria for each story
      - Order stories by priority (foundational work first, dependent work later)
      - Write the refined PRD back to the active PRD path
   d. Initialize `progress.txt` if it doesn't exist

2. **Pick next story**: Read the active PRD file and select the highest-priority story with `passes: false`.

3. **Implement the current story**:
   - Delegate to specialist agents at appropriate tiers:
     - Simple lookups: lightweight model
     - Standard work: standard model
     - Complex analysis: powerful model
   - If during implementation you discover sub-tasks, add them as new stories to the active PRD file
   - Run long operations in background

4. **Verify the current story's acceptance criteria**:
   a. For EACH acceptance criterion in the story, verify it is met with fresh evidence
   b. Run relevant checks (test, build, lint, typecheck) and read the output
   c. If any criterion is NOT met, continue working — do NOT mark the story as complete

5. **Mark story complete**:
   a. When ALL acceptance criteria are verified, set `passes: true` for this story
   b. Record progress in `progress.txt`: what was implemented, files changed, learnings

6. **Check PRD completion**:
   a. Read the active PRD file — are ALL stories marked `passes: true`?
   b. If NOT all complete, loop back to Step 2 (pick next story)
   c. If ALL complete, proceed to Step 7 (reviewer verification)

7. **Reviewer verification** (tiered, against acceptance criteria):
   - <5 files, <100 lines with full tests: standard review
   - Standard changes: standard review
   - >20 files or security/architectural changes: thorough review
   - The reviewer verifies against the SPECIFIC acceptance criteria from prd.json

8. **On approval**: Clean up all state files and exit the loop

9. **On rejection**: Fix the issues raised, re-verify, then loop back
</Steps>

<Examples>
<Good>
PRD refinement in Step 1:
```
Auto-generated scaffold has:
  acceptanceCriteria: ["Implementation is complete", "Code compiles without errors"]

After refinement:
  acceptanceCriteria: [
    "Function X returns Y when given Z",
    "Test file exists at path P and passes",
    "TypeScript compiles with no errors (npm run build)"
  ]
```
Why good: Generic criteria replaced with specific, testable criteria.
</Good>

<Good>
Story-by-story verification:
```
1. Story US-001: "Add flag detection helpers"
   - Criterion: "Function detects flags correctly" → Run test → PASS
   - Criterion: "TypeScript compiles" → Run build → PASS
   - Mark US-001 passes: true
2. Story US-002: "Wire PRD into the pipeline"
   - Continue to next story...
```
Why good: Each story verified against its own acceptance criteria before marking complete.
</Good>

<Bad>
Claiming completion without verification:
"All the changes look good, the implementation should work correctly. Task complete."
Why bad: Uses "should" and "look good" — no fresh evidence, no story-by-story verification.
</Bad>
</Examples>

<Escalation_And_Stop_Conditions>
- Stop and report when a fundamental blocker requires user input (missing credentials, unclear requirements, external service down)
- Stop when the user says "stop", "cancel", or "abort"
- Continue working when the loop system says to continue
- If the reviewer rejects verification, fix the issues and re-verify (do not stop)
- If the same issue recurs across 3+ iterations, report it as a potential fundamental problem
</Escalation_And_Stop_Conditions>

<Final_Checklist>
- [ ] All prd.json stories have `passes: true` (no incomplete stories)
- [ ] prd.json acceptance criteria are task-specific (not generic boilerplate)
- [ ] All requirements from the original task are met (no scope reduction)
- [ ] Zero pending or in_progress TODO items
- [ ] Fresh test run output shows all tests pass
- [ ] Fresh build output shows success
- [ ] progress.txt records implementation details and learnings
- [ ] Reviewer verification passed against specific acceptance criteria
</Final_Checklist>

## State File

Path: `.qwenpaw/loop_state/{sessionId}/ralph-state.json`

The system will check this file to determine if the loop should continue. The loop exits when all stories have `passes: true`.

Original task:
{{PROMPT}}
