---
title: "让 Agent 知道何时继续、何时停：QwenPaw Loop Engineering 与自定义 Loop"
date: 2026-07-29
author: QwenPaw Team
tags: [Loop Engineering, 自定义 Loop, Agent Mode, Goal, Mission]
cover: https://img.alicdn.com/imgextra/i1/O1CN01D73t2s1WdUUsjMQ2C_!!6000000002811-2-tps-1536-1024.png
excerpt: "QwenPaw 不只提供 Default、Goal、Mission 三种内置 Loop，还支持在 Console 中零代码组合 Gate，给 Agent 配置完成标准、资源预算与止损边界。"
---

# 让 Agent 知道何时继续、何时停：QwenPaw Loop Engineering 与自定义 Loop

一个 Agent 是否可靠，不只取决于它“会不会做”，也取决于它能不能判断：任务还没完成时要继续推进，已经没有进展时要及时停下。

普通对话很容易遇到两种相反的问题：

- 明明还有测试没有通过、资料没有查完，Agent 却给出一段总结后提前结束；
- Agent 反复调用相同工具、尝试相同方案，看起来一直在忙，却没有产生新进展。

QwenPaw 的 **Loop Engineering**，就是为这两个问题提供一套显式的控制机制。如果说 Skills 决定 Agent“会做什么”，Loop Engineering 决定的就是它“如何持续推进，以及何时把控制权交还给你”。

QwenPaw 2.0 提供了 Default、Goal、Mission 三种内置 Loop；从 QwenPaw 2.0.1 开始，你还可以在 Console 中直接创建自己的 Loop，不需要编写代码。

![image.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/eYVOL5or72jbRlpz/img/788fdbac-23f6-402d-999d-63ab549828be.png?x-oss-process=image/crop,x_0,y_95,w_1776,h_783/ignore-error,1)

## Loop Engineering：给每轮工作加一道“质检 Gate”

Agent 每完成一轮模型响应或工具调用，QwenPaw 都会检查当前模式下配置的 Gate。

```text
Agent 完成一轮工作
        ↓
按顺序检查 Gate
        ├── TERMINATE：当前 Turn 结束
        ├── CONTINUE：注入新的指令，让 Agent 继续
        └── BYPASS：不干预，继续检查下一个 Gate

```

Gate 可以关注不同信号：迭代次数、Token 用量、运行时间、工具调用次数、重复行为，或者任务是否满足完成标准。多个 Gate 组合起来，就形成一个 Loop 的执行策略。

这套设计的重点不是让 Agent 无限工作，而是给持续工作加上三类边界：

- **完成边界**：什么结果才算真正完成；
- **资源边界**：最多使用多少轮次、时间、Token 和工具调用；
- **止损边界**：发现重复和无效尝试时，什么时候换策略，什么时候停止。

时间和预算类 Gate 会在一轮模型响应或工具调用结束后的 Loop 边界进行检查，不会在工具执行到一半时强行中断。

## 目前内置的三种 Loop

| 模式        | 适合什么任务                           | 如何工作                                                                 | 如何判定结束                                     |
| ----------- | -------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------ |
| **Default** | 日常问答、分析、小范围修改             | 单 Agent 的受控 ReAct Loop                                               | Agent 给出最终答复，或触发迭代、重复行为等 Gate  |
| **Goal**    | 目标明确、需要持续推进且可以验证的任务 | 单 Agent 围绕一个目标持续工作，并检查目标状态                            | 目标被标记为完成或阻塞，或达到轮次、Token 等预算 |
| **Mission** | 可以拆成多个用户故事的大型任务         | 先生成 PRD，再通过 Master（Controller）、Worker、Verifier 流程执行和验证 | 所有 Story 通过，或达到任务轮次与重试上限        |

### Default：给日常对话加上基本护栏

![image.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/eYVOL5or72jbRlpz/img/45c1ab8a-ed91-4dc2-a2e3-722df7ed5aaf.png)

Default 是未启用显式模式时使用的标准 Loop。用户只需要发送一次请求，Agent 可以在这个 Turn 内进行多轮推理和工具调用，最后交回结果。

Default 的 Gate 流程包含：

- 可配置的 ReAct 迭代上限；
- 重复工具调用检测，可以先提醒 Agent 更换策略，再决定是否停止；
- 可选的定性完成度检查，在 Agent 只输出文本、没有调用工具时，再提醒它确认工作是否真的完成。

