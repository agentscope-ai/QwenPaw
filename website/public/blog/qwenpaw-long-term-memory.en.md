---
title: "QwenPaw Long-Term Memory: Turning Every Conversation into Knowledge You Can Reuse"
date: 2026-08-18
author: QwenPaw Team
tags: [Long-Term Memory, ReMe, Personal Knowledge Base, Memory as File]
cover: https://img.alicdn.com/imgextra/i3/O1CN01IvOZgheUdXK3OTaP_!!6000000004070-2-tps-1672-941.png
excerpt: "How does QwenPaw remember your research preferences, judgments, and supported materials—and retrieve the right information when you need it? This article follows a financial analyst through the complete long-term memory lifecycle."
---

# QwenPaw Long-Term Memory: Turning Every Conversation into Knowledge You Can Reuse

Have you ever run into this situation?

Last week, you spent an hour explaining your research framework to an AI. Today, you open a new conversation and it asks, “Which companies are you tracking?”

Three months ago, you carefully analyzed how falling lithium prices might affect battery makers and recorded the conditions behind your conclusion. Ask about it now, and the AI gives you a generic answer with no awareness of what you already validated or which risks remain unresolved.

The problem is not that the AI is not smart enough. It is that the things that truly mattered in the past were never organized into memory it could use over time.

QwenPaw's long-term memory is designed to solve this problem. It combines the QwenPaw-managed core `MEMORY.md` file with a [ReMe](https://github.com/agentscope-ai/ReMe) personal knowledge base. You and the Agent can maintain the former together and optionally load it directly into context; the latter turns conversations and currently supported materials into searchable Markdown knowledge.

