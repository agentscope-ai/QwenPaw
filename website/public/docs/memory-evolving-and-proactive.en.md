# Memory Evolution and Proactive Interaction (Beta)

> This page builds on [Long-Term Memory](./memory) and covers only the two things that page does not expand on: **how a single durable conclusion gets rewritten over time**, and **how `/proactive` actually works**. Memory directories, file formats, indexing internals, retrieval mechanics, and the complete configuration all live in [Long-Term Memory](./memory).

QwenPaw has two paths that cooperate but run independently:

| Path             | Input                                                                        | Output                                           |
| ---------------- | ---------------------------------------------------------------------------- | ------------------------------------------------ |
| Memory evolution | Daily memory under `memory/`                                                 | Durable knowledge in `digest/`                   |
| Proactive        | Durable memory, external notices, and the schedule registry (produced by ReMe) | Today's agenda in `memory/<date>/interests.yaml` |

Auto-Dream writes only `digest/`; the agenda comes from a **separate proactive chain** in ReMe, and that is exactly what `/proactive` reads.

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

### Interest topics and today's agenda

The agenda is not produced by Auto-Dream. ReMe runs a **separate proactive refresh chain**: it distils proposals from daily memory and external notices, deduplicates them into topics, plans them into scenario cards, selects today's agenda, and writes two files:

- `memory/<date>/interests.yaml` — today's `topics`, the ranked `agenda`, and this round's `suppressed` candidates;
- `memory/_proactive.yaml` — the rebuildable source of truth: `open_topics`, `resolved` tombstones, the `schedules` registry, and the `deliveries` ledger.

There are exactly four proposal kinds, and none of them is mandatory: a round may produce any subset, or nothing at all.

| Kind              | What it proposes                                                                             |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `reminder`        | Your own plans and appointments, plus notices and events from external sources you must know  |
| `follow_up`       | New progress on something you asked for but never closed, or keep tracking                    |
| `new_idea`        | Work the Agent can hand to you, based on its own resources (data, skills, tools)              |
| `interest_extend` | Refinements and extensions of the topics you care about                                       |

`reminder` outranks the other three: due schedules are **pinned** to the top of the agenda, never suppressed and never swapped out, while discovery items always keep their `min_discovery_slots` (2 by default). Every agenda item carries an `opener` and a minimal `next_action`; QwenPaw renders both verbatim instead of asking a model to rewrite them.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i1/O1CN01ddkg0rN9DXK49o5c_!!6000000001181-0-tps-2048-796.jpg" alt="Auto-Dream integration results and interest-topic summary" />
</p>

---

## 2. `/proactive`: Letting the Agent Speak First

Everything above answers questions you ask. `/proactive` inverts that: **while you are not asking anything, it puts the agenda worth telling you about today in front of you.**

The content comes from durable memory rather than a guess: ReMe's proactive chain has already ranked today's agenda from daily memory, external notices, and the schedule registry, and QwenPaw does only three things — **read, deduplicate, present**. The presentation path makes **no LLM call and runs no tool**: the message is ReMe's agenda verbatim, and the Agent never treats an item as an instruction to carry out.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01bGrMQC1kGxdbG4IDT_!!6000000004657-55-tps-1200-640.svg" alt="The agenda is read from durable memory, deduplicated, and presented for the user to decide" />
</p>

Proactive is **off by default**: `/proactive` becomes available only after you enable the master switch under **Running Config → Long-Term Memory → Proactive agenda**. While it is off, the command only replies with a hint, the idle listener is not armed, and the daily job is not registered.

### Three ways it triggers

| Trigger      | When                              | Where it lands                            | Forces a new extraction |
| ------------ | --------------------------------- | ----------------------------------------- | ----------------------- |
| `/proactive` | You run it                        | An agenda receipt in the **current chat**  | No (only when empty)    |
| Idle round   | Idle conditions hold after arming | **Inbox**                                 | No (only when empty)    |
| Daily job    | `proactive_cron` (18:00 default)  | **Inbox**, full agenda by default         | Yes                     |

`/proactive` reads the agenda right away, turns the top `proactive_max_items` (3 by default) into one message in the chat you are in, and **also** arms the idle listener. Idle rounds and the daily job write to the Inbox only and never interrupt an ongoing conversation; an Inbox card is read-only, so mention its number or title in chat to move one forward.

### Read first, refresh only when empty

Every trigger first calls ReMe's read-only `proactive` job for the existing agenda, then filters out items already shown within the cooldown using the local delivery ledger. **Only when nothing is left** does it call `proactive_refresh` to rerun from topic extraction, throttled by `proactive_refresh_min_interval_minutes` (120 by default). The daily job and `/proactive now` are the exception: they **always** refresh first.

Refresh does not spend anything for nothing either: with no daily-memory change, no new external notice, and no due schedule, ReMe returns before calling the LLM; when only the clock produced due reminders the chain still runs to completion with zero LLM calls (`reminder_only=true`).

### Deciding it is time to speak (idle rounds)

The idle listener checks every 30 seconds and pushes a round only when all of these hold: the feature is enabled and pushing is allowed, the Agent is idle, the time since the last activity *and* since `/proactive` was turned on are both ≥ the idle threshold (30 minutes by default), more than 60 seconds have passed since the previous attempt, the previous round has finished, and at least `proactive_refresh_min_interval_minutes` has passed since the last Inbox push. Almost all of them exist to avoid interrupting you.

