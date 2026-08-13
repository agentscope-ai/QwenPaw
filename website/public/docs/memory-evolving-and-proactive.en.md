# Memory Evolution and Proactive Interaction (Beta)

> This page focuses on how Auto-Memory, Auto-Dream, Auto-Memory-Search, and Proactive work together. For memory directories, file formats, indexing internals, and the complete configuration, see [Long-Term Memory](./memory).

Last week, you told QwenPaw: “Validate staging before production. Release notes must explain risks and rollback steps.” A few days later, the team added an exception: “An emergency hotfix may ship with lead approval, but the skipped checks must be completed afterward.”

If the system only stores transcripts, those statements remain buried in two conversations. Useful long-term memory has to do more: preserve what happened, decide whether new information confirms, extends, or corrects an earlier conclusion, and retrieve the resulting procedure during the next release.

QwenPaw handles this as one continuous workflow:

1. **Auto-Memory** extracts information worth reusing and saves it as daily memory.
2. **Auto-Dream** consolidates evidence from different days into durable knowledge that can keep changing.
3. **Memory Search** retrieves only the relevant knowledge and connected evidence for a new request.
4. **Proactive**, once explicitly enabled, watches recent activity for a useful opportunity to help early.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01mG5Uot1GQdX33v4h4_!!6000000000617-55-tps-1200-640.svg" alt="QwenPaw long-term memory from capture and consolidation to retrieval and discovery" />
</p>

These are two related but not yet fully connected loops. Memory evolution uses `memory/`, `digest/`, and retrieval. The current `/proactive` command reads recent sessions and optional screen context; it does **not** directly read Auto-Dream's `interests.yaml` or `digest/`.

## Step 1: Turn Conversations into Reliable Material

Auto-Memory does not merely rewrite a transcript. It selects information that may remain useful, such as:

- stable preferences and long-term agreements;
- project context, constraints, and important facts;
- confirmed decisions, rationale, and exceptions;
- progress, blockers, and next steps;
- reusable procedures and troubleshooting experience.

By default, Auto-Memory processes new conversation content after every five user turns. It removes tool results and large Base64 blocks, saves the source conversation under `mem_session/dialog/`, and creates or updates one Markdown note under that day's `memory/YYYY-MM-DD/` directory. Pending turns also enter this pipeline early when context is evicted or folded.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01Qg6uAk1VoeXMqbE54_!!6000000002700-55-tps-1200-640.svg" alt="Auto-Memory distilling a long conversation into reusable and traceable daily memory" />
</p>

A release discussion might first become:

```markdown
---
name: Production release agreement
description: Validate staging first; Chinese release notes must include risks and rollback steps.
source_conversation: "[[mem_session/dialog/qpsid_sha256_<64-hex>.jsonl]]"
---

- Complete staging validation before a production release.
- Write release notes in Chinese and include risks and rollback steps.
```

This is still evidence from a particular day, not an immutable final conclusion. Daily memory preserves the event; Auto-Dream organizes it across time.

## Step 2: Grow Daily Evidence into Durable Knowledge

A static memory can only append and retrieve. An evolving memory must also ask: **What does new evidence mean for what is already known?**

Auto-Dream runs daily by default and scans changed memory from the target day and the preceding day. It extracts reusable `personal`, `procedure`, and `wiki` units, searches `digest/` for potentially identical or related nodes, and chooses one integration action:

| Action        | What it does                                           | Typical case                                        |
| ------------- | ------------------------------------------------------ | --------------------------------------------------- |
| `CREATE`      | Creates a new durable node                             | A new preference, procedure, fact, or principle     |
| `CORROBORATE` | Keeps the conclusion and adds supporting evidence      | The same preference or practice appears again       |
| `REFINE`      | Adds scope, steps, conditions, or exceptions           | A later conversation fills in missing detail        |
| `CORRECT`     | Revises a stale, incomplete, or conflicting conclusion | The user changes a decision or corrects an old fact |

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01DSVTuF1rEr7yobCav_!!6000000005600-55-tps-1200-640.svg" alt="Auto-Dream consolidating daily experience into source-linked long-term knowledge" />
</p>

