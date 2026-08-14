---
title: "QwenPaw Files：一个地方看清 Agent 的工作、档案与记忆"
date: 2026-08-07
author: QwenPaw Team
tags: [Files, Workspace, Profile, Daily, Knowledge Base]
cover: https://img.alicdn.com/imgextra/i4/O1CN01pEZk6a8g9lK3gjEp_!!6000000001665-2-tps-1817-866.png
excerpt: "QwenPaw Files 把工作区、档案、日记和知识库放进同一个界面。你可以查看 Agent 正在使用什么、记住了什么，以及这些内容怎样变成以后还能用的知识。"
---

# QwenPaw Files：一个地方看清 Agent 的工作、档案与记忆

假设你让 QwenPaw 帮忙准备一次产品发布。

你先给它一份客户访谈，让它阅读项目里的变更记录；接着，它生成了一份发布说明。讨论过程中，你们还决定这次不迁移数据库，并总结出一条写作习惯：发布说明要先讲用户能得到什么，再介绍技术变化。

几周后，你可能会想知道：生成的文件放在哪里？Agent 还记得当时的决定吗？那条写作习惯以后还能继续使用吗？

这些内容不必散落在聊天记录里。QwenPaw 会把项目资料、Agent 档案、每日记录和长期知识保存为你可以直接查看的文件，而 **Files** 就是集中查看和管理这些文件的入口。

