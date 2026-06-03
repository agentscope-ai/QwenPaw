---
name: make-skill
description: "Use this skill when sedimenting a session into a reusable workspace skill. Triggers when the user wants to turn the current conversation, workflow, or troubleshooting path into a SKILL.md. Phrases like 'turn this into a skill', 'remember how I did X', 'save this workflow', 'make a skill from this', and any /make-skill <focus> invocation should fire this skill."
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

# Make Skill

Turn the current session into a reusable workspace skill.

You orchestrate a two-phase flow:

* **Phase A.** Propose a compact plan, yield the turn for user approval.
* **Phase B.** On approval, write the full SKILL.md body based on THIS
  conversation, then persist via `materialize_skill`.

Do **not** call `write_file` to save the SKILL.md directly. Always go through
`materialize_skill`, which runs the security scanner and writes the manifest
atomically.

## Step 0. Determine the focus and derive a skill name

Two invocation paths:

* `/make-skill <focus>`. The focus follows the command verbatim.
* Natural language ("turn this into a skill", "save this workflow",
  "把刚才的 X 流程变成 skill"). Derive a short focus phrase from the
  conversation topic the user wants to capture. If ambiguous, ask a
  one-line clarification first.

Derive the skill name from focus with **this exact rule**:

```
skill_name = "-".join(focus.split())
```

Internal whitespace (space, tab, full-width space, multiple spaces) collapses
to a single `-`. Other characters stay as is.

Examples:

* `cooking` → `cooking`
* `view image debug` → `view-image-debug`
* `烹饪 食谱` → `烹饪-食谱`
* `Stock Price` → `Stock-Price` (case preserved)

Use this `skill_name` consistently as `plan.name` in Step 1 and as the
`name=` argument to `materialize_skill` in Step 3.

## Step 1. Propose the plan and yield for approval

Call `create_plan` with **all four required arguments**
(`name`, `description`, `expected_outcome`, `subtasks`):

* **`name`**: the normalised `skill_name` from Step 0.
* **`description`**: a COMPACT preview the user reviews. Two parts:
  * **Part 1: Trigger preview.** 2 to 4 sentences, plain language. Cover
    all three of:
    * **Goal.** The end result this skill produces.
    * **Trigger.** User phrasings and contexts that should invoke it. Be
      a bit pushy on synonyms.
    * **I/O.** What inputs it expects, what outputs it produces.
    Not yet SKILL.md frontmatter format; that gets distilled later.
  * **Part 2: Step outline.** Numbered list, one short verb phrase per
    line. No per-step detail, no parameters, no error handling, no
    sub-bullets, no `##` sub-headings. Just the shape, so the user can
    judge ordering and scope and refine. Example layout (do NOT copy
    this content):
    ```
    1. <verb phrase, ~5-10 words>
    2. <verb phrase, ~5-10 words>
    3. <…>
    ```
    Draw step names from what actually happened in THIS conversation.
    Don't fabricate; omit anything not grounded in the conversation.
