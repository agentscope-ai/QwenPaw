# Memory Evolution and Proactive Interaction (Beta)

> This page builds on [Long-Term Memory](./memory) and covers only the two things that page does not expand on: **how a single durable conclusion gets rewritten over time**, and **how `/proactive` actually works**. Memory directories, file formats, indexing internals, retrieval mechanics, and the complete configuration all live in [Long-Term Memory](./memory).

QwenPaw has two related but currently **independent** paths:

| Path             | Input                                      | Output                                            |
| ---------------- | ------------------------------------------ | ------------------------------------------------- |
| Memory evolution | Daily memory under `memory/`               | Durable knowledge in `digest/` + `interests.yaml` |
| `/proactive`     | Recent chat sessions + optional screenshot | One message prefixed with `[PROACTIVE]`           |

`/proactive` does **not** read `digest/` or `interests.yaml` today. See “Current boundary” at the end of this page.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01mG5Uot1GQdX33v4h4_!!6000000000617-55-tps-1200-640.svg" alt="QwenPaw long-term memory from capture and consolidation to retrieval and discovery" />
</p>

---

## 1. How Memory “Evolves”

A static memory can only append and retrieve. An evolving memory has to answer a harder question: **what does new evidence mean for what is already known?**

### One conclusion, rewritten four times

Suppose last week you told QwenPaw: “Validate staging before production. Release notes must explain risks and rollback steps.” A few days later the team added an exception: “An emergency hotfix may ship with lead approval, but the skipped checks must be completed afterward.”

Those statements sit in conversations from different days. When Auto-Dream runs, it does not create a new file per statement. It finds the **same** durable node and rewrites it with exactly one action (the four actions are defined in [Long-Term Memory](./memory)):

| Time   | Action        | What changed in the node                          |
| ------ | ------------- | ------------------------------------------------- |
| Day 1  | `CREATE`      | Establish “validate staging before production”    |
| Day 3  | `CORROBORATE` | Another release confirms it; confidence increases |
| Day 8  | `REFINE`      | Add release notes, risks, and rollback steps      |
| Day 20 | `CORRECT`     | Add the approved emergency-hotfix exception       |

By Day 20, `digest/procedure/production-release.md` looks like this:

```markdown
---
name: Production release procedure
description: Standard releases require staging validation; emergency hotfixes use an approved exception path.
---

# Production release

## Standard path

1. Validate the release in staging.
2. Write release notes including risks and rollback steps.
3. Proceed to production only after validation passes.

## Emergency hotfix exception

Skip the full staging run only with incident-lead approval. Record the reason and complete the omitted checks afterward.

relates_to:: [[digest/personal/release-communication-preference.md]]
depends_on:: [[digest/procedure/rollback-verification.md]]

## Sources

- [[memory/2026-08-01/release-planning.md]]
- [[memory/2026-08-08/release-notes.md]]
- [[memory/2026-08-20/hotfix-retrospective.md]]
```

What matters is not that the file grew, but that four things hold at once:

- **Repetition became confidence**, instead of four records that contradict each other.
- **Detail became executable steps** you can follow next time.
- **A conflict became a scoped exception**, instead of deleting the old conclusion.
- **Every conclusion still leads back to its evidence** — `## Sources` preserves how it formed.

Besides plain `[[...]]` links, a node can use semantic relation fields such as `relates_to::` and `depends_on::` to state what it relates to and what it depends on, so retrieval can expand along those relationships after hitting a node.

### Each pass reads only what it needs

Auto-Dream does not re-read all of `memory/` every day:

- **Scan window**: only daily memory that changed on the target date and the **preceding day**.
- **Per-pass cap**: at most five memory units per run — it would rather settle knowledge over several days than fill `digest/` in one go.
- **Checkpointing**: successfully processed inputs are recorded in the dream catalog and are not consolidated again.
- **Retry on failure**: failed paths are **not** checkpointed, so a later run tries them again.
- **Writes only `digest/`**: `memory/` always keeps “what was seen and judged at the time” — Auto-Dream never rewrites it.

That is why long-term memory can be corrected indefinitely without losing history: conclusions are mutable, the record of the moment is not.

### Interest topics, produced along the way

While consolidating durable nodes, Auto-Dream also picks a small set of non-repetitive interest topics from recent evidence — up to three by default — and writes them to `memory/<date>/interests.yaml`:

