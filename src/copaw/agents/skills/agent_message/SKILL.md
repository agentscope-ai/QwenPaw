---
name: agent_message
description: Agent间通信和主动消息发送 - 查询agents/sessions，发送消息到channel，智能体间对话 | Inter-agent communication and proactive messaging - query agents/sessions, send to channels, agent-to-agent dialogue
metadata: { "builtin_skill_version": "1.0", "copaw": { "emoji": "💬" } }
---

# Agent 消息和通信 | Agent Messaging & Communication

## ⚠️ 重要提示 | Important Notice

**Agent间通信时必须标明身份！**  
**Always identify yourself in inter-agent messages!**

```bash
# ✅ 正确 | Correct
--text "[来自智能体 my_agent] 请分析数据"
--text "[Agent my_agent requesting] Analyze the data"

# ❌ 错误（目标agent会混淆）| Wrong (causes confusion)
--text "请分析数据"
--text "Analyze the data"
```

**为什么？** 目标agent需要区分消息来源是用户还是其他agent  
**Why?** Target agent needs to distinguish between user requests and agent requests

---

## 中文说明 | Chinese Documentation

使用 `copaw agents` 和 `copaw message` 命令实现智能体间通信和主动消息发送。

### 核心功能

1. **查询可用资源**：发现可通信的agents和sessions
2. **主动发送消息**：向channel用户发送文本消息
3. **智能体间对话**：与其他agent交互并获取响应

---

## 一、查询命令（发现目标）

### 1.1 列出所有 Agents

```bash
# 查看所有配置的agents
copaw agents list

# 或使用 message 子命令
copaw message list-agents
```

**返回示例**：
```json
{
  "agents": [
    {
      "id": "default",
      "name": "Default Agent",
      "description": "...",
      "workspace_dir": "/Users/..."
    },
    {
      "id": "finance_bot",
      "name": "Finance Assistant",
      "description": "...",
      "workspace_dir": "/Users/..."
    }
  ]
}
```

### 1.2 列出 Sessions 和 Users

```bash
# 查看指定agent的所有sessions
copaw message list-sessions --agent-id my_bot

# 过滤特定channel
copaw message list-sessions --agent-id my_bot --channel dingtalk

# 限制返回数量
copaw message list-sessions --agent-id my_bot --limit 10
```

**返回信息**：
- `sessions`：所有会话列表
- `unique_users`：聚合的用户信息（channels、session_count、last_active）
- `inter_agent_sessions`：智能体间通信的sessions

**重要**：发送消息前，**必须**先用此命令查询目标是否存在！

---

## 二、发送消息到 Channel

向已存在的用户/session发送文本消息。

### 2.1 基础用法

```bash
copaw message send \
  --agent-id my_bot \
  --channel console \
  --target-user alice \
  --target-session alice_session_001 \
  --text "Hello from my_bot!"
```

### 2.2 发送到不同 Channel

```bash
# 发送到 DingTalk
copaw message send \
  --agent-id sales_bot \
  --channel dingtalk \
  --target-user dt_user_123 \
  --target-session dt_session_456 \
  --text "您的订单已确认。"

# 发送到 Feishu
copaw message send \
  --agent-id support_bot \
  --channel feishu \
  --target-user fs_user_789 \
  --target-session fs_session_abc \
  --text "技术支持：问题已解决。"
```

### 2.3 必填参数

- `--agent-id`：发送者的agent ID（**必须**是你自己的agent ID）
- `--channel`：目标channel（console / dingtalk / feishu / discord / qq / imessage 等）
- `--target-user`：目标用户ID
- `--target-session`：目标会话ID
- `--text`：消息文本内容

### 2.4 使用建议

1. **查询先行**：先用 `list-sessions` 确认target-user和target-session存在
2. **获取agent-id**：从系统提示的 Agent Identity 部分读取（`Your agent id is ...`）
3. **验证channel**：用 `copaw channels list` 确认channel已配置
4. **错误处理**：如果发送失败，检查channel配置和用户权限

---

## 三、智能体间通信（ask-agent）

向其他agent发送消息并获取响应，实现agent协作。

### 3.1 基础用法（推荐）

```bash
# 自动生成唯一session（并发安全）
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --text "[来自智能体 bot_a] 今天天气怎么样？"
```

**重要提示**：
- ⚠️ **必须在消息开头说明身份**：使用 `[来自智能体 <your_agent_id>]` 前缀
- 避免目标agent混淆消息来源（区分agent请求 vs 用户请求）
- 格式示例：`"[来自智能体 bot_a] 请帮我分析数据"`