The diagram uses `CONFIRM` as a visual shorthand for adding supporting evidence. The formal action name in the current interface is `CORROBORATE`.

Auto-Dream never rewrites daily memory. `memory/` preserves what happened at the time, while `digest/` stores conclusions that remain useful across time and may still be corrected. Successfully processed inputs are checkpointed in the dream catalog; failed paths are not checkpointed, so a later run can retry them.

### How a Release Procedure Improves with Use

In the running example, one durable node can evolve four times:

| Time   | Action        | Change introduced by the evidence                    |
| ------ | ------------- | ---------------------------------------------------- |
| Day 1  | `CREATE`      | Establish “validate staging before production”       |
| Day 3  | `CORROBORATE` | Confirm the rule during another release              |
| Day 8  | `REFINE`      | Add Chinese release notes, risks, and rollback steps |
| Day 20 | `CORRECT`     | Add an approved emergency-hotfix exception           |

By Day 20, `digest/procedure/production-release.md` might look like this:

```markdown
---
name: Production release procedure
description: Standard releases require staging validation; emergency hotfixes use an approved exception path.
---

# Production release

## Standard path

1. Validate the release in staging.
2. Write release notes in Chinese, including risks and rollback steps.
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

The important change is not simply that the file grew. Repetition increased confidence, new detail became executable steps, a conflict became a scoped exception, and every conclusion still leads back to its evidence.

### Why Auto-Link Matters

Auto-Link is part of Auto-Dream's integration stage, not a separate job:

- links under `## Sources` connect durable conclusions to daily evidence;
- Wikilinks in the body connect related preferences, procedures, projects, and concepts;
- updates preserve existing sources and relationships instead of erasing the history during a correction;
- after search finds one node, it can expand incoming and outgoing links only when that context is useful.

This makes `digest/` a readable, traceable personal knowledge base that changes with new evidence, rather than a pile of summaries.

## Step 3: Put Evolved Memory Back to Work

Organized memory still has to be found at the right moment. `memory_search` combines three signals across Markdown under `memory/` and `digest/`:

- **BM25** finds exact terms such as function names, error codes, and project names.
- **Vector**, when an Embedding model is configured, finds semantically similar passages with different wording.
- **Wikilink** expands a matching file to its sources, related procedures, and neighboring knowledge.

The two retrieval branches are fused with RRF. BM25 and Wikilink expansion continue to work when Embedding is not configured.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01Zln7TK1TJOGqP84hk_!!6000000002361-55-tps-1200-640.svg" alt="BM25 and vector retrieval fused before related memory is expanded on demand" />
</p>

The Agent can call `memory_search` whenever a request depends on history. With Auto-Memory-Search enabled, every normal user request first searches memory. Results are injected only into the current request context: they are not written into formal conversation history or processed by Auto-Memory again, which prevents memory from copying itself.

For example, when the user asks, “What do we check before going live?”, retrieval can combine the exact term `staging`, the semantic match “production release validation,” and links to the rollback procedure and communication preference. The Agent receives the relevant passages and paths rather than the entire history.

## From Interest Topics to Proactive Interaction

While consolidating durable nodes, Auto-Dream also selects a small set of non-repetitive interest topics from recent evidence. It writes up to three topics by default to `memory/<date>/interests.yaml`. Each contains a title, reason, evidence, keywords, and relevant paths:

```yaml
- title: Verify the emergency rollback path
  reason: The hotfix exception was added, but the follow-up checks are not yet documented.
  evidence:
    - Emergency staging bypass discussed in the hotfix retrospective.
  keywords: [hotfix, rollback, release]
  paths:
    - memory/2026-08-20/hotfix-retrospective.md
```

ReMe exposes a low-level `proactive` job that reads this file for other integrations; a missing file produces a normal skipped result. After Auto-Dream finishes, its integration results and interest topics can also be delivered to Inbox. The actual content remains in `digest/` and `interests.yaml`.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i1/O1CN01ddkg0rN9DXK49o5c_!!6000000001181-0-tps-2048-796.jpg" alt="Auto-Dream integration results and interest-topic summary" />
</p>

### How `/proactive` Works Today

