---
name: autopilot
description: Full autonomous execution from idea to working code
argument-hint: "<product idea or task description>"
level: 4
---

<Purpose>
Autopilot takes a brief product idea and autonomously handles the full lifecycle: requirements analysis, technical design, planning, parallel implementation, QA cycling, and multi-perspective validation. It produces working, verified code from a 2-3 line description.
</Purpose>

<Use_When>
- User wants end-to-end autonomous execution from an idea to working code
- User says "autopilot", "auto pilot", "autonomous", "build me", "create me", "make me", "full auto", "handle it all", or "I want a/an..."
- Task requires multiple phases: planning, coding, testing, and validation
- User wants hands-off execution and is willing to let the system run to completion
</Use_When>

<Do_Not_Use_When>
- User wants to explore options or brainstorm — use planning skill instead
- User says "just explain", "draft only", or "what would you suggest" — respond conversationally
- User wants a single focused code change — use `ralph` or delegate directly
- User wants to review or critique an existing plan
- Task is a quick fix or small bug — use direct delegation
</Do_Not_Use_When>

<Why_This_Exists>
Most non-trivial software tasks require coordinated phases: understanding requirements, designing a solution, implementing in parallel, testing, and validating quality. Autopilot orchestrates all of these phases automatically so the user can describe what they want and receive working code without managing each step.
</Why_This_Exists>

<Execution_Policy>
- Each phase must complete before the next begins
- Parallel execution is used within phases where possible (Phase 2 and Phase 4)
- QA cycles repeat up to 5 times; if the same error persists 3 times, stop and report the fundamental issue
- Validation requires approval from all reviewers; rejected items get fixed and re-validated
</Execution_Policy>

<Steps>
1. **Phase 0 - Expansion**: Turn the user's idea into a detailed spec
   - **If deep-interview spec exists**: Skip analyst+architect expansion, use the pre-validated spec directly as Phase 0 output. Continue to Phase 1 (Planning).
   - **If input is vague** (no file paths, function names, or concrete anchors): Offer redirect to `/interview` for Socratic clarification before expanding
   - **Otherwise**: Analyst extracts requirements, Architect creates technical specification
   - Output: `.qwenpaw/loop_state/{sessionId}/spec.md`

2. **Phase 1 - Planning**: Create an implementation plan from the spec
   - Architect: Create plan (direct mode, no interview)
   - Critic: Validate plan
   - Output: `.qwenpaw/loop_state/{sessionId}/impl-plan.md`

3. **Phase 2 - Execution**: Implement the plan using Ralph + Ultrawork
   - Simple tasks: lightweight model
   - Standard tasks: standard model
   - Complex tasks: powerful model
   - Run independent tasks in parallel

4. **Phase 3 - QA**: Cycle until all tests pass
   - Build, lint, test, fix failures
   - Repeat up to 5 cycles
   - Stop early if the same error repeats 3 times (indicates a fundamental issue)

5. **Phase 4 - Validation**: Multi-perspective review in parallel
   - Functional completeness review
   - Security vulnerability check
   - Code quality review
   - All must approve; fix and re-validate on rejection

6. **Phase 5 - Cleanup**: Delete all state files on successful completion
</Steps>

<Examples>
<Good>
User: "autopilot A REST API for a bookstore inventory with CRUD operations using TypeScript"
Why good: Specific domain (bookstore), clear features (CRUD), technology constraint (TypeScript). Autopilot has enough context to expand into a full spec.
</Good>

<Good>
User: "build me a CLI tool that tracks daily habits with streak counting"
Why good: Clear product concept with a specific feature. The "build me" trigger activates autopilot.
</Good>

<Bad>
User: "fix the bug in the login page"
Why bad: This is a single focused fix, not a multi-phase project. Use direct delegation or ralph instead.
</Bad>

<Bad>
User: "what are some good approaches for adding caching?"
Why bad: This is an exploration/brainstorming request. Respond conversationally or use the plan skill.
</Bad>
</Examples>

<Escalation_And_Stop_Conditions>
- Stop and report when the same QA error persists across 3 cycles (fundamental issue requiring human input)
- Stop and report when validation keeps failing after 3 re-validation rounds
- Stop when the user says "stop", "cancel", or "abort"
- If requirements were too vague and expansion produces an unclear spec, offer redirect to `/interview` for Socratic clarification
</Escalation_And_Stop_Conditions>

<Final_Checklist>
- [ ] All 5 phases completed (Expansion, Planning, Execution, QA, Validation)
- [ ] All validators approved in Phase 4
- [ ] Tests pass (verified with fresh test run output)
- [ ] Build succeeds (verified with fresh build output)
- [ ] State files cleaned up
- [ ] User informed of completion with summary of what was built
</Final_Checklist>

## Deep Interview Integration

When autopilot is invoked with a vague input, Phase 0 can redirect to `/interview` for Socratic clarification:

```
User: "autopilot build me something cool"
Autopilot: "Your request is open-ended. Would you like to run a deep interview first?"
  [Yes, interview first (Recommended)] [No, expand directly]
```

If a deep-interview spec already exists, autopilot uses it directly as Phase 0 output (the spec has already been mathematically validated for clarity).

## Best Practices for Input

1. Be specific about the domain — "bookstore" not "store"
2. Mention key features — "with CRUD", "with authentication"
3. Specify constraints — "using TypeScript", "with PostgreSQL"
4. Let it run — avoid interrupting unless truly needed

## State File

Path: `.qwenpaw/loop_state/{sessionId}/autopilot-state.json`

The loop exits when `phase === "complete"`.
