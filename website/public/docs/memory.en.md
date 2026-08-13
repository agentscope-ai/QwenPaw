# Long-Term Memory

QwenPaw's long-term memory is powered by [ReMe](https://github.com/agentscope-ai/ReMe). Instead of rereading the entire conversation history for every request, it turns useful conversations and currently supported resources into Markdown files, then retrieves only the parts relevant to the current question.

In plain language, it does four things:

1. **Capture** preferences, facts, decisions, reasons, and next steps;
2. **Consolidate** scattered daily notes into durable knowledge;
3. **Connect** conclusions, evidence, and related knowledge with source links and Wikilinks;
4. **Recall** the right information through keywords, semantics, and knowledge relationships.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01mG5Uot1GQdX33v4h4_!!6000000000617-55-tps-1200-640.svg" alt="The complete QwenPaw long-term memory loop" />
</p>

## Understand the Memory Loop First

Imagine you are preparing a product release. Over several weeks, you tell QwenPaw that release notes should lead with user value, that the database migration is postponed, and that the migration plan must be reviewed after launch.

If those details remain only in chat logs, new conversations soon bury them. Long-term memory turns them into daily memory, durable knowledge, and searchable evidence.

### 1. Memory Starts as Files You Own

ReMe follows **Memory as File, File as Memory**. Core memory is stored as ordinary files in the Agent workspace rather than hidden in an opaque database:

- `memory/` contains daily facts, decisions, progress, and resource readings;
- `digest/` contains preferences, procedures, and knowledge that remain useful over time;
- `mem_session/` contains traceable source conversations;
- `resource/` contains raw assets such as PDFs downloaded by Daily Paper;
- `mem_metadata/` contains rebuildable indexes, graph data, and caches.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i4/O1CN01wj1PUE1a2d5QtEyUv_!!6000000003272-55-tps-1200-640.svg" alt="Markdown memory files connect durable knowledge with source evidence" />
</p>

You can inspect, edit, back up, or migrate these memories directly. Markdown files are the source of truth; indexes and graphs are derived state that can be rebuilt.

A durable memory might look like this:

```markdown
---
name: Release communication preference
description: Lead with user value before technical changes.
---

# Release communication preference

Explain what users gain before describing technical changes.

## Sources

- [[memory/2026-08-06/release-discussion.md]]
```

The body stores the knowledge, frontmatter summarizes it, and `[[...]]` connects sources and related nodes.

### 2. Auto-Memory Keeps What Will Matter Later

Auto-Memory does not copy the whole conversation. It periodically identifies durable information such as:

- stable preferences and agreements;
- project context and constraints;
- confirmed decisions and their reasons;
- progress, blockers, and next steps;
- reusable procedures and troubleshooting experience.

If you say, “Do not migrate the database this release because the deadline is close and the current setup is sufficient; review it after launch,” Auto-Memory keeps the decision, reason, follow-up, and source—not just “do not migrate.”

By default, it runs after every five user turns. If context is evicted or compacted, pending turns enter the same memory flow first. A run that finds nothing worth adding or updating creates neither an empty memory nor an Inbox event.

Auto-Memory stores the source session in a hash-named JSONL file and creates or updates one daily memory card:

```text
mem_session/dialog/qpsid_sha256_<64-hex>.jsonl
memory/2026-08-06/release-discussion.md
```

Previously recalled memory is removed before extraction so it cannot be mistaken for a new fact from the user.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01q1761gvctQB49nzS_!!6000000007099-0-tps-2048-414.jpg" alt="Auto-Memory result delivered to Inbox" />
</p>

Inbox is only a run-status surface. The reusable, editable memory remains in workspace files.

### 3. Daily Paper Brings Supported Resources into Memory

Useful information does not come only from conversations. When Daily Paper is enabled, QwenPaw selects papers from the Hugging Face Papers weekly and monthly rankings, saves the source PDFs, and produces three detailed readings plus a daily brief.

- PDFs go to `resource/papers/`;
- readings and the brief go to `memory/YYYY-MM-DD/`;
- the Markdown readings enter the normal memory index and can later be consolidated.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i4/O1CN01P4HuDOo3HjE3MD24_!!6000000007223-0-tps-1654-670.jpg" alt="Daily Paper schedule and topic settings" />
</p>

Daily Paper is the currently built-in resource entry point. Merely placing an arbitrary file in `resource/` does not process or index it.

### 4. Auto-Dream Turns Daily Notes into Durable Knowledge

Daily notes alone eventually become another pile of files. Auto-Dream scans recently changed daily memory and integrates reusable material into `digest/`.

For each new piece of evidence, it chooses one action:

| Action        | Meaning                                                 |
| ------------- | ------------------------------------------------------- |
| `CREATE`      | Create a node when no equivalent knowledge exists       |
| `CORROBORATE` | Add evidence or strengthen an existing memory           |
| `REFINE`      | Add steps, conditions, boundaries, or detail            |
| `CORRECT`     | Fix an error, omission, or conflict in an existing node |

