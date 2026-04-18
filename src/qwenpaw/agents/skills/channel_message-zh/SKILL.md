---
name: channel_message
description: 当需要主动向用户、会话或频道单向发送消息时，使用本 skill。通常仅在用户明确要求向某个 channel / 会话发送消息，或需要主动通知时使用。先用 qwenpaw chats list 查询 session，再用 qwenpaw channels send 推送消息。
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "📤"
---

# 频道消息推送

## 什么时候用

通常只有在**用户明确要求向某个 channel / 会话发送消息**，或你需要**主动推送通知**（如任务完成、提醒、告警）时，使用本 skill。  
这是**单向发送**，**不会返回回复**。

### 应该使用
- 用户明确要求发往某个 channel / 会话
- 任务完成后主动通知用户
- 定时提醒、告警、状态更新
- 将异步结果推送回某个已有会话
- 用户明确要求"处理完后通知我"

### 不应使用
- 如果只是当前会话中的正常回复，**不要使用 `qwenpaw channels send`**
- 需要和用户进行双向对话并立即等待回复
- 还不知道目标 session 是哪个
- 想当然猜测 `target-user` 或 `target-session`

## 决策规则

1. **通常只有在用户明确要求发往某个 channel / 会话，或需要主动通知时才使用**
2. **发送前必须先查 session**
3. **不要猜 `target-user` 和 `target-session`**
4. **如果查到多个 session，优先使用最近活跃的**
5. **`channel send` 是单向推送，不会返回用户回复**

---

## 最常用命令

### 1) 先查询可用 sessions

```bash
qwenpaw chats list --agent-id <your_agent> --channel <channel>
```

也可以按用户筛选：

```bash
qwenpaw chats list --agent-id <your_agent> --user-id <user_id>
```

### 2) 发送消息

```bash
qwenpaw channels send \
  --agent-id <your_agent> \
  --channel <channel> \
  --target-user <user_id> \
  --target-session <session_id> \
  --text "..."
```

---

## 最小工作流

```
1. 判断：是否为用户明确要求发送，或是否需要主动通知
2. qwenpaw chats list 查询目标 session
3. 从结果中获取 user_id 和 session_id
4. 若有多个 session，优先选最近活跃的
5. qwenpaw channels send 发送消息
6. 结束（无回复）
```

---

## 关键规则

### 必填参数

`qwenpaw channels send` 必须同时提供：
- `--agent-id`
- `--channel`
- `--target-user`
- `--target-session`
- `--text`

### 必须先查询

发送前先执行：

```bash
qwenpaw chats list --agent-id <your_agent> --channel <channel>
```

从结果中获取：
- `user_id` → `--target-user`
- `session_id` → `--target-session`

如果有多个候选 session，优先选择 `updated_at` 最近的会话。

### 单向推送

`qwenpaw channels send` 只负责发送，不等待回复。

---

## 简短示例

### 用户明确要求发往某个 channel

```bash
qwenpaw chats list --agent-id notify_bot --channel feishu

qwenpaw channels send \
  --agent-id notify_bot \
  --channel feishu \
  --target-user manager_id \
  --target-session manager_session \
  --text "周报已生成，请查收"
```

### 任务完成通知

```bash
qwenpaw chats list --agent-id task_bot --channel console

qwenpaw channels send \
  --agent-id task_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "✅ 任务已完成"
```

### 异步结果回推

```bash
qwenpaw chats list --agent-id analyst_bot --user-id alice

qwenpaw channels send \
  --agent-id analyst_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "数据分析已完成，结果已保存到 report.pdf"
```

---

## 常见错误

### 错误 1：把正常回复当成 channel send

如果你正在当前会话里直接回复用户，不要使用 `qwenpaw channels send`。

### 错误 2：没查 session 就直接发

不要猜 `target-user` 或 `target-session`，先执行：

```bash
qwenpaw chats list --agent-id <your_agent> --channel <channel>
```

### 错误 3：缺少必填参数

`--agent-id`、`--channel`、`--target-user`、`--target-session`、`--text` 五个都必填。

### 错误 4：以为 send 会拿到回复

不会。它只是推送消息。

### 错误 5：用户有多个 session 时随便选一个

应优先选择最近活跃的 session。

---

## 可选命令

### 查看所有会话

```bash
qwenpaw chats list --agent-id <your_agent>
```

### 查看某个用户的会话

```bash
qwenpaw chats list --agent-id <your_agent> --user-id <user_id>
```

### 查看可用频道

```bash
qwenpaw channels list --agent-id <your_agent>
```

---

## 与 Agent Chat 的区别

- **qwenpaw agents chat**：发给其他 agent，双向，有回复
- **qwenpaw channels send**：发给用户/会话/频道，单向，无回复

**选择原则**：
- 要找其他 agent 协作 → `qwenpaw agents chat`
- 要主动给用户推送消息 → `qwenpaw channels send`

---

## 完整参数说明

### qwenpaw chats list

**必填参数**：
- `--agent-id`：Agent ID

**可选参数**：
- `--channel`：按频道筛选
- `--user-id`：按用户筛选
- `--base-url`：覆盖API地址

### qwenpaw channels send

**必填参数**（5个）：
- `--agent-id`：发送方agent ID
- `--channel`：目标频道（console/dingtalk/feishu/discord/imessage/qq/...）
- `--target-user`：目标用户ID（从 `qwenpaw chats list` 获取）
- `--target-session`：目标会话ID（从 `qwenpaw chats list` 获取）
- `--text`：消息内容

**可选参数**：
- `--base-url`：覆盖API地址

---

## 帮助信息

随时使用 `-h` 查看详细帮助：

```bash
qwenpaw channels -h
qwenpaw channels send -h
qwenpaw chats -h
qwenpaw chats list -h
```
