---
title: "Agent 会话“存档点”：QwenPaw Checkpoint 功能展示"
date: 2026-08-07
author: QwenPaw Team
tags: [Checkpoint, 会话恢复, 状态管理]
cover: https://img.alicdn.com/imgextra/i3/O1CN01LXaNPg4UfYB3rvs1_!!6000000007061-2-tps-1906-943.png
excerpt: "QwenPaw Checkpoint 可以保存 Agent 的会话状态，并按需恢复长期记忆和工作区文件，让走偏的对话回到正确的时间线。"
---

# 给 Agent 会话加个“存档点”：QwenPaw Checkpoint 来了 🎮

和 Agent 对话时，偶尔会遇到这种情况：某一步理解错了，后面的内容也跟着越走越偏。继续纠正，错误上下文还留在会话里；重新开始，又得把背景和需求全部讲一遍。QwenPaw Checkpoint 就是为这种情况准备的。它可以保存会话状态，并在需要时回到之前的节点继续。

> 简单说：**对话走偏了，不用从头再来，回到还没走偏的时候就好。**

## 1. 功能说明

Checkpoint 类似游戏里的存档点。你可以在需求确认、功能完成或高风险操作开始前创建快照，之后再从这个节点恢复。每次恢复都会包含当前会话，另外还可以按需选择长期记忆和工作区文件：

| 恢复范围   | 默认状态 | 内容                      |
| ---------- | -------- | ------------------------- |
| 当前会话   | 包含     | 会话文件和 Agent 对话状态 |
| 长期记忆   | 不包含   | `MEMORY.md` 和 `memory/`  |
| 工作区文件 | 不包含   | 预览后明确选中的文件      |

Checkpoint 主要包含三种节点：

- **命名快照**：手动创建，适合保存重要状态，不参与自动 GC；
- **自动检查点**：开启后由系统自动记录，按照数量和时间规则清理；
- **恢复前安全点**：真正恢复前自动创建，避免恢复后想反悔却没有退路。

恢复旧节点后继续对话，会形成新的时间线分支，后面的历史不会直接消失。页面中的 **HEAD** 表示当前会话所在的检查点。

Checkpoint 的数据保存在当前 Agent 工作区，并与项目自身的 `.git/` 分离。它不会创建项目提交、切换项目分支或改写 Git 历史。它更适合日常会话回滚，不是整机备份或跨设备迁移工具。

