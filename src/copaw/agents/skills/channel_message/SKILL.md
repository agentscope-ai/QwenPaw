---
name: channel_message
description: Send messages to channels and users - use copaw chats list to query sessions, copaw channel send for one-way push (no reply) | 频道消息推送 - copaw chats list 查询会话，copaw channel send 单向推送（无回复）
metadata: { "builtin_skill_version": "2.0", "copaw": { "emoji": "📤" } }
---

# Channel Message (频道消息推送)

## 一句话记住

`copaw channel send`：**发消息给用户/会话**，单向推送，**无回复**
- 必填：`--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text`（五个参数全部必填）

---

## 最小使用规则

### 1. 发消息前，必须先查 session

`send` 不能猜 `target-user` 和 `target-session`，必须先查：

```bash
copaw chats list --agent-id <your_agent> --channel <channel>
```

然后再发送：

```bash
copaw channel send \
  --agent-id <your_agent> \
  --channel <channel> \
  --target-user <user_id> \
  --target-session <session_id> \
  --text "..."
```

### 2. 五个参数全部必填

```bash
copaw channel send \
  --agent-id my_bot \          # 1. 发送方agent
  --channel console \           # 2. 目标频道
  --target-user alice \         # 3. 目标用户（从chats list获取）
  --target-session alice_001 \  # 4. 目标会话（从chats list获取）
  --text "任务完成"             # 5. 消息内容
```

缺少任何一个参数都会报错。

### 3. 这是单向推送，没有回复

`channel send` 只负责推送消息到频道，**不会等待或返回用户回复**。

如果需要双向对话，应该等待用户在频道中回复你的agent。

---

## 常用命令

### 查询可用 sessions

**基础查询**：

```bash
copaw chats list --agent-id my_bot
```

**按频道筛选**：

```bash
copaw chats list --agent-id my_bot --channel console
copaw chats list --agent-id my_bot --channel dingtalk
```

**按用户筛选**：

```bash
copaw chats list --agent-id my_bot --user-id alice
```

**输出格式**：

```json
[
  {
    "id": "chat_001",
    "user_id": "alice",
    "session_id": "alice_console_001",
    "channel": "console",
    "name": "Chat with Alice",
    "updated_at": "2024-03-20T10:30:00Z"
  },
  {
    "id": "chat_002",
    "user_id": "bob",
    "session_id": "bob_dingtalk_002",
    "channel": "dingtalk",
    "name": "Chat with Bob",
    "updated_at": "2024-03-20T09:15:00Z"
  }
]
```

**从输出中提取**：
- `user_id`：用于 `--target-user`
- `session_id`：用于 `--target-session`
- `channel`：用于 `--channel`

### 发送消息给用户

```bash
copaw channel send \
  --agent-id my_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "您的任务已完成！"
```

---

## 关键示例

### 示例 1：发消息给控制台用户

**步骤 1 - 查询可用sessions**：

```bash
copaw chats list --agent-id my_bot --channel console
```

**输出**：

```json
[
  {
    "id": "abc-123",
    "user_id": "alice",
    "session_id": "alice_console_001",
    "channel": "console",
    "name": "Alice Console Chat",
    "updated_at": "2024-03-20T10:30:00Z"
  }
]
```

**步骤 2 - 提取参数并发送**：

```bash
copaw channel send \
  --agent-id my_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "数据分析已完成，结果已保存到 report.pdf"
```

### 示例 2：使用 jq 自动化

```bash
# 查询并自动提取参数
SESSIONS=$(copaw chats list --agent-id bot --channel console)
USER=$(echo "$SESSIONS" | jq -r '.[0].user_id')
SESSION=$(echo "$SESSIONS" | jq -r '.[0].session_id')

# 发送消息
copaw channel send \
  --agent-id bot \
  --channel console \
  --target-user "$USER" \
  --target-session "$SESSION" \
  --text "自动化消息推送"
```

### 示例 3：发送到不同频道

**发送到钉钉**：

```bash
# 查询钉钉会话
copaw chats list --agent-id my_bot --channel dingtalk

# 发送
copaw channel send \
  --agent-id my_bot \
  --channel dingtalk \
  --target-user user_dingtalk_id \
  --target-session session_dingtalk_id \
  --text "钉钉通知：任务已完成"
```

**发送到飞书**：

