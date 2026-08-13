---
title: "QwenPaw Long-Term Memory: Turning Every Conversation into Knowledge You Can Reuse"
date: 2026-08-07
author: QwenPaw Team
tags: [Long-Term Memory, ReMe, Personal Knowledge Base, Memory as File]
cover: https://img.alicdn.com/imgextra/i3/O1CN01IvOZgheUdXK3OTaP_!!6000000004070-2-tps-1672-941.png
excerpt: "How does QwenPaw remember your preferences, decisions, and supported materials—and retrieve the right information when you need it? This article follows one product release through the complete long-term memory lifecycle."
---

# QwenPaw Long-Term Memory: Turning Every Conversation into Knowledge You Can Reuse

Have you ever run into this situation?

Last week, you spent an hour explaining a project's background to an AI. Today, you open a new conversation and it asks, “Who are your target users?”

Three months ago, your team carefully compared two options and explained why it chose one over the other. Ask about it now, and the AI gives you generic advice with no awareness of the decision already made.

The problem is not that the AI is not smart enough. It is that the things that truly mattered in the past were never organized into memory it could use over time.

QwenPaw's long-term memory is designed to solve this problem. Powered by [ReMe](https://github.com/agentscope-ai/ReMe), it gradually organizes conversations and currently supported materials into a personal knowledge base that belongs to you.

