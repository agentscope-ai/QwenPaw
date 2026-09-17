---
title: "Play with QwenPaw-Pet"
date: 2026-07-01
tags: [Plugin, DesktopPet, PixelPets, SkillCreation]
excerpt: "QwenPaw introduced the plugin system in version 1.1.3 and the pet system in version 1.1.8. I was not a big fan of the official pet templates, so I had never configured them. Personally, I prefer pixel-style pet designs."
related:
  heading: "Related Capabilities"
  items:
    - label: "Plugin"
      name: "QwenPaw Pet"
      href: "https://platform.agentscope.io/plugins/qwenpaw-pet"
      description: "The official desktop pet plugin that forwards QwenPaw backend lifecycle events to QwenPaw Pet Desktop."
    - label: "Built-in Skill"
      name: "make-skill"
      href: "https://qwenpaw.agentscope.io/docs/skills#Create-from-current-session-via-make-skill-Beta"
      description: "Turns the workflow and experience from the current session into a reusable Skill. In this post, it is used to package the desktop-pet creation workflow as a reusable Skill."
---

# Play with QwenPaw-Pet

QwenPaw introduced the plugin system in version 1.1.3 and the pet system in version 1.1.8. I was not a big fan of the official pet templates, so I had never configured them. Personally, I prefer pixel-style pet designs.

This time I spent some time letting QwenPaw generate a batch of pet templates by itself. Using `make-skill` and `subagents`, the pet generation process can be autonomously distilled, summarized, and reused, which significantly accelerates the workflow.

## TL;DR Workflow

- QwenPaw version: v1.12

  - Note: The pet generation workflow in QwenPaw 2.0 may differ due to plugin system updates.

- Model: Qwen3.7-Max

Overall process:

- Create a dedicated **Pet Master** Agent.
- Iteratively tune it based on personal preferences until the first satisfying pet generation pipeline is achieved.
- Use **Make-skill** to distill historical generation experience into a reusable `make-pet` skill.
- Use the new skill + `subagents` for batch generation to build a pet army.

## 1. Pet Master Initialization

### 1.1 Preparation