```bash
# 查询飞书会话
copaw chats list --agent-id my_bot --channel feishu

# 发送
copaw channel send \
  --agent-id my_bot \
  --channel feishu \
  --target-user user_feishu_id \
  --target-session session_feishu_id \
  --text "飞书通知：系统已更新"
```

---

## 速记

**🔥 最重要的2件事**：
1. **send 前必须先 `copaw chats list`**：不能猜测 `target-user` 和 `target-session`
2. **五个参数全部必填**：`--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text`

---

## 完整参数说明

### copaw chats list

**必填参数**：
- `--agent-id`：Agent ID

**可选参数**：
- `--channel`：按频道筛选
- `--user-id`：按用户筛选
- `--limit`：返回数量限制（默认无限制）
- `--base-url`：覆盖API地址

### copaw channel send

**必填参数**（5个）：
- `--agent-id`：发送方agent ID
- `--channel`：目标频道（console/dingtalk/feishu/discord/imessage/qq）
- `--target-user`：目标用户ID（从 `copaw chats list` 获取）
- `--target-session`：目标会话ID（从 `copaw chats list` 获取）
- `--text`：消息内容

**可选参数**：
- `--base-url`：覆盖API地址

---

## 常见错误

### 错误 1：没查 session 就直接 send

```bash
# ❌ 错误：直接猜测参数
copaw channel send --agent-id bot --channel console \
  --target-user alice --target-session alice_session --text "hello"
```

**问题**：`target-user` 和 `target-session` 可能不存在或不匹配。

**正确做法**：

```bash
# 1. 先查询
copaw chats list --agent-id bot --channel console

# 2. 从输出中找到正确的 user_id 和 session_id

# 3. 再发送
copaw channel send --agent-id bot --channel console \
  --target-user <从查询结果获取> \
  --target-session <从查询结果获取> \
  --text "hello"
```

### 错误 2：缺少必填参数

```bash
# ❌ 错误：缺少 target-user
copaw channel send --agent-id bot --channel console \
  --target-session xxx --text "hello"

# ❌ 错误：缺少 target-session
copaw channel send --agent-id bot --channel console \
  --target-user alice --text "hello"

# ✅ 正确：五个参数都提供
copaw channel send \
  --agent-id bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "hello"
```

### 错误 3：期待收到回复

```bash
copaw channel send --agent-id bot --channel console \
  --target-user alice --target-session xxx --text "帮我分析数据"
# ❌ 问题：send 不会返回用户回复
```

**正确理解**：
- `copaw channel send` 是**单向推送**，不会等待或返回回复
- 如果用户回复了，agent会通过channel的正常消息流程收到（不是通过send命令）

---

## 工作流程图

```
┌─────────────────────────────────────────────────────────┐
│  1. 查询可用 sessions                                   │
│     copaw chats list --agent-id <your_agent> \          │
│       --channel <channel>                                │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  2. 从输出中提取参数                                    │
│     - user_id (用于 --target-user)                      │
│     - session_id (用于 --target-session)                │
│     - channel (用于 --channel)                          │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  3. 发送消息                                            │
│     copaw channel send \                                 │
│       --agent-id <your_agent> \                          │
│       --channel <channel> \                              │
│       --target-user <user_id> \                          │
│       --target-session <session_id> \                    │
│       --text "..."                                       │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  4. 消息推送成功                                        │
│     (无回复，单向推送完成)                              │
└─────────────────────────────────────────────────────────┘
```

---

## 支持的频道

以下是常见的频道类型（具体可用频道取决于配置）：

- `console` - 控制台/终端
- `dingtalk` - 钉钉
- `feishu` - 飞书
- `discord` - Discord
- `telegram` - Telegram
- `imessage` - iMessage
- `qq` - QQ
- `voice` - Twilio语音

使用前确保频道已配置：

```bash
copaw channel list --agent-id <your_agent>
```

---

## 使用场景

### 场景 1：任务完成通知

Agent完成任务后主动通知用户：

```bash
# 查询用户会话
copaw chats list --agent-id task_bot --channel dingtalk

# 发送完成通知
copaw channel send \
  --agent-id task_bot \
  --channel dingtalk \
  --target-user user_123 \
  --target-session session_456 \
  --text "✅ 数据处理任务已完成，共处理 1,234 条记录"
```

### 场景 2：定时提醒

Cron任务触发agent发送提醒：

