---
title: "Knowing When to Continue and When to Stop: QwenPaw Loop Engineering & Custom Loops"
date: 2026-07-29
author: QwenPaw Team
tags: [Loop Engineering, Custom Loop, Agent Mode, Goal, Mission]
cover: https://img.alicdn.com/imgextra/i1/O1CN01D73t2s1WdUUsjMQ2C_!!6000000002811-2-tps-1536-1024.png
excerpt: "QwenPaw ships Default, Goal, and Mission loops—and from 2.0.1 you can compose Gates in the Console with zero code to set completion criteria, resource budgets, and stop-loss boundaries."
---

# Knowing When to Continue and When to Stop: QwenPaw Loop Engineering & Custom Loops

A reliable Agent depends not only on whether it _can_ do the work, but also on whether it can judge: keep pushing when the task is not done yet, and stop in time when there is no real progress.

Ordinary chat easily runs into two opposite problems:

- Tests are still failing or sources are still missing, yet the Agent wraps up with a summary and ends early;
- The Agent keeps calling the same tools and trying the same approach—it looks busy, but nothing new is happening.

QwenPaw's **Loop Engineering** provides an explicit control layer for both cases. If Skills define _what_ an Agent can do, Loop Engineering defines _how_ it keeps going and _when_ it hands control back to you.

QwenPaw 2.0 ships three built-in loops—Default, Goal, and Mission. Starting in QwenPaw 2.0.1, you can also create your own loops directly in the Console, with no code required.

