# 终端界面（TUI）

QwenPaw **终端界面（TUI）** 是一个完全运行在终端里的全屏聊天界面。它连接的是与控制台、IM 频道**完全相同**的智能体——同一份记忆、同一套技能、同样的 MCP 工具、同样的会话——但你无需离开键盘。如果你习惯待在终端里，这是与智能体对话、推进任务，或接续在别处开启的会话的最快方式。

它也是 **Coding 模式** 最自然的入口：在某个代码仓库目录中启动，智能体就会把该目录当作它的工作场所。

![QwenPaw 终端界面](https://img.alicdn.com/imgextra/i2/O1CN01IULzib1TRAzigIcqG_!!6000000002378-2-tps-2350-1312.png)

---

## 启动方式

终端界面随 `qwenpaw` 命令行工具一同提供。直接运行不带参数的 `qwenpaw` 即可打开：

```bash
qwenpaw                       # 与当前激活的智能体开启对话
qwenpaw tui                   # 同上，可显式指定选项
qwenpaw tui --agent NAME      # 与指定的智能体对话
qwenpaw tui --resume <id>     # 恢复并继续之前的某个会话
```

要开启**绑定项目（Coding 模式）** 的会话，给它指定一个目录：

```bash
qwenpaw .                     # 以当前目录作为项目
qwenpaw tui /path/to/repo     # 指定一个明确的目录
```

这只会为**当前这次终端会话**启用 Coding 模式的提示词与工具行为——并不会改动 `agent.json` 中保存的项目，也不会改变控制台里选中的项目。关于底层会发生哪些变化，详见 [Coding 模式](/docs/coding-mode)。

> 无需单独安装或维护服务：终端界面会用它自带的解释器启动属于自己的 `qwenpaw acp` 后端，因此它驱动的始终是与你的 `qwenpaw` 命令相同的安装环境 / 虚拟环境。

---

## 界面布局

| 区域               | 展示内容                                                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| **状态栏**（顶部） | 当前智能体、模型、会话 id、实时 token 用量（`tok ↑输入 ↓输出`），以及忙碌 / 就绪状态指示。                              |
| **对话区**（中部） | 对话内容——你的消息、智能体的回复、可折叠的*思考*与*工具调用*面板、计划，以及文件链接。                                  |
| **输入框**（底部） | 你输入的地方。提示行会列出核心操作：`/` 唤起命令、`enter` 发送、`shift+enter` 换行、`esc` 中断，以及粘贴文件 / 长文本。 |

---

## 基础功能

**流式对话。** 回复以 token 为单位流式呈现。智能体的推理过程和每一次工具调用都会以可折叠面板的形式出现，方便你随时跟进或将其收起。

**忙碌时排队。** 你不必等当前回合结束。输入内容后按 `enter`，消息会进入**排队**，并在当前回合结束时自动发送。按 `up` 可以唤回并编辑最近一条排队消息。

**中断。** 按 `esc` 取消正在进行的回合（如果你还没发送，则会清空输入框）。

**会话与恢复。** 每段对话都是一个会话，并与 QwenPaw 的其余部分共享。用 `/resume` 从建议列表中挑选最近的会话，或用 `/resume list` 浏览全部会话。你也可以在启动时用 `qwenpaw tui --resume <id>` 直接恢复。

**粘贴文件与长文本。** 粘贴一张图片或一个文件路径，终端界面会将其作为附件交给智能体；粘贴一大段文本时，它会被存为附件，而不会塞满输入框。`data:` URL 同样适用。

**工具授权。** 当智能体想运行一个需要你批准的工具时，会就地弹出授权提示——无需离开终端界面即可批准或拒绝。

**检视模式。** 切换 `/inspect`（或按 `ctrl+i`）可展开更深层的思考与工具调用细节，方便你看清智能体到底在做什么。

**主题。** 运行 `/theme` 打开主题库，或用 `/theme <氛围词>` 把背景换成某个命名主题或一段自由描述的风格。

---

## 键盘快捷键

| 按键                | 操作                                  |
| ------------------- | ------------------------------------- |
| `enter`             | 发送消息（智能体忙碌时则排队）        |
| `shift+enter`       | 插入换行                              |
| `esc`               | 中断当前回合 / 清空输入框             |
| `up`                | 唤回并编辑最近一条排队消息            |
| `ctrl+i`            | 切换检视模式（更深的思考 / 工具细节） |
| `ctrl+t`            | 隐藏 / 显示工具调用面板               |
| `ctrl+c` / `ctrl+q` | 退出                                  |

---

## 斜杠命令

在输入框中输入 `/` 即可获得行内自动补全建议。命令分为两类。

### 由终端界面处理

这些命令控制终端界面本身：

| 命令       | 作用                                            |
| ---------- | ----------------------------------------------- |
| `/help`    | 显示终端界面的快捷键与命令提示                  |
| `/resume`  | 恢复最近的会话（`/resume list` 浏览全部）       |
| `/theme`   | 打开主题库，或用 `/theme <氛围词>` 套用某个主题 |
| `/inspect` | 切换更深的思考 / 工具调用细节                   |

### 由智能体处理

其余所有以 `/` 开头的输入都会转发给 QwenPaw 智能体——也就是控制台和频道中**同样的魔法命令**，例如 `/model`、`/clear`、`/compact`、`/skills`、`/status`。终端界面会展示所连接智能体支持的全部命令，因此建议列表始终与你的智能体保持一致。完整清单见 [魔法命令](/docs/commands)。

---

## 工作原理

使用终端界面无需了解其内部机制，但一段简短的心智模型有助于理解为什么会话、记忆和工具能像在其他地方一样“开箱即用”。

终端界面是一个轻量**客户端**。它是一个基于 [Textual](https://textual.textualize.io/) 的终端应用，通过 **ACP**（[Agent Client Protocol](/docs/acp-integration)）驱动本地的 QwenPaw 后端。启动时它会以子进程方式拉起 `qwenpaw acp` 并与之进行 ACP 通信；所有真正的工作——模型调用、记忆、技能、MCP 工具、会话存储——都发生在那个后端里，正是控制台和频道所使用的同一个后端。

<svg viewBox="0 0 760 220" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="QwenPaw 终端界面是一个轻量的 Textual 客户端，通过 ACP 以 stdio 子进程方式驱动本地的 qwenpaw acp 后端。" style="width:100%;height:auto;max-width:700px;display:block;margin:1.5rem auto;font-family:ui-sans-serif,system-ui,sans-serif;">
<defs>
<marker id="tui-arrow" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto" markerUnits="userSpaceOnUse">
<path d="M0,0 L7,3 L0,6 Z" fill="var(--color-primary, #ff9d4d)"></path>
</marker>
</defs>
<rect x="24" y="62" width="244" height="96" rx="12" fill="var(--color-primary, #ff9d4d)" fill-opacity="0.08" stroke="var(--color-primary, #ff9d4d)" stroke-width="1.5"></rect>
<text x="146" y="98" text-anchor="middle" font-size="17" font-weight="700" fill="currentColor">QwenPaw TUI</text>
<text x="146" y="122" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">Textual 终端应用</text>
<text x="146" y="141" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">渲染 · 转发输入</text>
<rect x="492" y="52" width="244" height="116" rx="12" fill="currentColor" fill-opacity="0.04" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"></rect>
<text x="614" y="86" text-anchor="middle" font-size="17" font-weight="700" fill="currentColor">qwenpaw acp</text>
<text x="614" y="110" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">智能体 · LLM · 工具</text>
<text x="614" y="129" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">记忆 · 技能 · MCP</text>
<text x="614" y="148" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">会话存储</text>
<line x1="274" y1="100" x2="486" y2="100" stroke="var(--color-primary, #ff9d4d)" stroke-width="1.5" marker-end="url(#tui-arrow)"></line>
<line x1="486" y1="130" x2="274" y2="130" stroke="var(--color-primary, #ff9d4d)" stroke-width="1.5" marker-end="url(#tui-arrow)"></line>
<text x="380" y="90" text-anchor="middle" font-size="13" font-weight="600" fill="var(--color-primary, #ff9d4d)">ACP</text>
<text x="380" y="152" text-anchor="middle" font-size="12" fill="currentColor" opacity="0.6">stdio 子进程</text>
</svg>

由此带来两个实际好处：

- **会话是共享的。** 你在终端界面里开启的对话，之后会出现在 `/resume` 中；你也可以恢复一个最初在控制台或某个频道里开启的会话——它们共用同一份会话存储。
- **终端界面保持轻量。** 因为它只负责渲染与转发输入，启动很快，沉重的智能体运行时则位于后端进程中。

---

## 相关链接

- [Coding 模式](/docs/coding-mode) —— 在代码仓库中启动终端界面时会有哪些变化
- [魔法命令](/docs/commands) —— 智能体斜杠命令的完整列表
- [ACP 集成](/docs/acp-integration) —— 终端界面与后端通信所使用的协议
- [CLI](/docs/cli) —— 其他 `qwenpaw` 子命令