它适合“帮我分析这个报错”“修改这几个文件”“整理一份简短对比”这类边界较小的任务。

### Goal：围绕一个明确目标持续推进

![image.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/eYVOL5or72jbRlpz/img/dd7b210e-daa0-4ed3-8075-5848af40719e.png)

当任务无法靠一次常规回复完成，但仍适合由一个 Agent 连续推进时，可以使用 Goal：

```text
/goal 调研主流大模型的上下文窗口，并输出带来源的对比表

```

Goal 会为 Agent 提供目标状态工具，让它查看进度，并在有证据证明需求已经满足后明确标记 `complete`；如果持续遇到同一个外部阻塞，则可以标记 `blocked`。同时，Goal 还有独立的轮次和 Token 预算。

它适合持续调研、批量修复测试、跨文件改造、长文翻译与结构化分析等目标明确的工作。Goal 的验证主体仍是当前 Agent，它强调的是“带状态协议的自我审计”，而不是引入一个独立评审 Agent。

### Mission：把大型任务交给多个上下文隔离的角色

![image.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/eYVOL5or72jbRlpz/img/2de182ca-cf97-4156-b1a6-04f7f72e9078.png)

当任务天然包含多个相对独立的子任务时，可以使用 Mission：

```text
/mission 创建一个支持增删改查的 CLI TODO 应用，并为核心功能补齐测试

```

Mission 分为两个阶段：

1.  分析需求并生成包含多个 User Stories 的 PRD，等待用户确认；
2.  按 Story 执行、验证和修复，直到全部通过或达到预算上限。

它通过 Master（Controller）、Worker、Verifier 的职责分工，让每个执行角色只关注当前子任务，减少长上下文中不同需求相互干扰。你还可以配置默认验证说明、测试命令、Mission 最大轮次，以及每个 Story 的最大重试次数。

Mission 可能让后台 Worker 执行命令或修改文件，建议只在可信工作区中使用，并保留合适的权限与审批设置。

需要查看进度时，可以使用：

```text
/mission status
/mission list

```

## 自定义 Loop：把你自己的工作标准保存成模式

![image.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/eYVOL5or72jbRlpz/img/e31a3f15-daa4-4f56-b35e-b7206676d9f6.png)

内置模式解决的是通用问题，但不同团队对“完成”的理解并不相同。

例如，同样是“做一次产品调研”，有人希望控制成本，有人更在意来源质量，还有人要求每个结论都必须可追溯。过去，这些要求通常散落在每次任务的 Prompt 里；现在，你可以把它们组合成一个可重复使用的自定义 Loop。

在 **智能体 Loop 设置** 中点击 `+`，可以从四种初始模板开始：

| 初始模板     | 默认组合                                              | 适合场景               |
| ------------ | ----------------------------------------------------- | ---------------------- |
| **安全运行** | 迭代限制 + Token 预算 + 重复行为保护 + 定性完成度检查 | 希望兼顾成本与基本质量 |
| **预算研究** | 迭代限制 + 时间限制 + 工具调用预算 + 重复行为保护     | 搜索、调研、信息收集   |
| **质量优先** | 迭代限制 + Token 预算 + 重复行为保护 + 完成信号检查   | 有清晰验收标准的任务   |
| **空白流程** | 不预置 Gate                                           | 从零搭建特殊策略       |

![image.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/eYVOL5or72jbRlpz/img/91c9693d-5776-453f-a7d6-18a1521ea611.png)

创建后，可以为模式设置显示名称、描述和专属斜杠命令，并通过拖拽调整 Gate 的检查顺序。当前可组合七种 Gate：

| Gate               | 作用                                                      |
| ------------------ | --------------------------------------------------------- |
| **迭代次数限制**   | 达到指定 ReAct 迭代次数后停止                             |
| **重复行为保护**   | 识别重复工具调用，先提示换策略，也可在严重时停止          |
| **Token 预算**     | 限制总 Token、输入 Token 或输出 Token                     |
| **Loop 时间限制**  | 达到时间上限后，在下一个 Loop 边界停止                    |
| **工具调用预算**   | 限制全部工具调用，或为指定工具设置单独上限                |
| **定性完成度检查** | Agent 给出纯文本答复时，按自然语言标准要求它继续完善      |
| **完成信号检查**   | 要求 Agent 对候选结果进行自检，只有返回精确完成信号才结束 |