![QwenPaw and ReMe turn conversations and materials into long-term memory](https://img.alicdn.com/imgextra/i3/O1CN01IvOZgheUdXK3OTaP_!!6000000004070-2-tps-1672-941.png)

Let us follow one product release through the complete process, from capture and organization to recall.

## Start with a Product Release

Suppose you are a product manager preparing a new release with your team. Over the past month, you have often discussed these questions with QwenPaw:

- How should the release notes be written?
- Why is the database not being migrated in this release?
- Which features matter most to customers?
- What went wrong in the previous release?
- What work is still unfinished?

If all of this remains scattered across dozens of chat logs, it will soon become difficult to reuse. A useful long-term memory system needs to complete four steps:

1. **Capture** information worth keeping from conversations and integrated resources.
2. **Index** memory so it can be found through keywords, semantics, and knowledge relationships.
3. **Consolidate** records from different dates into reusable long-term knowledge.
4. **Recall** only the relevant content and evidence when a new question appears.

![The complete QwenPaw long-term memory loop, from recording and organization to retrieval](https://img.alicdn.com/imgextra/i3/O1CN01mG5Uot1GQdX33v4h4_!!6000000000617-55-tps-1200-640.svg)

It works much like taking notes for yourself: preserve what happened, organize it into experience, and return to the right page when a real problem arises.

## Memory Is First and Foremost a File You Own

Before discussing how QwenPaw extracts and searches memory, there is a more important question: where does that memory live?

QwenPaw and ReMe follow the principle **Memory as File, File as Memory**. Core working and long-term memory do not hide inside an invisible product database. They live as ordinary Markdown files in the workspace. Raw conversations use JSONL, while source materials such as paper PDFs retain their original formats.

![Markdown memory files connect long-term experience with original evidence](https://img.alicdn.com/imgextra/i4/O1CN01wj1PUE1a2d5QtEyUv_!!6000000003272-55-tps-1200-640.svg)

This has four direct benefits:

- **You can inspect it**: Open daily notes and digest nodes to see what QwenPaw remembers.
- **You can edit it**: Correct content that is inaccurate or outdated just like an ordinary document.
- **You can trace it**: Follow long-term conclusions back to their source conversations or integrated materials.
- **You can take it with you**: Back up, sync, version with Git, or migrate the whole workspace.

For example, QwenPaw may record, “Every article should lead with the conclusion,” when you actually meant, “Technical proposals should lead with the conclusion.” You can correct the memory directly. The next time you write a brand story, the Agent will not mechanically apply the wrong preference.

Files are the source of truth. Indexes, graphs, and caches are derived state that can be rebuilt. An Agent can help organize your memory, but you remain in control.

## Auto Memory: Keep What Will Matter Later, Not Every Sentence

One day, you tell QwenPaw:

> “Start the release notes with what users will gain, then explain the technical changes. Do not open with version numbers and module names.”

This is not casual small talk. It is a writing preference that will be useful again.

That afternoon, your team also discusses a database migration. It decides not to migrate in this release because the delivery timeline is tight and the existing solution still meets its needs. A separate evaluation will follow after the release.

Auto Memory does not mechanically copy the whole conversation. It runs periodically after the configured number of user turns and, when context compression is enabled, flushes pending conversation first. It distills what is worth keeping into a daily note:

> **Writing preference**: Lead release notes with user value, then explain technical changes.
>
> **Project decision**: Do not migrate the database in this release.
>
> **Reason**: The delivery timeline is tight, and the current solution is still sufficient.
>
> **Next step**: Reevaluate the migration plan after the release.
>
> **Source**: The original conversation from that day.

![Auto Memory distills a long conversation into reusable, traceable daily memory](https://img.alicdn.com/imgextra/i3/O1CN01Qg6uAk1VoeXMqbE54_!!6000000002700-55-tps-1200-640.svg)

A few weeks later, when you draft release notes again, QwenPaw can naturally lead with user value. If someone raises the database migration, it can remind the team that the proposal was not rejected permanently; its evaluation was postponed until after the release.

Long-term memory becomes useful not by preserving an isolated sentence, but by retaining its context, reasoning, follow-up action, and source.

## Materials Can Enter the Same Flow

Useful information does not come only from chat.

ReMe provides Auto Resource, a Beta capability that interprets source material, preserves the original file, and writes a source-linked daily memory card. QwenPaw is progressively integrating this resource flow. Its currently available built-in entry point is Daily Paper.

When enabled, Daily Paper collects candidates from the Hugging Face Papers weekly and monthly rankings, selects papers, preserves the original PDFs, and produces detailed readings and a daily brief. These Markdown readings enter the same index as conversation memory and can later participate in Auto Dream.

For example, if a paper discusses why users overlook newly released capabilities, that reading may provide evidence the next time you ask how to improve feature discovery.

![ReMe Auto Resource turns source material into traceable memory; QwenPaw currently integrates this flow through Daily Paper](https://img.alicdn.com/imgextra/i2/O1CN015ankve1aJ7LTl8Cxa_!!6000000003308-55-tps-1200-640.svg)

Other resource types—including interview reports, meeting notes, project documents, and web content—are still being integrated. Simply placing an arbitrary file under `resource/` does not currently make QwenPaw process it automatically. Once integration is complete, these materials can follow the same traceable path from original source to daily note and long-term knowledge.

## Auto Dream: Turn Scattered Daily Notes into Long-Term Experience

Daily notes alone are not enough. After six months, there may be hundreds of records. If every task requires reading them from the beginning, memory has merely changed from a pile of chat logs into a pile of files.

Suppose you go through three releases:

- In the first, the release notes are too technical for customers to understand.
- In the second, they lead with user value and receive much better feedback.
- In the third, the team adds another lesson: important changes should include a concrete use case.

Auto Dream reads recently changed daily notes, extracts reusable knowledge, and integrates it into long-term digest nodes. When related knowledge already exists, it does not simply append another copy. It creates, corroborates, refines, or corrects the existing conclusion according to the new evidence.

Records scattered across different dates can therefore become one more complete guideline:

> Start release notes with what users will gain, then explain the technical changes. Whenever possible, pair an important change with a real-world use case.

![Auto Dream merges new and existing experience while Auto Link builds knowledge connections](https://img.alicdn.com/imgextra/i3/O1CN01DSVTuF1rEr7yobCav_!!6000000005600-55-tps-1200-640.svg)

During integration, Auto Link writes sources and related concepts as readable Wikilinks. A long-term conclusion can therefore point back to the daily note that produced it and connect to adjacent preferences, procedures, and knowledge nodes.

QwenPaw's Knowledge Base can display these relationships as a knowledge graph. Nodes represent dates, memories, or knowledge, while edges show their sources and relationships. You can inspect the final conclusion and trace how it formed across repeated experience.

![A knowledge graph of memories and materials in the QwenPaw Knowledge Base](https://img.alicdn.com/imgextra/i1/O1CN01JBjN5c3diWC49o9I_!!6000000000514-0-tps-2048-1024.jpg)

If the team later learns that enterprise customers prefer compatibility notices first, Auto Dream can refine the guideline's scope or correct an outdated conclusion instead of preserving contradictory statements forever.

## Memory Search: Retrieve the Right Memory When Needed

A month later, someone asks, “Why did we decide not to migrate the database?”

A literal keyword search might return everything that mentions “database.” QwenPaw's `memory_search` combines BM25 keyword retrieval with optional vector retrieval, fuses their rankings with RRF, and expands through Wikilinks when related nodes are useful.

It can first locate the most relevant decision, then inspect its reasoning, follow-up plan, and source before answering:

> The team did not conclude that migration had no value. The release date was approaching, and the existing database still met the requirements, so the evaluation was postponed until after the release. This decision came from the July release-planning discussion.

![Hybrid search finds relevant passages first, then follows knowledge relationships as needed](https://img.alicdn.com/imgextra/i2/O1CN01Zln7TK1TJOGqP84hk_!!6000000002361-55-tps-1200-640.svg)

This resembles finding something on a bookshelf: first locate the most likely book and chapter, then follow its table of contents and references. The Agent does not need to load every old conversation and neighboring node into context. It brings back only what the current question needs.

Even without an embedding model, BM25 and Wikilink expansion still work. When vector retrieval is configured, semantically similar content with different wording becomes easier to find as well.

## Put the Complete Memory Loop Together

Now return to the product release:

1. You discuss the release plan with QwenPaw. Auto Memory writes important preferences, decisions, reasons, and follow-up actions into a daily note while preserving the conversation source.
2. If Daily Paper is enabled, paper readings provide the currently integrated resource input to the same daily and indexing system.
3. The background index keeps Markdown in daily and digest memory searchable.
4. When you run `/dream`, or enable its schedule, Auto Dream integrates recent records into long-term digest nodes and preserves sources and relationships through Wikilinks.
5. When a new question appears, `memory_search` finds the most relevant fragments and follows relationships only when additional context is needed.
6. You can open, inspect, and correct the files at any time. Your corrections become part of future collaboration.

This flow does not require the model to reread the entire history, and it does not lock memory inside an invisible black box:

> What you discuss today becomes experience you can use tomorrow. Materials already integrated today can become evidence for answers in the future.

## Proactive Mode: A Separate Runtime Capability

QwenPaw's current `/proactive` mode is a separate runtime path from the long-term memory loop above. Auto Dream writes `interests.yaml`, and ReMe provides a low-level job that reads those topics, but QwenPaw's current `/proactive` implementation does not read that file.

After you explicitly enable proactive mode, QwenPaw waits until the configured idle threshold is reached. It then analyzes recent chat sessions and, when the active model supports images, can use a desktop screenshot as additional context. From that context, it identifies one to three likely tasks.

Suppose your recent conversations include unfinished release notes and repeated questions about feature discovery. After the idle interval, a temporary proactive assistant can investigate up to three task queries with the available tools, then send a proactive request back to the QwenPaw chat:

> Your recent sessions still have an open question about helping customers discover new features. Would you like to turn the release-note feedback into a concrete follow-up checklist?

This is more than a notification layer: the mode can read recent session history, inspect the screen when supported, and use tools for supporting investigation. You must therefore enable it explicitly. Use `/proactive <minutes>` to adjust the idle threshold and `/proactive off` to stop the background loop.

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

It does not merely “remember more.” It develops a better understanding of your habits, projects, and past decisions. More importantly, you can always see what it remembered, why it formed a conclusion, and how to correct it.

Learn more:

- [ReMe GitHub](https://github.com/agentscope-ai/ReMe)
- [QwenPaw long-term memory documentation](https://qwenpaw.agentscope.io/docs/memory)
- [Memory evolution and proactive interaction](https://qwenpaw.agentscope.io/docs/memory-evolving-and-proactive)