For example, three releases might produce “the notes were too technical,” “leading with user value worked better,” and “important changes need a usage scenario.” Auto-Dream can consolidate them into:

> Lead with what users gain, then explain technical changes; give important changes a practical usage scenario.

Auto-Link runs during this integration. Durable nodes link back to daily evidence through `## Sources` and connect to related preferences, procedures, and concepts through Wikilinks. Auto-Dream does not rewrite daily memory: `memory/` preserves what happened, while `digest/` stores reusable conclusions.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i1/O1CN01ddkg0rN9DXK49o5c_!!6000000001181-0-tps-2048-796.jpg" alt="Auto-Dream run summary delivered to Inbox" />
</p>

Auto-Dream also writes `interests.yaml`. This is separate from QwenPaw's current `/proactive` mode; `/proactive` does not currently read that file.

### 5. Memory Search Recalls the Right Evidence

When you ask, “Why did we postpone the database migration?”, `memory_search` does not reread all history. It:

1. uses BM25 to find exact keyword matches;
2. optionally uses Embeddings to find similar meanings expressed with different words;
3. combines both rankings with RRF;
4. expands sources and related knowledge through Wikilinks only when needed.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01Zln7TK1TJOGqP84hk_!!6000000002361-55-tps-1200-640.svg" alt="BM25 and vector retrieval are fused before related memory is expanded" />
</p>

BM25 and Wikilink expansion still work without an Embedding model. Embeddings add semantic recall—for example, matching “checks before going live” with “staging validation before production release.” See [Embedding Models](./embedding) for provider configuration.

The background index watches only `.md` files in `memory/` and `digest/`, with a 10 MiB limit per file. It chunks files by Markdown structure and retains paths and line numbers. `resource/` and `mem_session/` are not searched directly.

### The Complete Loop

Returning to the release example:

1. Auto-Memory writes important decisions, reasons, and preferences into daily notes;
2. Daily Paper readings can enter the same daily-memory system;
3. the background index keeps Markdown searchable;
4. Auto-Dream consolidates scattered notes into linked durable knowledge;
5. Memory Search retrieves only relevant passages and evidence;
6. you can inspect and correct the files at any time, and those edits guide future work.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN019aX2sCLIZvB6wGdo_!!6000000005818-0-tps-3418-1594.jpg" alt="QwenPaw long-term memory Console overview" />
</p>

## Configuration Reference

The default `remelight` backend runs inside the QwenPaw process and reuses the current Agent's model for memory extraction and consolidation. Configure it in the Console or under `running.reme_light_memory_config` in `agent.json`.

