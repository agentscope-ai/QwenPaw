---
name: make-skill
description: "Use this skill when sedimenting a session into a reusable workspace skill. Triggers when the user wants to turn the current conversation, workflow, or troubleshooting path into a SKILL.md. Phrases like 'turn this into a skill', 'remember how I did X', 'save this workflow', 'make a skill from this', and any /make-skill <focus> invocation should fire this skill."
metadata:
  builtin_skill_version: "1.1"
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

Do **not** call `write_file` to create the SKILL.md or any auxiliary files
(scripts, JSON, etc.) directly. All initial file creation must go through
`materialize_skill` (via the `body` and `extra_files` parameters), which runs
the security scanner and writes the manifest atomically. After successful
creation, use `edit_file` to modify existing files if needed.

## Step 0. Determine the focus and derive a skill name

### 0a. Determine the focus

Two invocation paths:

* `/make-skill <focus>`. The focus follows the command verbatim.
* Natural language ("turn this into a skill", "save this workflow",
  "把刚才的 X 流程变成 skill"). Derive a short focus phrase from the
  conversation topic the user wants to capture. If ambiguous, ask a
  one-line clarification first.

### 0b. Derive the skill name

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
  * **Part 2: Step outline and batch plan.** Two parts:
    * **Step outline.** Numbered list, one short verb phrase per line.
      No per-step detail, no parameters, no error handling, no
      sub-bullets, no `##` sub-headings. Just the shape, so the user
      can judge ordering and scope. Draw step names from what actually
      happened in THIS conversation. Don't fabricate; omit anything
      not grounded in the conversation.
      Example layout (do NOT copy this content):
      ```
      1. <verb phrase, ~5-10 words>
      2. <verb phrase, ~5-10 words>
      3. <…>
      ```
    * **Batch plan.** Briefly describe how the steps above will be
      organised into `run_tool_batch` JSON files:
      * Which steps chain into one batch (or need to be split into
        multiple batch files).
      * Which intermediate steps would normally require agent
        involvement but can actually be replaced by scripts (regex
        matching, keyword filtering, JSON parsing, etc.), reducing
        agent interaction and keeping more steps in the automated
        batch.
      * List the expected files, e.g.:
        ```
        scripts/main.json      — main batch workflow
        scripts/parse.py       — parse snapshot to extract target content
        ```
      The goal is to replace as much agent-in-the-loop judgement as
      possible with scripts, so the skill executes with a single
      `run_tool_batch` call and avoids multi-round agent-tool
      interaction. This lets the user see the batch structure before
      approving.
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
normalised `plan.name`, not the raw focus. This step only proposes the
plan and waits for user confirmation — do **not** call `materialize_skill`
here.

### Choose execution mode

After the user approves, ask about execution mode (yield one turn):

> Plan approved. Should Phase B (writing and persistence) **continue in
> the current conversation** or **run in the background via subagent**?
>
> - **Current conversation**: complete Phase B in this turn. Best when
>   iterative refinement is needed.
> - **Background**: delegate Phase B to a subagent without blocking the
>   current conversation. The subagent inherits this session's full
>   context and the approved plan.

**Yield the turn** and wait for the user's reply. If the user does not
explicitly choose, default to current-conversation mode.

* **Current conversation** mode: follow Steps 2–5 below as normal.
* **Background** mode: see the "Background Phase B" section below.

**If you are already a subagent** (spawned by the main agent via
`spawn_subagent`), skip the question and execute Steps 2–4 directly
(the main agent already handled plan closure; do not call any
plan-related tools).

### Background Phase B

Phase A (Steps 0–1) is already complete in the foreground. The user has
approved the plan. Now delegate Phase B to a subagent.

In this step you do **not** need to call `materialize_skill` or perform
any skill-creation work yourself — just assemble a task description and
submit it to the subagent, which will handle everything.

1. Assemble the following into a task description for the subagent:
   - The approved `plan.name` (`skill_name`) and plan content
   - Clear instructions: "Based on the current session context and the
     approved plan, execute make-skill Steps 2–4 in full: write the
     SKILL.md body, call materialize_skill to persist, verify batch
     references, test-run the batch. Report the result when done.
     **Do NOT call any plan-related tools (`create_plan`,
     `finish_subtask`, `finish_plan`). Skip user approval and complete
     all steps autonomously.**"