**Session管理**：
- 默认自动生成唯一session ID（格式：`{from}:to:{to}:{timestamp_ms}:{uuid_short}`）
- 每次调用独立session，避免并发冲突
- 适合单次问答、独立请求

### 3.2 复用 Session（上下文对话）

```bash
# 第一次对话
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:conv001" \
  --text "[来自智能体 bot_a] 我想了解量子计算"

# 继续对话（复用session）
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:conv001" \
  --text "[来自智能体 bot_a] 能详细解释一下量子纠缠吗？"
```

**注意**：
- 复用session时需注意并发问题（多个请求同时使用同一session会报错）
- 首次对话必须包含身份标识，后续对话可简化（session已建立上下文）

### 3.3 转发响应到 Channel

```bash
# 询问其他agent并将结果发送给用户
copaw message ask-agent \
  --from-agent monitor \
  --to-agent analyst \
  --text "[来自智能体 monitor] 分析最近的错误日志" \
  --channel dingtalk \
  --target-user manager_001 \
  --target-session alert_session
```

转发响应需要同时指定：
- `--channel`：目标channel
- `--target-user`：接收者用户ID
- `--target-session`：接收者会话ID

### 3.4 流式响应（Stream Mode）

```bash
# 实时流式输出（适合长响应）
copaw message ask-agent \
  --from-agent ui \
  --to-agent research \
  --text "[来自智能体 ui] 写一篇关于人工智能的文章" \
  --mode stream
```

- `--mode final`（默认）：等待完整响应
- `--mode stream`：实时增量输出（SSE）

### 3.5 JSON 输出格式

```bash
# 获取完整JSON响应（包含metadata）
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --text "[来自智能体 bot_a] 测试" \
  --json-output
```

### 3.6 其他选项

```bash
# 自定义超时时间（默认300秒）
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --text "[来自智能体 bot_a] 复杂任务" \
  --timeout 600

# 强制新建session（即使指定了--session-id）
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "old_session" \
  --new-session \
  --text "[来自智能体 bot_a] 新对话"
```

---

## 四、完整工作流程示例

### 示例1：智能体协作处理用户请求

```bash
# 步骤1：查询可用的agents
copaw message list-agents

# 步骤2：向专家agent提问（明确标识身份）
copaw message ask-agent \
  --from-agent general_assistant \
  --to-agent finance_expert \
  --text "[来自智能体 general_assistant] 分析Q1财报数据"

# 步骤3：将结果发送给用户
copaw message send \
  --agent-id general_assistant \
  --channel dingtalk \
  --target-user user_123 \
  --target-session session_456 \
  --text "财报分析已完成：..."
```

### 示例2：定期查询其他agent并通知

```bash
# 配合 cron skill 实现定期agent查询
# 在cron任务中调用
copaw message ask-agent \
  --from-agent monitor \
  --to-agent system_checker \
  --text "[来自智能体 monitor - 定时检查] 检查系统状态" \
  --channel console \
  --target-user admin \
  --target-session monitoring
```

### 示例3：多agent协作链

```bash
# Agent A 询问 Agent B
RESPONSE_B=$(copaw message ask-agent \
  --from-agent agent_a \
  --to-agent agent_b \
  --text "[来自智能体 agent_a] 数据收集" | tail -1)

# Agent A 将 Agent B 的响应转发给 Agent C
copaw message ask-agent \
  --from-agent agent_a \
  --to-agent agent_c \
  --text "[来自智能体 agent_a] 分析这些数据: $RESPONSE_B"
```

---

## 五、最佳实践

### 5.1 消息身份标识（重要！）

**必须在agent间消息中标明发送者身份**，避免目标agent混淆：

✅ **正确格式**：
```bash
--text "[来自智能体 my_agent] 请分析数据"
--text "[Agent my_agent requesting] Analyze the data"
```

❌ **错误格式**（会导致混淆）：
```bash
--text "请分析数据"  # 目标agent会误认为是用户请求
```

**身份标识建议**：
- 使用方括号 `[来自智能体 <agent_id>]` 或 `[Agent <agent_id> requesting]`
- 放在消息开头，清晰醒目
- 可选：说明请求目的，如 `[来自智能体 monitor - 定时检查]`

### 5.2 安全的并发策略

- **默认行为**：让系统自动生成唯一session ID
- **显式session**：仅在需要上下文连续性时使用
- **并发控制**：多个agent同时调用时，避免共享session ID