![QwenPaw Files 工作台总览](https://img.alicdn.com/imgextra/i4/O1CN01GjiXT3fTIrJ5Bkx9_!!6000000006529-2-tps-2556-1223.png)

## 四个入口，分别保存四类内容

打开 Files，你会看到四个入口：**Workspace、Profile、Daily 和 Knowledge Base**。

可以把它们想象成 Agent 的四个抽屉：

| 入口               | 可以把它理解成         | 里面有什么                                   |
| ------------------ | ---------------------- | -------------------------------------------- |
| **Workspace**      | 当前干活的桌面         | 项目文件、参考资料、代码和任务产物           |
| **Profile**        | Agent 的档案和工作说明 | 身份、行为方式、常驻信息和主动检查说明       |
| **Daily**          | 按日期整理的工作日记   | 对话中值得保留的事实、决定、偏好和资料解读   |
| **Knowledge Base** | 可以反复使用的知识库   | 从多次经历中整理出的个人信息、方法和知识结论 |

它们都以文件为基础，但各有分工：Workspace 关注“现在正在做什么”，Profile 说明“Agent 应该怎样工作”，Daily 记录“最近发生了什么”，Knowledge Base 则沉淀“以后还值得使用什么”。

## Workspace：当前任务都放在这里

Workspace 是最接近普通文件管理器的部分。你可以在这里展开目录，查看项目资料、代码、配置和 Agent 生成的结果。

例如，当你让 QwenPaw 整理发布说明时，客户访谈、变更记录和最终生成的 Markdown 都可以放在 Workspace。你不必猜文件藏在哪条对话里，也不需要先下载到电脑再打开。

<img class="blog-image--compact" src="https://img.alicdn.com/imgextra/i4/O1CN016kKPfi0G9MI1B8dh_!!6000000000228-0-tps-581-576.jpg" alt="Workspace 集中展示 Agent 当前使用的项目文件和工作资料" />

Workspace 顶部还可以切换目录：

- **Project Directory** 保存当前项目的代码、资料和任务产物；
- **Agent Configuration Directory** 保存这个 Agent 自己的配置、记忆、技能和其他内部文件。

两者的边界很清楚：Project Directory 决定 Files 当前展示哪个项目，也会成为当前 Chat 在普通任务中默认使用的项目目录；Agent Configuration Directory 则始终用于查看 Agent 自己的文件。

Project Directory 支持继承，也可以按对话切换。Agent 可以设置默认目录，单个 Chat 则可以选择自己的目录，并把选择保存在当前对话中。Files 始终展示这个 Chat 当前实际生效的目录。普通 Chat 没有另外指定文件路径或 Shell 工作目录时，文件读写与搜索、Shell、代码分析以及 Files 中的 Git 操作都会以它为默认根目录。清除 Chat 的目录选择后，便会重新继承 Agent 的默认设置；需要隔离运行的任务模式和 fork 工作区，则可以使用优先级更高的专用目录。

## Profile：告诉 Agent 自己是谁、应该怎样工作

Profile 不是个人头像或账号资料，而是一组会参与 Agent 工作上下文的档案文件。

常见文件包括：

- `SOUL.md`：Agent 的角色、语气和基本行为方式；
- `AGENTS.md`：处理任务时需要遵循的工作说明；
- `MEMORY.md`：需要稳定保留、经常使用的信息；
- `HEARTBEAT.md`：主动检查或定期关注事项的说明。

你可以打开这些文件查看和修改，也可以启用、停用或调整顺序。如果你希望 QwenPaw 写发布说明时少用术语、先讲用户价值，就可以把这条长期适用的要求写进合适的档案文件。

<img class="blog-image--compact" src="https://img.alicdn.com/imgextra/i4/O1CN01gOFlhZbUFHF1BW2y_!!6000000001829-0-tps-584-552.jpg" alt="Profile 管理决定 Agent 行为方式的档案文件" />

Profile 和后面的 Daily、Knowledge Base 有一个关键区别：Profile 更像你明确交给 Agent 的长期工作说明，而 Daily 和 Knowledge Base 会随着对话和任务不断积累、整理。

## Daily：把今天值得记住的事整理下来

一天的对话可能很长，但真正需要留下的通常只有少数内容：一个决定、一条偏好、某份资料的重要发现，或者下一步要做的事。

Daily 会按日期展示这些记录。比如关于数据库迁移的长对话，可以被整理成一条简明日记：

> **决定**：本次发布不迁移数据库。
>
> **原因**：发布时间紧，现有方案仍能满足需求。
>
> **下一步**：发布完成后重新评估。

<img class="blog-image--medium" src="https://img.alicdn.com/imgextra/i2/O1CN01f7mMLhPmiXB3rvvy_!!6000000001706-0-tps-1906-1188.jpg" alt="Daily 按日期保存从对话和任务中整理出的重要记录" />

这些日记不是完整聊天记录的副本，而是从中提炼真正有用的信息。由 ReMe Light 自动记忆流程生成的日记，还会在文件元数据中记录来源会话标识，方便你回到原始对话核对。

Daily 中的内容仍然是普通 Markdown 文件。记错了可以改，已经过时可以更新，重要的记录也可以直接拿来继续工作。

## Knowledge Base：让零散日记变成长期经验

只有日记还不够。使用一段时间后，几十甚至几百条记录仍然可能难以查找。

Knowledge Base 会把多次经历整理成更稳定、可以反复使用的知识。例如，经历几次产品发布后，分散在不同日期里的反馈可以逐渐沉淀为一条经验：

> 发布说明先讲用户能得到什么，再介绍技术变化；重要变化最好配一个实际使用场景。

知识库通常从三个角度组织内容：

- **Personal**：用户、团队或项目的身份、偏好和约定；
- **Procedure**：可以重复执行的流程、操作步骤和解决办法；
- **Wiki**：概念、结论、观察和可以作为先例的决定。

使用 ReMe Light 记忆后端时，Knowledge Base 还会提供关系图：

![Knowledge Base 用关系图展示记忆和知识之间的连接](https://img.alicdn.com/imgextra/i1/O1CN01JBjN5c3diWC49o9I_!!6000000000514-0-tps-2048-1024.jpg)

关系图让这些内容不再是一组彼此孤立的文件。节点对应已索引的 Daily、Knowledge Base 文件或分类入口，连线则来自文件中的 wiki 链接。你可以直接打开图中已索引的文件，也可以沿着连线查看与某条知识相关的日记或方法。

简单来说，Daily 回答“那天发生了什么”，Knowledge Base 回答“经过这些事情，我们学到了什么”。

## 不只是查看：还可以预览、编辑和核对修改

找到文件以后，不必离开 QwenPaw 才能继续处理。

- Markdown、代码、配置、CSV、图片和 PDF 可以直接预览；
- 文本文件可以切换到 Edit 模式修改；
- 同时打开多个文件时，标签页会保留光标和未保存内容；
- 当 Agent 或其他工具再次修改文件时，可以通过 Diff 查看具体变化；
- 每一处变化都可以选择保留或撤销，最后再明确保存。

![从 Chat 打开文件预览，再进入完整 Files 工作台](https://img.alicdn.com/imgextra/i3/O1CN01TTmgqymDpqH5CGAk_!!6000000002889-0-tps-2560-1226.jpg)

这意味着 Agent 可以先完成初稿，而最终检查权仍然在你手中。Files 不替你决定是否接受修改，而是把原文、修改结果和审阅操作放在同一个地方。

## 让文件在任务与对话之间流转

Files 同时连接任务的输入与输出：

- 上传资料到当前项目或 Agent 配置目录；
- 下载 Agent 生成的文件；
- 遇到同名文件时，选择重命名、跳过或覆盖；
- 把整个文件或选中的片段引用回 Chat；
- 从 Chat 中的附件和工具产物返回同一个预览界面。

引用文件时，QwenPaw 会尽量保留路径和行号。这样，当你说“请重写这一段”时，Agent 能准确知道你指的是哪个文件、哪一部分，而不必依赖一段脱离来源的复制文本。

## 把一次产品发布串起来看

现在把整个过程放在一起：

1. 你把客户访谈和项目变更记录放进 **Workspace**；
2. **Profile** 告诉 Agent，发布说明应该先讲用户价值，并保持简洁；
3. QwenPaw 生成发布说明，你在 Preview 中阅读，再进入 Edit 调整措辞；
4. 团队关于数据库迁移的决定被整理进当天的 **Daily**；
5. 多次发布积累的写作经验逐渐进入 **Knowledge Base**；
6. 下次再写发布说明时，Agent 可以结合项目文件、档案要求和过去经验继续工作。

聊天负责表达意图，Workspace 保存当前任务，Profile 说明怎样工作，Daily 记录发生过什么，Knowledge Base 留下以后还能复用的经验。

## 文件可见，协作才真正可控

Files 处理本地文件，因此文件接口会把访问限制在所选目录内，拒绝路径穿越以及指向目录外部的符号链接；上传文件重名时，也会要求你明确选择处理方式。对于无法确认仍位于当前 Project Directory 或 Agent Configuration Directory 的历史附件，Files 只提供只读预览，不会将其显示为可编辑文件。保存 Workspace 中的文本文件时，Files 还会核对打开文件时记录的版本：如果磁盘内容已经变化，就拒绝用旧版本覆盖；检查通过后，再以原子方式写入。

当前 Files 更适合常规规模的工作区。目录内容支持分页，但文件树暂不支持搜索和长列表虚拟化。文本虽然由服务端分块读取，界面仍会等所有分块拼接完成后再开始预览或编辑。因此，超大文本文件或包含大量同级文件的目录可能需要更长的打开时间。

更重要的是，记忆和配置没有藏在无法检查的黑盒里。它们以文件形式保存在 Agent Configuration Directory 中，你可以通过 Files 中的对应入口打开、阅读和修改。

Files 的价值不只是“多了一个文件树”，而是让你随时回答这些问题：

- Agent 正在使用哪些文件？
- 它按照什么档案和规则工作？
- 它从最近的任务中记住了什么？
- 零散记录最终形成了哪些长期知识？
- 哪些修改已经写入文件，哪些还在等待确认？

当工作文件、档案、日记和知识都清晰可见，你和 Agent 才能围绕同一份状态持续协作。

相关实现与设计记录：

- [QwenPaw #6504：统一 Files Workspace](https://github.com/agentscope-ai/QwenPaw/pull/6504)
