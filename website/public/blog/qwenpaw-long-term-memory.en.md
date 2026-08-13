---
title: "QwenPaw Long-Term Memory: Turning Every Conversation into Knowledge You Can Reuse"
date: 2026-08-07
author: QwenPaw Team
tags: [Long-Term Memory, ReMe, Personal Knowledge Base, Memory as File]
cover: https://img.alicdn.com/imgextra/i4/O1CN016mGvikM8DGD3OTaP_!!6000000003113-2-tps-1672-941.png
excerpt: "How does QwenPaw remember your preferences, decisions, and supported materials—and retrieve the right information when you need it? This article explains the full process through one continuous example."
---

# QwenPaw Long-Term Memory: Turning Every Conversation into Knowledge You Can Reuse

Have you ever run into this situation?

Last week, you spent an hour explaining the background of a project to an AI. Today, you open a new conversation and it asks, “Who are your target users?”

Three months ago, your team carefully compared two options and explained why you chose one over the other. Ask about it now, and the AI gives you generic advice with no awareness of the decision you already made.

The problem is not that the AI is not smart enough. It is that the things that truly mattered in the past were never turned into memory it could use over time.

QwenPaw's long-term memory is designed to solve this problem. Powered by [ReMe](https://github.com/agentscope-ai/ReMe), it organizes conversations and supported materials into a personal knowledge base that belongs to you.