```yaml
- title: Verify the emergency rollback path
  reason: The hotfix exception was added, but the follow-up checks are not yet documented.
  evidence:
    - Emergency staging bypass discussed in the hotfix retrospective.
  keywords: [hotfix, rollback, release]
  paths:
    - memory/2026-08-20/hotfix-retrospective.md
```

Each topic carries a reason, evidence, keywords, and relevant paths — so it does not just claim “you may care about X,” it can also explain why. Generation also checks the topics produced over the last seven days to avoid suggesting the same thing every day. ReMe exposes a low-level `proactive` job that reads this file for other integrations; a missing file returns a normal skipped result rather than an error.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i1/O1CN01ddkg0rN9DXK49o5c_!!6000000001181-0-tps-2048-796.jpg" alt="Auto-Dream integration results and interest-topic summary" />
</p>

---

## 2. `/proactive`: Letting the Agent Speak First

Everything above answers questions you ask. `/proactive` inverts that: **while you are not asking anything, it decides whether something is worth telling you now.**

Once enabled, this is what happens. You spent yesterday and today looking into a framework migration, then left for a meeting. Half an hour later you come back to a new message:

> **[PROACTIVE]** I noticed you've been working through the xxx migration. The official 3.0 migration guide shipped last week, and its API-change section covers the error you hit yesterday…

That message is not a template. It is sent only after the assistant **actually ran the search and got a result**. Here is the process, in order.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01bGrMQC1kGxdbG4IDT_!!6000000004657-55-tps-1200-640.svg" alt="Proactive mode using recent signals to discover a next step and ask before acting" />
</p>

### Step 1: Deciding it is time to speak

`/proactive` starts a background loop that checks **every 30 seconds**. Every condition below must hold before it triggers — and almost all of them exist to avoid interrupting you:

| Check               | Rule                                                                 | Why it exists                                   |
| ------------------- | -------------------------------------------------------------------- | ----------------------------------------------- |
| Agent idle          | No task is currently running                                         | Never interrupt work in progress                |
| Idle long enough    | ≥ the idle threshold since the last activity (30 minutes by default) | Only consider speaking once you've stepped away |
| Enabled long enough | ≥ the idle threshold since `/proactive` was turned on                | Firing right after enabling feels abrupt        |
| Cooldown            | > 60 seconds since the previous attempt                              | No bursts while conditions stay satisfied       |
| No overlap          | The previous proactive task has finished                             | One at a time                                   |
| Previous answered   | Skip if the last message is an unanswered `[PROACTIVE]`              | If you ignored it, don't keep talking           |

“Last activity” is the newest `updated_at` across **all chats in the current workspace**, not just the chat where you typed `/proactive`. Working in another chat therefore counts as still being busy.

### Step 2: What it knows about your work

Once the conditions hold, it assembles a context with only two parts.

**① Screen (optional)** — only when the active model supports multimodal input: it captures a desktop screenshot and asks the model to describe which application you are in and what activity you are engaged in. The result becomes `[SCREEN CONTEXT]`. Without multimodal support this part is skipped entirely.

**② Recent sessions** — `[SESSION CONTEXT]`, built by very concrete rules:

- List every chat in the current workspace and keep those updated within the **last 7 days**.
- If fewer than five match, fall back to the **five most recent** chats so there is always material.
- Read each session's content, **dropping system messages** and all non-text content (images, tool results, and so on).
- Order **newest first**, capped at **100 messages** and **50,000 characters**; anything beyond that is truncated.
- Skip every request message produced by proactive mode itself, so **it never mistakes its own output for your input**.

In other words, it sees a condensed excerpt of what you said over the past week — not your complete history. **It does not read `digest/`, and it does not read `interests.yaml`.**

### Step 3: From “what you're doing” to “what would help”

With that context, the model produces one to three candidates, each with three fields:

```json
{
  "tasks": [
    {
      "task": "a goal you are likely pursuing",
      "query": "one concrete new query that moves it forward",
      "why": "why this goal is likely and why this query helps"
    }
  ]
}
```

A few constraints on this step are worth knowing:

- Candidates are ranked by **priority**, based on how often and how recently the goal appeared.
- The `query` must be **new** — never a repeat of a command you already ran or a search you already made.
- Goals may come only from **what you said**; guessing from the screenshot alone is not allowed, the screen is supporting context.
- It must not duplicate any `[PROACTIVE]` message already sent.
- No tools during this step — think it through and answer directly.

### Step 4: Do the work first, then decide whether to speak

This is the biggest difference between `/proactive` and “guess what you want to ask”: **it never hands you the guess directly.** It verifies first.

