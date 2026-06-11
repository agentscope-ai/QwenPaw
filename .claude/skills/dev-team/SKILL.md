---
name: dev-team
description: Run the qwenpaw developer team (plan -> code -> review -> test) on a specific change. Surface-aware: backend changes (src/qwenpaw, Python/AgentScope) go through the agentscope-guardian gate and qwenpaw-coder + pytest; frontend UI/UX changes (console/, React/TS) go through qwenpaw-frontend-designer + vitest, ungated. Use when the user wants a feature/fix/UI change implemented in qwenpaw with built-in review and tests. Trigger on requests like "use the dev team to ...", "implement X in qwenpaw with review and tests", "redesign/restyle this Console screen with the team", "/dev-team ...".
---

# QwenPaw Dev Team

Orchestrates a multi-agent pipeline that implements a change to qwenpaw the way a small team would: a lead/guardian plan, an implementer, a reviewer (with fix loops), and a tester (with fix loops). The pipeline is **surface-aware** and routes work to the right specialist:

- **Backend** (`src/qwenpaw/**`, Python/AgentScope) → grounded in `docs/agentscope-v2/`, gated by the guardian, implemented by `qwenpaw-coder`, tested with pytest.
- **Frontend** (`console/**`, TS/React UI/UX) → grounded in `website/public/docs/plugins.en.md` + `console/src/` patterns, **not** guardian-gated, implemented by `qwenpaw-frontend-designer`, tested with vitest.
- **Mixed** → both, in the same run.

(There is no `docs/qwenpaw/` directory — the plan stage classifies the surface and reads the right sources.)

## Components

- **Subagents** (`.claude/agents/`): `qwenpaw-coder` (backend), `qwenpaw-frontend-designer` (UI/UX), `qwenpaw-reviewer` (surface-aware), `qwenpaw-tester` (pytest + vitest).
- **Sourcing** (`.claude/agents/`, runs *before* the pipeline): `qwenpaw-resource-scout` scouts the public ecosystem (top-rated GitHub repos, MCP registries, skill/plugin/agent-team marketplaces) for resources compatible with the fork's AgentScope 2.x + QwenPaw stack, then delivers an **implementation report and awaits approval**. It is **read-only / propose-only** — it never installs, adds an MCP server, or edits anything on its own. On approval it hands the concrete integration to this pipeline. Companion: `qwenpaw-upstream-watcher` does the same for the single upstream repo.
- **Orchestrator** (`.claude/workflows/dev-team.js`): plan/classify, then a single cyclic **state graph** `CODE → REVIEW → {CODE | TEST} → {CODE | DONE}` (LangGraph-style) — so a fix prompted by a test failure is re-reviewed before re-testing. One global budget (`maxRounds` code iterations) bounds the cycle. The Code phase is routed to the coder and/or the frontend-designer by detected surface.
- **Gate** (backend only): edits to `src/qwenpaw/**` / agentscope-importing `.py` are blocked until the plan stage records approval (`scripts/agentscope_guardian_approve.py`). Frontend `console/**` files are not gated. The pipeline handles this itself.

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