![QwenPaw and ReMe turn conversations and materials into long-term memory](https://img.alicdn.com/imgextra/i4/O1CN016mGvikM8DGD3OTaP_!!6000000003113-2-tps-1672-941.png)

Instead of starting with complicated theory, let us first meet a user named Lin.

## Lin Is Preparing a Product Release

Lin is a product manager working with her team on a new release. Over the past month, she has often discussed these questions with QwenPaw:

- How should the release notes be written?
- Why are they not changing the database in this release?
- Which features matter most to customers?
- What went wrong in the previous release?
- What work is still unfinished?

If all of this remains scattered across dozens of chat logs, it will soon become difficult to reuse. QwenPaw gradually organizes it into a simple memory loop:

> **What you discuss is recorded, scattered notes are organized, and the most relevant pieces are retrieved when you need them.**

![The complete QwenPaw long-term memory loop, from recording and organization to retrieval](https://img.alicdn.com/imgextra/i3/O1CN01deWyUt1jTUrXQRTJz_!!6000000004549-55-tps-1200-640.svg)

It works much like taking notes for ourselves: write down what happened today, review it later to extract lessons, and return to the right page when a real problem arises.

## It Does Not Remember Every Sentence—Only What May Be Useful Later

One day, Lin tells QwenPaw:

> “Start the release notes with what users will gain, then explain the technical changes. Do not open with version numbers and module names.”

This is not casual small talk. It is a writing preference that will be useful again and again.

That afternoon, the team also discusses a database migration. They ultimately decide not to migrate for this release because the delivery timeline is tight and the existing solution still meets their needs. They will schedule a separate evaluation after the release.

A long conversation may contain experiments, additions, and tangents. QwenPaw does not need to memorize it word for word. Instead, it can retain a concise record like this:

> **Writing preference**: Lead release notes with user value, then explain technical changes.
>
> **Project decision**: Do not migrate the database in this release.
>
> **Reason**: The delivery timeline is tight, and the current solution is still sufficient.
>
> **Next step**: Reevaluate the migration plan after the release.
>
> **Source**: The original conversation from that day.

![Auto Memory distills a long conversation into reusable, traceable daily memory](https://img.alicdn.com/imgextra/i2/O1CN01a8Gj7V1UUDFBk6GAU_!!6000000002520-55-tps-1200-640.svg)

A few weeks later, when Lin asks QwenPaw to draft release notes, it naturally leads with user value. If someone raises the database migration again, it can also remind the team: “The proposal was not rejected permanently; the evaluation was postponed until after the release.”

That is where long-term memory becomes truly useful. It does not merely remember a sentence; it remembers the context, the reasoning, and the next step.

## Scattered Daily Notes Gradually Become Experience

Keeping a daily record is not enough. After six months, there may be hundreds of entries. What makes the system genuinely helpful is that QwenPaw can consolidate repeated experiences into more stable knowledge.

For example, Lin goes through three releases:

- In the first, the release notes are too technical for customers to understand.
- In the second, the notes lead with user value and receive much better feedback.
- In the third, the team adds another lesson: important changes should include a concrete use case.

These observations do not need to remain scattered across three dates forever. Once organized, they become a more complete writing guideline:

> Start release notes with what users will gain, then explain the technical changes. Whenever possible, pair an important change with a real-world use case.

![Auto Dream merges new and existing experience while Auto Link builds knowledge connections](https://img.alicdn.com/imgextra/i2/O1CN011mEx1x1XmTtCPsruU_!!6000000002966-55-tps-1200-640.svg)

In QwenPaw's Knowledge Base, these connections can also be explored as a knowledge graph. Different nodes represent memories, materials, or dates, while the links show how they relate. Lin can trace an insight back to its original records and see how previously scattered information gradually forms a connected knowledge network.

![A knowledge graph of memories and materials in the QwenPaw Knowledge Base](https://img.alicdn.com/imgextra/i1/O1CN01JBjN5c3diWC49o9I_!!6000000000514-0-tps-2048-1024.jpg)

Existing memory is not frozen when new information appears.

Suppose the team later learns that enterprise customers prefer to see compatibility notices first. QwenPaw can update the earlier guideline and clarify where it applies, instead of preserving an outdated conclusion alongside a new and contradictory one.

Think of this as a periodic review: conclusions that recur become more reliable, incomplete lessons gain context, and outdated statements are corrected.

## Materials Can Enter the Same Memory Loop

Useful information does not come only from chat.

ReMe provides Auto Resource, a Beta capability that interprets source material, preserves the original file, and writes a source-linked daily memory card. QwenPaw is integrating this flow progressively. Today, its built-in integration is Daily Paper: when enabled, it selects research papers, keeps the original PDFs, and writes detailed readings and a daily brief into memory.

Those readings can then participate in the same search and consolidation loop as conversation memory. For example, if a paper discusses why users overlook newly released capabilities, it can later provide evidence when Lin asks how to improve feature discovery.

Support for bringing in other materials—such as interview reports, meeting notes, project documents, and web content—is still being integrated. Once available, a report like Lin's customer interview summary will be able to follow the same traceable path from original source to daily note and long-term knowledge.

![ReMe Auto Resource turns source material into traceable memory; QwenPaw currently integrates this flow through Daily Paper](https://img.alicdn.com/imgextra/i1/O1CN01bfUxpA1gdANS9XGQ1_!!6000000004164-55-tps-1200-640.svg)

## How Does It Retrieve the Right Memory When Needed?

A month later, someone asks Lin, “Why did we decide not to migrate the database?”

A literal keyword search might return everything that mentions “database.” QwenPaw instead finds the most relevant decision first, then examines its reasoning and follow-up plan as needed.

It can therefore answer:

> The team did not conclude that migration had no value. The release date was approaching, and the existing database still met the requirements, so the evaluation was postponed until after the release. This decision came from the July release-planning discussion.

![Hybrid search finds relevant passages first, then follows knowledge relationships as needed](https://img.alicdn.com/imgextra/i4/O1CN01rHmJoR22rI8gZpRsU_!!6000000007173-55-tps-1200-640.svg)

This resembles finding something on a bookshelf: first locate the book most likely to be relevant, then open the right chapter. Only when necessary do you continue into the sources it references.

Even as the history grows, QwenPaw does not need to reread every old conversation. It only brings back the few memories that are useful for the current question.

## Proactive Mode Can Follow Up on Recent Context

QwenPaw's current `/proactive` mode is a separate runtime capability from the interest topics produced by Auto Dream. It does not currently read Auto Dream's `interests.yaml` file.

After Lin explicitly enables proactive mode, QwenPaw waits until the configured idle threshold is reached. It then analyzes recent chat sessions and, when the active model supports images, can optionally use a desktop screenshot as additional context. From that context, it identifies one to three likely tasks.

Suppose Lin's recent conversations include unfinished work on release notes and repeated questions about feature discovery. After the idle interval, QwenPaw may infer that a follow-up would be useful. Its temporary proactive assistant can investigate up to three task queries with the available tools, then send a user-facing proactive request back to the QwenPaw chat.

The resulting message might ask:

> Your recent sessions still have an open question about helping customers discover new features. Would you like to turn the release-note feedback into a concrete follow-up checklist?

Because this mode can read recent session history, optionally inspect the screen, and use tools for supporting investigation, QwenPaw asks the user to enable it explicitly. The idle interval can be adjusted with `/proactive <minutes>`, and `/proactive off` stops the background loop.

## Memory Is Not a Black Box—It Is Your File

Many people worry about the same questions: Where does an AI store what it remembers? What if it remembers something incorrectly? Can I take that memory with me later?

QwenPaw and ReMe choose a straightforward answer: memory is stored in ordinary Markdown files.

![Markdown memory files connect long-term experience with original evidence](https://img.alicdn.com/imgextra/i1/O1CN01fF7xEt29K2hGFkXFC_!!6000000008048-55-tps-1200-640.svg)

This means:

- **You can see it**: Open the files directly and inspect what QwenPaw remembers.
- **You can edit it**: Correct anything that is inaccurate or outdated.
- **You can trace it**: Follow important conclusions back to their original conversations or materials.
- **You can take it with you**: Back it up, sync it, and migrate it without being locked into one product.

For example, QwenPaw may record, “Every article should lead with the conclusion,” when Lin actually meant, “Technical proposals should lead with the conclusion.” She can correct the memory directly. The next time she writes a brand story, QwenPaw will not mechanically apply the wrong preference.

An Agent can help organize your memory, but you remain in control.

## Can It Really Handle a Very Long History?

ReMe also uses public evaluations to test long-term memory performance.

On LongMemEval cleaned-S, which contains 500 multi-turn memory questions, ReMe achieved an overall score of **89.4%**. On another long-conversation benchmark, BEAM, its score changed from **66.1%** to **65.0%** as the conversation scale increased from 100K to 1M, remaining broadly stable.

![ReMe's published LongMemEval and BEAM benchmark results](https://img.alicdn.com/imgextra/i4/O1CN016I1rKF1tym4HogJ0A_!!6000000005971-55-tps-1200-640.svg)

These numbers do not represent every real-world scenario, and they depend on the model and evaluation setup. What they primarily show is that, even as history grows, organizing information and retrieving it on demand can still help an AI find the right evidence among large volumes of old information.

See the complete results in the [LongMemEval benchmark](https://github.com/agentscope-ai/ReMe/tree/main/benchmark/longmemeval) and [BEAM benchmark](https://github.com/agentscope-ai/ReMe/tree/main/benchmark/beam).

## Putting Lin's Day Together

In the morning, Daily Paper brings selected research papers and their readings into memory while preserving the original PDFs. Integration for other resource types, such as Lin's customer interview report, is still in progress.

Later that morning, she discusses the release plan with QwenPaw. Important decisions, reasons, and next steps are organized into the day's memory.

In the afternoon, she asks why the previous release failed. QwenPaw finds the old record and retrieves the solution used at the time.

In the evening, scattered new records are incorporated into existing experience. Conclusions that are no longer accurate are revised.

Later, after Lin has enabled `/proactive` and the session becomes idle, QwenPaw analyzes recent session context, investigates likely follow-up tasks when useful, and sends a proactive request back to the chat.

None of these steps is magic. The real value is that captured conversations and integrated source material do not simply disappear:

> What you discuss today becomes experience you can use tomorrow. What Daily Paper reads today can become evidence for answers in the future.

## Finally: Good Long-Term Memory Is Not About Remembering More

Useful long-term memory does not preserve every chat verbatim. It does four things well:

- Remembers what truly matters.
- Organizes scattered experiences into reusable knowledge.
- Retrieves the right information when needed and shows the supporting evidence.
- Lets you inspect, edit, and take your memory with you at any time.

As you continue using QwenPaw, the first few daily notes gradually grow into a personal knowledge base that truly belongs to you.

It does not merely “remember more.” It develops a better understanding of your habits, projects, and past decisions—and you can always see why it reached that understanding.

Learn more:

- [ReMe GitHub](https://github.com/agentscope-ai/ReMe)
- [QwenPaw long-term memory documentation](https://qwenpaw.agentscope.io/docs/memory)
- [Memory evolution and proactive interaction](https://qwenpaw.agentscope.io/docs/memory-evolving-and-proactive)
