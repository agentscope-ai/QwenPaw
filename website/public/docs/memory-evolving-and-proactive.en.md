# Memory Evolution and Proactive Interaction (Beta)

> This page builds on [Long-Term Memory](./memory) and covers only the two things that page does not expand on: **how a single durable conclusion gets rewritten over time**, and **how `/proactive` actually works**. Memory directories, file formats, indexing internals, retrieval mechanics, and the complete configuration all live in [Long-Term Memory](./memory).

QwenPaw has two paths that cooperate but run independently:

| Path             | Input                                                        | Output                                                    |
| ---------------- | ------------------------------------------------------------ | --------------------------------------------------------- |
| Memory evolution | Daily memory under `memory/`                                 | Durable knowledge in `digest/`                            |
| Proactive        | Long-term memory, external notices, and the schedule registry | Today's ranked agenda in `memory/<date>/interests.yaml`   |

Auto-Dream writes only `digest/`; the proactive agenda comes from a **separate ReMe proactive chain**. `/proactive` reads that agenda — it **no longer scans your sessions, no longer takes screenshots, and no longer starts an assistant that bypasses tool approvals**. It only presents what ReMe ranked, and you decide whether to act on it.

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

Auto-Dream does not produce the agenda. ReMe runs a **separate proactive refresh chain**: it extracts proposals from daily memory and external notices, dedupes them into topics, plans scenario cards, selects today's agenda, and finally writes two files (the directory name follows `daily_dir`, which defaults to `memory` in QwenPaw):

- `memory/<date>/interests.yaml` — today's `topics` (each with a `kind`, confidence, and evidence paths), the ranked `agenda`, and the `suppressed` entries withheld this round;
- `memory/_proactive.yaml` — a rebuildable truth source holding the long-lived `open_topics`, `resolved` tombstones, the `schedules` registry, and the `deliveries` log.

There are exactly four proposal kinds, and none of them is mandatory: a round may produce any subset, or nothing at all.

| Kind              | What it proposes                                                          |
| ----------------- | ------------------------------------------------------------------------- |
| `reminder`        | Your own plans and schedules, plus notices from external sources you must know about |
| `follow_up`       | New progress on something you assigned but never closed, or keep tracking  |
| `new_idea`        | Work you could delegate, based on the agent's own resources (data, skills, tools) |
| `interest_extend` | A deeper or wider angle on a topic you care about                          |

`reminder` outranks the other three: due schedules are **pinned** to the front of today's agenda, nearest due date first, and are never suppressed or swapped out. Discovery kinds always keep at least `min_discovery_slots` (2 by default) slots, so a calendar-heavy day does not degrade into a plain calendar. ReMe itself caps discovery agenda items at six per day.

Every agenda entry carries a conversational `opener` and a minimal `next_action`; QwenPaw presents that text verbatim instead of asking a model to rewrite it. Auto-Dream neither reads nor writes these proactive artifacts.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i1/O1CN01ddkg0rN9DXK49o5c_!!6000000001181-0-tps-2048-796.jpg" alt="Auto-Dream run summary delivered to Inbox" />
</p>

---

## 2. `/proactive`: Letting the Agent Speak First

Everything above answers questions you ask. `/proactive` inverts that: **while you are not asking anything, it decides whether something is worth telling you now.**

The content comes from long-term memory rather than from a guess. ReMe's proactive chain has already distilled today's agenda out of daily memory, external notices, and the schedule registry; QwenPaw does exactly three things with it: **read, dedupe, present.**

Here is what enabling it looks like. You spent the last two days pushing a framework migration forward, then left your computer for half an hour. When you come back, there is a new card in your inbox:

> **Proactive agenda suggestions (2)**
>
> **1. Quality regression in the memory retrieval path** `follow_up`
> Review the recent retrieval regressions before the next release.
> -> You could ask me to: compare the failing queries against the last index snapshot
>
> **2. Migration guide update** `interest_extend`
> The official 3.0 migration guide shipped last week, and its API-change section covers the error you hit yesterday.
> -> You could ask me to: turn the changes into a one-page comparison table
>
> These items come from the proactive agenda distilled from long-term memory. The inbox cannot run them: tell me the number or title in chat to take one forward.

**That message was not improvised by a model, and nobody did any work on your behalf** — it is the agenda ReMe ranked earlier, verbatim. The whole presentation path makes **zero LLM calls and zero tool calls**: the agent only ever lays the suggestions out, and never treats an agenda item as an instruction to carry out by itself.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01bGrMQC1kGxdbG4IDT_!!6000000004657-55-tps-1200-640.svg" alt="The proactive agenda is read from long-term memory, deduped, and presented for the user to decide" />
</p>

### Where the switch lives

Proactive is **off by default**. Turn on the master switch under **Run Config → Long-term Memory → Proactive**; only then does `/proactive` work. While it is off, the command just replies that proactive needs to be enabled, the idle watcher is never armed, and no daily job is registered.

### Three ways it triggers