* **`expected_outcome`** (plan-level, REQUIRED — distinct from the
  subtask's `expected_outcome`): one concrete sentence about what
  success looks like for the whole skill creation. Use the literal
  string `"A new workspace skill <skill_name> is created, enabled, and
  invocable via /<skill_name>."` with `<skill_name>` substituted.
* **`subtasks`**: a list with a single subtask:
  * `name`: `"Write and materialize skill"`
  * `description`: `"Write the SKILL.md body and call materialize_skill."`
  * `expected_outcome`: `"Skill created and visible via /skills."`

Write `plan.name` and `plan.description` in the same language as the user's
recent messages. `expected_outcome` can stay in English.

After `create_plan` returns, **yield the turn**. The user will reply approve,
refine, or cancel. The `/plan` mode's standard machinery handles the rest:

* Refine: call `revise_current_plan` with feedback baked into name,
  description, or step outline.
* Cancel: call `finish_plan` with `state="abandoned"`.

When presenting the plan, render the standard plan card. Do NOT add ad-hoc
fields like `Subtask: …` or `Focus: …` in the chat message. Use the
normalised `plan.name`, not the raw focus.

### Plan-tools-unavailable fallback

If `create_plan` is not in your toolkit (plan mode disabled in this
workspace), fall back to a text-based plan:

1. Write the same compact preview (Part 1 trigger + Part 2 step outline)
   as a plain chat message to the user.
2. End the message asking the user to reply approve, refine, or cancel.
3. **Yield the turn.** On approve, jump to Step 2 (write the body) using
   the outline you proposed. On refine, revise the text plan and yield
   again. On cancel, stop here.
4. Skip the `finish_subtask` / `finish_plan` calls in Step 5; they don't
   apply when there's no plan.

## Step 2. On approval, write the SKILL.md body

Once the user approves the plan and the single subtask is in-progress,
write a complete, detailed SKILL.md body grounded in THIS conversation.
Length is fine when content is load-bearing.

Writing style:

* Use the imperative form.
* Explain WHY non-obvious instructions matter (theory of mind for the next
  agent). Avoid heavy-handed `MUST`s.
* Target body length under ~500 lines. If approaching that, split into
  sub-sections with clear pointers.

### 2a. Align with the approved step outline

Body sections align 1-to-1 with `plan.description` Part 2: same order, same
scope. Use the step's verb phrase as the section heading. If the user
refined Part 2 during approval, follow the **refined** version.

### 2b. Fill each step from THIS conversation

For every step, answer four concrete questions grounded in what actually
happened in the session, not in common knowledge:

* **Which tool, API, file, or command actually worked?** Cite the real
  name. If multiple were tried, cite **only** the one that worked.
* **What concrete parameters did it take?** Use real argument values from
  the session, not placeholders. The next agent should be able to copy
  and run without guessing.
* **What errors hit this path, and how to avoid them?** Phrase as
  preventive guidance. Example: *"Note: the endpoint returns 429 if
  called more than once per second. Pass `delay=2` from the start to
  avoid the retry loop we saw earlier."*
* **What dead-ends should be skipped?** If three paths were tried and
  one worked, document the winning path in full. Mention failed paths
  **only** as terse `avoid X` reminders, not as full sub-procedures.

If the conversation doesn't contain a real answer for a question, **omit**
it instead of inventing one. Inventing parameters or error notes is the
most common failure mode of this skill.

### 2c. Optional sections

Add these only when they help a future agent. No fixed schema:

* **Prerequisites.** Env vars, auth credentials, expected input files,
  tool versions.
* **Worked example.** One realistic invocation, input through output.
* **Failure modes and recovery.** Known failure patterns and how to
  handle them.
* **Edge cases.** Anything surprising the next agent would otherwise
  stumble into.

Skip anything that doesn't apply. Empty sections are worse than omitted
ones.

### 2d. Output format (only if stable)

If the session settled on a stable output shape (table, JSON schema,
markdown template), document it **once** at the top of the producing step
with an `ALWAYS use this template:` block. Example:

```markdown
ALWAYS use this exact template:

| Ticker | Last close | Currency | Source |
|--------|-----------|----------|--------|
| <symbol> | <price> | <iso-4217> | <api-name> |
```

Skip this for skills whose output is genuinely free-form.

### 2e. Self-check before persisting

Re-read the body once and verify ALL THREE. Single pass, no second round:

* **Concise.** No redundancy; don't restate what's already obvious.
* **Covers focus end-to-end.** Every step from `plan.description` Part 2
  is present in the body and substantiated by session facts.
* **Correct.** Every tool name, API name, parameter value, and error note
  accurately reflects what actually happened. **No invented facts.**

If any check fails, revise the body.

## Step 3. Persist via `materialize_skill`

Call `materialize_skill` with:

* **`name`**: the same normalised `skill_name` you used for `plan.name`.
* **`description`**: a tight `Use this skill when …` string distilled from
  `plan.description` Part 1. ≤ 200 characters. Preserve synonyms and
  adjacent phrasings from the preview (LLMs tend to under-trigger skills,
  so a slightly pushy description is better than a narrow one).
* **`body`**: the reviewed SKILL.md body. No frontmatter; the tool renders
  it.

Do **not** call `write_file` to save SKILL.md directly.

## Step 4. Handle errors from `materialize_skill`

### Conflict (skill name already taken)

The tool returns the conflicting name and a suggested rename. **Recover
automatically; don't gate this on a user question.**

1. Pick a fresh name. The tool's suggestion (e.g. timestamped) is fine,
   but anything that avoids the conflict works. Examples for an existing
   `cooking`: `cooking-v2`, `cooking-2`, `cooking-new`.
2. Call `revise_current_plan` to set `plan.name` to the chosen name. (In
   the text-plan fallback, just update your working name in memory.)
3. Call `materialize_skill` again with the new name.
4. When reporting success in Step 5, mention the rename so the user knows
   the original was taken. Example: *"Saved as `cooking-v2` because
   `cooking` was already in your workspace. Delete the old one and re-run
   if you want the original name back."*

### Format error

Fix the SKILL.md content (frontmatter fields, body sections, etc.) and
call `materialize_skill` again. Do NOT call `finish_subtask` until it
returns success.

### Security-scan rejection

Remove the flagged patterns from the body and retry.

### Other errors

Adjust inputs and retry, or abandon the plan if the failure is not
recoverable.

## Step 5. Finish

Once `materialize_skill` returns success:

1. Call `finish_subtask` for the single subtask.
2. Call `finish_plan` with `state="completed"`.
3. Tell the user the new skill is created and enabled, and they can
   invoke it via `/<skill_name>`.