It initializes a separate `ProactiveAssistant` that reuses the current Agent's model, with a toolset it is told to use lightest-first:

1. `web_search` to find information;
2. `web_fetch` to read a known URL;
3. `browser` only for interactive cases (login, clicking, JS-heavy pages);
4. `read_file` and `execute_shell_command` only when essential;
5. `desktop_screenshot` additionally, on multimodal models.

It then runs the queries of **at most three** candidates in priority order, requiring the model to end each answer with a `[SUCCESS]` or `[FAILURE]` self-assessment. **The first candidate that both succeeds and actually returns content stops the remaining attempts** — good enough is enough; it does not run all three.

If all of them fail, the round simply produces nothing and no message is sent.

### Step 5: Where the message goes

Given a result, the model writes it up in the language configured for the current Agent, phrased along the lines of “I noticed you've been focusing on X, so I looked into…” — explaining why it brought this up before giving the answer. The output **must start with `[PROACTIVE] `**, and that same marker drives the “previous answered” check in Step 1.

Delivery happens by calling QwenPaw's own API (`POST /api/console/chat`) with a fixed session of `proactive_mode:<agentId>` and a 300-second timeout. So **proactive messages land in a dedicated session rather than in the middle of a conversation you are having.**

### It can be interrupted at any point

Three checkpoints ask “is the user back?”: after the context is built, before each candidate runs, and after execution completes. Two signals are used — whether the Agent became busy again, and whether **any chat's update time is newer than the moment this round started**. Either one aborts the round immediately, so no half-finished message is ever sent.

### Privacy and safety

This is the section worth reading carefully. Enabling `/proactive` means:

- It **reads chat history** (the last 7 days, or the five most recent sessions).
- On a multimodal model, it may **capture your desktop**.
- The assistant it starts has web search/fetch, browser, file-read, and shell-command capabilities.
- That assistant runs with **bypass permissions**, meaning it **skips the normal tool-authorization prompts**.

`/proactive` displays this warning when you enable it. Turn it on only when that level of access is appropriate, and use `/proactive off` to stop at any time. Note also that monitor settings live **only in process memory** — they must be enabled again after a QwenPaw restart.

### Current boundary

`/proactive` derives both its trigger and its tasks **only from recent sessions and optional screen context**; it reads neither `interests.yaml` nor `digest/`. The two halves of this page are therefore independent paths today: memory evolution makes knowledge more accurate with use, while proactive interaction runs purely on recent activity. Connecting them is still in progress.

---

## 3. Configuration and Commands

### The `/proactive` command

Proactive uses **no `agent.json` settings**. It is managed entirely by commands, scoped to the current Agent:

```text
/proactive           # enable; trigger after 30 minutes of inactivity
/proactive on        # same as above
/proactive 45        # use a 45-minute idle threshold (positive integer minutes)
/proactive off       # stop proactive monitoring
```

Enabling it returns the current idle threshold together with the safety warning above. An invalid argument prints the usage. Settings are lost on restart and must be re-enabled.

### Running Auto-Dream manually

```text
/dream          # run one Auto-Dream pass now
/dream <hint>   # run one pass with an additional hint, e.g. a focus area
```

You normally do not need this: Auto-Dream runs on a daily schedule by default.

### Settings relevant to this page

These live under `running.reme_light_memory_config` in `agent.json`. For the complete configuration (directories, Embedding, Daily Paper, Auto Fin, index maintenance, and other backends) see [Long-Term Memory](./memory).

| Field                               | Default        | Description                                                      |
| ----------------------------------- | -------------- | ---------------------------------------------------------------- |
| `dream_cron_enabled`                | `true`         | Enable scheduled Auto-Dream                                      |
| `dream_cron`                        | `"0 23 * * *"` | Five-field cron; the run starts after a random 0–60 second delay |
| `auto_dream_inbox_push_enabled`     | `true`         | Send Auto-Dream changes and failures to Inbox                    |
| `auto_memory_interval`              | `5`            | Run Auto-Memory after every N user turns                         |
| `auto_memory_search_config.enabled` | `false`        | Search memory automatically before every normal user request     |

A smaller Auto-Memory interval feeds fresher material into Auto-Dream, at the cost of more model calls and tokens.

---

## Related Pages

- [Long-Term Memory](./memory) — directory layout, file formats, indexing and retrieval, full configuration
- [Embedding Models](./embedding) — configure vector retrieval so semantically similar memory can be found
- [Console](./console) — inspect background jobs and Inbox results