In the official plugin store, download the QwenPaw Pet plugin. ![image](https://img.alicdn.com/imgextra/i1/O1CN01niHx461stRq372qrr_!!6000000005824-2-tps-2335-330.png)

Make sure the plugin is downloaded and enabled correctly.

For easier management, create a new Agent named **Pet Master** with the following skills:

- **Make-skill**: Used to turn workflows into reusable skills, preparing for later large-scale pet generation.

  - Also install things like Spawn-subagent along the way.

- QA-source-index: Helps QwenPaw understand how its own pet system is designed.

  - You can also use the `qwenpaw-docs-zh` skill from the QwenPaw skill marketplace.

Note:

- If you need to collect pet assets, you can also add `tavily mcp` or browser-related skills.
- If you need to compare image assets, enable `view_image` and use a model with multimodal image understanding (for example, qwen3.6-plus).

### 1.2 Initialization Setup

Through conversation, provide background knowledge to the new Agent:

![image](https://img.alicdn.com/imgextra/i2/O1CN01tQwcZE1XAT0cTWILz_!!6000000002883-2-tps-1662-932.png)

Start a new chat to help QwenPaw understand its own pet system. You can see that after asking questions, QwenPaw invokes the **QA-source-index** skill and starts understanding the pet plugin system.

This step provides necessary context for creating our own Agent later.

## ![image](https://img.alicdn.com/imgextra/i4/O1CN018HkxEd1VI8PNNKbIx_!!6000000002629-2-tps-1654-620.png)

## 2. First Pet Creation

After the first round of conversation, QwenPaw understands its pet mechanism. Now we can ask it to create a pet.

![image](https://img.alicdn.com/imgextra/i4/O1CN01MoQRjb1E1mnpDFfbP_!!6000000000292-2-tps-1684-598.png)

![image](https://img.alicdn.com/imgextra/i1/O1CN015Nhs1a1PBMrV0h8vG_!!6000000001802-2-tps-1022-1220.png)

See the image below. QwenPaw completed the task in one shot, but there were still a few minor issues we could continue to tune:

- The pet name was not confirmed.
- It did not match my personal taste. I wanted it to be closer to Charmander and more aligned with Pokemon style.
- The movement and expressions were somewhat stiff; I wanted finer-grained actions.

![image](https://img.alicdn.com/imgextra/i3/O1CN01L7of8y1Oo0f8WspAn_!!6000000001751-2-tps-1490-230.png)

After nearly one round of iterative adjustments, Charmander looked much closer to its Pokemon appearance.

![image](https://img.alicdn.com/imgextra/i4/O1CN01TSgZuS1dNe6HMC81Z_!!6000000003724-2-tps-1536-268.png)

### Review

The whole process succeeded in one go, but there were still details to improve, such as:

- The Agent created many temporary scripts for drawing and validation.
- The model failed in the first few script-writing attempts, causing significant token waste.

Final result: for this creation, we spent about ~50K tokens and went through around 120 rounds of dialogue + tool calls.

![image](https://img.alicdn.com/imgextra/i2/O1CN01DIro7M1oig3ravFi5_!!6000000005259-2-tps-1986-406.png)

## 3. Make-skill: Pet-maker

In version 1.11, QwenPaw introduced `make-skill`, which can distill user dialogue history and tool invocations into a reusable skill. With this capability, we turned pet creation into a reusable skill that includes my personalized preferences and habits, as well as reusable execution scripts.

In the first pet-creation chat, use `/make-skill` and name it `pet-maker`. This is also the skill name we will invoke for future pet creation.

### 3.1 Distilling the Pet-maker Skill

![image](https://img.alicdn.com/imgextra/i1/O1CN01q8sMj6224HkgucJ30_!!6000000007066-2-tps-1734-510.png)

![image](https://img.alicdn.com/imgextra/i4/O1CN01qrdErs1YS9vO2uJlf_!!6000000003057-2-tps-1716-840.png)

Choose Approve. You can see that besides `skill.md`, `/make-skill` also creates `.json` files for automation, and includes `generate_pet.py` as an executable script.

After distillation, the `\pet-maker` skill exists in the **Pet Master** workspace. We can reuse this skill in new chats and try creating more pets.

### 3.2 Example: Bulbasaur

![image](https://img.alicdn.com/imgextra/i2/O1CN01Yrai4D22z4reHJLHS_!!6000000007190-2-tps-1680-574.png)

![image](https://img.alicdn.com/imgextra/i2/O1CN019n8TCb1Jm6wS6ZUHE_!!6000000001070-2-tps-1444-242.png)

Start a new chat. This time we want to create Bulbasaur. The process became much easier: with one simple invocation, a pet in a similar style was successfully created.

- Context and tool-calling frequency were both significantly reduced, and more pets in similar style can be generated at scale.

![image](https://img.alicdn.com/imgextra/i2/O1CN01mx6hSg1SRnvHcdZKY_!!6000000002244-2-tps-1902-352.png)

### 3.3 Example: Batch Creation

With the `subagents` tool, multiple pets can be created in parallel:

![image](https://img.alicdn.com/imgextra/i1/O1CN01Bqzx701UvEbZIRRQE_!!6000000002579-2-tps-1692-408.png)

![image](https://img.alicdn.com/imgextra/i1/O1CN015Rh7GX1sfhxMSotJS_!!6000000005794-2-tps-538-196.png)

At this point, the main Agent only needs to monitor the progress of three tasks. Verification shows the main Agent even consumed fewer tokens:

![image](https://img.alicdn.com/imgextra/i1/O1CN01SYxIwc1J6QtqPTjSu_!!6000000000979-2-tps-1922-460.png)

![image](https://img.alicdn.com/imgextra/i2/O1CN010opvm71Nu8LIl2pbE_!!6000000001629-2-tps-1592-1012.png)

## 4. Summary

This article demonstrates how to use QwenPaw to create pets, and how to leverage Make-skill to distill the workflow so that large-scale generation of pixel-style Pokemon pets becomes possible afterward. Going forward, the author plans to continue with:

- Adapting to the 2.0 pet system.
- Using QwenPaw to self-update pet interactions and enrich pet system capabilities.

Welcome to keep discussing the pet system ✌️