The user-facing `/proactive` command follows a separate runtime path. Once explicitly enabled, it waits for the workspace to become idle, then uses recent chats and an optional desktop screenshot to infer one to three potentially useful goals. It attempts concrete queries for up to three candidates, stops after the first successful result, and sends the suggestion back to the conversation.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01bGrMQC1kGxdbG4IDT_!!6000000004657-55-tps-1200-640.svg" alt="Proactive mode using recent signals to discover a next step and ask before acting" />
</p>

The monitor checks every 30 seconds. Its idle clock uses the newest `updated_at` across all chats in the current workspace, not only the chat where the command was entered. At the threshold, it reads sessions updated during the previous seven days; if fewer than five match, it falls back to the latest five. Input is limited to 100 recent non-system text messages and 50,000 characters. When the active model supports multimodal input, it may also capture and analyze the desktop.

If the user becomes active while a task is running, that attempt is interrupted. No new message is sent while an earlier `[PROACTIVE]` message remains unanswered. Monitor settings exist only in process memory and must be enabled again after a restart.

> **Current boundary:** `/proactive` derives its trigger and tasks from recent sessions and optional screen context. It does not directly read `interests.yaml` or `digest/`. Interest generation and the user-facing proactive mode are currently independent paths.

### Privacy and Safety

The proactive assistant can read chat history and may capture the desktop when multimodal analysis is available. It also initializes a separate assistant with web search/fetch, browser, file-read, shell, and optional screenshot tools, running with bypass permissions. `/proactive` displays this warning. Enable it only when that access is appropriate, and use `/proactive off` at any time to stop monitoring.

## Configuration Quick Reference

The following settings are the ones directly involved in this page's workflow. They live under `running.reme_light_memory_config` in `agent.json`. For directory, Embedding, Daily Paper, and index-maintenance settings, see [Long-Term Memory](./memory).

```json
{
  "running": {
    "memory_manager_backend": "remelight",
    "reme_light_memory_config": {
      "auto_memory_interval": 5,
      "auto_memory_inbox_push_enabled": true,
      "dream_cron_enabled": true,
      "dream_cron": "0 23 * * *",
      "auto_dream_inbox_push_enabled": true,
      "memory_search_enabled": true,
      "auto_memory_search_config": {
        "enabled": false,
        "max_results": 2
      }
    }
  }
}
```

| Field                                   | Default        | Description                                                                             |
| --------------------------------------- | -------------- | --------------------------------------------------------------------------------------- |
| `auto_memory_interval`                  | `5`            | Run Auto-Memory after every N user turns; `null` or `<= 0` disables periodic triggering |
| `auto_memory_inbox_push_enabled`        | `true`         | Send a result to Inbox when Auto-Memory actually changes memory                         |
| `dream_cron_enabled`                    | `true`         | Enable scheduled Auto-Dream                                                             |
| `dream_cron`                            | `"0 23 * * *"` | Five-field cron expression; the run starts after a random delay of 0–60 seconds         |
| `auto_dream_inbox_push_enabled`         | `true`         | Send successful or failed Auto-Dream summaries to Inbox                                 |
| `memory_search_enabled`                 | `true`         | Expose the manually callable `memory_search` tool to the Agent                          |
| `auto_memory_search_config.enabled`     | `false`        | Search memory automatically before every normal user request                            |
| `auto_memory_search_config.max_results` | `2`            | Maximum number of results injected by each automatic search                             |

A smaller Auto-Memory interval produces fresher memory but increases model calls, token usage, and background work. `memory_search_enabled` and automatic search are independent: disabling the manual tool does not automatically disable Auto-Memory-Search, or vice versa.

Auto-Dream can also be run immediately:

```text
/dream          # run one Auto-Dream pass now
/dream <hint>   # run one pass with an additional hint
```

Proactive does not use `agent.json` settings. Its in-memory task for the current Agent is managed with commands:

```text
/proactive           # enable; trigger after 30 minutes of inactivity
/proactive on        # same as above
/proactive 45        # use a 45-minute idle threshold
/proactive off       # stop proactive monitoring
```

In short: Auto-Memory preserves reliable material, Auto-Dream evolves knowledge as evidence changes, Memory Search brings that knowledge into new conversations, and `/proactive` decides when explicit user authorization makes early assistance worthwhile.
