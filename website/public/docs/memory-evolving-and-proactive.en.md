# Agent Memory Evolving & Proactive Interaction (Beta)

> **Beta Feature**: QwenPaw's ReMeLight memory manager embeds [ReMe](https://github.com/agentscope-ai/ReMe) as an in-process application. Auto Memory, Auto Resource, Auto Dream, search, and ReMe's low-level proactive topic reader are ReMe jobs. QwenPaw's `/proactive` command is a separate runtime feature that reads recent chat sessions and optional screen context.

QwenPaw stores memory as files under the agent workspace. Conversations are saved as JSONL source logs, useful conversation facts are written to daily Markdown notes, resources can be converted into daily notes, and Auto Dream periodically integrates reusable abstractions into digest memory.

---

## Actual Flow

```mermaid
graph LR
    A[Conversation turns] --> B[MemoryMiddleware]
    B --> C[ReMe auto_memory job]
    C --> D[mem_session/dialog/*.jsonl]
    C --> E[memory/<date>/<note>.md]
    R[resource/<date>/*] --> S[resource_watch_loop]
    S --> T[ReMe auto_resource job]
    T --> E
    E --> U[ReMe auto_dream job]
    U --> V[digest/personal|procedure|wiki/*.md]
    U --> W[memory/<date>/interests.yaml]
```

| Capability           | Code path                                                    | Trigger                                                                                                     | Main output                                                                            |
| -------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | --------------- | --------------------------------------------------------- |
| Auto Memory          | `ReMeLightMemoryManager.auto_memory()` -> ReMe `auto_memory` | `MemoryMiddleware` after every configured number of user turns, and before context compression when enabled | `mem_session/dialog/<session_id>.jsonl`, `memory/<date>/<note>.md`, `memory/<date>.md` |
| Auto Resource        | ReMe `resource_watch_loop` -> `auto_resource`                | Embedded ReMe background watcher for `resource_dir`                                                         | `memory/<date>/<resource_note>.md`                                                     |
| Auto Dream           | `ReMeLightMemoryManager.dream()` -> ReMe `auto_dream`        | `/dream` command or `dream_cron` scheduler                                                                  | `digest/*/*.md`, `memory/<date>/interests.yaml`                                        |
| ReMe proactive job   | ReMe `proactive`                                             | Direct ReMe job call only                                                                                   | Metadata/content from `memory/<date>/interests.yaml`                                   |
| QwenPaw `/proactive` | `src/qwenpaw/agents/memory/proactive`                        | `/proactive [minutes                                                                                        | on                                                                                     | off]` idle loop | A proactive chat request sent through `/api/console/chat` |

The important boundary is that `memory/<date>/interests.yaml` is produced by Auto Dream and can be read by ReMe's `proactive` job, but QwenPaw's current `/proactive` implementation does not call that job.

---

## File Layout

The embedded ReMe config comes from `src/qwenpaw/agents/memory/reme_config.py` and the user-facing defaults come from `ReMeLightMemoryConfig`.

```text
<workspace>/
├── mem_metadata/   # ReMe persistent state, indexes, catalogs
├── mem_session/    # Source conversation logs used by auto-memory
│   └── dialog/
│       └── <session_id>.jsonl
├── mem_agent/      # Internal ReMe memory-agent sessions
├── resource/       # External assets watched by Auto Resource
│   └── YYYY-MM-DD/
│       └── <resource>.<ext>
├── memory/         # Daily memory notes and day indexes
│   ├── YYYY-MM-DD.md
│   └── YYYY-MM-DD/
│       ├── <note>.md
│       └── interests.yaml
└── digest/         # Long-term digest memory
    ├── personal/
    ├── procedure/
    └── wiki/
```

Default directory names are configurable through `metadata_dir`, `session_dir`, `mem_session_dir`, `resource_dir`, `daily_dir`, and `digest_dir`.

---

## Auto Memory

Auto Memory is invoked by `MemoryMiddleware`, not directly on every model call. The middleware:

- skips automation requests whose source is `cron` or `heartbeat`;
- optionally injects auto memory search context before model calls when `auto_memory_search_config.enabled` is true;
- collects user-turn markers after replies;
- flushes pending turns after `auto_memory_interval` user turns;
- also flushes before context compression when `summarize_when_compact` is true and compression is about to happen.