![image.png](https://img.alicdn.com/imgextra/i2/O1CN01N7AdGblTdqG3bZE7_!!6000000000365-2-tps-1776-783.png)

## Loop Engineering: A Quality Gate After Every Round of Work

After each model response or tool call, QwenPaw evaluates the Gates configured for the current mode.

```text
Agent completes one round of work
        ↓
Check Gates in order
        ├── TERMINATE: end the current Turn
        ├── CONTINUE: inject new instructions and keep the Agent going
        └── BYPASS: do not intervene; check the next Gate

```

Gates can watch different signals: iteration count, token usage, runtime, tool-call count, repeated behavior, or whether the task meets completion criteria. Combined, they form a Loop execution policy.

The point is not to make the Agent work forever. It is to add three kinds of boundaries to sustained work:

- **Completion boundary**: what counts as truly done;
- **Resource boundary**: caps on rounds, time, tokens, and tool calls;
- **Stop-loss boundary**: when to change strategy or stop after repeated or ineffective attempts.

Time and budget Gates are checked at Loop boundaries—after a model response or tool call finishes—not by forcibly interrupting a tool mid-execution.

## Three Built-in Loops Today

| Mode        | Best for                                                          | How it works                                                                  | How it ends                                                                |
| ----------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| **Default** | Everyday Q&A, analysis, small scoped edits                        | Single-Agent controlled ReAct Loop                                            | Agent delivers a final answer, or iteration / repeated-behavior Gates fire |
| **Goal**    | Clear objectives that need sustained progress and can be verified | Single Agent works toward one goal and checks goal state                      | Goal marked complete or blocked, or round/token budget reached             |
| **Mission** | Large tasks that split into multiple user stories                 | Generate a PRD first, then run Master (Controller), Worker, and Verifier flow | All Stories pass, or mission round and retry limits hit                    |

### Default: Basic Guardrails for Everyday Chat

![image.png]https://img.alicdn.com/imgextra/i3/O1CN010E5YOV1pwhoZKuMLZ_!!6000000005425-2-tps-2322-1278.png)

Default is the standard Loop when no explicit mode is enabled. You send one request; the Agent can reason and call tools across multiple rounds within that Turn, then return the result.

Default's Gate flow includes:

- Configurable ReAct iteration cap;
- Repeated tool-call detection—first nudge the Agent to change strategy, then decide whether to stop;
- Optional qualitative completion check: when the Agent outputs text only with no tool calls, remind it to confirm the work is actually done.

It fits smaller tasks like "analyze this error," "edit these files," or "put together a short comparison."

### Goal: Sustained Progress Around One Clear Objective

![image.png](https://img.alicdn.com/imgextra/i3/O1CN01ZBbk2MObx4K4g2BK_!!6000000000836-2-tps-2304-1206.png)

When a task cannot be finished in one ordinary reply but still suits one Agent working continuously, use Goal:

```text
/goal Research mainstream LLM context windows and output a sourced comparison table

```

Goal gives the Agent goal-state tools to check progress and explicitly mark `complete` once evidence shows requirements are met; if the same external blocker persists, it can mark `blocked`. Goal also has its own round and token budgets.

It suits clearly scoped work: ongoing research, batch test fixes, cross-file refactors, long-form translation, and structured analysis. Verification still lives with the current Agent—it emphasizes self-audit with a state protocol, not a separate review Agent.

### Mission: Large Tasks Split Across Context-Isolated Roles

![image.png](https://img.alicdn.com/imgextra/i4/O1CN01a9OC27KCn4I4k3wM_!!6000000004813-2-tps-2336-1246.png)

When a task naturally breaks into several relatively independent subtasks, use Mission:

```text
/mission Build a CLI TODO app with CRUD support and add tests for core features

```

Mission runs in two phases:

1.  Analyze requirements and generate a PRD with multiple User Stories, then wait for user confirmation;
2.  Execute, verify, and fix Story by Story until all pass or budgets are exhausted.

Master (Controller), Worker, and Verifier split responsibilities so each role focuses on the current subtask, reducing cross-talk between unrelated requirements in long context. You can configure default verification instructions, test commands, Mission max rounds, and max retries per Story.

Mission may have background Workers run commands or edit files. Use it only in trusted workspaces, with appropriate permissions and approval settings.

To check progress:

```text
/mission status
/mission list

```

## Custom Loops: Save Your Own Work Standards as a Mode

![image.png](https://img.alicdn.com/imgextra/i3/O1CN01uHuiXTNBGmL2tlIe_!!6000000001518-2-tps-1428-1108.png)

Built-in modes solve common cases, but teams disagree on what "done" means.

For the same "product research" task, one person wants cost control, another cares about source quality, and a third requires every conclusion to be traceable. Those requirements used to live in one-off prompts; now you can compose them into a reusable custom Loop.

In **Agent Loop Settings**, click `+` and start from one of four templates:

| Starter template    | Default combination                                                                          | Best for                                |
| ------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------- |
| **Safe Run**        | Iteration limit + Token budget + Repeated-behavior protection + Qualitative completion check | Balancing cost and baseline quality     |
| **Budget Research** | Iteration limit + Time limit + Tool-call budget + Repeated-behavior protection               | Search, research, information gathering |
| **Quality First**   | Iteration limit + Token budget + Repeated-behavior protection + Completion-signal check      | Tasks with clear acceptance criteria    |
| **Blank Flow**      | No Gates preconfigured                                                                       | Building a special policy from scratch  |

![image.png](https://img.alicdn.com/imgextra/i4/O1CN01Xitzy7v6xEH57Tbq_!!6000000002994-2-tps-2522-1276.png)

After creation, set a display name, description, and dedicated slash command, and drag to reorder Gate checks. You can combine seven Gate types today:

| Gate                             | What it does                                                                              |
| -------------------------------- | ----------------------------------------------------------------------------------------- |
| **Iteration limit**              | Stop after a set number of ReAct iterations                                               |
| **Repeated-behavior protection** | Detect repeated tool calls; prompt a strategy change first, optionally stop if severe     |
| **Token budget**                 | Cap total, input, or output tokens                                                        |
| **Loop time limit**              | Stop at the next Loop boundary when time runs out                                         |
| **Tool-call budget**             | Cap all tool calls, or set per-tool limits                                                |
| **Qualitative completion check** | When the Agent replies with text only, require further work per natural-language criteria |
| **Completion-signal check**      | Require the Agent to self-check; end only on an exact completion signal                   |

Qualitative completion check and completion-signal check are two different completion strategies—pick one per mode. The latter makes completion state explicit but triggers extra model judgment, adding token and time cost. It is still self-check by the current Agent, not a separate Verifier.

## Example: Create a "Deep Research" Loop

Suppose you often ask QwenPaw for industry and technical research. Create a mode named "Deep Research" with slash command:

```text
/deep-research

```

Start from the "Budget Research" template, then add Token budget and completion-signal check. A reference Gate flow:

1.  **Iteration limit**: prevent the task from running indefinitely;
2.  **Token budget**: control model cost per research run;
3.  **Loop time limit**: set a maximum runtime for one research session;
4.  **Tool-call budget**: cap total calls and set a separate limit for search tools;
5.  **Repeated-behavior protection**: when the same query is searched repeatedly, require new keywords or sources;
6.  **Completion-signal check**: allow ending only when your research criteria are met.

Completion criteria prompt example:

```text
Mark the task complete only when all of the following are true:
1. At least 6 primary or official sources are cited;
2. Every key fact traces back to a source;
3. Conflicting information is cross-checked with rationale for choices made;
4. Output includes a comparison table, conclusions, and known limitations;
5. Source facts are clearly separated from analytical judgment.

```

After saving, pick "Deep Research" in the chat input area, or type:

```text
/deep-research Research mainstream open-source Agent frameworks in 2026—compare architecture, extension mechanisms, and deployment cost

```

Custom modes stay active for the current session. Each new user Turn resets iteration, time, token, and tool budgets, but the mode itself does not turn off automatically. Exit with `/mode off`, or reset the session with `/clear` or `/new`.

## Need a More Complex Loop? Extend Workflows with Plugins

Visual custom Loops fit combining QwenPaw's seven Gates. If stop conditions depend on external system state, an independent review model, or a dedicated state machine, register new Agent Modes via plugins.

Oh-My-Paw (OMP Workflows) in QwenPaw 2.0.1 is an example of this extension layer:

| Plugin Loop   | Primary use                                                                                |
| ------------- | ------------------------------------------------------------------------------------------ |
| **UltraQA**   | Loop through inspect → diagnose → fix → re-check for tests, builds, lint, or custom checks |
| **Ralph**     | Drive continuous implementation and acceptance from a PRD and User Stories                 |
| **Ultrawork** | Split independent subtasks and run them in parallel across sub-Agents                      |
| **Autopilot** | Sequentially expand requirements, plan, execute, QA, verify, and clean up                  |
| **Team**      | Complete planning, execution, verification, and fixes with a configurable multi-Agent team |

These modes are not part of the three core built-in Loops. After installing a plugin, they appear alongside user-created modes under "Custom & Plugins" in the chat input area.

## Which One Should You Choose?

- Everyday Q&A and small edits: **Default**;
- A clear objective one Agent can finish alone: **Goal**;
- Large tasks split into Stories with isolated execution and verification: **Mission**;
- Recurring tasks with fixed budgets or completion standards: **Custom Loop**;
- Dedicated state machines, multi-Agent workflows, or external decision logic: **Loop plugins**.

A good Loop does not make the Agent work longer—it gives it clear completion criteria, controllable resource budgets, and the ability to stop when progress stalls.

From repeating "keep going" in prompts to saving work policy as a reusable mode—that is what Loop Engineering changes.

## Further Reading

- [QwenPaw Loop Engineering documentation](https://qwenpaw.agentscope.io/docs/loop-engineering)
- [QwenPaw v2.0.1 release notes](https://qwenpaw.agentscope.io/release-notes#v2.0.1)
- [QwenPaw GitHub repository](https://github.com/agentscope-ai/QwenPaw)