### Common Configuration

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
      "daily_paper_cron_enabled": false,
      "daily_paper_cron": "0 9 * * *",
      "daily_paper_use_hf_mirror": false,
      "daily_paper_topics": "",
      "daily_paper_inbox_push_enabled": true,
      "memory_search_enabled": true,
      "auto_memory_search_config": {
        "enabled": false,
        "max_results": 2
      }
    }
  }
}
```

| Field                                   | Default        | Description                                                                       |
| --------------------------------------- | -------------- | --------------------------------------------------------------------------------- |
| `auto_memory_interval`                  | `5`            | Run Auto-Memory every N user turns; `null` or `<= 0` disables interval-based runs |
| `auto_memory_inbox_push_enabled`        | `true`         | Push an Inbox result when Auto-Memory changes memory                              |
| `dream_cron_enabled`                    | `true`         | Enable scheduled Auto-Dream                                                       |
| `dream_cron`                            | `"0 23 * * *"` | Five-field cron; execution starts after a random 0–60 second delay                |
| `auto_dream_inbox_push_enabled`         | `true`         | Push Auto-Dream results to Inbox                                                  |
| `daily_paper_cron_enabled`              | `false`        | Enable scheduled Daily Paper                                                      |
| `daily_paper_cron`                      | `"0 9 * * *"`  | Five-field Daily Paper cron expression                                            |
| `daily_paper_use_hf_mirror`             | `false`        | Fetch paper information through the Hugging Face mirror                           |
| `daily_paper_topics`                    | `""`           | Topics to prioritize during paper selection                                       |
| `daily_paper_inbox_push_enabled`        | `true`         | Push Daily Paper results to Inbox                                                 |
| `memory_search_enabled`                 | `true`         | Expose the manual `memory_search` tool to the Agent                               |
| `auto_memory_search_config.enabled`     | `false`        | Search memory before every normal user request                                    |
| `auto_memory_search_config.max_results` | `2`            | Maximum results injected by automatic search                                      |

Automatic results are injected only into the current request. They are excluded from persistent conversation history and Auto-Memory. Automation-originated requests do not trigger automatic search.

### Directory and Index Configuration

| Field                    | Default          | Description                                                         |
| ------------------------ | ---------------- | ------------------------------------------------------------------- |
| `metadata_dir`           | `"mem_metadata"` | Indexes, graph data, catalogs, and caches                           |
| `session_dir`            | `"mem_session"`  | Auto-Memory source-conversation directory                           |
| `mem_session_dir`        | `"mem_agent"`    | Internal ReMe memory-agent sessions                                 |
| `resource_dir`           | `"resource"`     | Raw resources for Daily Paper and future workflows                  |
| `daily_dir`              | `"memory"`       | Daily memory directory                                              |
| `digest_dir`             | `"digest"`       | Durable knowledge directory                                         |
| `embedding_model_config` | Disabled         | Optional vector model; see [Embedding Models](./embedding)          |
| `needs_reindex`          | `false`          | Runtime-maintained pending-rebuild flag after a vector-space change |

Legacy `inbox_push_enabled` is migration input only. It initializes any missing per-job Inbox switches but is not serialized back into validated configuration.

### Runtime Status and Rebuilding the Index

The long-term memory page shows background jobs, the waiting queue, resource use, and index-component status.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01hrPfLUAdE1C2Fz5c_!!6000000006909-0-tps-1112-1312.jpg" alt="ReMe background activity, resource usage, and index component status" />
</p>

Normal Markdown additions and edits are indexed incrementally. Use **Rebuild Memory Index** only when the Console reports a vector-space change, the index is damaged, or search is clearly abnormal. You can also call:

```http
POST /api/agents/{agentId}/memory/reindex
```

A rebuild clears derived index data and recreates it from Markdown in `memory/` and `digest/`; it does not delete source memory. CPU and memory use may rise during the rebuild, and only one rebuild can run per Agent.

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01BCTjXC0jfMG1GYA0_!!6000000005728-0-tps-624-276.jpg" alt="Resource-usage confirmation before rebuilding the memory index" />
</p>

---

## Other Memory Backends

QwenPaw's memory system uses a pluggable backend architecture. In addition to the default ReMeLight (local file storage), you can switch to other backends via `memory_manager_backend`.

### ADBPG (AnalyticDB for PostgreSQL)

A long-term memory backend backed by a cloud vector database. It is suitable for scenarios that need cross-device sharing or large-scale semantic retrieval. QwenPaw connects through the ADBPG memory service REST API, so no additional database driver is required.

**Key features:**

- **Cross-session persistence** — Memories are stored in a cloud database, retained across restarts, and shareable across devices.
- **Server-side fact extraction** — Fact extraction is handled by the ADBPG memory service, with no extra client-side overhead.
- **REST API access** — Calls the ADBPG memory service over HTTP.
- **Graceful degradation** — When ADBPG is unreachable, the agent keeps running normally; only the long-term memory feature is temporarily disabled.

**How to configure:**

Open the agent's "Running Config" tab in the Console, locate the "Long-term Memory Management Backend" dropdown, choose `adbpg`, and fill in `REST Base URL` and `REST API Key` under the "ADBPG Long-term Memory" tab.

![adbpg-backend](https://img.alicdn.com/imgextra/i3/O1CN01bH1Rj41wwQs3v04U6_!!6000000006372-2-tps-2954-1484.png)

> ⚠️ Switching the backend does not support hot reload. After saving, restart QwenPaw for the change to take effect (the page also shows a yellow banner reminder).

> Migration note: ADBPG direct SQL mode has been removed. Old fields such as
> `api_mode: "sql"`, `host`, `port`, `user`, `password`, `dbname`, and LLM /
> Embedding settings are ignored; configure `rest_base_url` and `rest_api_key`
> instead, then restart QwenPaw.

| Field                       | Description                                                                              | Default                               |
| --------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------- |
| `rest_base_url`             | REST API URL of the ADBPG memory service                                                 | `""`                                  |
| `rest_api_key`              | Access key for the REST API                                                              | `""`                                  |
| `memory_isolation`          | Memory isolation mode: `true` for per-agent, `false` for shared                          | `true`                                |
| `search_timeout`            | Memory search timeout (seconds)                                                          | `10.0`                                |
| `auto_memory_search_config` | Auto memory search configuration; same shape as ReMe Light's `auto_memory_search_config` | `{"enabled": true, "max_results": 3}` |

**Configuration example:**

The full configuration can be written into `running.adbpg_memory_config` of `agent.json`:

```json
{
  "running": {
    "memory_manager_backend": "adbpg",
    "adbpg_memory_config": {
      "rest_base_url": "https://your-adbpg-memory-api.example.com",
      "rest_api_key": "your-rest-api-key",
      "memory_isolation": true,
      "search_timeout": 10.0,
      "auto_memory_search_config": {
        "enabled": true,
        "max_results": 3
      }
    }
  }
}
```

> 💡 When you fill these fields in the Console "Running Config" page, the framework writes them into `agent.json` automatically — no need to edit the file by hand.

---

## Related Pages

- [Memory-Evolving & Proactive Interaction](./memory-evolving-and-proactive) — Auto-Memory, Auto-Dream, Auto-Memory-Search, and Proactive workflows
- [Embedding Models](./embedding) — Vector model capabilities, backends, configuration, and troubleshooting
- [Console](./console) — Manage memory and configuration in the Console
- [Configuration & Working Directory](./config) — Workspace and Agent configuration
