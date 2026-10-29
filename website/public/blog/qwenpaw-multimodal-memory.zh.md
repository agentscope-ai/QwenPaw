---
title: "QwenPaw 记忆更新：多模态记忆与 Memory Tags"
date: 2026-10-27
author: QwenPaw Team
tags: [多模态记忆, ReMe, 记忆标签, Memory as File]
cover: https://img.alicdn.com/imgextra/i2/O1CN01qVVKgkcRb5D3OTaP_!!6000000005716-2-tps-1672-941.png
excerpt: "图文会话中的事实与决策怎样留到下次使用？积累的记忆怎样按项目找回？这篇文章分别介绍 QwenPaw 的多模态记忆和 Memory Tags，以及它们在记录、来源回查和检索中的作用。"
---

# QwenPaw 记忆更新：多模态记忆与 Memory Tags

今天，你和 QwenPaw 看图讨论了设计方案。几天后，换个聊天继续写文案，却又要上传图片、解释之前的选择。与此同时，几个项目都在讨论预算和排期，想找回某次决策，还得从大量记录里翻找。在[文件化长期记忆](./qwenpaw-long-term-memory)的基础上，QwenPaw 接入了 [ReMe](https://github.com/agentscope-ai/ReMe) 的两项能力，让它能记住图文会话，也能按项目、人物等线索找回记忆。

**多模态记忆**面向包含图片和文字交互的会话（session）。启用后，Auto Memory 会在后台阅读会话中的图片和文字，把图像细节、用户的选择、约束和理由写成笔记。选中了哪张照片、为什么选它、海报上有哪些活动信息，都可以留到下次使用。笔记还会引用原图和源会话，方便核对。换个聊天继续任务时，Agent 可以检索这些笔记，你就不用反复解释背景。

**Memory Tags**解决的是记忆积累后的定位问题。同样一句“上线前还有什么要确认”，可能对应不同项目的记录。为笔记补充项目、人物或组织等实体标签后，检索可以先用这些线索确定候选文件，再查找具体内容。标签也适用于纯文字记忆，不依赖图片输入。

两项能力都沿用 Markdown 文件保存记忆，你可以直接查看和编辑。

![QwenPaw 整理图文会话记忆与标签笔记](https://img.alicdn.com/imgextra/i2/O1CN01qVVKgkcRb5D3OTaP_!!6000000005716-2-tps-1672-941.png)

## 一、多模态记忆：让图文会话中的信息在下次任务中继续可用

![图文会话中的图片与讨论进入记忆，并保留回看来源的入口](https://img.alicdn.com/imgextra/i4/O1CN01FZjxTO1kcwfMP8mPI_!!6000000004705-55-tps-1200-640.svg)

### 从一次周末快闪活动说起

假设你正在筹备一场服装品牌的周末快闪活动。你把两张模特照片发给 QwenPaw，希望宣传看起来像周末出门散步。

QwenPaw 推荐街头拍摄的照片 A，认为它更符合这次活动；另一张偏通勤风格的照片 B 留作其他用途。用户确认后，继续发来活动海报和场地照片，讨论宣传文案与现场安排，并明确这次没有折扣或赠品。

![首次图文讨论：比较两张模特照片，选择活动主视觉](https://img.alicdn.com/imgextra/i2/O1CN01wkoJ8tirBGL4s7Ss_!!6000000004233-0-tps-2400-1354.jpg)

### 记住图片，也记住围绕图片的讨论

如果只保存文字，记忆可能知道“选了 A”，却不知道照片里的人穿什么、背什么包。若只给图片生成一段独立描述，又容易遗漏用户为什么选择它。

ReMe 的 Auto Memory 在启用图像输入后，把对话文字与图片一起交给视觉模型，保留消息顺序、消息内的图文顺序，以及发送者和时间。模型据此提取事实，并通过记忆工具创建或更新 Markdown 笔记。

对这次活动筹备来说，需要一起留下的包括：

- **图片内容**：模特的穿搭、包和拍摄光线，以及海报上的时间、地点和预约方式。
- **明确决策**：照片 A 用作本次活动主视觉，照片 B 留作其他用途。
- **用户约束**：宣传要像周末散步，活动没有折扣或赠品。
- **选择理由**：照片 A 的街头场景和休闲穿搭更符合活动主题。

这些信息写成文字后，可以沿用已有的关键词和可选语义检索流程。以后用文字提问，也可以检索图片里记录下来的细节。

模型可能漏掉或误读图片里的信息，笔记需要保留原图来源，方便之后核对。

### 需要核对时，还能回看原图

今天选定宣传照片，明天可能要确认包的款式，而当时的摘要未必记下了这一点。

ReMe 会为图像保留来源：Base64 图像的原始字节默认保存到 `session/images/<session_id>/`，HTTP(S) 图像保留原地址。实际目录由 `session_dir` 控制，QwenPaw 默认使用 `mem_session/`。记忆提取提示要求在相关视觉事实旁引用准确来源，笔记的 `source_images` 汇总关联图像，`source_conversation` 则连接源会话。后续更新会合并新的图像来源并保留已有链接。

下面用简化后的路径和文字展示笔记格式：

```markdown
---
name: 周末快闪活动主视觉
description: 主视觉选择与宣传文案要求。
source_conversation: "[[mem_session/dialog/popup-planning.jsonl]]"
source_images:
  - "[[mem_session/images/popup-planning/photo-a.jpg]]"
---

本次活动选用照片 A，宣传主题是周末出门散步。
模特的穿搭、银色斜挎包和街头自然光见原图：
[[mem_session/images/popup-planning/photo-a.jpg]]。

活动没有折扣或赠品，宣传文案需要说清楚这一点。
```

回答时，Agent 可以先检索记忆片段，再按需打开完整笔记、源会话或原图，核对摘要里没有记录的细节。回看原图需要来源文件或链接仍可访问，且当前模型和工具支持图像读取。

### 换个聊天，继续写摄影方案

等后台记忆任务完成后，在同一个 Agent 下新建聊天，不重新上传图片，再请 QwenPaw 写一份可以发给摄影师的简短说明，提醒对方使用哪套造型，尤其是服装、包和光线。

QwenPaw 沿用了此前选定的照片 A，找回了绿色外套、浅色长裤、银色斜挎包和户外自然光等细节，整理成可以直接转发的摄影 brief。

![新聊天的摄影 brief：沿用之前选定的穿搭、包和光线](https://img.alicdn.com/imgextra/i2/O1CN018kGUFEWRjnC4s7Ss_!!6000000000381-0-tps-2400-1354.jpg)

新聊天还生成了社交平台预告，带上之前海报中的时间、地点和预约信息。查看生成的 Markdown 笔记，可以找到主视觉选择、海报讨论以及对应的原图和源会话引用。

### 在 QwenPaw 中启用图片记忆

在使用 ReMe 长期记忆后端的 Agent 记忆设置中，打开**在自动记忆中包含图片**。该开关默认关闭，要求 Agent 的记忆模型已确认支持图片输入与工具调用。模型能力未知时，需要先在模型设置中确认图片支持；聊天中临时选择的模型不会改变记忆模型。

![图片记忆配置：启用 Auto-memory，并打开 Include images in auto-memory](https://img.alicdn.com/imgextra/i1/O1CN01lbs7HYzP5FC6Pn1y_!!6000000007790-2-tps-3160-1534.png)

启用定期自动记忆并设置提取间隔后，在聊天中发送图片并展开讨论，等后台任务完成、笔记生成，再在同一 Agent 的新聊天里继续提问。你可以查看记忆文件，核对视觉事实、选择理由和来源是否保存。具体设置见[长期记忆文档](/docs/memory)和[配置说明](/docs/config)。

### 长期图文问答中，效果如何？

如果会话历史变得很长，还能找对图像里的信息吗？ReMe 用 MemLens-256K 比较了五种方法，以下是官方公布的 LLM-Judge 得分。

<div class="blog-figure-grid">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01y0PIU11haFUGGiIf0_!!6000000004293-55-tps-1000-520.svg" alt="MemLens-256K：Qwen3.6-35B-A3B 上五种方法的 LLM-Judge 得分" />
  <img src="https://img.alicdn.com/imgextra/i1/O1CN018cHcp11dv52RQTh1J_!!6000000003797-55-tps-1000-520.svg" alt="MemLens-256K：Qwen3.8-Max 上五种方法的 LLM-Judge 得分" />
</div>

_图源：[ReMe 图像记忆博客](https://reme.agentscope.io/en/blog_20261009)。_

ReMe Image 在两个模型上的得分分别为 **53.44%** 和 **72.49%**，相对 Full Context Image 分别提高 **6.35** 和 **6.88 个百分点**。

原题集共 195 题，其中 6 题在至少一种方法中触发模型提供方内容审查，所有方法统一使用筛选后的 **189/195 题**。这是完整系统的比较：ReMe 可以检索源会话，Image 配置可以回看源图；本次评测中的 OpenViking 检索范围限定为 memory。结果适用于该实验设置。更多配置、排除规则与复现比较见 [ReMe 评测说明](https://reme.agentscope.io/en/memlens_256k_evaluation)。

## 二、Memory Tags：先确定范围，再检索细节

长期记忆还会遇到另一类问题：几个项目都讨论过预算、上线时间和负责人，现在问“上线前还要确认什么”，该从哪一组记录里找？

只靠关键词和语义相似度，有时会把不同项目的记录混在一起。Memory Tags 用标签标记笔记主要涉及的人、项目、组织或资产，帮助检索先找对范围。纯文字记忆也可以使用标签。

![ReMe Memory Tags：从 Markdown 标签建立索引，在候选文件范围内检索](https://img.alicdn.com/imgextra/i1/O1CN01wDeKKV1Qz7WkSx4fp_!!6000000002046-55-tps-1200-620.svg)

_图源：[ReMe Memory Tags](https://reme.agentscope.io/en/blog_20260920)。_

### 让每份记忆说明它主要关于什么

标签直接保存在 Markdown 的 YAML frontmatter 中。例如，一份项目上线笔记可以这样标记：

```markdown
---
name: 项目 A 上线清单
description: 上线窗口、回滚条件和客户通知安排。
memory_tags:
  - Project_A
---

项目 A 计划周四晚间上线。上线前完成回归测试，
并由负责人确认客户通知。错误率超过约定阈值时回滚。
```

项目、人和组织通常会在多次对话中反复出现，适合用来标记记忆。“工作”“重要”“会议”等宽泛主题则容易覆盖太多文件，难以缩小范围。通常标记笔记主要涉及的实体就够了；同时涉及几个实体时，可以使用多个标签。

标签与目录结构相互独立。一份会议记录可以同时标记项目和负责人，文件仍保存在原来的位置。你可以直接查看、编辑标签，也可以逐步统一同一实体的命名。

### 标签如何参与检索

![Memory Tags pipeline：标签写入、索引同步与按范围检索](https://img.alicdn.com/imgextra/i3/O1CN01PewzqI1EcsuQhRnH6_!!6000000000373-55-tps-1440-850.svg)

| 线索           | 回答的问题                     |
| -------------- | ------------------------------ |
| 自然语言 query | 现在想找什么细节？             |
| Memory Tag     | 应该先查哪些实体或项目的记忆？ |
| Wikilink       | 这份记忆还与哪些记录相关？     |

ReMe 根据 frontmatter 建立双向 Tag Index，记录每个标签关联的文件，以及每份文件包含的标签。创建、修改和删除记忆时，索引随之更新。标签保存在 Markdown 中，索引可以从文件重建。

当搜索带上 `Project_A`，Tag Index 先筛出相关文件，BM25 与可选向量检索再在这些文件中查找“上线前还要确认什么”。多个标签按“匹配任意一个”取候选集合，例如 `tags=["Project_A", "Project_B"]` 会搜索两个项目的记录；不传标签时仍按原有方式搜索。

标签约束直接检索命中，Wikilink 展开仍可能列出标签范围外的相关笔记。因此，标签是检索线索，不能作为权限隔离。

### 在 QwenPaw 中生成和使用标签

在 Agent 的记忆设置中打开**生成记忆标签**。该开关默认关闭；开启后，QwenPaw 会在 Auto Memory 保存笔记后追加实体标签生成步骤，因此会增加模型调用。关闭开关不会删除已有标签。

![标签配置：独立打开 Generate memory tags](https://img.alicdn.com/imgextra/i4/O1CN01ml5EwQd3ZkL6NWXs_!!6000000003416-2-tps-3142-1526.png)

启用记忆搜索后，Agent 可以通过 `memory_list_tags` 查看已有实体和文件数，再给 `memory_search` 传入 `tags`。你也可以在聊天里输入 `/reme list_tags` 查看已有标签，或在记忆文件预览中查看 `memory_tags` 元数据。

手动导入或编辑笔记不会自动生成标签，但文件里已有的标签会由文件监听同步到 Tag Index。更多标签约定与索引维护方式见 [ReMe Memory Tags](https://reme.agentscope.io/en/blog_20260920)。

### 从标签浏览到原始笔记

在 **Files → Tags** 中，可以看到已索引的标签及各自关联的文件数。选择一个标签，就能浏览对应的记忆文件。

![Files 的 Tags 页：展示已索引标签及关联文件数](https://img.alicdn.com/imgextra/i3/O1CN01aOf17D5AMdG7mt2s_!!6000000006319-2-tps-3836-1858.png)

打开标签下的一份记忆后，右侧展示原始笔记的预览，包括标签、源会话引用和正文。你可以据此核对当时保存的事实与上下文。标签浏览依赖已建立的索引，尚未索引的文件可能不会出现在列表中。

![选择标签后打开关联记忆，查看标签、源会话引用和笔记正文](https://img.alicdn.com/imgextra/i2/O1CN01p2M4uxVRrDE7mt2u_!!6000000002688-2-tps-3836-1860.png)
