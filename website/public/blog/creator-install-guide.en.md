---
title: "QwenPaw Creator: From Installation to Your First Creation"
date: 2026-08-19
author: QwenPaw Team
tags: [QwenPaw Creator, Video Creation, Installation Guide, Agentic Workflow]
cover: https://img.alicdn.com/imgextra/i3/O1CN01BrV3VrZ2axF5qXky_!!6000000006553-2-tps-2880-1620.png
excerpt: "Explore the core capabilities of QwenPaw Creator, then install, configure, and open it for the first time in seven steps."
---

# QwenPaw Creator: From Installation to Your First Creation

> **QwenPaw Creator** is an agentic video creation platform. Turn a single idea into a short-form drama, or edit existing footage into a finished video, with a team of agents collaborating throughout the process while every key decision remains in your hands.
>
> This guide introduces Creator's core capabilities and walks you through installation and first launch in seven steps. For instructions on installing QwenPaw itself, visit the [QwenPaw website](https://qwenpaw.agentscope.io/).

![QwenPaw Creator product demo](https://cloud.video.taobao.com/vod/QrQ22smEYzVP5QtchnWO6ix6caO84v72wVKmqDmRoDY.mp4)

_QwenPaw Creator product demo: from an initial idea to the video creation workflow._

The red boxes and numbered circles in the screenshots (1, 2, 3, and so on) mark the controls to use in each step.

---

## What Is QwenPaw Creator?

In Creator, you define the goal, provide source material, and guide the creative direction. A team of agents handles planning, generation, editing, and composition, returning control to you at every important decision point.

### Core Capabilities

- **Agents throughout the workflow**: Specialist agents for writing, directing, visual development, motion design, editing, and more collaborate according to the current project state instead of stopping after a one-off generation.
- **Two creation paths**: Turn one idea into a short-form drama (script -> storyboard -> reference-to-video -> composition), or transform existing footage into a finished video (VLM/ASR media understanding -> editing plan -> human-agent refinement -> composition).
- **Selection becomes context**: Select a point in time, clip, subtitle, effect, transition, asset, or even page text and ask an agent to revise it precisely. You can also make detailed edits manually.
- **You stay in control**: Every agent change enters a decision tray where you can keep or revert it. Before a paid generation model is called, Creator presents a confirmation card with the estimated cost.

### Native Qwen-MM-Plugins Integration

Creator includes native integration with [Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins), a plugin suite that gives any agent built-in multimodal capabilities:

- **core (foundational vision)**: Dynamic-resolution understanding of images, videos, documents, and 3D models, including OCR, object grounding, segmentation, automatic speech recognition (ASR), visual question answering, and web search.
- **video-memory (long-video memory)**: Hierarchical graph memory for understanding, retrieving, and answering questions about very long video assets.
- **video-edit (video editing)**: Editing workflows and image, video, and audio generation, with quality controls such as black-frame detection, loudness checks, and review gates.
- **edu-agent (educational video)**: Converts math and science problems or images into step-by-step explanation videos or interactive pages.

---

## Before You Begin: Open QwenPaw

Install QwenPaw by following the [Quick Start guide](https://qwenpaw.agentscope.io/#qwenpaw-quickstart). QwenPaw supports pip, the one-click script, Docker, cloud deployment, and desktop installation. Then start it from a terminal. The console opens automatically in your browser:

```bash
# Start QwenPaw (listens on 127.0.0.1:8088 by default)
qwenpaw app

# If the browser does not open automatically, open the URL manually
open http://127.0.0.1:8088
```

> This guide uses the default local mode. No account registration is required on first launch.

---

## Step 1: Open the Main Interface

After QwenPaw starts, the console opens automatically on the Chat page.

![Step 1: QwenPaw main interface](https://img.alicdn.com/imgextra/i2/O1CN01fvYmw40BXLL5qXky_!!6000000007717-2-tps-2880-1620.png)

_Red marker 1: the Apps entry in the left navigation._

---

## Step 2: Open the Apps Center

Select **Apps** in the left navigation (red marker 1) to open the Apps center.

![Step 2: Select Apps in the left navigation](https://img.alicdn.com/imgextra/i2/O1CN011STeolhCvZJ5qXky_!!6000000000214-2-tps-2880-1620.png)

_Red marker 1: the Apps menu item. If no apps have been installed yet, the page displays an empty-state guide._

---

## Step 3: Select Creator and Choose Install

Open the **Official Apps** tab, find the **QwenPaw Creator** card, and select **Install** in the lower-right corner of the card (marker 1).

![Step 3: Creator card on the Official Apps tab](https://img.alicdn.com/imgextra/i4/O1CN01MFQj17c3uGC5qXky_!!6000000001609-2-tps-2880-1620.png)

_Red marker 1: the Creator card and its Install button._

---

## Step 4: Wait for Installation to Finish

After you select Install, the button immediately changes to **Installing...**. Wait a moment for the installation to complete.

![Step 4: Creator installation in progress](https://img.alicdn.com/imgextra/i4/O1CN01vMj1GXuwbeD5qXky_!!6000000000654-2-tps-2880-1620.png)

_Red marker 1: the Install button in its Installing state._

---

## Step 5: Confirm Successful Installation

When installation finishes, a green check notification at the top of the page confirms **Installed: QwenPaw Creator**.

![Step 5: Installation success notification](https://img.alicdn.com/imgextra/i3/O1CN01khWNWYm8iTG5qXky_!!6000000004768-2-tps-2880-1620.png)

_Red marker 1: the installation success toast._

---

## Step 6: Find Creator Under My Apps

Return to the **My Apps** tab. The Creator card is now visible with an Installed badge.

![Step 6: Creator under My Apps](https://img.alicdn.com/imgextra/i1/O1CN01L9fm1RpQJZJ5qXky_!!6000000004775-2-tps-2880-1620.png)

_Red marker 1: the Creator app card with its green Installed badge._

---

## Step 7: Choose Open and Start Creating

Select **Open** on the Creator card (marker 1) to enter the Creator workspace. Enter your idea, choose a model and aspect ratio, and start creating.

![Step 7: Open Creator](https://img.alicdn.com/imgextra/i3/O1CN01BrV3VrZ2axF5qXky_!!6000000006553-2-tps-2880-1620.png)

_Red marker 1: the Open button, with the Creator workspace shown below it._

> Before using Creator for the first time, you need to configure a model. Select Settings in the upper-right corner of the home page and follow the setup guide. You can start generating as soon as configuration is complete.
