---
name: dev-team
description: Run the qwenpaw developer team (code -> review -> test) on a specific change. Use when the user wants a feature/fix implemented in qwenpaw with built-in review and tests, grounded in the AgentScope v2 knowledge base (docs/agentscope-v2/) and respecting the agentscope-guardian gate. Trigger on requests like "use the dev team to ...", "implement X in qwenpaw with review and tests", "/dev-team ...".
---

# QwenPaw Dev Team

Orchestrates a multi-agent pipeline that implements a change to qwenpaw the way a small team would: a guardian plan/approval, a coder, a reviewer (with fix loops), and a tester (with fix loops). Every stage is grounded in `docs/agentscope-v2/` and `docs/qwenpaw/` and obeys the guardian gate.

## Components

- **Subagents** (`.claude/agents/`): `qwenpaw-coder`, `qwenpaw-reviewer`, `qwenpaw-tester`.
- **Orchestrator** (`.claude/workflows/dev-team.js`): guardian → code ↔ review (loop) → test ↔ fix (loop).
- **Gate**: edits to `src/qwenpaw/**` / agentscope-importing `.py` are blocked until the guardian stage records approval (`scripts/agentscope_guardian_approve.py`). The pipeline handles this itself.

## How to run

This pipeline can edit real code and spawn several agents, so it runs through the **Workflow** tool, which the user must opt into. When this skill is invoked:

1. **Get a concrete task.** You need a clear description of the change. If the user was vague, ask for: what behavior to add/fix, and (optionally) which files. Do not start with an underspecified task.
2. **Confirm scope** briefly (one line) and that they want the multi-agent run (it costs tokens).
3. **Invoke the workflow:**

   Call `Workflow` with:
   ```
   { name: "dev-team", args: { task: "<clear task description>", files: ["src/qwenpaw/.../x.py"], maxRounds: 2 } }
   ```
   - `task` (required): the change to make.
   - `files` (optional): hint of target files; the guardian will confirm/expand.
   - `maxRounds` (optional, default 2): review and test fix-loop iterations.

4. **Relay the result.** The workflow returns `{ status: GREEN | NEEDS_ATTENTION, finalReview, finalTest, approvedFiles, plan, ... }`. Summarize: what changed, review verdict, test result. If `NEEDS_ATTENTION`, surface the outstanding blockers/failures and offer to continue (re-run with more rounds or fix manually).

## Notes

- For pure exploration or a one-line trivial edit, you don't need the team — just do it (still respect the guardian gate for gated files).
- If the guardian stage returns `approved=false`, the change was judged unsound (e.g. non-existent/deprecated AgentScope API). Report its `concerns` and revise the task rather than forcing it.
- The pipeline targets fast, affected tests — not the whole suite. Run the full suite separately if needed.
