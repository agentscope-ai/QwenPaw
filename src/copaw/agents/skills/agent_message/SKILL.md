---
name: agent_message
description: Agent 间协作与消息推送：copaw message list-agents 查 agent，copaw message list-sessions 查会话，copaw message ask-agent 双向对话（有回复），copaw message send 单向推送（无回复）。用 -h 查看命令帮助 | Inter-agent collaboration and messaging - copaw message list-agents to query agents, copaw message list-sessions to query sessions, copaw message ask-agent for two-way dialogue (with reply), copaw message send for one-way push (no reply). Use -h for command help
metadata: { "builtin_skill_version": "1.1", "copaw": { "emoji": "💬" } }
---

# Agent 消息与通信

## 一句话记住

- `copaw message send`：**发给用户/会话**，单向推送，**无回复**
  - 必填：`--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text`
- `copaw message ask-agent`：**发给其他 agent**，双向对话，**有回复**
  - 必填：`--from-agent`, `--to-agent`, `--text`

---

## 最小使用规则

### 1. 发消息给用户前，必须先查 session

`send` 不能猜 `target-user` 和 `target-session`，必须先查：

```bash
copaw message list-sessions --agent-id <your_agent>
```

然后再发送：

```bash
copaw message send \
  --agent-id <your_agent> \
  --channel <channel> \
  --target-user <user_id> \
  --target-session <session_id> \
  --text "..."
```

### 2. Agent 间协作用 ask-agent

发消息给agent前，必须先查 agent，不要用 `send` 给 agent 发消息；想要回复时，必须用：

```bash
copaw message list-agents

# ⚠️ 三个参数全部必填：--from-agent, --to-agent, --text
copaw message ask-agent \
  --from-agent <your_agent_id> \
  --to-agent <target_agent_id> \
  --text "[来自智能体 <your_agent>] ..."
```

### 3. Agent 消息要标明身份

推荐在开头带前缀：

```text
[来自智能体 my_agent] 请分析数据
```

如果没写，系统通常会自动补，但建议主动写清楚。

### 4. 不要回调消息来源 agent

如果你当前收到的是来自 Agent B 的消息，不要再调用 Agent B，避免 A→B→A 死循环。

---

## 常用命令

### 查询 agent

```bash
copaw message list-agents
# 或
copaw agents list
```

### 查询 session

```bash
copaw message list-sessions --agent-id <your_agent>
copaw message list-sessions --agent-id <your_agent> --channel console
```

### 发送消息给用户（无回复）

```bash
copaw message send \
  --agent-id <your_agent> \
  --channel <channel> \
  --target-user <user_id> \
  --target-session <session_id> \
  --text "..."
```

### 询问其他 agent（有回复）

```bash
copaw message ask-agent \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --text "[来自智能体 <your_agent>] ..."
```

---

## 关键示例

### 示例 1：发消息给用户

**先查询**：

```bash
copaw message list-sessions --agent-id my_bot --channel console
```

假设查到：
- `user_id=alice`
- `session_id=alice_console_001`

**再发送**：

```bash
copaw message send \
  --agent-id my_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "任务已完成"
```

### 示例 2：询问其他 agent，并继续对话

**第一次提问**：

```bash
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --text "[来自智能体 bot_a] 请分析最近的错误日志"
```

**输出示例**：

```text
[SESSION: bot_a:to:bot_b:1773998835:abc123]

分析结果如下...
```

**如果要继续这段对话**，复用同一个 `session_id`：

```bash
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:1773998835:abc123" \
  --text "[来自智能体 bot_a] 请展开讲第 2 点"
```

**要点**：
- 不传 `--session-id`：默认新对话
- 传相同 `--session-id`：保留上下文

---

## 速记

**🔥 最重要的3件事**：
1. **`ask-agent` 三个参数必填**：`--from-agent`, `--to-agent`, `--text`
2. **想续聊必须传 `--session-id`**：从输出的 `[SESSION: xxx]` 复制
3. **不要回调来源 agent**：避免 A→B→A 死循环

---

### send
- **用途**：发给用户
- **特点**：单向、无回复
- **必填参数**：`--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text`（5个）
- **前提**：必须先 `list-sessions`