![Checkpoint 状态检查点页面](https://img.alicdn.com/imgextra/i3/O1CN01LXaNPg4UfYB3rvs1_!!6000000007061-2-tps-1906-943.png)

## 2. 命令总览

Checkpoint 可以在 Console 页面中操作，也可以直接在聊天中使用魔法命令。

![在聊天中查看 Checkpoint 命令](https://img.alicdn.com/imgextra/i2/O1CN01ygWpyuERcQG2b85m_!!6000000000472-1-tps-1280-638.gif)

| 命令                                          | 说明                         |
| --------------------------------------------- | ---------------------------- |
| `/checkpoint`                                 | 查看命令帮助                 |
| `/checkpoint auto [on\|off]`                  | 查看、开启或关闭自动检查点   |
| `/checkpoint snapshot [名称]`                 | 创建命名快照                 |
| `/checkpoint timeline [--limit=N] [--all]`    | 查看检查点历史               |
| `/checkpoint restore <目标> [选项]`           | 预览或执行恢复               |
| `/checkpoint gc [--all-sessions] [--compact]` | 预览或清理旧检查点           |
| `/checkpoint reset --confirm`                 | 清空检查点历史并恢复默认配置 |

恢复目标可以写成时间线编号（如 `#3`）、命名快照或至少 7 位的 SHA 前缀。日常使用时，记住下面几个参数基本就够了：

| 参数                | 作用                         |
| ------------------- | ---------------------------- |
| `--dry-run`         | 只预览变化，不实际恢复或清理 |
| `--confirm`         | 确认执行操作                 |
| `--include-memory`  | 恢复时包含长期记忆           |
| `--include-files`   | 恢复时包含工作区文件         |
| `--files <路径...>` | 指定要恢复或删除的工作区文件 |
| `--all-sessions`    | GC 时处理工作区内的全部会话  |
| `--compact`         | 删除所有非 HEAD 自动检查点   |

一个常见的命令流程如下：

```text
/checkpoint snapshot demo-start
/checkpoint auto on
/checkpoint timeline
/checkpoint restore demo-start --dry-run
/checkpoint restore demo-start --confirm
```

建议先执行 `--dry-run`，确认目标和变化后再使用 `--confirm`。两者不能同时使用。

如果需要恢复工作区文件，可以先查看候选差异：

```text
/checkpoint restore demo-start --include-files --dry-run
```

确认后再指定路径：

```text
/checkpoint restore demo-start --include-files --files checkpoint-demo/state.txt checkpoint-demo/temp.txt --confirm
```

如果某个已选文件在目标检查点中不存在，恢复时会删除当前文件。预览会明确标记这类操作，执行前记得看一眼。

## 3. 功能展示

下面用一个简单的文件修改场景，看看 Checkpoint 怎么把走偏的会话和文件一起恢复。

### 创建基线状态

先让 Agent 创建 `checkpoint-demo/state.txt`：

```text
Checkpoint Demo
version=1
status=baseline
```

此时会话和文件都处于正确状态。进入「工作区 → 状态检查点」，点击「创建快照」，将它命名为 `demo-start`。如果希望后续状态自动被记录，也可以打开右上角的「自动检查点」。

![创建 demo-start 快照](https://img.alicdn.com/imgextra/i4/O1CN01SFtF4KZZWqF2b85m_!!6000000008121-1-tps-1280-638.gif)

### 修改文件，让状态发生变化

接着让 Agent 把 `state.txt` 改成：

```text
Checkpoint Demo
version=2
status=modified
```

同时新建 `checkpoint-demo/temp.txt`：

```text
temporary=true
```

回到检查点页面，可以看到时间线上已经出现新的自动检查点，当前 HEAD 也向前移动。

![命名快照和自动检查点](https://img.alicdn.com/imgextra/i3/O1CN01dETNOWraAFB5CGBb_!!6000000007332-2-tps-2560-1279.png)

### 预览并恢复

选中 `demo-start`，点击「恢复」，勾选「工作区文件」，然后先预览变化。

在这个例子中，预览结果会包含：

- `checkpoint-demo/state.txt`：恢复；
- `checkpoint-demo/temp.txt`：删除。

`temp.txt` 是在目标快照之后才创建的，所以恢复到 `demo-start` 时会被删除。确认文件列表后，执行恢复即可。

![预览并恢复工作区文件](https://img.alicdn.com/imgextra/i1/O1CN01e0eWox9nnTI2b85m_!!6000000004176-1-tps-1280-638.gif)

恢复完成后再次读取 `state.txt`，内容已经回到：

```text
Checkpoint Demo
version=1
status=baseline
```

快照之后创建的 `temp.txt` 也已经消失。更重要的是，会话本身同样回到了快照时的状态，之前走偏的上下文不会再继续影响对话。

恢复后，时间线会保留原来的历史，并生成恢复前安全点。自动检查点积累较多时，可以通过 Console 或下面的命令先预览 GC：

```text
/checkpoint gc --dry-run
/checkpoint gc --confirm
```

如果需要更彻底地压缩历史，可以使用 `--compact`。命名快照和会话 HEAD 仍会保留。

![清理检查点](https://img.alicdn.com/imgextra/i1/O1CN01y0la0Zgm81F2b85m_!!6000000007125-1-tps-1280-638.gif)

Checkpoint 的目标并不是让我们频繁撤销，而是在 Agent 理解偏离预期时，提供一个可靠的返回点。找到之前保存的状态，预览变化，然后恢复——会话还在，重要上下文还在，工作也能从正确的位置继续。🙂