![QwenPaw and ReMe turn conversations and materials into long-term memory](https://img.alicdn.com/imgextra/i3/O1CN01IvOZgheUdXK3OTaP_!!6000000004070-2-tps-1672-941.png)

Let us follow a financial analyst researching the electric-vehicle supply chain through the complete process, from capture and organization to recall.

## Start with a Supply-Chain Study

Suppose you are a financial analyst continuously researching the electric-vehicle supply chain. Over the past month, you have often discussed these questions with QwenPaw:

- How are CATL's EV-battery and energy-storage businesses changing?
- How will falling battery prices affect gross margin?
- Where is lithium carbonate in its supply-demand cycle?
- Do lower lithium prices benefit battery makers, or create inventory-impairment risk?
- Which assumptions behind the current view still need validation?

If all of this remains scattered across dozens of chat logs, it will soon become difficult to reuse. A useful long-term memory system needs to do six things:

1. **Record** research preferences, facts, judgments, reasons, and hypotheses that still need validation.
2. **Ingest** papers and other material from external sources that are already integrated.
3. **Organize** records scattered across dates into long-term knowledge.
4. **Connect** companies, supply chains, conclusions, and evidence with source links and Wikilinks.
5. **Retrieve** genuinely relevant content through keywords, semantics, and knowledge relationships.
6. **Expand** from the best-matching excerpts into files and links only when more evidence is needed.

![The complete QwenPaw long-term memory loop, from recording and organization to retrieval](https://img.alicdn.com/imgextra/i3/O1CN01mG5Uot1GQdX33v4h4_!!6000000000617-55-tps-1200-640.svg)

It works much like taking notes for yourself: preserve what happened, organize it into experience, and return to the right page when a real problem arises.

## Memory Is First and Foremost a File You Own

Before discussing how QwenPaw extracts and searches memory, there is a more important question: where does that memory live?

QwenPaw and ReMe follow the principle **Memory as File, File as Memory**. Core memory, daily memory, and consolidated long-term knowledge do not hide inside an invisible product database. They live as ordinary Markdown files in the Agent Configuration Directory—the Agent's own workspace. Raw conversations use JSONL, while source materials such as paper PDFs retain their original formats.

![Markdown memory files connect long-term experience with original evidence](https://img.alicdn.com/imgextra/i3/O1CN01vwIbuJ1zAkVDvcYjh_!!6000000006674-55-tps-1200-640.svg)

As the analyst's research develops, the workspace gradually grows into a structure like this:

```text
workspace/
├── MEMORY.md                         # A small set of stable core memories
├── memory/
│   ├── 2026-08-14.md                 # Automatically maintained index for the day
│   └── 2026-08-14/
│       ├── catl-earnings-review.md    # One memory note for one session
│       └── lithium-price-sensitivity.md
├── digest/
│   ├── personal/                     # Preferences, coverage, and standing agreements
│   ├── procedure/                    # Reusable research workflows
│   └── wiki/                         # Companies, industries, metrics, and concepts
├── mem_session/                      # Traceable source conversations
├── resource/                         # Original materials such as PDFs
└── mem_metadata/                     # Rebuildable indexes, graph, and caches
```

| Object or mechanism                         | What it does                                                                                                                           | How it enters context or is retrieved                                                                                          |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `MEMORY.md`                                 | QwenPaw's core long-term memory; both you and the Agent in the main session may freely read and edit it                                | Read on demand with file tools; it is not part of ReMe's `memory_search` index                                                 |
| `memory/YYYY-MM-DD.md`                      | Index page for that day's memory notes; ReMe maintains the `notes:auto` block, while you and the main Agent may add content outside it | Part of the personal knowledge base; searchable, directly readable, and usable for progressive expansion                       |
| `memory/YYYY-MM-DD/{name}.md`               | One topic-named memory note created or updated by Auto Memory for a session                                                            | Part of the personal knowledge base; the main Agent normally does not manage it directly                                       |
| All `.md` files under `digest/`             | Consolidated long-term knowledge organized into `personal`, `procedure`, and `wiki`, connected with Wikilinks                          | Part of the retrieval scope of `memory_search`                                                                                 |
| All `.md` files under `memory/` + `digest/` | ReMe's complete personal knowledge base: daily research evidence plus knowledge consolidated over time                                 | The complete retrieval scope of `memory_search`                                                                                |
| Excerpts returned by `memory_search`        | The passages most relevant to the current question, including their file paths                                                         | If an excerpt is insufficient, the Agent uses `read_file` to progressively expand only the context needed for the current task |

This has four direct benefits:

- **You can inspect it**: Open daily notes and digest nodes to see what QwenPaw remembers.
- **You can edit it**: Correct content that is inaccurate or outdated just like an ordinary document.
- **You can trace it**: Follow long-term conclusions back to their source conversations or integrated materials.
- **You can take it with you**: Back up, sync, version with Git, or migrate the entire Agent workspace.

A consolidated supply-chain memory might look like this:

```markdown
---
name: EV supply chain
description: Tracks the transmission from vehicle demand to battery earnings and upstream lithium resources.
---

# EV supply chain

Vehicle sales affect battery production schedules, which in turn affect demand for cathode materials and lithium resources.

- Representative battery maker: [[digest/wiki/catl.md]]
- Key cost input: [[digest/wiki/lithium-carbonate.md]]
- Analytical method: [[digest/procedure/battery-earnings-sensitivity.md]]

## Sources

- [[memory/2026-08-14/lithium-price-sensitivity.md]]
```

The body stores knowledge, frontmatter provides a summary, and Wikilinks connect companies, cost inputs, analytical methods, and sources. The link from “EV supply chain” to “CATL” is an outlink. The system also builds a reverse index, so CATL can lead back to the supply-chain node and research records that reference it. The author writes the link once; the Agent can traverse it in both directions during retrieval.

For example, QwenPaw may record, “Always start company analysis with the P/E ratio,” when you actually meant, “Start with P/E for consumer companies with stable earnings.” You can correct the memory directly. The next time you research a cyclical stock, the Agent will not mechanically apply the wrong valuation framework.

Files are the source of truth. Indexes, graphs, and caches are derived state that can be rebuilt. Auto Memory and Auto Dream do not overwrite `MEMORY.md`. An Agent can help organize your memory, but you remain in control.

To make these files searchable, ReMe parses frontmatter and builds a Markdown AST from heading levels, paragraphs, lists, tables, and code blocks instead of cutting text at arbitrary character counts. Each chunk retains the necessary ancestor headings, file path, and line numbers, while Wikilinks form a separate file graph. The same Markdown file can therefore provide semantically coherent search excerpts and relationship paths from a company to its industry, analytical methods, and original evidence.

## Auto Memory: Keep What Will Matter Later, Not Every Sentence

One day, you tell QwenPaw:

> “Add CATL to the priority watchlist. My current hypothesis is that falling lithium carbonate prices reduce unit cell costs, but we still need to check inventory impairment and pricing pass-through.”

This is not an isolated market opinion. It contains a research scope, a current judgment, and two conditions that still need validation.

That afternoon, you add battery-pricing and inventory-cycle data, explaining that the profit-improvement thesis holds only if raw-material costs fall faster than cell prices and the risk from high-cost inventory remains manageable.

Auto Memory does not mechanically copy the whole conversation. By default, it runs after every five user turns; it also processes pending conversation before context eviction or compaction. It distills what is worth keeping into a daily note, and if there is nothing worth adding or updating, it does not create an empty memory:

> **Research target**: Add CATL to the priority EV-supply-chain watchlist.
>
> **Current judgment**: Falling lithium prices generally reduce unit cell costs.
>
> **Conditions**: Raw-material costs fall faster than cell prices, and high-cost inventory impairment remains manageable.
>
> **To validate**: Pricing pass-through, inventory costs, and the product mix between EV batteries and energy storage.
>
> **Source**: The original conversation from that day.

![Auto Memory distills a long conversation into reusable, traceable daily memory](https://img.alicdn.com/imgextra/i3/O1CN01Qg6uAk1VoeXMqbE54_!!6000000002700-55-tps-1200-640.svg)

The background preserves the source conversation as traceable JSONL and creates or updates one topic note for that session under the day's directory, such as `memory/2026-08-14/lithium-price-sensitivity.md`. `memory/2026-08-14.md` is the automatically maintained index for that day's notes. If the same session is processed again that day, the system merges the new information into the original note instead of splitting the conversation into multiple topic files. The main Agent normally follows these paths after retrieval rather than maintaining the notes directly.

The date index actually looks something like this:

```text
---
name: 2026-08-14
description: 2 note(s) today.
---

<!-- notes:auto -->
- [[memory/2026-08-14/catl-earnings-review.md]] name: CATL earnings review description: Tracks volume, price, and cost drivers across EV batteries and energy storage.
- [[memory/2026-08-14/lithium-price-sensitivity.md]] name: Lithium-price sensitivity description: Analyzes the effects of falling lithium prices on cell costs, selling prices, and inventory impairment.
<!-- /notes:auto -->
```

Each index line comes from the corresponding note's frontmatter. The `notes:auto` block is rebuilt whenever the index refreshes and should not be edited by hand; content outside the automatic block is preserved. The actual session memory lives under the date directory and points back to the source JSONL through `session_id` and `source_conversation`:

```markdown
---
name: Lithium-price sensitivity
description: Analyzes the effects of falling lithium prices on cell costs, selling prices, and inventory impairment.
session_id: qpsid_sha256_<64-hex>
source_conversation: "[[mem_session/dialog/qpsid_sha256_<64-hex>.jsonl]]"
---

## Current judgment

Falling lithium prices generally reduce cell-material costs, but pricing pass-through and impairment on high-cost inventory still need to be checked.
```

If the model later improves the note's `name`, the file is safely renamed and its links are updated. Recalled old memory is removed before extraction so the system does not mistake something it just retrieved for a new fact supplied by the user.

![The task result pushed to Inbox after Auto Memory completes](https://img.alicdn.com/imgextra/i3/O1CN01q1761gvctQB49nzS_!!6000000007099-0-tps-2048-414.jpg)

Inbox only displays the result of the background run. The editable, reusable memory still lives in the workspace's Markdown files.

A few weeks later, when you update the CATL report, QwenPaw can recover this judgment. If someone treats falling lithium prices as an automatic earnings benefit, it can remind you to check pricing pass-through, inventory costs, and product mix instead of drawing a conclusion from the direction of lithium prices alone.

Long-term memory becomes useful not by preserving an isolated sentence, but by retaining its context, reasoning, follow-up action, and source.

## Materials Can Enter the Same Flow

Useful information does not come only from chat.

Auto Resource is the umbrella term for a Beta pipeline that brings in external material. QwenPaw's currently available built-in entry point is Daily Paper; support for other resource types is still expanding.

When enabled, Daily Paper collects candidates from the Hugging Face Papers weekly and monthly rankings, selects papers, preserves the original PDFs, and produces three detailed readings and one daily brief. These Markdown readings enter the same index as conversation memory and can later participate in Auto Dream.

If the analyst sets the topics to `battery, lithium, energy storage`, the pipeline can continuously add research on battery materials, life prediction, and energy-storage technology. Original PDFs go to `resource/papers/`; detailed readings and the daily brief go to `memory/YYYY-MM-DD/`. Because the records under the date directory are Markdown, they participate in ordinary retrieval and can later be consolidated into long-term knowledge.

For example, if a paper discusses battery-life prediction or energy-storage technology, that reading may provide evidence the next time you assess a battery maker's technical competitiveness.

![Daily Paper schedule and topic settings](https://img.alicdn.com/imgextra/i4/O1CN01P4HuDOo3HjE3MD24_!!6000000007223-0-tps-1654-670.jpg)

![ReMe Auto Resource turns source material into traceable memory; QwenPaw currently integrates this flow through Daily Paper](https://img.alicdn.com/imgextra/i2/O1CN015ankve1aJ7LTl8Cxa_!!6000000003308-55-tps-1200-640.svg)

Simply placing an arbitrary file under `resource/` does not currently make QwenPaw process it automatically, and automatically collecting financial news into the knowledge base is still planned work. At this stage, Auto Resource should not be understood as a general-purpose file importer.

## Auto Dream: Turn Scattered Daily Notes into Long-Term Experience

Daily notes alone are not enough. After six months, there may be hundreds of records. If every task requires reading them from the beginning, memory has merely changed from a pile of chat logs into a pile of files.

Suppose you leave three research notes on different dates:

- The first says that falling lithium prices reduce cathode-material costs.
- The second notes that cell prices may decline with raw-material prices.
- The third records short-term impairment pressure from high-cost inventory.

Auto Dream reads recently changed daily notes, extracts reusable knowledge, and integrates it into long-term digest nodes. It first decides what kind of long-term memory the material should become:

| Memory type | What it stores and how it is written                            | Financial-analyst example                                             |
| ----------- | --------------------------------------------------------------- | --------------------------------------------------------------------- |
| `personal`  | Identity, preferences, coverage, and standing agreements        | Focus on China's EV supply chain and lithium-resource companies       |
| `procedure` | A reusable runbook with steps, inputs, and cautions             | Earnings-sensitivity analysis for battery makers                      |
| `wiki`      | Definitions, facts, observations, principles, and mental models | CATL, lithium carbonate, inventory impairment, and price pass-through |

After classification, Auto Dream searches existing nodes, determines how the new material relates to established knowledge, and selects exactly one consolidation action:

| Action        | What it means in this research process                                   |
| ------------- | ------------------------------------------------------------------------ |
| `CREATE`      | No equivalent knowledge exists, so create a new node                     |
| `CORROBORATE` | New data supports the existing view, adding a source or stronger wording |
| `REFINE`      | New material adds conditions, boundaries, steps, or detail               |
| `CORRECT`     | New evidence fixes an error, omission, or outdated judgment              |

Records scattered across different dates can therefore become one more complete guideline:

> Falling lithium prices generally ease battery-material costs, but their net effect on CATL's profit still depends on pricing pass-through, inventory costs, customer bargaining power, and product mix. The direction of lithium prices alone is not enough.

![Auto Dream merges new and existing experience while Auto Link builds knowledge connections](https://img.alicdn.com/imgextra/i3/O1CN01DSVTuF1rEr7yobCav_!!6000000005600-55-tps-1200-640.svg)

During integration, Auto Link writes sources and related concepts as readable Wikilinks. A long-term conclusion can therefore point back to the daily note that produced it and connect to adjacent preferences, procedures, and knowledge nodes. Auto Dream does not rewrite daily memory: `memory/` preserves the research as it stood at the time, while `digest/` stores conclusions that remain reusable across time.

For example, it does not merely pile bare links at the end of a document. It can write the relationship into a sentence: “Lithium-price changes affect the material costs of [[digest/wiki/catl.md]] through [[digest/wiki/lithium-carbonate.md]]; use [[digest/procedure/battery-earnings-sensitivity.md]] for the full analysis.” Each long-term node also points back to daily notes under `## Sources`, preserving an evidence trail for the final conclusion.

![The task summary pushed to Inbox after Auto Dream completes](https://img.alicdn.com/imgextra/i1/O1CN01ddkg0rN9DXK49o5c_!!6000000001181-0-tps-2048-796.jpg)

QwenPaw's Knowledge Base can display these relationships as a knowledge graph. Nodes represent dates, memories, or knowledge, while edges show their sources and relationships. You can inspect the final conclusion and trace how it formed across repeated experience.

![A knowledge graph of memories and materials in the QwenPaw Knowledge Base](https://img.alicdn.com/imgextra/i1/O1CN01JBjN5c3diWC49o9I_!!6000000000514-0-tps-2048-1024.jpg)

If later quarterly data shows that the inventory cycle changes the short-term effect, Auto Dream can refine the conclusion's boundaries. If the original note says, “Falling lithium prices always benefit CATL,” it can correct the wording to match what the evidence supports instead of preserving contradictory statements forever.

## Memory Search: Retrieve the Right Memory When Needed

A month later, as you update the report, you ask, “Are falling lithium prices good for CATL?”

A literal keyword search might return everything that mentions “lithium prices” or “CATL.” QwenPaw's `memory_search` combines BM25 keyword retrieval with optional vector retrieval, fuses their rankings with RRF, and expands through Wikilinks when related nodes are useful.

It can first locate the most relevant judgment, then inspect its conditions, open questions, and source before answering:

> Falling lithium prices generally reduce material costs, but the net effect on CATL's profit depends on pricing pass-through, inventory costs, customer bargaining power, and product mix. The earlier sensitivity analysis supports the direction of cost improvement, but these conditions still need to be checked against the latest quarterly data.

![Hybrid search finds relevant passages first, then follows knowledge relationships as needed](https://img.alicdn.com/imgextra/i2/O1CN01Zln7TK1TJOGqP84hk_!!6000000002361-55-tps-1200-640.svg)

This resembles finding something on a bookshelf: first locate the most likely book and chapter, then follow its table of contents and references. The Agent does not need to load every old conversation and neighboring node into context. It brings back only what the current question needs.

Even without an embedding model, BM25 and Wikilink expansion still work. When vector retrieval is configured, semantically similar content with different wording becomes easier to find as well.

BM25 is strong at explicit names such as “CATL” and “lithium carbonate.” Vector retrieval can connect “the earnings impact of cheaper upstream materials on a leading cell maker” to a differently worded note titled “Lithium-price sensitivity.” RRF merges the rankings from both routes, preventing either score scale from dominating the final order.

`memory_search` covers every Markdown file under `daily_dir` (default `memory/`) and `digest_dir` (default `digest/`). The background index watches only these two directories, with a 10 MiB limit per file. It does not index the root `MEMORY.md`, `resource/`, or `mem_session/`. For example, a search for “how falling lithium prices affect CATL's earnings” might return:

```text
========== digest/wiki/catl.md:18-24 [score=0.0325 vector=0.8120 keyword=8.4700] ==========
## Lithium-price and earnings sensitivity
Falling lithium prices generally reduce material costs, but the net effect depends on pricing pass-through, inventory costs, and product mix.
See [[digest/wiki/lithium-carbonate.md]] and [[digest/procedure/battery-earnings-sensitivity.md]].
  outlinks (2):
    → digest/wiki/lithium-carbonate.md  name="Lithium carbonate"
    → digest/procedure/battery-earnings-sensitivity.md  name="Battery earnings sensitivity"
  inlinks (2):
    ← digest/wiki/ev-supply-chain.md  name="EV supply chain"
    ← memory/2026-08-14/catl-earnings-review.md  name="CATL earnings review"
```

The result starts with the matched excerpt's path and line range, along with keyword, vector, and fused-ranking information. Its body may contain original Wikilinks. `outlinks` are downstream documents referenced by the hit; `inlinks` are upstream documents that reference it.

This is progressive hybrid search. The first step retrieves only the most relevant local excerpt. If that is not enough to explain “why,” the Agent opens the lithium-carbonate node or the earnings-sensitivity procedure. If it needs to verify when the judgment formed, it follows an inlink to the August 14 discussion. The system does not load the whole knowledge base into context at the outset, but it preserves a path from the conclusion to concepts, methods, and original records. `MEMORY.md` is read on demand with file tools and does not depend on ReMe search.

## Put the Complete Memory Loop Together

Now return to the financial analyst's research process:

1. In `MEMORY.md`, you record a stable research scope: EVs, lithium batteries, and lithium resources.
2. Auto Memory summarizes that day's CATL and lithium-price session into one note under the date directory, then refreshes the date index.
3. If Daily Paper is enabled, relevant paper readings enter the same daily-memory and indexing system.
4. The background keeps Markdown chunks, BM25, the optional vector index, and the Wikilink file graph up to date.
5. When you run `/dream`, or enable its schedule, Auto Dream organizes records from multiple days into `personal`, `procedure`, and `wiki` nodes.
6. The next time you write a research report, `memory_search` returns the best-matching excerpts first, then follows outlinks, inlinks, and file paths only as needed.
7. You can open, inspect, and correct the Markdown at any time. Your corrections become part of future collaboration.

![QwenPaw long-term memory console overview](https://img.alicdn.com/imgextra/i2/O1CN019aX2sCLIZvB6wGdo_!!6000000005818-0-tps-3418-1594.jpg)

This flow does not require the model to reread the entire history, and it does not lock memory inside an invisible black box:

> What you discuss today becomes experience you can use tomorrow. Materials already integrated today can become evidence for answers in the future.

## Can It Really Handle a Very Long History?

ReMe uses public evaluations to test memory across multiple sessions and very long conversations.

On LongMemEval cleaned-S, which contains 500 questions, ReMe achieved an overall Agentic score of **89.4%**. On BEAM, the 100K setting contains 20 cases / 400 questions and scored **66.1%**; the 1M setting contains 35 cases / 700 questions and scored **65.0%**.

![ReMe's published LongMemEval and BEAM benchmark results](https://img.alicdn.com/imgextra/i4/O1CN01ohO0e31MntKw6mQZL_!!6000000001480-55-tps-1200-640.svg)

These numbers do not represent every real-world scenario, and they depend on the model, dataset, and evaluation setup. They show that as history grows, file-based organization, hybrid retrieval, and on-demand reading can still help an Agent find supporting evidence among large volumes of old information.

See the complete settings and per-category results in the [LongMemEval benchmark](https://github.com/agentscope-ai/ReMe/tree/main/benchmark/longmemeval) and [BEAM benchmark](https://github.com/agentscope-ai/ReMe/tree/main/benchmark/beam).

## Finally: Good Long-Term Memory Is Not About Remembering More

Useful long-term memory does not preserve every chat verbatim. It does four things well:

- Captures what truly matters while preserving its source.
- Organizes scattered experience into knowledge that can continue to evolve.
- Retrieves the right information and expands supporting evidence only when needed.
- Lets you inspect, edit, back up, and take your memory with you.

As you continue using QwenPaw, the first few daily notes gradually grow into a personal knowledge base that truly belongs to you.

It does not merely “remember more.” It develops a better understanding of your research preferences, coverage universe, and how your judgments formed. More importantly, you can always see what it remembered, why it formed a conclusion, and how to correct it.

Learn more:

- [ReMe GitHub](https://github.com/agentscope-ai/ReMe)
- [QwenPaw long-term memory documentation](https://qwenpaw.agentscope.io/docs/memory)