2. Call:
   ```
   spawn_subagent(
       task="<task description above>. Do NOT call any plan-related tools. Complete all steps autonomously.",
       fork=True,
       background=True,
   )
   ```
3. Immediately call `finish_subtask` for the single subtask, then call
   `finish_plan` with `state="completed"`. Do not wait for the subagent
   to finish.
4. Inform the user the task has been submitted. They can check progress
   via `check_agent_task(task_id=...)`. The subagent will create the
   skill in the workspace without requiring user approval mid-process.

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

### 2b. Organise the full workflow into a batch JSON (preferred execution method)

**The core of the SKILL.md body is a `run_tool_batch` call.** When the
future agent triggers this skill, it should **call the batch directly**
rather than executing tools step by step. Per-step notes serve only as
supplementary reference for debugging (see 2c), not as the primary
execution instructions.

Review the tool-call sequence from THIS session and capture the skill's
**complete end-to-end workflow** as a single `run_tool_batch` JSON file.
From start to finish, all steps that **can be executed unconditionally
in sequence** should go into the batch.

#### When applicable

* The skill's core workflow contains **≥ 2 tool-call steps**.
* Typical scenarios: bulk file operations, search-then-process, multi-
  file modification pipelines, multi-step browser automation, etc.
* **Most workflows can be fully automated with scripts.** Don't give up
  on including a step in the batch just because it "looks like it needs
  judgement". The vast majority of intermediate processing — content
  extraction, result filtering, format conversion, conditional logic,
  data cleaning — can be programmed by inserting
  `execute_shell_command` calls into the batch. Two approaches:
  * **Inline short scripts**: write `python3 -c "..."` one-liners
    directly in `command`.
  * **Standalone script files**: put complex logic in `.py` or `.sh`
    files etc. under `scripts/` (bundled via `extra_files`), and call
    them in the batch with `execute_shell_command`, e.g.
    `"command": "python3 <skill_dir>/scripts/parse.py --param1 ${steps.<index1>.<path>} --param2 ${steps.<index2>.<path>}"`.
  Pass previous steps' output to scripts via command-line arguments
  (`${steps.<index>.<path>}`), and the script's stdout feeds subsequent
  steps through `${steps}` references. This chains the entire workflow
  into a single batch with no manual intervention. Only steps that
  **truly require real-time user decisions** (e.g. "ask the user which
  option to pick", "wait for user confirmation") need to be excluded.

  `${steps.<index>.<path>}` is not limited to script calls — any tool's
  arguments can reference previous steps' output. For example, pass
  `read_file` results to `write_file`, or feed a `browser_use` snapshot
  into `execute_shell_command`.

  Example — take a browser snapshot, extract keyword-matching content
  with a standalone Python script, and write the result to a file.
  `${args.keyword}` etc. are runtime variables passed in via the `args`
  parameter when calling `run_tool_batch`, substituted before execution.

  `scripts/extract_headings.py` (bundled via `extra_files`):
  ```python
  import sys, re, json

  keyword = sys.argv[1]
  snapshot_file = sys.argv[2]
  with open(snapshot_file) as f:
      text = f.read()
  items = [
      m.group(1)
      for m in re.finditer(
          r'heading "([^"]*' + re.escape(keyword) + r'[^"]*)" \[ref=(\w+)\]',
          text,
      )
  ]
  print(json.dumps(items, ensure_ascii=False))
  ```

  Batch JSON (`scripts/extract.json`):
  ```json
  [
    {
      "tool_name": "browser_use",
      "arguments": {"action": "snapshot"}
    },
    {
      "tool_name": "write_file",
      "arguments": {
        "file_path": "${args.work_dir}/snapshot.txt",
        "content": "${steps.0.text}"
      }
    },
    {
      "tool_name": "execute_shell_command",
      "arguments": {
        "command": "python3 ${args.skill_dir}/scripts/extract_headings.py ${args.keyword} ${args.work_dir}/snapshot.txt"
      }
    },
    {
      "tool_name": "write_file",
      "arguments": {
        "file_path": "${args.output_file}",
        "content": "${steps.2.text}"
      }
    }
  ]
  ```
  This automates the "extract keyword-matching content from a snapshot"
  step that would otherwise require manual inspection: step 0 takes the
  page snapshot, step 1 writes it to a temp file, step 2 calls the
  standalone script which reads the file and extracts matches with
  regex, step 3 writes the result to the output file. Complex parsing
  logic goes into standalone `.py` files under `scripts/`. Both scripts
  and batch JSON are bundled into the skill directory via `extra_files`.
  When triggering the skill, just call:
  ```
  run_tool_batch(
    file_path="<skill_dir>/scripts/extract.json",
    args={
      "keyword": "search keyword",
      "skill_dir": "<this skill dir>",
      "work_dir": "<working directory>",
      "output_file": "result.json"
    }
  )
  ```

#### When NOT applicable (fall back to pure step-by-step)

The vast majority of workflows can be automated. Only fall back to
step-by-step logic when ALL of the following apply:

* **Content understanding cannot be rule-based** — impossible to handle
  with keyword matching, regex, JSON parsing, or any rule-based
  approach; requires semantic understanding. (Note: if the user provides
  explicit search terms or filter criteria, that IS rule-based and
  should go into the batch.)
* **Branching decisions cannot be predetermined** — the user must judge
  what to do next based on runtime context, rather than being able to
  supply all parameters upfront when triggering the skill.
* The entire skill is a single tool call (no batch needed).

Even when a workflow contains steps requiring human judgement, **still
extract all mergeable consecutive steps into batch files**. This means a
skill may ship with multiple batch files — e.g. `scripts/phase1.json`
(data acquisition phase) and `scripts/phase2.json` (result processing
phase), with the agent making semantic decisions in between. Automate as
much as possible.

#### SKILL.md body structure (when using batch)

The body should lead with the batch call:

````markdown
### Execution

This skill ships with a batch JSON file `scripts/<name>.json`.

**Call `run_tool_batch` strictly in the format below, using `file_path`
to load the file. Do not construct your own `actions` list inline.**

`run_tool_batch` requires an **absolute path** for `file_path`. Use the
absolute directory path you see when reading this SKILL.md to construct
the full path.

```
run_tool_batch(
  file_path="<this skill dir>/scripts/<name>.json",
  args={
    "param1": "<actual sample value>",
    "param2": "<actual sample value>"
  }
)
```

### Batch Parameters

Explain every parameter in `args`. Every variable used in the batch JSON
as `${args.<name>}` must be listed here:

* `param1`: what it controls; when the user should change it; the
  default/recommended value; example: `<actual sample value>`.
* `param2`: what it controls; when the user should change it; the
  default/recommended value; example: `<actual sample value>`.

When calling `run_tool_batch`, pass all parameters listed above. **Do not
pass `args={}` and do not omit `args`** when the batch JSON contains
`${args.<name>}` references; otherwise the placeholder may be used as a
literal filename, URL, or command argument.

### Batch failure handling

If `run_tool_batch` fails (returns `ok: false` or errors mid-way):
1. First verify every parameter listed in "Batch Parameters" was passed
   with a real value, especially that you did not pass empty `args={}`;
   then fix parameters based on the error message and retry.
2. If it still fails, try using `run_tool_batch` with an inline
   `actions` list instead of `file_path`.
3. If inline execution also fails, fall back to manual step-by-step
   execution using the "Step-by-step reference" section below.
4. After completing the task, tell the user: "The batch execution hit an
   issue so I completed the task manually. Would you like me to use
   edit_file to adjust and optimise this skill's batch script so it
   works correctly next time?"

### Step-by-step reference

The following details each batch step, for debugging or manual execution
only:

1. ...
2. ...

### Notes

(Place skill-specific notes here, such as parameter optimisation tips,
data format requirements, etc.)

**Execution reminder**: When triggering this skill, just call
`run_tool_batch(file_path=..., args=...)` as shown above to complete the
entire workflow. There is no need to write each action yourself
step by step. Only follow the "Batch failure handling" fallback if the
batch execution fails.
````

> **Path note**: `run_tool_batch` only accepts absolute paths. Batch
> JSON files are written into the skill directory via the `extra_files`
> parameter of `materialize_skill`. The agent receives the skill
> directory's absolute path in its system prompt (the `{dir}` in
> `Check "{dir}/SKILL.md"`). The SKILL.md body **must** explicitly tell
> the future agent to use that absolute directory to construct the
> `file_path`.

