# 魔法命令

魔法命令是一组以 `/` 开头的特殊指令，让你可以**直接控制对话状态**，而不需要等 AI 理解你的意图。

### 上下文管理

| 命令       | 需要等待 | 压缩摘要      | 长期记忆    | 返回内容             |
| ---------- | -------- | ------------- | ----------- | -------------------- |
| `/compact` | ⏳ 是    | 📦 生成新摘要 | ✅ 后台保存 | ✅ 压缩完成 + 新摘要 |
| `/new`     | ⚡ 否    | 🗑️ 清空       | ✅ 后台保存 | ✅ 新对话开始提示    |
| `/clear`   | ⚡ 否    | 🗑️ 清空       | ❌ 不保存   | ✅ 历史清空提示      |

### 上下文调试

| 命令            | 返回内容                 |
| --------------- | ------------------------ |
| `/history`      | 📋 消息列表 + Token 统计 |
| `/message`      | 📄 指定消息详情          |
| `/compact_str`  | 📝 压缩摘要内容          |
| `/dump_history` | 📁 历史导出文件路径      |
| `/load_history` | ✅ 历史加载结果          |

---

## /history - 查看当前对话历史

显示当前对话中所有未压缩的消息列表，以及详细的**上下文占用情况**。

```
/history
```

**返回示例：**

```
**Conversation History**

- Total messages: 3
- Estimated tokens: 1256
- Max input length: 128000
- Context usage: 0.98%
- Compressed summary tokens: 128

[1] **user** (text_tokens=42)
    content: [text(tokens=42)]
    preview: 帮我写一个 Python 函数...

[2] **assistant** (text_tokens=256)
    content: [text(tokens=256)]
    preview: 好的，我来帮你写一个函数...

[3] **user** (text_tokens=28)
    content: [text(tokens=28)]
    preview: 能不能加上错误处理？
```