定性完成度检查和完成信号检查是两种不同的完成策略，同一个模式中只能选择一种。后者让完成状态更加显式，但会触发额外的模型判断，增加 Token 和时间消耗；它依然是当前 Agent 的自检，不等同于独立 Verifier。

## 一个例子：创建“深度调研”Loop

假设你经常让 QwenPaw 做行业和技术调研，可以创建一个名为“深度调研”的模式，并配置斜杠命令：

```text
/deep-research

```

从“预算研究”模板开始，再补充 Token 预算和完成信号检查。一个可参考的 Gate 流程是：

1.  **迭代次数限制**：避免任务无限延长；
2.  **Token 预算**：控制单次调研的模型成本；
3.  **Loop 时间限制**：为一次调研设置最长运行时间；
4.  **工具调用预算**：限制总调用次数，并为搜索工具单独设置上限；
5.  **重复行为保护**：发现反复搜索同一问题时要求切换关键词或来源；
6.  **完成信号检查**：只有满足你的调研标准后才允许结束。

完成判断 Prompt 可以这样写：

```text
仅在同时满足以下条件时，才将任务视为完成：
1. 至少引用 6 个一手或官方来源；
2. 每个关键事实都能追溯到来源；
3. 对冲突信息进行交叉核验并说明取舍；
4. 输出对比表、结论和已知局限；
5. 明确区分来源事实与分析判断。

```

保存后，你可以在聊天输入区直接选择“深度调研”，也可以输入：

```text
/deep-research 调研 2026 年主流开源 Agent 框架，比较架构、扩展机制和部署成本

```

自定义模式会在当前会话中持续生效。新的用户 Turn 会重新计算迭代、时间、Token 和工具预算，但模式本身不会自动关闭；需要退出时使用 `/mode off`，也可以通过 `/clear` 或 `/new` 重置会话。

## 还需要更复杂的 Loop？用插件扩展工作流

可视化自定义 Loop 适合组合 QwenPaw 当前提供的七种 Gate。如果你的停止条件依赖外部系统状态、独立评审模型或专用状态机，则可以通过插件注册新的 Agent Mode。

QwenPaw 2.0.1 中提供的 Oh-My-Paw（OMP Workflows）插件就是这一层扩展的示例：

| 插件 Loop     | 主要用途                                                           |
| ------------- | ------------------------------------------------------------------ |
| **UltraQA**   | 按“检查 → 诊断 → 修复 → 复查”循环执行测试、构建、Lint 或自定义检查 |
| **Ralph**     | 以 PRD 和 User Stories 驱动持续实现与验收                          |
| **Ultrawork** | 将独立子任务拆开，并行交给多个子 Agent 执行                        |
| **Autopilot** | 依次完成需求扩展、规划、执行、QA、验证和清理                       |
| **Team**      | 通过可配置的多 Agent 团队完成规划、执行、验证与修复                |

这些模式不是三个核心内置 Loop 的一部分。安装插件后，它们会和用户创建的模式一起出现在聊天输入区的“自定义与插件”分组中。

## 应该选择哪一种？

- 日常问答、小改动：使用 **Default**；
- 一个 Agent 可以独立完成的明确目标：使用 **Goal**；
- 可以拆成多个 Story、需要独立执行和验证的大型任务：使用 **Mission**；
- 经常重复出现、拥有固定预算或完成标准的任务：创建 **自定义 Loop**；
- 需要专用状态机、多 Agent 工作流或外部判定逻辑：安装或开发 **Loop 插件**。

好的 Loop 不是让 Agent 工作得更久，而是让它拥有清晰的完成标准、可控的资源预算，以及在没有进展时及时停下的能力。

从 Prompt 中反复说“继续”，到把工作策略保存成可复用的模式，这就是 Loop Engineering 带来的变化。

## 延伸阅读

- [QwenPaw Loop Engineering 文档](https://qwenpaw.agentscope.io/docs/loop-engineering)
- [QwenPaw v2.0.1 发布说明](https://qwenpaw.agentscope.io/release-notes#v2.0.1)
- [QwenPaw GitHub 仓库](https://github.com/agentscope-ai/QwenPaw)