#### Batch JSON writing guidelines

* **`file_path` must be an absolute path.** The SKILL.md body should
  explicitly say: "use the directory path you see when reading this
  SKILL.md and append `scripts/xxx.json`", so the future agent can
  construct the absolute path.
* **Use `${args.<name>}`** to parameterise all values that vary by
  context (file paths, search keywords, URLs, etc.). Hard-code values
  that are always the same. The brace-delimited syntax is required so
  placeholders are unambiguous inside mixed-content strings like shell
  commands.
* **The SKILL.md body must include a `### Batch Parameters` section**.
  That section must explain every `${args.<name>}` used in the batch
  JSON: meaning, when the user should change it, default/recommended
  value, and one concrete sample value that can be used for a test run.
  The `run_tool_batch` example's `args` must contain those concrete
  sample values. Do not write `{}`, `null`, `<description>`, or only
  placeholder prose for required args.
* **Use `${steps.<index>.<path>}`** for inter-step references — later
  steps can reference earlier steps' output. For example,
  `"content": "${steps.0.text}"` references step 0's text result.
  The `<path>` depends on the actual return value structure of the
  preceding tool. `materialize_skill` will automatically analyse all
  `${steps}` references in the batch JSON and list them in its response.
  **You must follow the prompts to call each referenced tool and verify
  that its return value actually contains the referenced field.** If a
  field doesn't exist, use `edit_file` to fix the batch JSON file
  directly in the skill directory.
