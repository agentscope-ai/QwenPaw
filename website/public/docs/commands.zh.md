# 魔法命令

魔法命令是一组以 `/` 开头的特殊指令，让你可以**直接控制对话状态**，而不需要等 AI 理解你的意图。

| 命令           | 需要等待 | 压缩摘要      | 长期记忆    | 消息历史      | 上下文占用          |
| -------------- | -------- | ------------- | ----------- | ------------- | ------------------- |
| `/compact`     | ⏳ 是    | 📦 生成新摘要 | ✅ 后台保存 | 🏷️ 标记已压缩 | -                   |
| `/new`         | ⚡ 否    | 🗑️ 清空       | ✅ 后台保存 | 🏷️ 标记已压缩 | -                   |
| `/clear`       | ⚡ 否    | 🗑️ 清空       | ❌ 不保存   | 🗑️ 完全清空   | -                   |
| `/history`     | ⚡ 否    | -             | -           | 📖 只读查看   | 📊 Token明细+使用率 |
| `/compact_str` | ⚡ 否    | -             | -           | -             | 📖 查看摘要内容     |

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

> 💡 **提示**：建议多使用 `/history` 命令了解当前上下文占用情况。当 `Context usage` 接近 100% 时，说明对话即将触发自动压缩，此时可以主动使用 `/compact` 或 `/new` 来管理上下文。

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

## Daemon 命令（运维）

在对话中发送 `/daemon <子命令>` 或在终端执行 `copaw daemon <子命令>`，可查看状态、最近日志、版本等，无需经过 Agent。支持短名（如 `/status` 等价于 `/daemon status`）。

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