`auto_memory_interval` defaults to `5`. `None`, `0`, or a negative value disables periodic auto-memory.

When flushed, QwenPaw calls ReMe's `auto_memory` job with:

| Field         | Source                                                    |
| ------------- | --------------------------------------------------------- |
| `messages`    | Selected conversation messages for the pending user turns |
| `session_id`  | Agent session id                                          |
| `memory_hint` | Optional hint passed by caller                            |

ReMe's `AutoMemoryStep` then:

1. validates that `session_id` is present and valid;
2. saves or appends sanitized source messages to `mem_session/dialog/<session_id>.jsonl`;
3. removes tool-result blocks and base64 data blocks from the saved source log;
4. chooses the note date from an explicit date, message timestamps, or the configured timezone's current date;
5. looks for an existing daily note whose frontmatter has the same `session_id` or `source_conversation`;
6. creates at most one note for a new session, or updates the existing note for that session;
7. ensures frontmatter contains `session_id` and `source_conversation`;
8. may rename the note from frontmatter `name`;
9. refreshes the day index at `memory/<date>.md`;
10. returns metadata including `date`, `path`, `created`, `modified`, `n_messages`, `source_conversation`, and `index`.

If the job succeeds but no note was changed, QwenPaw does not push an inbox event for `auto_memory`. Otherwise it pushes an inbox event titled `Auto-memory result`.

---

## Auto Resource

QwenPaw configures a ReMe background job named `resource_watch_loop`. It watches `resource_dir` and dispatches change batches to `auto_resource`.

Watched suffixes are:

```text
md, txt, json, jsonl, csv, yaml, html
```

Each change item may contain `path` or `file_path` and a `change` value such as `added`, `modified`, or `deleted`. The ReMe step interprets changed resource files into daily notes. QwenPaw pushes an `Auto-resource result` inbox event only when the job reports a real modification.

---

## Auto Dream

Auto Dream is exposed in QwenPaw through:

- `/dream [hint]`, handled by `CommandHandler._process_dream()`;
- the scheduler configured by `dream_cron`, default `0 23 * * *`;
- `ReMeLightMemoryManager.dream(date="", hint="")`.

QwenPaw runs the ReMe job named `auto_dream` with `needs_llm=True`, so the embedded ReMe app refreshes its LLM component from the active QwenPaw model before the job runs.

The embedded job configuration uses these defaults:

| Parameter              | Default | Meaning                                      |
| ---------------------- | ------: | -------------------------------------------- |
| `date`                 |    `""` | Empty means today in the configured timezone |
| `hint`                 |    `""` | Optional user/operator hint                  |
| `scan_days`            |     `2` | Scan target date and recent days             |
| `max_units`            |     `5` | Maximum extracted reusable memory units      |
| `topic_count`          |     `3` | Maximum final interest topics                |
| `topic_diversity_days` |     `7` | Avoid repeating topics from recent days      |

Auto Dream runs four ReMe steps:

| Step                   | Actual behavior                                                                                                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `dream_extract_step`   | Refreshes day indexes, compares daily files against the dream catalog, deletes missing catalog entries, and extracts reusable memory units plus topic candidates only from changed daily inputs. |
| `dream_integrate_step` | Integrates each extracted unit into one digest node. It uses `node_search`, `read`, `frontmatter_read`, `write`, `edit`, and `frontmatter_update`.                                               |
| `dream_topics_step`    | Selects and de-duplicates interest topics, writes `memory/<date>/interests.yaml`, and refreshes the day index.                                                                                   |
| `dream_finish_step`    | Upserts successful changed paths, interest files, and day indexes into the dream catalog, persists the catalog, and returns a summary.                                                           |

If there are no changed daily inputs, extract finishes with a no-change response. If an LLM is unavailable, extract or integrate fails because those steps require an LLM.

Digest nodes are stored by bucket:

| Bucket       | What belongs there                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------------------ |
| `personal/`  | User, team, or project identity, preferences, conventions, constraints, and avoid-rules                |
| `procedure/` | How-to workflows, runbooks, recipes, methods, and executable patterns                                  |
| `wiki/`      | Definitions, principles, observations, decisions as precedent, factual claims, and catch-all knowledge |

Integration actions are `CREATE`, `CORROBORATE`, `REFINE`, or `CORRECT`. The integration prompts require workspace-relative wikilinks such as `derived_from:: [[memory/<date>/<note>.md]]` so digest memory remains traceable to daily material.

