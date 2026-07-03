---
title: "Play with QwenPaw-Pet"
date: 2026-07-01
tags: [pet, plugin, make-skill]
excerpt: "QwenPaw introduced the plugin system in version 1.1.3 and the pet system in version 1.1.8. I was not a big fan of the official pet templates, so I had never configured them. Personally, I prefer pixel-style pet designs."
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

In the official plugin store, download the QwenPaw Pet plugin. ![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/03e71187-8a0c-48ba-a5bd-bd93de36239b.png)

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

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/025aa983-5104-40cc-ac79-7605feecf47a.png)

Start a new chat to help QwenPaw understand its own pet system. You can see that after asking questions, QwenPaw invokes the **QA-source-index** skill and starts understanding the pet plugin system.

This step provides necessary context for creating our own Agent later.

## ![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/a5f21248-0990-44b2-b5ac-5ec0c9999008.png)

## 2. First Pet Creation

After the first round of conversation, QwenPaw understands its pet mechanism. Now we can ask it to create a pet.

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/3a843792-db87-45a5-bc86-5552ed57c98a.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/0aa0e9ca-3ed4-4c18-a645-aa0f33e653ee.png)

See the image below. QwenPaw completed the task in one shot, but there were still a few minor issues we could continue to tune:

- The pet name was not confirmed.
- It did not match my personal taste. I wanted it to be closer to Charmander and more aligned with Pokemon style.
- The movement and expressions were somewhat stiff; I wanted finer-grained actions.

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/da1269e1-3562-4114-81c2-2c98887bc895.png)

After nearly one round of iterative adjustments, Charmander looked much closer to its Pokemon appearance.

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/3e9f4ad1-e6c9-4c7c-a19f-109ba1e43634.png)

### Review

The whole process succeeded in one go, but there were still details to improve, such as:

- The Agent created many temporary scripts for drawing and validation.
- The model failed in the first few script-writing attempts, causing significant token waste.

Final result: for this creation, we spent about ~50K tokens and went through around 120 rounds of dialogue + tool calls.

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/6634ca6d-4275-4380-989c-7f02e58cdb1e.png)

## 3. Make-skill: Pet-maker

In version 1.11, QwenPaw introduced `make-skill`, which can distill user dialogue history and tool invocations into a reusable skill. With this capability, we turned pet creation into a reusable skill that includes my personalized preferences and habits, as well as reusable execution scripts.

In the first pet-creation chat, use `/make-skill` and name it `pet-maker`. This is also the skill name we will invoke for future pet creation.

### 3.1 Distilling the Pet-maker Skill

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/33de88a0-4b16-4d89-b390-040316983fcc.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/bb74d4af-4236-49ef-9306-1f3534a247bb.png)

Choose Approve. You can see that besides `skill.md`, `/make-skill` also creates `.json` files for automation, and includes `generate_pet.py` as an executable script.

After distillation, the `\pet-maker` skill exists in the **Pet Master** workspace. We can reuse this skill in new chats and try creating more pets.

### 3.2 Example: Bulbasaur

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/18b89e2b-9a94-4652-bc8b-674bd8ec3204.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/e4b928f9-0b2e-4840-af7d-eaa180982805.png)

Start a new chat. This time we want to create Bulbasaur. The process became much easier: with one simple invocation, a pet in a similar style was successfully created.

- Context and tool-calling frequency were both significantly reduced, and more pets in similar style can be generated at scale.

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/1a3760da-3be2-49ae-a434-0c67dcab574e.png)

### 3.3 Example: Batch Creation

With the `subagents` tool, multiple pets can be created in parallel:

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/c7f78719-f6e6-4ea3-be85-6efd66146345.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/53d0ecf6-1027-483b-b3ff-e6699aef119f.png)

At this point, the main Agent only needs to monitor the progress of three tasks. Verification shows the main Agent even consumed fewer tokens:

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/3bec5acd-d9a6-4396-9a41-bb62dd3f253a.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/7538a924-a647-4a19-8203-2d6283008146.png)

## 4. Summary

This article demonstrates how to use QwenPaw to create pets, and how to leverage Make-skill to distill the workflow so that large-scale generation of pixel-style Pokemon pets becomes possible afterward. Going forward, the author plans to continue with:

- Adapting to the 2.0 pet system.
- Using QwenPaw to self-update pet interactions and enrich pet system capabilities.

Welcome to keep discussing the pet system ✌️
