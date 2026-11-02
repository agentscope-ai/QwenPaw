---
title: "QwenPaw 多模态记忆：让看过的图片，成为下次任务的依据"
date: 2026-10-27
author: QwenPaw Team
tags: [多模态记忆, ReMe, 图像记忆, Memory as File]
cover: https://img.alicdn.com/imgextra/i2/O1CN01qVVKgkcRb5D3OTaP_!!6000000005716-2-tps-1672-941.png
excerpt: "从选定活动照片到换个聊天写摄影方案，看看 QwenPaw 怎样把图片、讨论和选择理由保存为可检索、可回查的记忆。"
---

# QwenPaw 多模态记忆：让看过的图片，成为下次任务的依据

今天，你和 QwenPaw 比较了几张照片，选定活动主视觉，也讨论好了文案方向。几天后，换个聊天请它写摄影方案，却又要上传图片、解释之前为什么选了这一张。

如果记忆只留下“选了照片 A”，下次仍然不知道照片里的人穿什么、背什么包，更不知道它为什么适合这次活动。能继续派上用场的记忆，需要把图片里的细节和围绕它作出的决定一起保存。

在[文件化长期记忆](/blog/qwenpaw-long-term-memory)的基础上，QwenPaw 接入 [ReMe](https://github.com/agentscope-ai/ReMe) 的多模态记忆能力。启用后，Auto Memory 可以在后台阅读图文会话，把视觉事实、用户约束和选择理由写成 Markdown 笔记，并保留原图和源会话引用。

接下来，我们跟随一次服装品牌的周末快闪活动，从选照片、留下记忆，到换个聊天继续写摄影方案，把这条链路走一遍。

![图文会话中的图片与讨论进入记忆，并保留回看来源的入口](https://img.alicdn.com/imgextra/i4/O1CN01FZjxTO1kcwfMP8mPI_!!6000000004705-55-tps-1200-640.svg)

## 从一次周末快闪活动说起

假设你正在筹备一场服装品牌的周末快闪活动。你把两张模特照片发给 QwenPaw，希望宣传看起来像周末出门散步。

QwenPaw 推荐街头拍摄的照片 A，认为它更符合这次活动；另一张偏通勤风格的照片 B 留作其他用途。用户确认后，继续发来活动海报和场地照片，讨论宣传文案与现场安排，并明确这次没有折扣或赠品。

![首次图文讨论：比较两张模特照片，选择活动主视觉](https://img.alicdn.com/imgextra/i2/O1CN01wkoJ8tirBGL4s7Ss_!!6000000004233-0-tps-2400-1354.jpg)

## 记住图片，也记住围绕图片的讨论

如果只保存文字，记忆可能知道“选了 A”，却不知道照片里的人穿什么、背什么包。若只给图片生成一段独立描述，又容易遗漏用户为什么选择它。

ReMe 的 Auto Memory 在启用图像输入后，把对话文字与图片一起交给视觉模型，保留消息顺序、消息内的图文顺序，以及发送者和时间。模型据此提取事实，并通过记忆工具创建或更新 Markdown 笔记。

对这次活动筹备来说，需要一起留下的包括：

- **图片内容**：模特的穿搭、包和拍摄光线，以及海报上的时间、地点和预约方式。
- **明确决策**：照片 A 用作本次活动主视觉，照片 B 留作其他用途。
- **用户约束**：宣传要像周末散步，活动没有折扣或赠品。
- **选择理由**：照片 A 的街头场景和休闲穿搭更符合活动主题。

这些信息写成文字后，可以沿用已有的关键词和可选语义检索流程。以后用文字提问，也可以检索图片里记录下来的细节。

模型可能漏掉或误读图片里的信息，笔记需要保留原图来源，方便之后核对。

## 需要核对时，还能回看原图

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

## 换个聊天，继续写摄影方案

等后台记忆任务完成后，在同一个 Agent 下新建聊天，不重新上传图片，再请 QwenPaw 写一份可以发给摄影师的简短说明，提醒对方使用哪套造型，尤其是服装、包和光线。

QwenPaw 沿用了此前选定的照片 A，找回了绿色外套、浅色长裤、银色斜挎包和户外自然光等细节，整理成可以直接转发的摄影 brief。

![新聊天的摄影 brief：沿用之前选定的穿搭、包和光线](https://img.alicdn.com/imgextra/i2/O1CN018kGUFEWRjnC4s7Ss_!!6000000000381-0-tps-2400-1354.jpg)

新聊天还生成了社交平台预告，带上之前海报中的时间、地点和预约信息。查看生成的 Markdown 笔记，可以找到主视觉选择、海报讨论以及对应的原图和源会话引用。

## 在 QwenPaw 中启用图片记忆

在使用 ReMe 长期记忆后端的 Agent 记忆设置中，打开**在自动记忆中包含图片**。该开关默认关闭，要求 Agent 的记忆模型已确认支持图片输入与工具调用。模型能力未知时，需要先在模型设置中确认图片支持；聊天中临时选择的模型不会改变记忆模型。

![图片记忆配置：启用 Auto-memory，并打开 Include images in auto-memory](https://img.alicdn.com/imgextra/i1/O1CN01lbs7HYzP5FC6Pn1y_!!6000000007790-2-tps-3160-1534.png)

启用定期自动记忆并设置提取间隔后，在聊天中发送图片并展开讨论，等后台任务完成、笔记生成，再在同一 Agent 的新聊天里继续提问。你可以查看记忆文件，核对视觉事实、选择理由和来源是否保存。具体设置见[长期记忆文档](/docs/memory)和[配置说明](/docs/config)。

## 长期图文问答中，效果如何？

如果会话历史变得很长，还能找对图像里的信息吗？ReMe 用 MemLens-256K 比较了五种方法，以下是官方公布的 LLM-Judge 得分。

<div class="blog-figure-grid">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01y0PIU11haFUGGiIf0_!!6000000004293-55-tps-1000-520.svg" alt="MemLens-256K：Qwen3.6-35B-A3B 上五种方法的 LLM-Judge 得分" />
  <img src="https://img.alicdn.com/imgextra/i1/O1CN018cHcp11dv52RQTh1J_!!6000000003797-55-tps-1000-520.svg" alt="MemLens-256K：Qwen3.8-Max 上五种方法的 LLM-Judge 得分" />
</div>

_图源：[ReMe 图像记忆博客](https://reme.agentscope.io/en/blog_20261009)。_

ReMe Image 在两个模型上的得分分别为 **53.44%** 和 **72.49%**，相对 Full Context Image 分别提高 **6.35** 和 **6.88 个百分点**。

原题集共 195 题，其中 6 题在至少一种方法中触发模型提供方内容审查，所有方法统一使用筛选后的 **189/195 题**。这是完整系统的比较：ReMe 可以检索源会话，Image 配置可以回看源图；本次评测中的 OpenViking 检索范围限定为 memory。结果适用于该实验设置。更多配置、排除规则与复现比较见 [ReMe 评测说明](https://reme.agentscope.io/en/memlens_256k_evaluation)。

## 把这次活动的记忆串起来

1. 你上传照片和海报，说明宣传主题、选择与约束。
2. Auto Memory 在后台把图像细节和讨论一起整理成 Markdown 笔记。
3. 笔记保留原图与源会话引用，便于回查没有写进摘要的细节。
4. 同一 Agent 的新聊天检索这些记忆，再据此继续写摄影方案或活动文案。

这样，留到下次的就不只是一句“选了 A”，还有当时看到的细节、作出的选择，以及继续核对的入口。你可以随时打开笔记，检查和修正保存的内容。

如果还想按项目或人物缩小记忆检索范围，可以继续阅读 [Memory Tags](/blog/qwenpaw-memory-tags)；完整的记录、整理与找回流程见[长期记忆博客](/blog/qwenpaw-long-term-memory)。