### 5.3 错误处理

```bash
# 检查命令执行结果
if copaw message send --agent-id bot --channel console \
   --target-user alice --target-session s1 --text "test"; then
  echo "发送成功"
else
  echo "发送失败，检查参数和配置"
fi
```

### 5.4 查询验证

**发送消息前的检查清单**：
1. ✅ `copaw message list-agents` - 确认目标agent存在
2. ✅ `copaw message list-sessions --agent-id X` - 确认session/user存在
3. ✅ `copaw channels list` - 确认channel已配置
4. ✅ 验证自己的agent_id（系统提示中查找）
5. ✅ **在消息中标明身份** - 使用 `[来自智能体 <your_id>]` 前缀

### 5.5 日志和调试

- 使用 `--json-output` 查看完整响应结构
- 检查 `~/.copaw/logs/` 中的日志文件
- 用 `copaw app` 的日志输出排查问题

---

## 六、命令速查表

| 命令 | 用途 | 示例 |
|------|------|------|
| `copaw agents list` | 列出所有agents | `copaw agents list` |
| `copaw message list-agents` | 列出所有agents（同上） | `copaw message list-agents` |
| `copaw message list-sessions` | 查询sessions和users | `copaw message list-sessions --agent-id bot` |
| `copaw message send` | 发送消息到channel | `copaw message send --agent-id bot ...` |
| `copaw message ask-agent` | agent间通信 | `copaw message ask-agent --from-agent a --to-agent b ...` |

---

## English Documentation

Use `copaw agents` and `copaw message` commands for inter-agent communication and proactive messaging.

### Core Features

1. **Query Resources**: Discover available agents and sessions
2. **Send Messages**: Send text messages to channel users
3. **Agent Dialogue**: Interact with other agents and get responses

---

## I. Query Commands (Resource Discovery)

### 1.1 List All Agents

```bash
# View all configured agents
copaw agents list

# Or use message subcommand
copaw message list-agents
```

**Example Response**:
```json
{
  "agents": [
    {
      "id": "default",
      "name": "Default Agent",
      "description": "...",
      "workspace_dir": "/Users/..."
    }
  ]
}
```

### 1.2 List Sessions and Users

```bash
# View all sessions for a specific agent
copaw message list-sessions --agent-id my_bot

# Filter by channel
copaw message list-sessions --agent-id my_bot --channel dingtalk

# Limit results
copaw message list-sessions --agent-id my_bot --limit 10
```

**Important**: **Always query first** before sending messages!

---

## II. Send Messages to Channels

Send text messages to existing users/sessions.

### 2.1 Basic Usage

```bash
copaw message send \
  --agent-id my_bot \
  --channel console \
  --target-user alice \
  --target-session alice_session_001 \
  --text "Hello from my_bot!"
```

### 2.2 Required Parameters

- `--agent-id`: Your agent ID (sender)
- `--channel`: Target channel (console / dingtalk / feishu / discord / qq / imessage, etc.)
- `--target-user`: Target user ID
- `--target-session`: Target session ID
- `--text`: Message text content

---

## III. Inter-Agent Communication (ask-agent)

Send messages to other agents and receive responses.

### 3.1 Basic Usage (Recommended)

```bash
# Auto-generate unique session (concurrency-safe)
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --text "[Agent bot_a requesting] What's the weather today?"
```

**Important Note**:
- ⚠️ **Always identify yourself in messages**: Use `[Agent <your_agent_id> requesting]` prefix
- Prevents target agent from confusing message source (agent request vs user request)
- Format example: `"[Agent bot_a requesting] Please analyze the data"`

**Session Management**:
- Default: Auto-generates unique session ID (format: `{from}:to:{to}:{timestamp_ms}:{uuid_short}`)
- Each call uses independent session (avoids concurrency conflicts)
- Best for one-off questions and independent requests

### 3.2 Reuse Session (Contextual Conversation)

```bash
# First conversation
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:conv001" \
  --text "[Agent bot_a requesting] Tell me about quantum computing"

# Continue conversation (reuse session)
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:conv001" \
  --text "[Agent bot_a] Can you explain quantum entanglement?"
```

**Warning**: 
- Be careful with concurrent requests to the same session (will cause errors)
- First message must include identity, subsequent messages can be simplified (context established)

### 3.3 Forward Response to Channel