```bash
# 每天早上9点提醒
copaw channel send \
  --agent-id reminder_bot \
  --channel feishu \
  --target-user manager_id \
  --target-session manager_session \
  --text "📅 今日待办事项：\n1. 团队周会 10:00\n2. 审核预算 14:00"
```

### 场景 3：异常报警

监控agent发现异常后推送告警：

```bash
copaw channel send \
  --agent-id monitor_bot \
  --channel console \
  --target-user admin \
  --target-session admin_console \
  --text "⚠️ 警告：服务器CPU使用率超过90%"
```

---

## Quick Reference (EN)

**🔥 Top 2 Most Important**:
1. **Before `send`, must run `copaw chats list`**: Cannot guess `target-user` and `target-session`
2. **All 5 params required**: `--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text`

---

- `copaw channel send` = one-way push to user/session, **no reply**
  - **Required**: `--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text` (5 params)
- Before `send`, always run:
  ```bash
  copaw chats list --agent-id <your_agent> --channel <channel>
  ```
- Extract from output: `user_id` and `session_id`
- Example:
  ```bash
  # Query
  copaw chats list --agent-id bot --channel console
  
  # Send (use values from query output)
  copaw channel send \
    --agent-id bot \
    --channel console \
    --target-user alice \
    --target-session alice_console_001 \
    --text "Notification message"
  ```
- Use `-h` for command help:
  ```bash
  copaw channel send -h
  ```

---

## 典型工作流

### 完整示例：向钉钉用户发送消息

```bash
#!/bin/bash

# 1. 查询钉钉会话
echo "查询可用会话..."
SESSIONS=$(copaw chats list --agent-id notify_bot --channel dingtalk)

# 2. 提取第一个用户的信息
USER=$(echo "$SESSIONS" | jq -r '.[0].user_id')
SESSION=$(echo "$SESSIONS" | jq -r '.[0].session_id')

echo "目标用户: $USER"
echo "目标会话: $SESSION"

# 3. 发送消息
echo "发送消息..."
copaw channel send \
  --agent-id notify_bot \
  --channel dingtalk \
  --target-user "$USER" \
  --target-session "$SESSION" \
  --text "📊 周报已生成，请查收！"

echo "✓ 消息发送成功"
```

---

## 注意事项

### ⚠️ 必须先查询再发送

系统不会自动查找或匹配用户，必须提供精确的 `target-user` 和 `target-session`。

**错误的想法**：
- "我知道用户叫alice，直接发给alice"
- "随便填个session_id试试"

**正确做法**：
- 先用 `copaw chats list` 查询
- 从返回结果中获取准确的 `user_id` 和 `session_id`

### ⚠️ Session必须存在

如果 `target-session` 不存在或已过期，消息发送会失败。

建议：
- 使用最近活跃的session（查看 `updated_at` 字段）
- 如果session不存在，可能需要先通过 `copaw chats create` 创建

### ⚠️ Channel必须已配置

发送前确保目标频道已正确配置并启用：

```bash
copaw channel list --agent-id <your_agent>
```

检查目标channel的状态是 `enabled`。

---

## 支持的Channel类型

| Channel | 值 | 说明 |
|---------|-----|------|
| Console | `console` | 控制台/终端 |
| DingTalk | `dingtalk` | 钉钉 |
| Feishu | `feishu` | 飞书/Lark |
| Discord | `discord` | Discord |
| Telegram | `telegram` | Telegram |
| iMessage | `imessage` | iMessage (macOS) |
| QQ | `qq` | QQ |
| Voice | `voice` | Twilio语音 |

---

## 帮助信息

随时使用 `-h` 查看详细帮助：

```bash
copaw channel -h
copaw channel send -h
copaw chats -h
copaw chats list -h
```

---

## 与 Agent Chat 的区别

| 特性 | copaw agents chat | copaw channel send |
|------|-------------------|---------------------|
| **用途** | Agent间通信 | 向用户推送消息 |
| **方向** | 双向（有回复） | 单向（无回复） |
| **目标** | 其他Agent | 用户/频道 |
| **必填参数** | 3个 | 5个 |
| **前置查询** | 可选 (copaw agents list) | 必须 (copaw chats list) |
| **Session管理** | 自动生成唯一ID | 必须提供已存在的ID |
| **上下文** | 支持多轮对话 | 单次推送 |

**选择原则**：
- 要和另一个agent对话 → 用 `copaw agents chat`
- 要给用户/频道发消息 → 用 `copaw channel send`
