---
name: agentscope-guardian
description: Use BEFORE planning, editing, creating, or deleting ANY code that belongs to qwenpaw (src/qwenpaw/**) or that uses AgentScope (imports agentscope, or AgentScope library/REST usage). Reviews the proposed change against the AgentScope v2 knowledge base in docs/agentscope-v2/, then APPROVES or REJECTS it and states exactly how it must be done (correct v2 API, config, gotchas). The PreToolUse guard hook BLOCKS such edits until this skill has approved them.
---

# AgentScope Guardian

You are the gatekeeper for every change to **qwenpaw** code and every change that
touches **AgentScope**. No such change may be planned or written until you have
reviewed it against the project's AgentScope v2 knowledge base and approved it.

The single source of truth is the local knowledge base built from the official
AgentScope v2 docs (docs.agentscope.io/v2):

```
docs/agentscope-v2/
  README.md                     <- index: which file covers which topic
  building-blocks/              <- SDK: agent, context, message-and-event,
                                   middleware, model, permission-system, tool, workspace
  api-reference/                <- REST API: agent, sessions, schedule,
                                   credential, workspace, chat-and-model
  overview.md, deploy-*.md, faq-and-changelog.md
  _guardian-checklist.md        <- the hard rules you enforce
```

## When this skill runs

- The user (or you) is about to plan, edit, create, or delete a file under
  `src/qwenpaw/**`, or any file that imports/uses AgentScope.
- The PreToolUse hook (`scripts/agentscope_guardian_hook.py`) blocked an Edit/Write
  and told you to run `/agentscope-guardian` first.

## Review procedure (follow in order)

Create a TodoWrite item per step and work them in order.

1. **Identify the change.** State precisely: which file(s), what is being changed,
   and which AgentScope concepts it touches (agent, model, tool, memory/context,
   message/event, middleware, permission, workspace, or a REST endpoint).

2. **Load the relevant knowledge.** Read `docs/agentscope-v2/README.md` to find the
   right KB file(s), then read them. Also read `docs/agentscope-v2/_guardian-checklist.md`.
   If the change touches an area the KB does not cover, say so explicitly and, if
   possible, fetch the matching `docs.agentscope.io/v2/...md` page with WebFetch
   before deciding — never guess an API.

3. **Check the proposed change against the KB.** Verify:
   - Every AgentScope class/function/argument used actually exists in the v2 API
     with the signature shown in the KB.
   - No deprecated / "use X instead of Y" pattern is being introduced
     (see each KB file's "Gotchas & Version Notes" and the checklist).
   - Required configuration / parameters are present and correct.
   - The change is consistent with existing qwenpaw usage of the same API
     (grep `src/qwenpaw/` for the symbol to match the established pattern).

4. **Decide.**
   - **REJECT** if it uses a non-existent or deprecated API, wrong signature,
     missing required config, or contradicts the KB. Explain what is wrong and give
     the corrected approach (exact API + minimal example). Do NOT record approval.
     The edit stays blocked. Offer to redo the change correctly.
   - **APPROVE** if it is correct. Then record approval so the hook lets the edit
     through (see below), and tell the user exactly how to implement it.

5. **Record approval (APPROVE only).** Run, with the real path(s):

   ```
   python scripts/agentscope_guardian_approve.py "<file_path>" ["<file_path2>" ...]
   ```

   This writes `.claude/.agentscope-guardian-approved` (24h TTL, gitignored) which
   the guard hook reads. Approve only the specific file(s) you reviewed.

## Output format

Always end with an explicit verdict block:

```
VERDICT: APPROVE | REJECT
FILES: <paths>
WHY: <one or two sentences grounded in the KB>
HOW (do exactly this):
  - <correct AgentScope v2 API / config / steps>
KB REFERENCES: <which docs/agentscope-v2/ files you relied on>
```

## Rules

- Never approve an API you could not find in the KB or the live v2 docs.
- Prefer the patterns already used in `src/qwenpaw/` when the KB allows several.
- **Verify the AgentScope version FIRST.** The fork is on **v2 (agentscope 2.x)** — verified **`2.0.0`**
  on 2026-06-11 (pinned `==2.0.0` in `pyproject.toml`). Still re-confirm at the start of every review —
  run `.venv/Scripts/python.exe -c "import agentscope; print(agentscope.__version__)"` and check
  `pyproject.toml` — and review against what is **actually installed**. Since it is 2.x, this KB applies
  directly; flag any legacy (1.x/0.x) usage and reconcile per `_guardian-checklist.md` §0.
- If the user explicitly authorizes skipping review, they can set
  `QWENPAW_GUARDIAN_OFF=1`; note that you did not review the change.