When Auto Dream completes, QwenPaw pushes an inbox event titled `Auto-dream result`.

---

## Interest Topics and ReMe Proactive Job

`dream_topics_step` writes:

```text
memory/<date>/interests.yaml
```

The YAML payload contains:

| Field            | Meaning                                                                     |
| ---------------- | --------------------------------------------------------------------------- |
| `date`           | Target date                                                                 |
| `topic_count`    | Requested maximum topic count                                               |
| `diversity_days` | Recent-day duplicate avoidance window                                       |
| `topics`         | Selected topics with `title`, `reason`, `evidence`, `keywords`, and `paths` |

ReMe also defines a `proactive` job implemented by `proactive_step`. That job only reads `memory/<date>/interests.yaml`. It accepts:

| Parameter         | Default | Meaning                           |
| ----------------- | ------: | --------------------------------- |
| `date`            |    `""` | Empty means today                 |
| `include_content` |  `true` | Include raw YAML text in metadata |

If the interests file is missing, the ReMe proactive job returns a normal skipped result.

---

## QwenPaw `/proactive`

QwenPaw's current `/proactive` command is implemented under `src/qwenpaw/agents/memory/proactive`. It is separate from ReMe's `proactive` job.

Command behavior:

```text
/proactive           # enable with default 30 minute idle threshold
/proactive on        # enable with default 30 minute idle threshold
/proactive 45        # enable with a 45 minute idle threshold
/proactive off       # cancel the background monitoring task
```

When enabled, QwenPaw stores an in-memory `ProactiveConfig` for the session and starts a background loop. The loop:

- wakes every 30 seconds;
- skips while the agent has active tasks;
- reads the latest chat update time;
- waits until the session has been idle for the configured number of minutes;
- avoids retrying more than once per 60 seconds;
- skips if the latest message is already an unanswered `[PROACTIVE]` message;
- runs the proactive responder.

The responder builds context from recent chat sessions, not from `interests.yaml`:

- reads chat metadata from `workspace.chat_manager`;
- keeps sessions updated within the last 7 days, or the latest 5 sessions when fewer than 5 match the date window;
- loads up to 100 recent text messages, capped at 50,000 characters;
- filters system messages, non-text blocks, and prior proactive helper requests;
- optionally analyzes a desktop screenshot when the active model supports multimodal input.

It then asks a temporary `ProactiveAssistant` agent to extract 1 to 3 likely tasks from that context, executes up to the first 3 task queries using tools, and sends a user-facing proactive request through:

```text
POST <agent-api-base>/api/console/chat
session_id = proactive_mode:<active_agent_id>
text starts with "[Agent proactive_helper requesting]"
```

The final user-facing prompt instructs the agent response to begin with `[PROACTIVE]`.

The command warning is accurate: proactive mode may read historical session memory and may take screenshots when multimodal screen analysis is available. The proactive agent uses tool protection bypass mode through its own temporary agent/tool setup.

---

## Search and Indexing

The embedded ReMe app starts an `index_update_loop` background job. Search indexing watches:

| Config                          | Indexed directories                       | Suffixes      |
| ------------------------------- | ----------------------------------------- | ------------- |
| `enable_search_raw_log = false` | `daily_dir`, `digest_dir`                 | `md`          |
| `enable_search_raw_log = true`  | `daily_dir`, `digest_dir`, `resource_dir` | `md`, `jsonl` |

The QwenPaw `memory_search` tool runs ReMe's `search` job with `query`, `limit`, and `min_score`. The job is configured as hybrid workspace search with vector recall, BM25 keyword recall, RRF fusion, and wikilink expansion. The storage backend in QwenPaw's embedded ReMe config is local.

---

## Current Status

This document describes the current code paths:

- ReMeLight is implemented by `ReMeLightMemoryManager` and embedded `get_reme_app_config()`;
- Auto Memory is turn-count based and defaults to every 5 user turns;
- Auto Dream runs by `/dream` or `dream_cron`;
- ReMe writes `interests.yaml`, and ReMe has a low-level reader for it;
- QwenPaw `/proactive` currently uses recent chat/session/screen context rather than ReMe interest topics;
- Auto Memory, Auto Resource, and Auto Dream results may be delivered to the inbox when they produce reportable output.

The feature remains Beta, but the behavior above is the behavior represented by the current code.
