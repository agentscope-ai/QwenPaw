---
name: skill-maker
description: "Use this skill when sedimenting a session into a reusable workspace skill — when the user wants to turn the current conversation, workflow, or troubleshooting path into a SKILL.md. Triggers on phrases like 'turn this into a skill', 'remember how I did X', 'save this workflow', 'make a skill from this', or any /make-skill <focus> invocation. Reads the conversation history relevant to a focus, drafts a complete SKILL.md body, and persists it via the materialize_skill tool."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "✍️"
    requires: {}
---

<!--
  Inspired by Anthropic's `skill-creator` skill (the "creating a skill"
  portion in particular). Rewritten for QwenPaw.
  Credit: https://github.com/anthropics/skills/blob/main/skill-creator/SKILL.md
-->

# Skill Maker

Capture how a `focus` was accomplished in the current session as a reusable workspace skill. Read this file end-to-end, follow the steps, and persist via the `materialize_skill` tool at the end — do **not** write the SKILL.md directly with `write_file`.

## Context this skill expects

This skill is invoked by `/make-skill <focus>` after the user has approved a plan. By the time you read this, you have:

- `focus` — the user-supplied focus string (passed in the subtask).
- `plan.name` — the normalised skill directory name.
- `plan.description` — the compact preview the user approved, in two parts:
  - **Part 1**: trigger preview (goal + trigger phrasings + I/O shape).
  - **Part 2**: a numbered **step outline** (one short verb phrase per step).
- The full conversation memory of the current session.

If the user refined the plan during approval, the **refined** `plan.description` is the source of truth — the original draft is discarded.

## Scope: everything must serve `focus`

Every section, paragraph, and example in the body must serve the line "how `focus` was accomplished in THIS session". Ignore unrelated tangents — even if they happened in the same conversation, even if they were technically interesting. A future agent reading this skill should not be distracted by content that has nothing to do with the focus.

## Writing style

Use the imperative form. Address the reader as the agent who will execute the skill next time.

Explain WHY non-obvious instructions matter — modern LLMs use theory of mind to adapt, so a one-sentence reason is more durable than a heavy-handed `MUST` or `ALWAYS`. Brittle rules age badly; reasons survive context changes.

Target body length < ~500 lines. If you're approaching that, split details into sub-sections with clear pointers rather than padding the body.

## Step 1 — Align with the approved step outline

The body's main sections must align 1-to-1 with `plan.description` Part 2: same order, same scope. Use the step's verb phrase as the section heading.

If the user refined Part 2 during approval (added / removed / re-ordered steps), follow the **refined** version. Don't bring back removed steps; don't reorder.

## Step 2 — Fill each step from THIS conversation

For every step, answer four concrete questions, grounded in what actually happened in the session — not common knowledge:

- **Which tool / API / file / command actually worked?** Cite the real name. If multiple were tried, cite **only** the one that produced the working result.
- **What concrete parameters did it take?** Use the real argument values from the session, not placeholders. A future agent should be able to copy and run without guessing.
- **What errors hit this path, and how to avoid them?** Phrase as preventive guidance, e.g. *"Note: the endpoint returns 429 if called more than once per second — pass `delay=2` from the start to avoid the retry loop we saw earlier."*
- **What dead-ends should be skipped?** If three paths were tried and one worked, document the winning path in full. Mention failed paths **only** as terse `avoid X` reminders, not as full sub-procedures.

If the conversation does not contain a real answer for a given question, **omit** it rather than invent one — inventing parameters or error notes is the most common failure mode of this skill.

## Step 3 — Optional sections beyond the step list

Add sections beyond the step outline only when they help a future agent. No fixed schema:

- **Prerequisites**: env vars, auth credentials, expected input files, tool versions.
- **Worked example**: one realistic invocation with input → output.
- **Failure modes & recovery**: known failure patterns and how to handle them.
- **Edge cases / gotchas**: anything surprising the next agent would otherwise stumble into.

Skip anything that doesn't apply — empty sections are worse than omitted ones.

## Step 4 — Output format (only if stable)

If the session settled on a stable output shape (a fixed table layout, a JSON schema, a markdown template), document it **once** at the top of the producing step using an `ALWAYS use this template:` block, e.g.:

```markdown
ALWAYS use this exact template:

| Ticker | Last close | Currency | Source |
|--------|-----------|----------|--------|
| <symbol> | <price> | <iso-4217> | <api-name> |
```

Skip this step entirely for skills whose output is genuinely free-form (a written summary, a code refactor, a research note).

## Step 5 — Persist via `materialize_skill`

After drafting the body, **do a pre-call self-check** — re-read the body end-to-end once and verify ALL THREE:

- **Concise** — no redundancy; don't restate what's already obvious from earlier sections or the description.
- **Covers `focus` end-to-end** — every step from `plan.description` Part 2 is present in the body and substantiated by session facts; the body shows the full path from input to output.
- **Correct** — every tool name, API name, parameter value, and error note accurately reflects what actually happened in THIS conversation. **No invented facts, no guessed parameters.**

If any check fails, revise the body. 

Once the self-check passes, call `materialize_skill` with:

- `name` = `plan.name` (the normalised skill directory name).
- `description` = a tight `Use this skill when …` string distilled from `plan.description` Part 1. ≤ 200 characters. **Preserve** the synonyms and adjacent phrasings from the preview — LLMs tend to under-trigger skills, so a slightly pushy description is better than a narrow one.
- `body` = the SKILL.md body you just wrote (**no frontmatter** — the tool renders it).

Do **not** call `write_file` to save SKILL.md directly — `materialize_skill` runs the security scanner, writes the manifest entry, and enables the skill atomically; bypassing it leaves the workspace in an inconsistent state.

If `materialize_skill` returns an error (format / scan / name conflict), correct the relevant input and call it again. Do **not** call `finish_subtask` until `materialize_skill` returns success.