| Trigger      | When                                    | Where the result lands              | Forces a re-extraction |
| ------------ | --------------------------------------- | ----------------------------------- | ---------------------- |
| `/proactive` | You run it                              | A receipt in the **current chat**   | No (only when empty)   |
| Idle round   | Idle conditions hold after arming       | The **inbox**                       | No (only when empty)   |
| Daily job    | `proactive_cron` (18:00 by default)     | The **inbox**, full agenda by default | Yes                  |

All three read the same agenda; they differ only in where it lands and whether the refresh is forced:

- **`/proactive` answers immediately.** The command does not wait for an idle window. It reads the agenda now, replies in your current chat with the top `proactive_max_items` (3 by default), **and** arms the idle watcher (a 30-minute threshold by default; `/proactive 45` changes it). Due `reminder` items always come first.
- **Idle rounds and the daily job write to the inbox only.** These are automatic surfaces, so they never break into a conversation you are having. The inbox is a reading surface and its cards cannot execute anything; to take an item forward, say its number or title in chat.
- **`/proactive now`** skips the wait and immediately runs one "forced refresh + inbox push" round, which is what you want right after importing new material. It uses the push path, so it also requires the inbox notification switch.

### Read first, refresh only when empty

Every trigger follows the same path:

1. Call ReMe's `proactive` job to **read** the existing agenda (due reminders are already pinned first).
2. Filter out entries the local delivery ledger shows you inside the cooldown window.
3. **Only if nothing is left**, call `proactive_refresh` to rebuild from topic extraction, then read again.
4. That on-demand refresh is rate-limited by `proactive_refresh_min_interval_minutes` (120 by default), so an expensive chain cannot be triggered over and over.

The daily job and `/proactive now` skip the condition in step 3 and **always** refresh first, so each push reflects today's material instead of a stale `interests.yaml`.

A refresh is not automatically expensive either: with no daily-memory changes, no new external notices, and nothing due, ReMe ends the round before calling an LLM. When the clock alone finds due reminders, the chain still runs to completion with zero LLM calls so today's agenda gets them.

### Deciding it is time to speak (idle rounds)

The idle watcher checks **every 30 seconds**. Every condition below must hold before it pushes a round — and almost all of them exist to avoid interrupting you:

| Check             | Rule                                                                 | Why it exists                                    |
| ----------------- | -------------------------------------------------------------------- | ------------------------------------------------ |
| Feature on        | `proactive_enabled` is true                                          | The master switch stops the whole path           |
| Push allowed      | `proactive_inbox_push_enabled` is true                               | You may want the chat receipt but no pushes      |
| Agent idle        | No task is currently running                                         | Never interrupt work in progress                 |
| Idle long enough  | ≥ the idle threshold since the last activity (30 minutes by default)  | Only consider speaking once you've stepped away  |
| Enabled long enough | ≥ the idle threshold since `/proactive` was turned on               | Firing right after enabling feels abrupt         |
| Cooldown          | > 60 seconds since the previous attempt                              | No bursts while conditions stay satisfied        |
| No overlap        | The previous round has finished                                      | One at a time                                    |
| Push spacing      | ≥ `proactive_refresh_min_interval_minutes` since the last inbox push | No repeated nudges in one day                    |

"Last activity" is the newest `updated_at` across **all chats in the current workspace**, not just the chat where you typed `/proactive`. Working in another chat therefore counts as still being busy.

### When there is nothing to show

The automatic surfaces (idle rounds and the daily job) stay **completely silent** on an empty agenda: no inbox card, no notification, just a log line. The inbox is a reading surface, and a card that says "nothing today" is noise.

`/proactive`, which you ran yourself, always answers — and says why:

| Situation                            | What you get                                                     |
| ------------------------------------ | ---------------------------------------------------------------- |
| ReMe is not started, or the read failed | A prompt to check Run Config → Long-term Memory and retry      |
| The refresh is rate-limited          | How many minutes are left before the agenda can be rebuilt        |
| Every agenda item was already delivered | How many items are hidden, and for how many days               |
| Still empty after a refresh          | That there is nothing worth raising today                        |

### Never showing you the same thing twice

Deduplication has three layers, and a hit in any of them removes the item from the round:

1. **ReMe, write side** — the agenda step suppresses candidates inside `redelivery_cooldown_days` and records an auditable reason in `suppressed`.
2. **ReMe, read side** — the `proactive` job withholds delivered entries inside the cooldown window and reports them as `delivered_ids`.
3. **QwenPaw's local ledger** — `<metadata_dir>/proactive_delivered.json` records every item actually surfaced. It covers two things ReMe cannot see: a fallback when the ReMe-side write fails, and **cross-day dedupe** (the same topic reappearing in a later `interests.yaml`).

`reminder` is the one exception to all three layers. A schedule that is due has to be announced, and a reminder's `topic_id` derives from a stable schedule title, so applying the cooldown normally would silence a recurring reminder for the whole window after a single delivery. ReMe's write and read sides and QwenPaw's local ledger therefore all let `kind == "reminder"` through; the other three kinds (`follow_up` / `new_idea` / `interest_extend`) are deduplicated as usual.