> 💡 **提示**：建议多使用 `/history` 命令了解当前上下文占用情况。
>
> 当 `Context usage` 接近 75% 时，对话即将触发自动 `compact`。
>
> 如果出现上下文超过最大上限的情况，请向社区反馈对应的模型和 `/history` 日志，然后主动使用 `/compact` 或 `/new` 来管理上下文。
>
> Token计算逻辑详见 [ReMeInMemoryMemory 实现](https://github.com/agentscope-ai/ReMe/blob/v0.3.0.6b2/reme/memory/file_based/reme_in_memory_memory.py#L122)。

---

## /message - 查看单条消息

查看当前对话中指定索引的消息详细内容。

```
/message <index>
```

**参数：**

- `index` - 消息索引号（从 1 开始）

**返回示例：**

```
/message 1
```

**输出：**

```
**Message 1/3**

- **Timestamp:** 2024-01-15 10:30:00
- **Name:** user
- **Role:** user
- **Content:**
帮我写一个 Python 函数，实现快速排序算法
```

---

## /compact_str - 查看压缩摘要

显示当前的压缩摘要内容。

```
/compact_str
```

**返回示例（有摘要时）：**

```
**Compressed Summary**

用户请求帮助构建用户认证系统，已完成登录接口的实现...
```

**返回示例（无摘要时）：**

```
**No Compressed Summary**

- No summary has been generated yet
- Use /compact or wait for auto-compaction
```

---

## /compact - 压缩当前对话

手动触发对话压缩，将当前对话消息浓缩成摘要（**需要等待**），同时后台保存到长期记忆。

```
/compact
```

**返回示例：**

```
**Compact Complete!**

- Messages compacted: 12
**Compressed Summary:**
用户请求帮助构建用户认证系统，已完成登录接口的实现...
- Summary task started in background
```

> 💡 与自动压缩不同，`/compact` 会压缩**所有**当前消息，而不是只压缩超出阈值的部分。

---

## /new - 清空上下文并保存记忆

**立即清空当前上下文**，开始全新对话。后台同时保存历史到长期记忆。

```
/new
```

**返回示例：**

```
**New Conversation Started!**

- Summary task started in background
- Ready for new conversation
```

---

## /clear - 清空上下文（不保存记忆）

**立即清空当前上下文**，包括消息历史和压缩摘要。**不会**保存到长期记忆。

```
/clear
```

**返回示例：**

```
**History Cleared!**

- Compressed summary reset
- Memory is now empty
```

> ⚠️ **警告**：`/clear` 是**不可逆**的！与 `/new` 不同，清除的内容不会被保存。

---

## /dump_history - 导出对话历史

将当前对话历史（包括压缩摘要）保存到 JSONL 文件，便于调试和备份。

```
/dump_history
```

**返回示例：**

```
**History Dumped!**

- Messages saved: 15
- Has summary: true
- File: `/path/to/workspace/debug_history.jsonl`
```

> 💡 **提示**：导出的文件可用于 `/load_history` 恢复对话历史，也可用于调试分析。

---

## /load_history - 加载对话历史

从 JSONL 文件加载对话历史到当前内存，**会先清空现有内存**。

```
/load_history
```

**返回示例：**

```
**History Loaded!**

- Messages loaded: 15
- Has summary: true
- File: `/path/to/workspace/debug_history.jsonl`
- Memory cleared before loading
```

**注意事项：**

- 文件来源：从工作目录下的 `debug_history.jsonl` 加载
- 最大加载：10000 条消息
- 如果文件第一条消息包含压缩摘要标记，会自动恢复压缩摘要
- 加载前会**清空当前内存**，请确保已备份重要内容

> ⚠️ **警告**：`/load_history` 会清空当前内存后再加载，现有对话将丢失！

---

## 控制命令（即时响应）

控制命令具有最高优先级，会立即处理，无需等待正在运行的任务完成。适用于紧急操作场景。

| 命令                         | 说明                           |
| ---------------------------- | ------------------------------ |
| `/stop`                      | 立即终止当前会话的运行中任务   |
| `/stop session=<session_id>` | 终止指定会话的任务（可选参数） |

### `/stop` - 停止任务

立即终止当前会话中正在执行的 Agent 任务。

**用法**：

```
/stop                       # 停止当前会话的任务
/stop session=<session_id>  # 停止指定会话的任务（高级用法）
```

**特性**：

- **立即响应**：优先级最高（priority=0），即使有任务正在执行也能并发处理
- **安全终止**：通过 `task_tracker.request_stop()` 优雅地取消任务
- **会话隔离**：只影响目标会话，不影响其他用户或会话
- **默认当前会话**：不带参数时终止当前会话的任务

**使用场景**：

- Agent 陷入循环或长时间无响应
- 任务执行错误需要立即中断
- 不想等待当前任务完成

**示例**：

```
用户：帮我分析这个 10GB 的日志文件
Agent：[开始处理...]

用户：/stop
系统：**Task Stopped** - Task for session `console:user1` has been terminated.
```

> ⚠️ **注意**：`/stop` 会立即终止任务，可能导致部分结果丢失。

---

## Daemon 命令（运维）

在对话中发送 `/daemon <子命令>` 或在终端执行 `copaw daemon <子命令>`，可查看状态、最近日志、版本等，无需经过 Agent。支持短名（如
`/status` 等价于 `/daemon status`）。

| 命令                                | 说明                                                                   |
| ----------------------------------- | ---------------------------------------------------------------------- |
| `/daemon status` 或 `/status`       | 查看运行状态（配置、工作目录、记忆服务等）                             |
| `/daemon restart` 或 `/restart`     | 在对话中为进程内重启（频道、定时任务、MCP）；在 CLI 下仅打印说明       |
| `/daemon reload-config`             | 重新读取并校验配置（频道/MCP 变更需 /daemon restart 或重启进程后生效） |
| `/daemon version`                   | 版本号与工作目录、日志路径                                             |
| `/daemon logs` 或 `/daemon logs 50` | 查看最近 N 行控制台日志（默认 100 行，来自工作目录下 `copaw.log`）     |

终端中可直接使用：

```bash
copaw daemon status
copaw daemon version
copaw daemon logs -n 50
```
