---
title: "QwenPaw Multimodal Memory: Put Images to Work in Your Next Conversation"
date: 2026-10-27
author: QwenPaw Team
tags: [Multimodal Memory, ReMe, Image Memory, Memory as File]
cover: https://img.alicdn.com/imgextra/i2/O1CN01qVVKgkcRb5D3OTaP_!!6000000005716-2-tps-1672-941.png
excerpt: "From choosing a campaign photo to writing a photographer brief in a new conversation, see how QwenPaw saves images, discussion, and decisions as searchable memories with sources."
---

# QwenPaw Multimodal Memory: Put Images to Work in Your Next Conversation

Today, you compare photos with QwenPaw, choose a campaign image, and agree on the copy direction. A few days later, you open a new conversation to write a photographer brief—then upload the photos and explain the choice all over again.

A memory that only says “we chose photo A” leaves out the outfit, the bag, and why that photo suited the event. To help with a later task, memory needs to preserve both the image details and the decisions made around them.

Building on its [file-based long-term memory](/blog/qwenpaw-long-term-memory), QwenPaw integrates [ReMe](https://github.com/agentscope-ai/ReMe)'s multimodal memory. When enabled, Auto Memory reads image-and-text sessions in the background, writes visual facts, user constraints, and reasons into Markdown notes, and keeps references to the original images and conversations.

Follow a clothing brand's weekend pop-up from selecting a photo to saving the context and writing a brief in a new conversation.

![Images and discussion within a session become memories, with links back to their sources](https://img.alicdn.com/imgextra/i4/O1CN01FZjxTO1kcwfMP8mPI_!!6000000004705-55-tps-1200-640.svg)

## Start with a Weekend Pop-up

Suppose you are planning a weekend pop-up for a clothing brand. You share two model photos with QwenPaw and ask for a campaign that feels like heading out for a weekend walk.

QwenPaw recommends photo A, taken on the street, as the better fit. Photo B has more of an office look and is kept for other uses. After confirming the choice, the user shares an event poster and a venue photo to discuss the copy and arrangements, making clear that there will be no sale or giveaway.

![The first image discussion compares two model photos and selects the campaign image](https://img.alicdn.com/imgextra/i2/O1CN01wkoJ8tirBGL4s7Ss_!!6000000004233-0-tps-2400-1354.jpg)

## Remember the Image and the Discussion Around It

Saving only the text might preserve “we chose A” without recording what the model is wearing or which bag she carries. Describing the image separately could lose the user's reason for choosing it.

With image input enabled, ReMe Auto Memory sends conversation text and images together to a vision model. It preserves message order, the relative order of text and images within each message, and the speaker and timestamp. The model extracts facts and uses memory tools to create or update Markdown notes.

For this event, the useful information includes:

- **Image content:** the outfit, bag, and lighting, plus the time, location, and booking details on the poster.
- **Explicit decisions:** use photo A for this campaign and keep photo B for other uses.
- **User constraints:** the campaign should feel like a weekend walk; there is no sale or giveaway.
- **Reason for the choice:** photo A's street setting and casual outfit better fit the event theme.

These details become searchable text and enter the existing keyword and optional semantic retrieval workflow. A later text question can therefore find facts that originally appeared in an image.

The model may miss or misread image details, so notes need references to the original images for later checks.

## Reopen the Original Image to Check Details

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

## Write a Photographer Brief in a New Conversation

After the background memory job finishes, open a new conversation under the same Agent without reuploading images. Ask QwenPaw for a short message to the photographer, reminding them which look to use, especially the outfit, bag, and lighting.

QwenPaw uses the previously selected photo A. It recalls the green jacket, light-colored trousers, silver crossbody bag, and natural outdoor light, and puts them into a brief ready to forward.

![The new conversation's photographer brief reuses the selected outfit, bag, and lighting](https://img.alicdn.com/imgextra/i2/O1CN018kGUFEWRjnC4s7Ss_!!6000000000381-0-tps-2400-1354.jpg)

The new conversation also produces a social media announcement with the time, location, and booking details from the poster. The generated Markdown notes record the photo selection and poster discussion, with references to the original images and source conversations.

## Enable Image Memory in QwenPaw

For an Agent using the ReMe long-term memory backend, turn on **Include images in auto-memory** in memory settings. This switch is off by default and requires confirmed image-input and tool-calling support in the Agent's memory model. If image capability is unknown, confirm it in model settings first. A model temporarily selected for a chat does not change the memory model.

![Image-memory configuration: enable Auto-memory and Include images in auto-memory](https://img.alicdn.com/imgextra/i1/O1CN01lbs7HYzP5FC6Pn1y_!!6000000007790-2-tps-3160-1534.png)

Enable periodic auto-memory and choose an extraction interval. Share images and discuss them in chat, wait for the background task to finish and write its notes, then continue in a new conversation under the same Agent. Inspect the memory files to check the visual facts, reasons, and sources. See [long-term memory](/docs/memory) and [configuration](/docs/config) for the settings.

## How Does It Perform on Long Image Histories?

Can memory still find the right image details when the conversation history grows long? ReMe compared five methods on MemLens-256K. The charts below show the published LLM-Judge scores.

<div class="blog-figure-grid">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01y0PIU11haFUGGiIf0_!!6000000004293-55-tps-1000-520.svg" alt="MemLens-256K: LLM-Judge scores for five methods with Qwen3.6-35B-A3B" />
  <img src="https://img.alicdn.com/imgextra/i1/O1CN018cHcp11dv52RQTh1J_!!6000000003797-55-tps-1000-520.svg" alt="MemLens-256K: LLM-Judge scores for five methods with Qwen3.8-Max" />
</div>

_Charts from the [ReMe image memory article](https://reme.agentscope.io/en/blog_20261009)._

ReMe Image scores **53.44%** and **72.49%** on the two models, exceeding Full Context Image by **6.35** and **6.88 percentage points**, respectively.

Of the original 195 cases, six triggered model-provider content moderation in at least one method. All methods use the same filtered **189/195 cases**. This compares complete systems: ReMe can retrieve source conversations, and the Image configuration can reopen source images; OpenViking retrieval in this evaluation is restricted to memory. The results apply to that experimental setup. See the [ReMe evaluation notes](https://reme.agentscope.io/en/memlens_256k_evaluation) for settings, exclusions, and reproduction comparisons.

## Connect the Event's Memory from Start to Finish

1. You upload photos and a poster, explaining the theme, choices, and constraints.
2. Auto Memory processes the images and discussion together into Markdown notes in the background.
3. The notes retain image and conversation references for checking details omitted from the summary.
4. A new conversation under the same Agent retrieves those memories to continue writing the photographer brief or campaign copy.

What carries forward is more than “we chose A”: it includes the visible details, the decision, and a way to check the sources. You can open the notes to inspect and correct what was saved.

To narrow retrieval by project or person, continue with [Memory Tags](/blog/qwenpaw-memory-tags). For the full recording, consolidation, and retrieval workflow, see [long-term memory](/blog/qwenpaw-long-term-memory).
