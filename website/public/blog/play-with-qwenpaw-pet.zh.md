---
title: "Play with QwenPaw-Pet"
date: 2026-07-01
tags: [插件, 桌宠, 像素宠物, 技能制作]
excerpt: "QwenPaw在1.1.3版本引入了插件系统，并在1.1.8版本引入了宠物系统。但官方的宠物模板个人不太喜欢，就一直没有配置。个人一直比较喜欢像素风的宠物类型"
related:
  heading: "相关能力"
  items:
    - label: "插件"
      name: "QwenPaw Pet"
      href: "https://platform.agentscope.io/plugins/qwenpaw-pet"
      description: "QwenPaw 官方桌宠插件，用于将后端生命周期事件同步至 QwenPaw Pet Desktop。"
    - label: "内置技能"
      name: "make-skill"
      href: "https://qwenpaw.agentscope.io/docs/skills#通过-make-skill-从当前会话创建-Beta"
      description: "将当前会话中的操作流程与经验沉淀为可复用 Skill。本文使用该能力将桌宠制作流程封装为可复用 Skill。"
---

# Play with QwenPaw-Pet

QwenPaw在1.1.3版本引入了插件系统，并在1.1.8版本引入了宠物系统。但官方的宠物模板个人不太喜欢，就一直没有配置。个人一直比较喜欢像素风的宠物类型。

这次抽时间尝试让QwenPaw自己生产了一批宠物模板，使用make-skill和subagents，生成宠物的过程可以自主沉淀总结归纳，显著加速流程。

## 太长不看版流程：

- QwenPaw版本：v1.12

  - Note：QwenPaw 2.0版本的宠物生产流程，因插件系统更新可能有所不同

- Model：Qwen3.7-Max

总体流程：

- 创建独立的**宠物大师**Agent
- 根据个人喜好微调，得到第一个满意的宠物生成流水线
- 使用**Make-skill**沉淀历史生成经验，形成可服用的make-pet skill。
- 使用新生成的skill + subagents批量生产，得到宠物大军。

## 1. 宠物大师初始化

### 1.1. 准备阶段

