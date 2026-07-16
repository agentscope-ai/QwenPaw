---
title: "PawGit：为 QwenPaw Agent 会话状态提供可恢复性"
date: 2026-07-07
author: QwenPaw Team
tags: [插件, 会话版本控制, 状态快照, 会话回滚]
cover: https://img.alicdn.com/imgextra/i2/O1CN01cdSRbU26gXIFiTRjL_!!6000000007691-2-tps-1254-1254.png
excerpt: "长会话里 Agent 会被脏上下文拖住。PawGit 为 QwenPaw Agent 会话状态提供 checkpoint、timeline 与 rewind，让你在不必新开窗口重喂 prompt 的前提下，回到之前还干净的状态。"
related:
  heading: "相关插件：PawGit"
  description: "QwenPaw 会话与记忆版本控制插件，支持状态快照、DAG 时间线、会话回滚与状态重置。"
  linkText: "查看并安装 PawGit →"
  linkUrl: "https://platform.agentscope.io/plugins/pawgit"
---

# PawGit：为 QwenPaw Agent 会话状态提供可恢复性

如果你经常用 QwenPaw 做复杂任务，应该很熟悉这种时刻：

一开始，它非常聪明。你新开了一个会话，把项目背景、目录结构、设计目标、限制条件、已经踩过的坑，一点点喂给它。它读得很认真，回答也很到位。你甚至会有一种错觉：这次稳了，它真的懂了。

然后任务开始变长。你让它先分析，再改一点代码，再回头讨论方案。中间发现某个判断不对，于是纠正它。后来又发现接口和预期不一致，于是再改。再后来，你临时换方向，让它先别做 phase 2，只把 phase 1 收口。

十几轮、几十轮之后，奇怪的事情开始发生。它还在回答，但味道不对了。它会把已经废弃的方案重新拿出来。它会记住一个你明明已经纠正过的错误前提。它会在新判断里混入旧上下文。它会突然变得小心翼翼，或者相反，突然开始自信地补一些并不存在的洞。