* Each action uses `"tool_name"` and `"arguments"` fields (`"tool"` +
  `"args"` also accepted).
* Max 50 steps per batch file. Split into multiple files if needed.
* JSON files are bundled into the skill directory via `extra_files`
  (see Step 3).

### 2c. Add step-by-step notes (reference documentation for the batch)

After the batch call section, provide brief per-step notes. These are
reference material for the future agent when debugging or running
manually — **not the primary execution instructions**.

For each step, answer from **session facts** (not common knowledge):

* **Which tool, API, file, or command actually worked?** Cite the real
  name. If multiple were tried, cite **only** the one that worked.
* **What concrete parameters did it take?** Use real argument values
  from the session.
* **What errors hit this path, and how to avoid them?** Phrase as
  preventive guidance.
* **What dead-ends should be skipped?** Mention failed paths **only**
  as terse `avoid X` reminders.

If the conversation doesn't contain a real answer for a question, **omit**
it instead of inventing one. Inventing parameters or error notes is the
most common failure mode of this skill.

When the skill is not suitable for batch (requires branching logic),
these step-by-step notes become the body's main content and the future
agent executes them sequentially.

### 2d. Optional sections

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

### 2e. Output format (only if stable)

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

### 2f. Self-check before persisting

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
* **`extra_files`** (optional): if Step 2c produced batch JSON files or
  other auxiliary files, bundle them here. Keys are relative paths
  (e.g. `"scripts/check-config.json"`), values are file content strings.
  Example:
  ```python
  materialize_skill(
      name="my-skill",
      description="Use this skill when ...",
      body="...",
      extra_files={
          "scripts/check-config.json": '{"actions": [...]}',
      },
  )
  ```
  `extra_files` keys are paths relative to the skill directory. The
  files are written into the corresponding locations under the skill
  directory. The SKILL.md body should tell the future agent to use the
  skill directory's absolute path (visible in the system prompt) to
  construct the full `file_path` for `run_tool_batch`.

Do **not** call `write_file` to create SKILL.md or auxiliary files directly.
All initial creation must go through `materialize_skill`. After creation, use
`edit_file` to modify existing files.

## Step 4. Handle `materialize_skill` response

### 4a. Verify `$steps` references (when batch JSON is included)