在官方插件处，下载QwenPaw Pet插件。![image](https://img.alicdn.com/imgextra/i1/O1CN01niHx461stRq372qrr_!!6000000005824-2-tps-2335-330.png)

确保插件被下载，并正确启用。

为了方便管理，创建新Agent**宠物大师**，配备如下技能：

- **Make-skill**：用于复用流程为skill，准备后续批量化生产宠物

  - Spawn-subagent等也顺便装载

- QA-source-index：便于QwenPaw了解自己的宠物系统如何设计

  - 也可以用QwenPaw skill市场的`qwenpaw-docs-zh`技能

Note：

- 如果需要收集宠物素材，可以同时配备`tavily mcp`或者browser相关skill。
- 如果需要对比图片素材，需要开启`view_image`并使用具备多模态识图能力模型（比如qwen3.6-plus）

### 1.2. 初始化配置：

通过对话，为新Agent提供背景知识：

![image](https://img.alicdn.com/imgextra/i2/O1CN01tQwcZE1XAT0cTWILz_!!6000000002883-2-tps-1662-932.png)

开启一个新会话，让QwenPaw了解自己的宠物系统。可以看到发出问题后，QwenPaw调用**QA-source-index**技能，开始理解宠物插件系统。

这一步可以为后续创建我们自己的Agent提供必要的上下文。

## ![image](https://img.alicdn.com/imgextra/i4/O1CN018HkxEd1VI8PNNKbIx_!!6000000002629-2-tps-1654-620.png)

## 2. 首次创建宠物

经过第一轮对话，QwenPaw了解了自己的宠物机制，下面就可以让它创建宠物了！

![image](https://img.alicdn.com/imgextra/i4/O1CN01MoQRjb1E1mnpDFfbP_!!6000000000292-2-tps-1684-598.png)

![image](https://img.alicdn.com/imgextra/i1/O1CN015Nhs1a1PBMrV0h8vG_!!6000000001802-2-tps-1022-1220.png)

见下图。可以看到QwenPaw一次就完成了任务，但仍然有一些小问题，我们可以继续微调。

- 宠物命名没有确认。
- 不符合我的个人审美，我希望更贴近小火龙的形象，而且更符合宝可梦的风格
- 动作神态比较僵硬，希望动作粒度更细

![image](https://img.alicdn.com/imgextra/i3/O1CN01L7of8y1Oo0f8WspAn_!!6000000001751-2-tps-1490-230.png)

经过近一轮对话调整，小火龙更贴近宝可梦中的形象了！

![image](https://img.alicdn.com/imgextra/i4/O1CN01TSgZuS1dNe6HMC81Z_!!6000000003724-2-tps-1536-268.png)

### 回顾

整个过程一次就完成，但仍然有一些小细节可以完善，比如：

- Agent创建了许多临时脚本，用于绘图和校验
- 模型写脚本的前几次均犯错失败，造成大量token浪费

最终结果如下：为了本次创建，我们花费了~50K tokens，并且经历了约120轮对话+工具调用。

![image](https://img.alicdn.com/imgextra/i2/O1CN01DIro7M1oig3ravFi5_!!6000000005259-2-tps-1986-406.png)

## 3. Make-skill: Pet-maker

在版本1.11中，QwenPaw引入了`make-skill`，可以沉淀用户对话历史和工具调用为skill。借助该技能，我们将宠物创建变成可复用skill，该技能包含我的个性化偏好和习惯，同时也有可复用的执行脚本。

在首次创建宠物的对话中，使用`/make-skill`，命名为`pet-maker`，这也是我们以后继续创建宠物时调用的技能名。

### 3.1. 沉淀Pet-maker Skill

![image](https://img.alicdn.com/imgextra/i1/O1CN01q8sMj6224HkgucJ30_!!6000000007066-2-tps-1734-510.png)

![image](https://img.alicdn.com/imgextra/i4/O1CN01qrdErs1YS9vO2uJlf_!!6000000003057-2-tps-1716-840.png)

选择Approve。可以看到除了skill.md，/make-skill还会创建.json文件进行自动化；同时还包含generate_pet.py作为可执行脚本。

沉淀后，`\pet-maker`技能会存在于**宠物大师**的工作区。我们可以在新对话中复用该技能，尝试创建更多宠物。

### 3.2. Example: 妙蛙种子

![image](https://img.alicdn.com/imgextra/i2/O1CN01Yrai4D22z4reHJLHS_!!6000000007190-2-tps-1680-574.png)

![image](https://img.alicdn.com/imgextra/i2/O1CN019n8TCb1Jm6wS6ZUHE_!!6000000001070-2-tps-1444-242.png)

开启新会话，这次我们想创建妙蛙种子。本次创建就简单多了，经过一次简单的调用，类似风格的宠物顺利创建：

- 上下文和工具调用次数均显著减少，之后类似风格的宠物可以大量创建。

![image](https://img.alicdn.com/imgextra/i2/O1CN01mx6hSg1SRnvHcdZKY_!!6000000002244-2-tps-1902-352.png)

### 3.3 Example: 批量创建

借助`subagents`工具，可以并行创建多个宠物：

![image](https://img.alicdn.com/imgextra/i1/O1CN01Bqzx701UvEbZIRRQE_!!6000000002579-2-tps-1692-408.png)

![image](https://img.alicdn.com/imgextra/i1/O1CN015Rh7GX1sfhxMSotJS_!!6000000005794-2-tps-538-196.png)

此时主Agent只需要监控三个task的进度即可，经检验，主agent消耗的token甚至更少：

![image](https://img.alicdn.com/imgextra/i1/O1CN01SYxIwc1J6QtqPTjSu_!!6000000000979-2-tps-1922-460.png)

![image](https://img.alicdn.com/imgextra/i2/O1CN010opvm71Nu8LIl2pbE_!!6000000001629-2-tps-1592-1012.png)

## 4. 小结

本文展示如何使用QwenPaw进行Pet创建，借助Make-skill技能沉淀流程，为之后批量生产像素风宝可梦宠物提供支持。再之后作者将继续考虑：

- 适配2.0版本宠物系统
- 使用QwenPaw，自更新宠物交互，丰富宠物系统功能

欢迎大家就宠物系统继续交流✌️