```bash
# Ask another agent and send result to user
copaw message ask-agent \
  --from-agent monitor \
  --to-agent analyst \
  --text "[Agent monitor requesting] Analyze recent error logs" \
  --channel dingtalk \
  --target-user manager_001 \
  --target-session alert_session
```

### 3.4 Stream Mode

```bash
# Real-time streaming output (for long responses)
copaw message ask-agent \
  --from-agent ui \
  --to-agent research \
  --text "[Agent ui requesting] Write an article about AI" \
  --mode stream
```

- `--mode final` (default): Wait for complete response
- `--mode stream`: Real-time incremental output (SSE)

### 3.5 JSON Output Format

```bash
# Get full JSON response (with metadata)
copaw message ask-agent \
  --from-agent bot_a \
  --to-agent bot_b \
  --text "test" \
  --json-output
```

---

## IV. Complete Workflow Examples

### Example 1: Agent Collaboration

```bash
# Step 1: Query available agents
copaw message list-agents

# Step 2: Ask expert agent (identify yourself)
copaw message ask-agent \
  --from-agent general_assistant \
  --to-agent finance_expert \
  --text "[Agent general_assistant requesting] Analyze Q1 financial report"

# Step 3: Send result to user
copaw message send \
  --agent-id general_assistant \
  --channel dingtalk \
  --target-user user_123 \
  --target-session session_456 \
  --text "Financial analysis completed: ..."
```

---

## V. Best Practices

### 5.1 Message Identity (Critical!)

**Always identify yourself in inter-agent messages** to prevent confusion:

✅ **Correct Format**:
```bash
--text "[Agent my_agent requesting] Please analyze the data"
--text "[来自智能体 my_agent] 请分析数据"
```

❌ **Wrong Format** (causes confusion):
```bash
--text "Please analyze the data"  # Target agent thinks it's from a user
```

**Identity Guidelines**:
- Use square brackets: `[Agent <agent_id> requesting]` or `[来自智能体 <agent_id>]`
- Place at message beginning for clarity
- Optional: Add purpose, e.g., `[Agent monitor - scheduled check]`

### 5.2 Concurrency-Safe Strategy

- **Default behavior**: Let system auto-generate unique session IDs
- **Explicit session**: Only use when context continuity is needed
- **Concurrency control**: Avoid sharing session IDs across concurrent calls

### 5.3 Query Before Send

**Pre-send checklist**:
1. ✅ `copaw message list-agents` - Verify target agent exists
2. ✅ `copaw message list-sessions --agent-id X` - Verify session/user exists
3. ✅ `copaw channels list` - Verify channel is configured
4. ✅ Get your agent_id from system prompt (Agent Identity section)
5. ✅ **Identify yourself in message** - Use `[Agent <your_id> requesting]` prefix

---

## VI. Command Quick Reference

| Command | Purpose | Example |
|---------|---------|---------|
| `copaw agents list` | List all agents | `copaw agents list` |
| `copaw message list-agents` | List all agents (same as above) | `copaw message list-agents` |
| `copaw message list-sessions` | Query sessions and users | `copaw message list-sessions --agent-id bot` |
| `copaw message send` | Send message to channel | `copaw message send --agent-id bot ...` |
| `copaw message ask-agent` | Inter-agent communication | `copaw message ask-agent --from-agent a --to-agent b ...` |

---

## 重要提示 | Important Notes

1. **消息身份标识 | Message Identity (Critical!)**：
   - 中文：**必须**在agent间消息开头标明身份：`[来自智能体 <your_id>]`
   - English: **Must** identify yourself at message beginning: `[Agent <your_id> requesting]`
   - **原因 | Reason**: 避免目标agent混淆消息来源（agent vs user）
   - **Why**: Prevents target agent from confusing message source (agent vs user)

2. **Agent ID 来源 | Agent ID Source**：
   - 中文：从系统提示的 "Agent Identity" 部分获取（`Your agent id is ...`）
   - English: Get from system prompt "Agent Identity" section (`Your agent id is ...`)

3. **查询先行 | Query First**：
   - 中文：发送消息前**必须**先查询目标是否存在
   - English: **Always** query before sending to verify target exists

4. **并发安全 | Concurrency Safety**：
   - 中文：默认使用自动生成的唯一session，避免并发冲突
   - English: Use auto-generated unique sessions by default to avoid concurrency issues

5. **错误排查 | Troubleshooting**：
   - 中文：检查 `~/.copaw/logs/` 日志文件
   - English: Check `~/.copaw/logs/` for log files