“Last activity” is the newest `updated_at` across **all chats in the current workspace**, not just the chat where you typed `/proactive`, so working in another chat counts as still being busy.

### When there is nothing to show

The automatic surfaces (idle rounds and the daily job) stay **completely silent** when the agenda is empty: no Inbox card, no notification, only a log line. A manual `/proactive` always replies, and distinguishes four reasons: ReMe is not running or the read failed, the refresh was throttled, every item was already delivered, or the refresh still produced nothing.

### Never showing you the same thing twice

Deduplication has three layers, and an item is skipped this round as soon as any of them hits: on ReMe's write side the agenda step suppresses delivered candidates by `redelivery_cooldown_days` and records the reason in `suppressed`; on ReMe's read side the `proactive` job withholds delivered items using `deliveries` and returns `delivered_ids`; and QwenPaw's local ledger `<metadata_dir>/proactive_delivered.json` records every item actually shown, covering ReMe write failures and **cross-day** duplicates.

`reminder` is the only exception to all three cooldowns: its `topic_id` derives from a stable schedule title, so normal suppression would silence a recurring reminder for the whole window after a single delivery. After items are really shown, QwenPaw makes a best-effort `proactive_feedback` call to report them; the receipt is an **optional contract** — ReMe behaves exactly as before when a host never reports.

### Privacy and safety

- **No screenshots** and **no raw session text** — it reads the agenda text ReMe distilled from durable memory.
- **No bypass assistant**: no sub-agent with tools is started, and the agenda is presented, never executed.
- The only model spend happens inside ReMe's `proactive_refresh`, and only when the material changed.

The agenda does come from your durable memory, so it may mention things you really said. The idle listener's state lives **only in process memory** and must be armed again with `/proactive` after a restart; the master switch and the scheduled job are persisted in `agent.json`.

---

## 3. Configuration and Commands

### The `/proactive` command

```text
/proactive           # reply with today's agenda now and arm the idle listener (30 min default)
/proactive on        # same as above
/proactive 45        # same, with a 45-minute idle threshold (positive integer)
/proactive now       # force one refresh now and push it to the Inbox
/proactive off       # stop the idle listener
```

An invalid argument prints the usage; with the master switch off the command only replies “enable the proactive agenda under Running Config → Long-Term Memory first”. Idle-listener state lives only in process memory and must be re-armed after a restart. The underlying actions can also be called directly: `/reme proactive` (read-only, supports `date` and `include_delivered`) and `/reme proactive_refresh` (reruns from extraction, spends model calls, requires approval).

### Running Auto-Dream manually

```text
/reme auto_dream                         # run one Auto-Dream pass now
/reme auto_dream hint="focus on a topic" # run with an additional hint
```

You normally do not need this: Auto-Dream runs on a daily schedule by default.
Manual runs require approval from the originating chat identity before the
action starts; the authenticated Console can approve as an administrator.
Run `/reme help` to see all currently available chat-allowed actions.

### Settings relevant to this page

These live under `running.reme_light_memory_config` in `agent.json` and can all be edited in the **Running Config → Long-Term Memory** panel. For the complete configuration (directories, Embedding, Daily Paper, Auto Fin, index maintenance, and other backends) see [Long-Term Memory](./memory).

| Field                               | Default        | Description                                                      |
| ----------------------------------- | -------------- | ---------------------------------------------------------------- |
| `dream_cron_enabled`                | `true`         | Enable scheduled Auto-Dream                                      |
| `dream_cron`                        | `"0 23 * * *"` | Five-field cron; the run starts after a random 0–60 second delay |
| `auto_dream_inbox_push_enabled`     | `true`         | Send Auto-Dream changes and failures to Inbox                    |
| `auto_memory_interval`              | `5`            | Run Auto-Memory after every N user turns                         |
| `auto_memory_search_config.enabled` | `false`        | Search memory automatically before every normal user request     |
| `proactive_enabled`                      | `false`          | Master switch; while off `/proactive` only explains how to enable it |
| `proactive_max_items`                    | `3`              | Agenda items presented per round (1–10)                  |
| `proactive_inbox_push_enabled`           | `true`           | Push idle rounds and the daily job to Inbox              |
| `proactive_cron_enabled`                 | `false`          | Register the daily agenda push job                       |
| `proactive_cron`                         | `"0 18 * * *"`   | Five-field cron for the daily push; random 0–60 s delay  |
| `proactive_cron_max_items`               | `0`              | Items per daily push; `0` means all (ReMe caps at 6/day) |
| `proactive_delivery_cooldown_days`       | `3`              | Days a delivered item stays hidden (0–90); `reminder` is exempt |
| `proactive_refresh_min_interval_minutes` | `120`            | Minimum interval for an on-demand refresh; also caps idle push density; `0` disables |

A smaller Auto-Memory interval feeds fresher material into Auto-Dream and proactive extraction, at the cost of more model calls and tokens.

---

## Related Pages

- [Long-Term Memory](./memory) — directory layout, file formats, indexing and retrieval, full configuration
- [Embedding Models](./embedding) — configure vector retrieval so semantically similar memory can be found
- [Console](./console) — inspect background jobs and Inbox results
