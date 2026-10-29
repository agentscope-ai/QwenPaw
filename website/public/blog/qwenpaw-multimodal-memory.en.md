---
title: "QwenPaw Memory Update: Multimodal Memory and Memory Tags"
date: 2026-10-27
author: QwenPaw Team
tags: [Multimodal Memory, ReMe, Memory Tags, Memory as File]
cover: https://img.alicdn.com/imgextra/i2/O1CN01qVVKgkcRb5D3OTaP_!!6000000005716-2-tps-1672-941.png
excerpt: "How can facts and decisions from image-and-text conversations support a later task? How can accumulated memories be found by project? Explore QwenPaw's multimodal memory and Memory Tags separately, from recording and source inspection to scoped retrieval."
---

# QwenPaw Memory Update: Multimodal Memory and Memory Tags

Today, you discuss a design with QwenPaw using images. A few days later, you open a new conversation to draft copy, only to upload the images and explain your choices again. Meanwhile, several projects have been discussing budgets and schedules, and finding a past decision means searching through many records. Building on its [file-based long-term memory](./qwenpaw-long-term-memory), QwenPaw integrates two capabilities from [ReMe](https://github.com/agentscope-ai/ReMe) to remember image-and-text conversations and retrieve memories by project, person, or other entity.

**Multimodal memory** works with sessions containing image-and-text interactions. When enabled, Auto Memory reads the session's images and text in the background and writes notes about image details, the user's choices, constraints, and reasons. Which photo was selected, why it was chosen, and what an event poster said can all be saved for later use. Notes also reference the original images and conversation for checking. In a new conversation, the Agent can retrieve these notes so you do not have to explain the background again.

**Memory Tags** addresses the problem of finding relevant records as memory grows. A question such as “What still needs confirming before launch?” could refer to several projects. Entity tags for projects, people, or organizations help establish the candidate files before searching their contents. Tags also work with text-only memories and do not depend on image input.

Both capabilities retain memories as Markdown files that you can open and edit.

![QwenPaw organizes memories from image-and-text conversations and tagged notes](https://img.alicdn.com/imgextra/i2/O1CN01qVVKgkcRb5D3OTaP_!!6000000005716-2-tps-1672-941.png)

## 1. Multimodal Memory: Reuse Conversation Context in Later Tasks

![Images and discussion within a session become memories, with links back to their sources](https://img.alicdn.com/imgextra/i4/O1CN01FZjxTO1kcwfMP8mPI_!!6000000004705-55-tps-1200-640.svg)

### Start with a Weekend Pop-up

Suppose you are planning a weekend pop-up for a clothing brand. You share two model photos with QwenPaw and ask for a campaign that feels like heading out for a weekend walk.

QwenPaw recommends photo A, taken on the street, as the better fit. Photo B has more of an office look and is kept for other uses. After confirming the choice, the user shares an event poster and a venue photo to discuss the copy and arrangements, making clear that there will be no sale or giveaway.

![The first image discussion compares two model photos and selects the campaign image](https://img.alicdn.com/imgextra/i2/O1CN01wkoJ8tirBGL4s7Ss_!!6000000004233-0-tps-2400-1354.jpg)

### Remember the Image and the Discussion Around It

Saving only the text might preserve “we chose A” without recording what the model is wearing or which bag she carries. Describing the image separately could lose the user's reason for choosing it.

With image input enabled, ReMe Auto Memory sends conversation text and images together to a vision model. It preserves message order, the relative order of text and images within each message, and the speaker and timestamp. The model extracts facts and uses memory tools to create or update Markdown notes.

For this event, the useful information includes:

- **Image content:** the outfit, bag, and lighting, plus the time, location, and booking details on the poster.
- **Explicit decisions:** use photo A for this campaign and keep photo B for other uses.
- **User constraints:** the campaign should feel like a weekend walk; there is no sale or giveaway.
- **Reason for the choice:** photo A's street setting and casual outfit better fit the event theme.

These details become searchable text and enter the existing keyword and optional semantic retrieval workflow. A later text question can therefore find facts that originally appeared in an image.

The model may miss or misread image details, so notes need references to the original images for later checks.

### Reopen the Original Image to Check Details

Today, you choose the campaign photo; tomorrow, you may need to check the bag's shape, which the summary may not have recorded.

ReMe preserves image sources. Original Base64 image bytes are saved under `session/images/<session_id>/` by default, while HTTP(S) images retain their original addresses. The `session_dir` setting controls the actual directory; QwenPaw defaults to `mem_session/`. The extraction prompt asks for exact source references beside relevant visual facts. A note's `source_images` collects associated image sources, and `source_conversation` points to the source conversation. Later updates merge new image sources while retaining existing links.

Here is the note format, using simplified paths and wording:

```markdown
---
name: Weekend pop-up campaign image
description: Photo selection and campaign copy requirements.
source_conversation: "[[mem_session/dialog/popup-planning.jsonl]]"
source_images:
  - "[[mem_session/images/popup-planning/photo-a.jpg]]"
---

Use photo A for the campaign, with the theme of heading out for a weekend walk.
The outfit, silver crossbody bag, and natural street light are visible in:
[[mem_session/images/popup-planning/photo-a.jpg]].

There is no sale or giveaway. Make this clear in the campaign copy.
```

When answering, the Agent can retrieve a memory excerpt, then open the full note, source conversation, or image as needed to check details omitted from the summary. Reopening an image requires an accessible source file or link and image-reading support in the current model and tools.

### Write a Photographer Brief in a New Conversation

After the background memory job finishes, open a new conversation under the same Agent without reuploading images. Ask QwenPaw for a short message to the photographer, reminding them which look to use, especially the outfit, bag, and lighting.

QwenPaw uses the previously selected photo A. It recalls the green jacket, light-colored trousers, silver crossbody bag, and natural outdoor light, and puts them into a brief ready to forward.

![The new conversation's photographer brief reuses the selected outfit, bag, and lighting](https://img.alicdn.com/imgextra/i2/O1CN018kGUFEWRjnC4s7Ss_!!6000000000381-0-tps-2400-1354.jpg)

The new conversation also produces a social media announcement with the time, location, and booking details from the poster. The generated Markdown notes record the photo selection and poster discussion, with references to the original images and source conversations.

### Enable Image Memory in QwenPaw

For an Agent using the ReMe long-term memory backend, turn on **Include images in auto-memory** in memory settings. This switch is off by default and requires confirmed image-input and tool-calling support in the Agent's memory model. If image capability is unknown, confirm it in model settings first. A model temporarily selected for a chat does not change the memory model.

![Image-memory configuration: enable Auto-memory and Include images in auto-memory](https://img.alicdn.com/imgextra/i1/O1CN01lbs7HYzP5FC6Pn1y_!!6000000007790-2-tps-3160-1534.png)

Enable periodic auto-memory and choose an extraction interval. Share images and discuss them in chat, wait for the background task to finish and write its notes, then continue in a new conversation under the same Agent. Inspect the memory files to check the visual facts, reasons, and sources. See [long-term memory](/docs/memory) and [configuration](/docs/config) for the settings.

### How Does It Perform on Long Image Histories?

Can memory still find the right image details when the conversation history grows long? ReMe compared five methods on MemLens-256K. The charts below show the published LLM-Judge scores.

<div class="blog-figure-grid">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01y0PIU11haFUGGiIf0_!!6000000004293-55-tps-1000-520.svg" alt="MemLens-256K: LLM-Judge scores for five methods with Qwen3.6-35B-A3B" />
  <img src="https://img.alicdn.com/imgextra/i1/O1CN018cHcp11dv52RQTh1J_!!6000000003797-55-tps-1000-520.svg" alt="MemLens-256K: LLM-Judge scores for five methods with Qwen3.8-Max" />
</div>

_Charts from the [ReMe image memory article](https://reme.agentscope.io/en/blog_20261009)._

ReMe Image scores **53.44%** and **72.49%** on the two models, exceeding Full Context Image by **6.35** and **6.88 percentage points**, respectively.

Of the original 195 cases, six triggered model-provider content moderation in at least one method. All methods use the same filtered **189/195 cases**. This compares complete systems: ReMe can retrieve source conversations, and the Image configuration can reopen source images; OpenViking retrieval in this evaluation is restricted to memory. The results apply to that experimental setup. See the [ReMe evaluation notes](https://reme.agentscope.io/en/memlens_256k_evaluation) for settings, exclusions, and reproduction comparisons.

## 2. Memory Tags: Establish the Scope, Then Find the Details

Long-term memory also faces a different problem. Several projects have discussed budgets, release dates, and owners. When you ask, “What remains before launch?”, which set of records should the Agent search?

Keywords and semantic similarity can sometimes mix up records from different projects. Memory Tags marks the person, project, organization, or asset a note is mainly about, helping retrieval narrow its scope first. Text-only memories can use tags too.

![ReMe Memory Tags: derive an index from Markdown tags and search within candidate files](https://img.alicdn.com/imgextra/i1/O1CN01wDeKKV1Qz7WkSx4fp_!!6000000002046-55-tps-1200-620.svg)

_Chart from [ReMe Memory Tags](https://reme.agentscope.io/en/blog_20260920)._

### Let Each Memory Say What It Is Mainly About

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

### How Tags Participate in Retrieval

![Memory Tags pipeline: write tags, synchronize the index, and search within scope](https://img.alicdn.com/imgextra/i3/O1CN01PewzqI1EcsuQhRnH6_!!6000000000373-55-tps-1440-850.svg)

| Cue                    | Question it answers                               |
| ---------------------- | ------------------------------------------------- |
| Natural-language query | Which details am I looking for now?               |
| Memory Tag             | Which entities or projects should I search first? |
| Wikilink               | Which other records are related to this memory?   |

ReMe builds a bidirectional Tag Index from frontmatter, recording the files associated with each tag and the tags in each file. It updates the index as memories are created, changed, or deleted. Tags are stored in Markdown, so the index can be rebuilt from files.

With `Project_A` attached to a search, the Tag Index first selects relevant files. BM25 and optional vector retrieval then look for “What remains before launch?” within those files. Multiple tags match any supplied tag: `tags=["Project_A", "Project_B"]` searches records from either project. Searches without tags retain their existing behavior.

Tags constrain direct retrieval hits; Wikilink expansion may still list related notes outside that scope. Tags are retrieval cues rather than access controls.

### Generate and Use Tags in QwenPaw

Turn on **Generate memory tags** in the Agent's memory settings. This switch is off by default. When enabled, QwenPaw adds an entity-tagging step after Auto Memory saves a note, increasing model calls. Disabling generation leaves existing tags intact.

![Tag configuration: enable Generate memory tags separately](https://img.alicdn.com/imgextra/i4/O1CN01ml5EwQd3ZkL6NWXs_!!6000000003416-2-tps-3142-1526.png)

With memory search enabled, the Agent can discover entities and file counts through `memory_list_tags`, then pass `tags` to `memory_search`. You can also enter `/reme list_tags` in chat to inspect existing tags, or view `memory_tags` in a memory file's preview metadata.

Manual imports and edits do not automatically generate tags, but file watching synchronizes tags already present in a file to the Tag Index. See [ReMe Memory Tags](https://reme.agentscope.io/en/blog_20260920) for tag conventions and index maintenance.

### Browse from a Tag to the Original Note

In **Files → Tags**, you can see indexed tags and their associated file counts. Select a tag to browse its matching memory files.

![The Tags tab in Files lists indexed tags and their associated file counts](https://img.alicdn.com/imgextra/i3/O1CN01aOf17D5AMdG7mt2s_!!6000000006319-2-tps-3836-1858.png)

Opening a matching memory displays the note preview on the right, including its tags, source-conversation reference, and body. You can check the saved facts and context there. Tag browsing relies on the existing index; files that have not been indexed may be absent from the list.

![Select a tag and open a matching memory to inspect its tags, source conversation, and note body](https://img.alicdn.com/imgextra/i2/O1CN01p2M4uxVRrDE7mt2u_!!6000000002688-2-tps-3836-1860.png)