After each real delivery QwenPaw makes a best-effort call to ReMe's `proactive_feedback` job reporting those items (`topic_id`, `agenda_date`, `delivered_at`, `channel`, `status`, `external_ref`, and so on). Reporting is an **optional contract**: a framework that never reports back leaves ReMe behaving exactly as before. `status` only moves forward (`shown` → `executed` / `dismissed`), and `failed` never blocks a later re-delivery.

### Privacy and safety

The permission surface is much smaller than it used to be:

- **No screenshots**, and **no reading of raw sessions** — it reads the agenda text ReMe distilled from long-term memory.
- **No bypass assistant**; no sub-agent with tools is started at all.
- **Zero LLM calls and zero tool calls**: presentation is pure string assembly, so an agenda item is never executed as an instruction.
- The only model spend happens inside ReMe's `proactive_refresh`, and only when material actually changed.

Worth remembering: the agenda is derived from your long-term memory, so it can mention private things you really did say. Also, the idle watcher's state lives **only in process memory** — re-run `/proactive` to re-arm it after a QwenPaw restart. The master switch and the schedule are persisted in `agent.json`.

---

## 3. Configuration and Commands

### The `/proactive` command

```text
/proactive           # reply with today's agenda now, and arm the idle watcher (30 minutes)
/proactive on        # same as above
/proactive 45        # same, with a 45-minute idle threshold (positive integer)
/proactive now       # rebuild the agenda immediately and push it to the inbox
/proactive off       # stop the idle watcher
```

An invalid argument prints the usage. With the master switch off, the command only replies that proactive has to be enabled under Run Config → Long-term Memory first. The idle watcher's state lives in process memory, so re-run `/proactive` after a QwenPaw restart.

### Running the proactive jobs manually

```text
/reme proactive                        # read today's agenda, no refresh
/reme proactive date="2026-10-12"      # read a specific date
/reme proactive include_delivered=true # include already-delivered items
/reme proactive_refresh                # rebuild from topic extraction
```

`proactive` is read-only and callable from chat directly. `proactive_refresh` consumes model resources and persists results, so — exactly like `auto_dream` — it needs approval from the originating chat identity before it starts; the authenticated Console can approve as an administrator. Run `/reme help` to see all currently available chat-allowed actions.

### Running Auto-Dream manually

```text
/reme auto_dream                         # run one Auto-Dream pass now
/reme auto_dream hint="focus on a topic" # run with an additional hint
```

You normally do not need this: Auto-Dream runs on a daily schedule by default.
Manual runs require approval from the originating chat identity before the
action starts; the authenticated Console can approve as an administrator.

### Settings relevant to this page

These live under `running.reme_light_memory_config` in `agent.json`, and all of them are editable in the **Run Config → Long-term Memory** panel. For the complete configuration (directories, Embedding, Daily Paper, Auto Fin, index maintenance, and other backends) see [Long-Term Memory](./memory).

| Field                                    | Default        | Description                                                       |
| ---------------------------------------- | -------------- | ----------------------------------------------------------------- |
| `dream_cron_enabled`                     | `true`         | Enable scheduled Auto-Dream                                       |
| `dream_cron`                             | `"0 23 * * *"` | Five-field cron; the run starts after a random 0–60 second delay   |
| `auto_dream_inbox_push_enabled`          | `true`         | Send Auto-Dream changes and failures to Inbox                     |
| `auto_memory_interval`                   | `5`            | Run Auto-Memory after every N user turns                          |
| `auto_memory_search_config.enabled`      | `false`        | Search memory automatically before every normal user request      |
| `proactive_enabled`                      | `false`        | Master switch; while off `/proactive` only explains how to enable it |
| `proactive_max_items`                    | `3`            | Items per `/proactive` receipt or idle round (1–10)               |
| `proactive_inbox_push_enabled`           | `true`         | Push idle rounds and the daily job to Inbox                       |
| `proactive_cron_enabled`                 | `false`        | Register the daily agenda push                                    |
| `proactive_cron`                         | `"0 18 * * *"` | Five-field cron for the daily push; required when enabled          |
| `proactive_cron_max_items`               | `0`            | Items in the daily push; `0` sends the whole agenda (ReMe caps at 6/day) |
| `proactive_delivery_cooldown_days`       | `3`            | Days a delivered item stays hidden, in ReMe and in the local ledger (0-90); `reminder` is exempt |
| `proactive_refresh_min_interval_minutes` | `120`          | Minimum gap between on-demand refreshes; also spaces idle pushes; `0` lifts it |

A smaller Auto-Memory interval feeds fresher material into both Auto-Dream and proactive extraction, at the cost of more model calls and tokens.

---

## Related Pages

- [Long-Term Memory](./memory) — directory layout, file formats, indexing and retrieval, full configuration
- [Embedding Models](./embedding) — configure vector retrieval so semantically similar memory can be found
- [Console](./console) — inspect background jobs and Inbox results