When `extra_files` contains `run_tool_batch` JSON files,
`materialize_skill` automatically analyses all `${steps.<index>.<path>}`
references and lists each reference's source tool and referenced field
in its response.

**You must check the returned reference list and verify that each
referenced tool's return value actually contains the referenced field.**
Record your verification in a markdown table like this:

| Reference expression | Source tool | Referenced field | Verification method | Result |
|---------------------|------------|-----------------|-------------------|--------|
| `${steps.0.text}` | `read_file` | `text` | Check previous `read_file` call result in this session | ✅ exists |
| `${steps.2.content}` | `grep_search` | `content` | Call `grep_search` once with sample args to confirm | ❌ field missing, should be `text` |

Two verification methods, in order of preference:

1. **Check session history**: if you already called that tool in this
   session, inspect the previous return value for the field.
2. **Call and test**: if you haven't called that tool yet, call it once
   with sample arguments and observe the returned JSON structure.

If any field reference is incorrect:

1. Use `edit_file` to edit the batch JSON file directly in the skill
   directory, fixing the `$steps` path. The skill directory's absolute
   path is available from `materialize_skill`'s success response.
2. If the SKILL.md body contains related reference documentation that
   also needs updating, edit the `SKILL.md` in the skill directory
   directly with `edit_file`.

Do not call `materialize_skill` again — the skill is already created,
just edit the files in place.

**All references must pass verification** before proceeding to 4b.

### 4b. Test-run the batch (when batch JSON is included)

After reference verification passes, try running the batch once with sample
arguments to confirm the entire chain works end-to-end:

```python
run_tool_batch(
    file_path="<skill_dir>/scripts/<name>.json",
    args={
        "param1": "concrete sample value matching the SKILL.md Batch Parameters section",
        ...
    }
)
```

If the batch JSON contains any `${args.<name>}` references, the test run
must pass concrete sample values for those args. **Do not test-run with
`args={}` or `args=None`**, because that does not verify argument
expansion.

* If it returns `ok: true`, the batch works — proceed to Step 5.
* If it returns an error, use `edit_file` to fix the batch JSON or helper
  scripts based on the error message, then re-run. Iterate until it passes
  or you confirm the issue cannot be fixed in the current environment
  (e.g. missing external dependencies, requires live network, etc.).
* If environment constraints prevent a test run (e.g. requires a browser,
  specific files that don't exist yet, etc.), skip the test and note in
  Step 5: "Batch was not test-run; recommend verifying on first use."

Only proceed to Step 5 after the test run passes (or is explicitly skipped
due to environment constraints).

### 4c. Conflict (skill name already taken)

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

### 4d. Format error

Fix the SKILL.md content (frontmatter fields, body sections, etc.) and
call `materialize_skill` again. Do NOT call `finish_subtask` until it
returns success.

### 4e. Security-scan rejection

Remove the flagged patterns from the body and retry.

### 4f. Other errors

Adjust inputs and retry, or abandon the plan if the failure is not
recoverable.

## Step 5. Finish

Once Step 4a reference verification and 4b test-run pass (or test-run is
skipped due to environment constraints), and `materialize_skill` returns
success:

1. Call `finish_subtask` for the single subtask.
2. Call `finish_plan` with `state="completed"`.
3. Tell the user the new skill is created and enabled, and they can
   invoke it via `/<skill_name>`.

---

## Complete flow summary

```
Step 0   Determine focus → derive skill_name
          │
Step 1   create_plan → yield turn → user approves/refines/cancels
          │
       Choose execution mode → yield turn → user picks foreground/background
          │
          ├─ Foreground ──────────────────────────────────────┐
          │                                                    │
          │  Step 2  Write SKILL.md body (batch-first)         │
          │  Step 3  Call materialize_skill to persist          │
          │  Step 4  Verify refs → test-run batch → handle err │
          │  Step 5  finish_subtask + finish_plan + inform     │
          │                                                    │
          ├─ Background ──────────────────────────────────────┐
          │                                                    │
          │  spawn_subagent(fork=True, background=True)        │
          │  Main agent immediately finish_subtask+finish_plan │
          │  Subagent executes Steps 2–4 (no plan tools)       │
          └────────────────────────────────────────────────────┘
```