![长会话进行到后半段，Agent 开始被旧上下文拖住](https://img.alicdn.com/imgextra/i2/O1CN01cdSRbU26gXIFiTRjL_!!6000000007691-2-tps-1254-1254.png)

让人更烦的是，你知道模型本身没有问题，而是上下文太长了。它只是被这个长会话里的历史包袱拖住了。现在越来越多人把这种现象叫做**上下文腐蚀（Context Rot）**，不是上下文不够长，而是上下文开始变脏。

这时候我们很多人最自然的想法是：开一个新窗口吧。但你马上又会犹豫。新窗口意味着重新喂 prompt、重新解释项目背景、重新贴设计文档、重新说明哪些方案已经被否掉、重新告诉它当前代码改到了哪里。更关键的是，前面很多有价值的讨论也会一起丢掉。

于是你卡在一个很**难受**的位置：

> 当前会话已经不干净了。
> 但新开会话又太“贵”了。
> 你真正想要的其实不是“重新开始”，而是“回到之前某个还干净的状态”。

这就是 PawGit 想解决的问题。

![不想新开窗口重新喂背景，只想回到一个还干净的会话状态](https://img.alicdn.com/imgextra/i1/O1CN013ToS4J1giCj57TDSI_!!6000000004175-2-tps-1254-1254.png)

## 内容概览

1. PawGit 的定位：面向 Agent 会话状态的可恢复性
2. PawGit 的使用介绍：Rewind、Timeline、GC 与 Reset
3. 推荐使用流程：在真实 Agent 工作中如何使用 PawGit
4. 总结：为长会话提供可恢复的第三种选择

（整体阅读时间大约 8 分钟）

## 一、PawGit 的定位：面向 Agent 会话状态的可恢复性

### 1. Agent 会话为什么需要版本管理

我们已经习惯了给代码做版本控制。改坏了，可以回到上一个 commit。重构前，可以打一个 tag。想试一个不确定的方向，可以开一个 branch。哪怕最后失败了，也不是世界末日。因为 Git 给了我们一种很朴素的安全感：我可以探索，但我也可以回来。

可是当我们和 Agent 一起工作时，真正发生变化的不只是代码，还有这些东西：

- 当前会话状态。
- Agent 对项目的理解。
- 几十轮对话里积累出来的判断、偏见、错误修正和半成品结论。

这些东西没有 Git。所以我们经常会遇到一种很荒诞的情况：项目文件可以恢复到 10 分钟前，但 Agent 的脑子回不去了。它还是带着刚才那堆混乱上下文继续往前走。如果只是普通聊天，这也许没什么。但 Agent 不一样。Agent 会读文件、写文件、调用工具、修改记忆，还会基于已有上下文继续推理。一旦错误状态进入后续推理，它就不只是一个错误回答，而会变成一笔上下文债务。

PawGit 的切入点就在这里，它不是项目 Git 的替代品，它想做的是另一件事：**给 QwenPaw 的 Agent 会话状态加上存档点**。

### 2. PawGit 如何保存 Agent 会话状态

PawGit 是一个 QwenPaw 插件，目前可以在官方 platform 下载：[https://platform.agentscope.io/plugins/pawgit](https://platform.agentscope.io/plugins/pawgit)。

![PawGit 插件页面](https://img.alicdn.com/imgextra/i1/O1CN01d0hBui28YrtUkYTK4_!!6000000007945-2-tps-1366-680.png)

它会在 workspace 里维护一个私有目录：

```text
<workspace>/.pawgit/
```

你可以把它理解成 Agent 的存档槽。里面有一个影子 Git 仓库，用来保存 PawGit 自己的检查点。这个仓库不接管你的项目，也不要求你的业务代码必须使用 Git。它只是借用了 Git 对象存储和 ref 管理的能力，来保存 Agent 工作过程中的状态快照。目录结构如下：

```text
<workspace>/.pawgit/
|-- shadow.git/    # PawGit 私有 Git 仓库
|-- index          # PawGit 自己使用的 Git index
|-- config.toml    # PawGit 配置
|-- heads.json     # 每个 session 的逻辑 HEAD
```

每次创建检查点时，PawGit 会捕获 workspace 中需要纳入管理的内容，写成一个独立的 Git tree。这里有个细节需要提一下：**PawGit 的 checkpoint commit 是 parentless commit**。也就是说，这里设计的每个检查点都是一个独立快照，不靠 Git commit parent 链表达历史。真正的会话时间线 DAG，是 PawGit 自己通过 metadata 和 `heads.json` 维护的。

那么为什么要这么设计？

因为 PawGit 关心的不是源码历史，而是 Agent 状态历史。它需要的是**快速创建**、**快速定位**、可以**快速清理**、可以**回滚的状态点**，而不是一条传统代码提交链。设计成 parentless commit，那么 GC 的时候就能快速清理大多没用的检查点。

## 二、PawGit 的使用介绍：Rewind、Timeline、GC 与 Reset

这一部分集中介绍 PawGit 的核心能力。实际使用时，不需要记住内部实现，只需要理解几个动作：先通过 snapshot 建立恢复点，再用 timeline 查看状态路径；真正回滚前先 dry-run，确认后再 rewind；自动快照过多时使用 GC；如果需要清空 PawGit 自己的存档系统，再使用 reset。

### 1. Snapshot：创建稳定恢复点

有了 PawGit，现在用 QwenPaw 做稍微有风险的 Agent 任务前，我会先打一条命名快照。

```bash
/pawgit snapshot before-runtime-refactor
```

虽然每个回复后也会自动进行快照，但是手动快照可以自定义一个好用的名字，而且不会被 GC 清理。这个动作很小，但心理负担会立刻变轻。

![在关键任务开始前创建命名快照](https://img.alicdn.com/imgextra/i3/O1CN01Z9WH0k1PROiyJIykS_!!6000000001837-2-tps-853-232.png)

接下来我可以放心让 QwenPaw 去读代码、比较方案、尝试实现，而不用担心一旦聊偏，就只能在一团脏上下文里继续硬撑。命名快照会进入 PawGit 的永久快照区域，它不会被普通 GC 清掉：

```text
refs/snap/
```

相比自动快照，我更喜欢在关键节点手动命名。因为几天之后，`before-runtime-refactor` 仍然比“第 17 个自动检查点”更容易理解。

### 2. Timeline：查看检查点与状态历史

我认为最适合 PawGit 的时刻，是你突然意识到：这个会话已经不对劲了。常见信号大概有：

- 它又开始提一个已经否掉的方案。
- 它反复解释一个不重要的兼容分支。
- 你说“不要动核心代码”，它表面答应了，但后续分析里总是默认可以改核心。
- 它已经在几个方向之间来回折返，导致每个回答都带着一点旧方案的残留。

这时你可以先看时间线：

```bash
/pawgit timeline
```

你会看到当前会话里有哪些检查点，包括自动检查点、手动 snapshot，以及真正 rewind 前创建的安全备份。

![通过 timeline 查看当前会话的检查点](https://img.alicdn.com/imgextra/i1/O1CN01xOJkHY1FEtl1isRJT_!!6000000000456-2-tps-1047-976.png)

概念上，它会像这样：

```text
# PawGit Timeline

## Checkpoint Graph

`*` HEAD, `o` active path, `x` branch

ROOT
\-- o #1 auto 40d652e48fa5
    \-- * #2 snap before-runtime-refactor 92d92e8808fd
```

几个符号很直观：

```text
*  当前 session HEAD
o  当前活跃路径
x  rewind 后留下的分支
```

在最新的 PawGit 0.2 版本里面，也提供了一个 UI 页面来更好地查看检查点视图。在这里，可以更直观地看到各个阶段之间的时间关系和具体信息。

![PawGit UI 中的检查点视图](https://img.alicdn.com/imgextra/i1/O1CN01VGvGmE1VRIKVP23j3_!!6000000002649-2-tps-1771-794.png)

根据 `/pawgit timeline` 的输出信息，你可以用序号回滚：

```bash
/pawgit rewind 1
```

也可以用 snapshot 名称：

```bash
/pawgit rewind before-runtime-refactor
```

或者用 commit SHA 前缀：

```bash
/pawgit rewind 92d92e8808fd
```

但我建议不要直接回滚。先 dry-run。

```bash
/pawgit rewind before-runtime-refactor --dry-run
```

dry-run 不会写文件，不会移动 HEAD，也不会真的改变当前会话。它只是告诉你：如果执行真实 rewind，会恢复哪些东西。

![执行 rewind 前先 dry-run 预览影响范围](https://img.alicdn.com/imgextra/i2/O1CN01TFA2pa20fitbYvAMF_!!6000000006877-2-tps-953-362.png)

这个步骤很重要。因为“想回到过去”和“真的回到某个过去状态”之间，最好隔着一次预览。

### 3. Slash Command、Skill 与 Tool：多入口使用 PawGit

看到这里，你可能会觉得：怎么都需要手动输入 command，好麻烦。别着急，PawGit 也提供了 skill 和 tool。除了手动输入这些 slash command，PawGit 也配备了相关的 skill 和 tool，可以在技能和工具页面查看。目前针对 QwenPaw 2.0 的版本正在开发；在 1.0 版本中，skill 的名称为 `pawgit`。

![PawGit skill 页面](https://img.alicdn.com/imgextra/i2/O1CN016Dta6X1e9jgg24tzt_!!6000000003829-2-tps-1282-812.png)

![PawGit tool 页面](https://img.alicdn.com/imgextra/i2/O1CN01HFd2Fk1gHBMH1Ao5Z_!!6000000004116-2-tps-2154-842.png)

也就是说，除了真正执行 `/pawgit rewind`，其他命令都可以直接问 Agent，或者直接让它帮我们执行。

比如让 Agent 帮我查看 timeline：

![让 Agent 帮忙查看 PawGit timeline](https://img.alicdn.com/imgextra/i3/O1CN01EFxrMO1xajjikUykz_!!6000000006460-2-tps-940-811.png)

再比如让 Agent 教我如何使用 PawGit：

![让 Agent 解释 PawGit 的使用方式](https://img.alicdn.com/imgextra/i3/O1CN01l53HPa1n6NK66TWQz_!!6000000005040-2-tps-956-1156.png)

这里有一条安全边界：因为 rewind 会进行文件修改，会直接影响 Agent 的运行状态，所以无论任何时候，Agent 都不会自己执行真实 rewind。它最多会允许带有 `--dry-run` 参数的 rewind。真正的 rewind，还是交给人类手动执行。

### 4. Rewind：恢复当前会话状态

确认 dry-run 没问题后，可以执行：

```bash
/pawgit rewind before-runtime-refactor
```

![执行普通 rewind](https://img.alicdn.com/imgextra/i3/O1CN01f20Kf51EOED6NGg00_!!6000000000341-2-tps-927-362.png)

普通 rewind 的边界很克制。它只恢复当前会话的 session JSON。也就是说，它不会回滚你的项目代码，不会乱动 workspace 里的任意文件，也不会顺手改掉 `MEMORY.md`。

它解决的是一个非常具体的问题：

> 我不想新开窗口。
> 我也不想继续背着脏上下文。
> 我只想让这个会话回到之前某个干净状态。

这也是 PawGit 和普通 Git 最大的区别之一。Git 管的是项目文件历史。PawGit 管的是 Agent 会话状态历史。这两个东西互补，但不是一回事。

### 5. Memory Rewind：处理长期记忆污染

有时问题不只在当前会话。比如你让 Agent 总结项目约定，它写进了：

```text
MEMORY.md
memory/
```

后来你发现这份总结是错的，或者已经过时了。这就麻烦了。这些文件往往是 workspace 级别共享的。后续新会话可能会继续读取它们。也就是说，错误不再只是“当前聊天里的错误”，而变成了长期记忆污染。

这时可以使用记忆回滚：

```bash
/pawgit rewind before-memory-change --include-memory --dry-run
```

确认之后，再执行：

```bash
/pawgit rewind before-memory-change --include-memory --confirm
```

![执行带 include-memory 的记忆回滚](https://img.alicdn.com/imgextra/i2/O1CN01DHssFo28UHvwZsORq_!!6000000007935-2-tps-912-403.png)

这条命令必须加 `--confirm`。这是故意设计的。因为 `--include-memory` 会恢复：

```text
当前会话 JSON
MEMORY.md
memory/
```

而 `MEMORY.md` 和 `memory/` 可能影响多个会话。你在一个会话里回滚它们，可能会丢掉另一个会话在目标检查点之后写进去的记忆。所以 PawGit 不允许你轻飘飘地执行记忆回滚。它要求你先 dry-run，再 confirm。

### 6. 安全边界：真实 Rewind 必须由用户触发

PawGit 有两种入口。

一种是用户直接输入 slash command：

```bash
/pawgit timeline
/pawgit snapshot before-refactor
/pawgit rewind 1
```

另一种是 Agent tool 里面提供的方式：

```python
pawgit(action="timeline", limit=10)
pawgit(action="snapshot", message="before-risky-change")
pawgit(action="rewind", target="1", dry_run=true)
pawgit(action="gc", dry_run=true)
```

但有一条安全线：

> Agent tool 可以做 rewind dry-run，但不能执行真实 rewind。
> 如果 Agent 尝试执行真实回滚，PawGit 会要求走 slash command。

这点很重要。因为真实 rewind 会修改当前会话状态。如果允许 Agent 在工具调用里直接改写自己正在依赖的上下文，就会出现一种很绕的递归风险：它一边思考，一边把“自己为什么这么思考”的依据换掉。

所以真实 rewind 必须由用户显式触发。Agent 可以帮你看 timeline，可以帮你解释风险，可以帮你做 dry-run。但最后那一下，应该是人按下去的。

### 7. GC：控制自动检查点生命周期

除了手动 snapshot，PawGit 也会在 Agent 每次回复后创建自动检查点。这些检查点会存进：

```text
refs/auto/
```

为了避免过于频繁的 auto snapshot ，它有防抖配置：

```toml
[auto]
debounce_seconds = 1.5
```

自动检查点适合处理“刚才那几轮聊偏了，我想回到前面一点”的场景。但自动快照不能无限增长，所以 PawGit 也有 GC：

```bash
/pawgit gc --dry-run
/pawgit gc
```

默认配置大概是：

```toml
[gc]
gc_keep_count = 20
gc_keep_days = 7
pre_rewind_retention_days = 7
```

也就是说，每个会话保留最近的一批自动检查点，保留一定天数内的 auto 和 pre-rewind，手动 snapshot 则始终保留。

如果你想更激进地清理，加上"--compact"：

```bash
/pawgit gc --compact
```

如果想清理所有会话，加上"--all-sessions"：

```bash
/pawgit gc --all-sessions
```

不过我一般建议先 dry-run。PawGit 的大部分危险动作都应该先预览。

### 8. Reset：清空 PawGit 状态而非回滚项目

如果你想完全清掉 PawGit 自己的状态，可以：

```bash
/pawgit reset --confirm
```

它会删除并重建：

```text
.pawgit/
```

也就是清掉 PawGit 的检查点、refs、timeline metadata 和配置。但它不会修改：

```text
项目文件
当前 session JSON
MEMORY.md
memory/
```

所以 reset 的意思不是“恢复 workspace”，而是“清空 PawGit 的存档系统”。

## 三、推荐使用流程：在真实 Agent 工作中如何使用 PawGit

如果只是日常工作，我觉得记住几套流程就够了。

### 1. 长任务开始前创建快照

```bash
/pawgit snapshot before-long-session
```

### 2. 上下文异常时先预览再回滚

```bash
/pawgit timeline
/pawgit rewind 2 --dry-run
/pawgit rewind 2
```

### 3. 长期记忆异常时使用 Memory Rewind

```bash
/pawgit timeline
/pawgit rewind before-good-memory --include-memory --dry-run
/pawgit rewind before-good-memory --include-memory --confirm
```

### 4. 定期清理旧自动快照

```bash
/pawgit gc --dry-run
/pawgit gc
```

### 5. 清空 PawGit 存档状态

```bash
/pawgit reset --confirm
```

就这些。PawGit 不需要你每天盯着它。它更像安全带。大部分时候你感觉不到它，但一旦长会话开始腐蚀，你会很庆幸之前系上快照了。

## 四、总结：为长会话提供可恢复的第三种选择

我不觉得 AI Agent 最大的问题是会犯错。人也会犯错，程序也会犯错，系统设计也会走弯路。真正麻烦的是错误状态被继承。一个错误的认知如果只停留在一条回复里，很容易被纠正。但如果它进入上下文，进入记忆，进入后续几十轮推理，它就会变成一种认知债务。你会花越来越多时间纠偏，而不是推进任务。

这也是为什么我越来越觉得，Agent 系统需要的不只是更长上下文、更强模型、更丰富工具。它还需要可恢复性。

需要 checkpoint。

需要 dry-run。

需要 rewind。

需要在“新开窗口重喂 prompt”和“忍着脏上下文继续聊”之间，提供第三种选择。

PawGit 想做的就是这个。它不保证 Agent 永远不犯错。它只是承认 Agent 会犯错，承认长会话会腐蚀，承认上下文有时会变脏。然后给你一个体面地回到过去的办法。

写在最后，虽然 cc 使用了某些魔法不让大家使用，但是仍然感谢 cc 的 rewind 设计为 PawGit 的实现提供了参考。
