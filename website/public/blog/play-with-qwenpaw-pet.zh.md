---
title: "Play with QwenPaw-Pet"
date: 2026-07-01
tags: [pet, plugin, make-skill]
excerpt: "QwenPaw在1.1.3版本引入了插件系统，并在1.1.8版本引入了宠物系统。但官方的宠物模板个人不太喜欢，就一直没有配置。个人一直比较喜欢像素风的宠物类型"
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

在官方插件处，下载QwenPaw Pet插件。![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/03e71187-8a0c-48ba-a5bd-bd93de36239b.png)

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

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/025aa983-5104-40cc-ac79-7605feecf47a.png)

开启一个新会话，让QwenPaw了解自己的宠物系统。可以看到发出问题后，QwenPaw调用**QA-source-index**技能，开始理解宠物插件系统。

这一步可以为后续创建我们自己的Agent提供必要的上下文。

## ![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/a5f21248-0990-44b2-b5ac-5ec0c9999008.png)

## 2. 首次创建宠物

经过第一轮对话，QwenPaw了解了自己的宠物机制，下面就可以让它创建宠物了！

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/3a843792-db87-45a5-bc86-5552ed57c98a.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/0aa0e9ca-3ed4-4c18-a645-aa0f33e653ee.png)

见下图。可以看到QwenPaw一次就完成了任务，但仍然有一些小问题，我们可以继续微调。

- 宠物命名没有确认。
- 不符合我的个人审美，我希望更贴近小火龙的形象，而且更符合宝可梦的风格
- 动作神态比较僵硬，希望动作粒度更细

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/da1269e1-3562-4114-81c2-2c98887bc895.png)

经过近一轮对话调整，小火龙更贴近宝可梦中的形象了！

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/3e9f4ad1-e6c9-4c7c-a19f-109ba1e43634.png)

### 回顾

整个过程一次就完成，但仍然有一些小细节可以完善，比如：

- Agent创建了许多临时脚本，用于绘图和校验
- 模型写脚本的前几次均犯错失败，造成大量token浪费

最终结果如下：为了本次创建，我们花费了~50K tokens，并且经历了约120轮对话+工具调用。

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/6634ca6d-4275-4380-989c-7f02e58cdb1e.png)

## 3. Make-skill: Pet-maker

在版本1.11中，QwenPaw引入了`make-skill`，可以沉淀用户对话历史和工具调用为skill。借助该技能，我们将宠物创建变成可复用skill，该技能包含我的个性化偏好和习惯，同时也有可复用的执行脚本。

在首次创建宠物的对话中，使用`/make-skill`，命名为`pet-maker`，这也是我们以后继续创建宠物时调用的技能名。

### 3.1. 沉淀Pet-maker Skill

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/33de88a0-4b16-4d89-b390-040316983fcc.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/bb74d4af-4236-49ef-9306-1f3534a247bb.png)

选择Approve。可以看到除了skill.md，/make-skill还会创建.json文件进行自动化；同时还包含generate_pet.py作为可执行脚本。

沉淀后，`\pet-maker`技能会存在于**宠物大师**的工作区。我们可以在新对话中复用该技能，尝试创建更多宠物。

### 3.2. Example: 妙蛙种子

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/18b89e2b-9a94-4652-bc8b-674bd8ec3204.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/e4b928f9-0b2e-4840-af7d-eaa180982805.png)

开启新会话，这次我们想创建妙蛙种子。本次创建就简单多了，经过一次简单的调用，类似风格的宠物顺利创建：

- 上下文和工具调用次数均显著减少，之后类似风格的宠物可以大量创建。

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/1a3760da-3be2-49ae-a434-0c67dcab574e.png)

### 3.3 Example: 批量创建

借助`subagents`工具，可以并行创建多个宠物：

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/c7f78719-f6e6-4ea3-be85-6efd66146345.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/53d0ecf6-1027-483b-b3ff-e6699aef119f.png)

此时主Agent只需要监控三个task的进度即可，经检验，主agent消耗的token甚至更少：

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/3bec5acd-d9a6-4396-9a41-bb62dd3f253a.png)

![image](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/4j6OJ5joE6dbKq3p/img/7538a924-a647-4a19-8203-2d6283008146.png)

## 4. 小结

本文展示如何使用QwenPaw进行Pet创建，借助Make-skill技能沉淀流程，为之后批量生产像素风宝可梦宠物提供支持。再之后作者将继续考虑：

- 适配2.0版本宠物系统
- 使用QwenPaw，自更新宠物交互，丰富宠物系统功能

欢迎大家就宠物系统继续交流✌️
