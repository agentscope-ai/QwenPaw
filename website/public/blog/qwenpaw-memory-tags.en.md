---
title: "QwenPaw Memory Tags: Find Accumulated Memories by Project"
date: 2026-10-27
author: QwenPaw Team
tags: [Memory Tags, ReMe, Long-term Memory, Memory as File]
cover: https://img.alicdn.com/imgextra/i1/O1CN01wDeKKV1Qz7WkSx4fp_!!6000000002046-55-tps-1200-620.svg
excerpt: "Several projects have discussed budgets, schedules, and owners. Follow a launch checklist through entity tagging, scoped retrieval, and browsing the original notes."
---

# QwenPaw Memory Tags: Find Accumulated Memories by Project

You are working on several projects, each with its own conversations with QwenPaw about budgets, release dates, and owners.

A week later, you ask, “What still needs confirming before Project A launches?” Search brings back plenty of records, but one describes Project B's schedule and another covers a different team's customer notifications. They all mention a launch, yet they are not all about the task at hand.

As [long-term memory](/blog/qwenpaw-long-term-memory) grows, it helps to know who or what each note is mainly about. QwenPaw integrates [ReMe](https://github.com/agentscope-ai/ReMe)'s Memory Tags to keep those entity cues in Markdown files, letting retrieval establish the scope before looking for details.

Tags work with text-only memories too. Follow Project A's launch checklist to see how a note gets tagged, retrieved, and opened for inspection.

## Start with Two Project Launches

Suppose you agree on Project A's plan with QwenPaw: launch on Thursday evening, complete regression checks, have the owner confirm customer notifications, and roll back if the error rate exceeds the agreed threshold.

Later, you discuss Project B, with its own launch window, test progress, and notifications. Both discussions are worth saving. But when you search for outstanding launch checks, similar wording alone does not mean they describe the same project.

Adding `Project_A` to one note and `Project_B` to the other leaves an explicit scope cue for later retrieval.

![ReMe Memory Tags: derive an index from Markdown tags and search within candidate files](https://img.alicdn.com/imgextra/i1/O1CN01wDeKKV1Qz7WkSx4fp_!!6000000002046-55-tps-1200-620.svg)

_Chart from [ReMe Memory Tags](https://reme.agentscope.io/en/blog_20260920)._

## Let Each Memory Say What It Is Mainly About

Tags are stored in Markdown YAML frontmatter. For example, a project launch note can be tagged like this:

```markdown
---
name: Project A launch checklist
description: Launch window, rollback conditions, and customer notifications.
memory_tags:
  - Project_A
---

Project A is scheduled to launch on Thursday evening. Complete regression
checks and have the owner confirm customer notifications before launch.
Roll back if the error rate exceeds the agreed threshold.
```

Projects, people, and organizations recur across conversations, making them useful stable cues. Broad topics such as “work,” “important,” or “meeting” often cover too many files to narrow retrieval. Usually, tagging the note's main entity is enough. Use several tags when it covers several entities.

Tags are independent of directory structure. A meeting note can carry tags for both a project and its owner while staying in its original location. You can inspect and edit tags, including making names consistent for the same entity.

## How Tags Participate in Retrieval

![Memory Tags pipeline: write tags, synchronize the index, and search within scope](https://img.alicdn.com/imgextra/i3/O1CN01PewzqI1EcsuQhRnH6_!!6000000000373-55-tps-1440-850.svg)

| Cue                    | Question it answers                               |
| ---------------------- | ------------------------------------------------- |
| Natural-language query | Which details am I looking for now?               |
| Memory Tag             | Which entities or projects should I search first? |
| Wikilink               | Which other records are related to this memory?   |

ReMe builds a bidirectional Tag Index from frontmatter, recording the files associated with each tag and the tags in each file. It updates the index as memories are created, changed, or deleted. Tags are stored in Markdown, so the index can be rebuilt from files.

With `Project_A` attached to a search, the Tag Index first selects relevant files. BM25 and optional vector retrieval then look for “What remains before launch?” within those files. Multiple tags match any supplied tag: `tags=["Project_A", "Project_B"]` searches records from either project. Searches without tags retain their existing behavior.

Tags constrain direct retrieval hits; Wikilink expansion may still list related notes outside that scope. Tags are retrieval cues rather than access controls.

## Next Time, Find Project A's Records First

Return to the question a week later:

> “What still needs confirming before Project A launches?”

With both memory search and tag generation enabled, the Agent can use `memory_list_tags` to discover the existing entity names, identify Project A's tag, then search for launch arrangements within that scope. Here are simplified tool arguments:

```text
memory_list_tags()
memory_search(query="What remains before launch?", tags=["Project_A"])
```

After finding the checklist above, an answer can follow the saved record:

> Project A is scheduled to launch on Thursday evening. The checklist calls for regression checks and confirmation of customer notifications by the owner. Also verify the agreed rollback threshold. These are the plans recorded at the time; whether they are complete still needs checking against current progress.

The tag identifies the project, while the note supplies the requirements. To check who proposed them or why, the Agent can follow source references in the note back to the original discussion. If the question does not identify a project, the scope still needs to come from context or a clarification.

## Generate and Use Tags in QwenPaw

Turn on **Generate memory tags** in the Agent's memory settings. This switch is off by default. When enabled, QwenPaw adds an entity-tagging step after Auto Memory saves a note, increasing model calls. Disabling generation leaves existing tags intact.

![Tag configuration: enable Generate memory tags separately](https://img.alicdn.com/imgextra/i4/O1CN01ml5EwQd3ZkL6NWXs_!!6000000003416-2-tps-3142-1526.png)

With both memory search and tag generation enabled, the Agent can discover entities and file counts through `memory_list_tags`, then pass `tags` to `memory_search`. Disabling tag generation keeps existing tags available for filtered search, but removes the tag discovery tool from the Agent. You can also enter `/reme list_tags` in chat to inspect existing tags, or view `memory_tags` in a memory file's preview metadata.

Manual imports and edits do not automatically generate tags, but file watching synchronizes tags already present in a file to the Tag Index. See [ReMe Memory Tags](https://reme.agentscope.io/en/blog_20260920) for tag conventions and index maintenance.

## Browse from a Tag to the Original Note

In **Files → Tags**, you can see indexed tags and their associated file counts. Select a tag to browse its matching memory files.

![The Tags tab in Files lists indexed tags and their associated file counts](https://img.alicdn.com/imgextra/i3/O1CN01aOf17D5AMdG7mt2s_!!6000000006319-2-tps-3836-1858.png)

Opening a matching memory displays the note preview on the right, including its tags, source-conversation reference, and body. You can check the saved facts and context there. Tag browsing relies on the existing index; files that have not been indexed may be absent from the list.

![Select a tag and open a matching memory to inspect its tags, source conversation, and note body](https://img.alicdn.com/imgextra/i2/O1CN01p2M4uxVRrDE7mt2u_!!6000000002688-2-tps-3836-1860.png)

## From One Checklist to Project Memories You Can Find Again

1. Auto Memory saves a project discussion and, with tag generation enabled, adds entity tags to its notes.
2. Tags stay in Markdown frontmatter, with the index synchronized as files change.
3. On a later question, the Agent uses tags to select candidate files, then retrieves the relevant facts and constraints.
4. You can also browse those files through Files → Tags and open the original notes to inspect and correct them.

As discussions accumulate, Project A's plans, decisions, and revisions may live in files from different dates. Tags provide a shared cue for finding them. The notes and their sources still supply the details and evidence.

See [long-term memory](/blog/qwenpaw-long-term-memory) for the complete workflow. For discussions that include photos, posters, or designs, continue with [multimodal memory](/blog/qwenpaw-multimodal-memory).