### ask-agent
- **用途**：发给其他 agent
- **特点**：双向、有回复
- **必填参数**：`--from-agent`, `--to-agent`, `--text`（3个，缺一不可）
- **可选参数**：`--session-id`（用于复用对话上下文）
- **前提**：目标 agent 存在，且不要回调来源 agent

**⚠️ 复用对话（非常重要！）**：
```bash
# 第1次：不传 --session-id（自动生成）
copaw message ask-agent --from-agent bot_a --to-agent bot_b --text "[来自智能体 bot_a] 分析数据"
# 输出：[SESSION: bot_a:to:bot_b:1773998835:abc123]  ← 复制这个！

# 第2次：传 --session-id（续聊）
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:1773998835:abc123" \
  --text "[来自智能体 bot_a] 展开第2点"
# 现在 bot_b 有上下文了！
```

**关键**：不传 `--session-id` = 新对话（无上下文），传了 = 续聊（有上下文）

---

## 常见错误

### 错误 1：ask-agent 缺少必填参数

```bash
# ❌ 错误：缺少 --from-agent
copaw message ask-agent --to-agent default "你好"

# ❌ 错误：缺少 --to-agent
copaw message ask-agent --from-agent bot_a "你好"

# ✅ 正确：三个参数都提供
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent default \
  --text "你好"
```

**问题**：`--from-agent`、`--to-agent`、`--text` 三个参数全部必填！

### 错误 2：没查 session 就直接 send

```bash
copaw message send --agent-id bot --channel console --text "hello"
```

**问题**：缺少 `target-user` / `target-session`，或目标不存在。

### 错误 3：想拿回复却用了 send

```bash
copaw message send --agent-id bot --channel console --target-user xxx --target-session yyy --text "帮我分析"
```

**问题**：`send` 不会返回 agent 回复。  
**正确做法**：改用 `ask-agent`。

### 错误 4：想续聊但没传 session-id

```bash
# 第一次对话
copaw message ask-agent --from-agent bot_a --to-agent bot_b --text "[来自智能体 bot_a] 请分析数据"
# 输出：[SESSION: bot_a:to:bot_b:1773998835:abc123]

# ❌ 错误：想继续对话但没传 session-id
copaw message ask-agent --from-agent bot_a --to-agent bot_b --text "[来自智能体 bot_a] 展开第2点"
# 问题：生成了新 session，bot_b 不知道"第2点"是什么！

# ✅ 正确：复用 session-id
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:1773998835:abc123" \
  --text "[来自智能体 bot_a] 展开第2点"
```

**问题**：不传 `--session-id` 就是新对话，对方没有上下文。  
**正确做法**：手动复制首次输出的 `[SESSION: xxx]`，用 `--session-id` 传入。

### 错误 5：收到 Agent B 的消息后又调用 Agent B

会造成循环调用。  
**正确做法**：改为调用第三方 agent，或直接回复用户。

---

## Quick Reference (EN)

**🔥 Top 3 Most Important**:
1. **`ask-agent` requires 3 params**: `--from-agent`, `--to-agent`, `--text`
2. **To continue conversation, must pass `--session-id`**: Copy from `[SESSION: xxx]` output
3. **Don't call back source agent**: Avoid A→B→A infinite loops

---

- `send` = one-way push to user/session, **no reply**
  - **Required**: `--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text` (5 params)
- `ask-agent` = two-way dialogue with another agent, **has reply**
  - **Required**: `--from-agent`, `--to-agent`, `--text` (3 params, all mandatory!)
  - **Optional**: `--session-id` (for conversation context)
- Before `send`, always run:
  ```bash
  copaw message list-sessions --agent-id <your_agent>
  ```
- **Session ID reuse example**:
  ```bash
  # 1st call: auto-generate session
  copaw message ask-agent --from-agent bot_a --to-agent bot_b --text "[Agent bot_a] Analyze"
  # Output: [SESSION: bot_a:to:bot_b:1773998835:abc123]  ← Copy this!
  
  # 2nd call: reuse session (has context)
  copaw message ask-agent \
    --from-agent bot_a \
    --to-agent bot_b \
    --session-id "bot_a:to:bot_b:1773998835:abc123" \
    --text "[Agent bot_a] Expand point 2"
  ```
- **Do not call back the source agent** that just messaged you
- Use `-h` for command help:
  ```bash
  copaw message send -h
  copaw message ask-agent -h
  ```
