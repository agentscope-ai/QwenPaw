---
name: multi_agent_collaboration
description: Multi-agent collaboration and inter-agent communication - use copaw agents list to query agents, copaw chats list to query sessions, copaw agents chat for two-way dialogue with replies | 多智能体协作与通信 - copaw agents list 查询 agent，copaw chats list 查询会话，copaw agents chat 双向对话（有回复）
metadata: { "builtin_skill_version": "2.0", "copaw": { "emoji": "🤝" } }
---

# Multi-Agent Collaboration (多智能体协作)

## 一句话记住

`copaw agents chat`：**Agent间双向对话**，**有回复**
- 必填：`--from-agent`, `--to-agent`, `--text`（三个参数缺一不可）

---

## 最小使用规则

### 1. Agent间协作必须先查 agent

不要猜测agent ID，必须先查询：

```bash
copaw agents list
```

然后再通信：

```bash
copaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --text "[Agent <your_agent> requesting] ..."
```

### 2. 想续聊必须传 session-id

**第一次对话**（自动生成session）：

```bash
copaw agents chat \
  --from-agent bot_a \
  --to-agent bot_b \
  --text "[Agent bot_a requesting] 分析数据"
```

**输出示例**：

```text
INFO: Using session_id: bot_a:to:bot_b:1773998835:abc123
[SESSION: bot_a:to:bot_b:1773998835:abc123]

分析结果如下...
```

**继续对话**（复用session）：

```bash
# ⚠️ 必须传 --session-id，否则会创建新对话！
copaw agents chat \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:1773998835:abc123" \
  --text "[Agent bot_a requesting] 展开第2点"
```

**关键**：
- 不传 `--session-id` = 新对话（无上下文）
- 传了 `--session-id` = 续聊（有上下文）

### 3. Agent 消息要标明身份

推荐在开头带前缀：

```text
[Agent my_agent requesting] 请分析数据
```

如果没写，系统会自动补：

```text
INFO: Auto-added identity prefix: [Agent my_agent requesting]
```

### 4. 不要回调消息来源 agent

如果你当前收到的是来自 Agent B 的消息，**不要再调用 Agent B**，避免 A→B→A 死循环。

---

## 常用命令

### 查询可用 agents

```bash
copaw agents list
```

**输出格式**：

```json
{
  "agents": [
    {
      "id": "default",
      "name": "Default Assistant",
      "description": "General purpose assistant",
      "workspace_dir": "/path/to/workspace"
    },
    {
      "id": "finance_expert",
      "name": "Finance Expert",
      "description": "Financial analysis specialist",
      "workspace_dir": "/path/to/finance"
    }
  ]
}
```

### 查询现有会话（可选，用于复用session）

```bash
# 查询所有会话
copaw chats list --agent-id my_bot

# 只看agent间会话，用jq过滤
copaw chats list --agent-id my_bot | \
  jq '[.[] | select(.session_id | contains(":to:"))]'
```

从输出中找到 `session_id` 字段，用于续聊。

### 与其他 agent 对话

**新对话**：

```bash
copaw agents chat \
  --from-agent bot_a \
  --to-agent bot_b \
  --text "[Agent bot_a requesting] 请分析最近的错误日志"
```

**续聊**（复用session）：

```bash
copaw agents chat \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:1773998835:abc123" \
  --text "[Agent bot_a requesting] 展开讲第2点"
```

---

## 关键示例

### 示例 1：首次协作对话

**步骤 1 - 查询可用agents**：

```bash
copaw agents list
```

**步骤 2 - 发起对话**：

```bash
copaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agent scheduler_bot requesting] 今天有哪些待处理的财务任务？"
```

**输出**：

```text
INFO: Using session_id: scheduler_bot:to:finance_bot:1710912345:a1b2c3d4
[SESSION: scheduler_bot:to:finance_bot:1710912345:a1b2c3d4]

今天有以下财务任务：
1. 审核报销单 (3个待处理)
2. 生成月度报表
3. 核对供应商发票
```

### 示例 2：多轮对话（保持上下文）

**第一轮**：

```bash
copaw agents chat \
  --from-agent data_bot \
  --to-agent analyst_bot \
  --text "[Agent data_bot requesting] 分析sales_2024.csv"
```

**输出**（复制session_id）：

```text
INFO: Using session_id: data_bot:to:analyst_bot:1710912500:xyz789
[SESSION: data_bot:to:analyst_bot:1710912500:xyz789]

分析结果：
- 总销售额：$1.2M
- 增长率：15%
- 主要产品：A、B、C
```

**第二轮**（续聊）：

```bash
# ⚠️ 必须传 --session-id
copaw agents chat \
  --from-agent data_bot \
  --to-agent analyst_bot \
  --session-id "data_bot:to:analyst_bot:1710912500:xyz789" \
  --text "[Agent data_bot requesting] 详细说明产品A的数据"
```

**输出**（同一session）：

```text
INFO: Using session_id: data_bot:to:analyst_bot:1710912500:xyz789
[SESSION: data_bot:to:analyst_bot:1710912500:xyz789]

产品A详细数据：
（基于之前的上下文，知道是在讨论sales_2024.csv）
- 销量：500单位
- 收入：$300K
- 同比增长：20%
```

### 示例 3：强制创建新对话

如果想和同一个agent开启全新对话（不保留上下文）：

```bash
copaw agents chat \
  --from-agent bot_a \
  --to-agent bot_b \
  --new-session \
  --text "[Agent bot_a requesting] 这是全新的问题"
```

或者直接不传 `--session-id`（默认就是新对话）。

---

## 高级功能

### 流式输出

实时看到agent的回复过程：

```bash
copaw agents chat \
  --from-agent bot_a \
  --to-agent bot_b \
  --mode stream \
  --text "[Agent bot_a requesting] 生成长报告"
```

### JSON输出

获取完整的JSON响应（包含metadata）：

```bash
copaw agents chat \
  --from-agent bot_a \
  --to-agent bot_b \
  --json-output \
  --text "[Agent bot_a requesting] 分析"
```

---

## 速记

**🔥 最重要的3件事**：
1. **`chat` 三个参数必填**：`--from-agent`, `--to-agent`, `--text`（缺一不可）
2. **想续聊必须传 `--session-id`**：从输出的 `[SESSION: xxx]` 复制
3. **不要回调来源 agent**：避免 A→B→A 死循环

---

## 完整参数说明

### copaw agents list

**参数**：
- `--base-url`（可选）：覆盖API地址

**无必填参数**，直接运行即可。

### copaw agents chat

**必填参数**（3个）：
- `--from-agent`：发起方agent ID
- `--to-agent`：目标agent ID
- `--text`：消息内容

**可选参数**：
- `--session-id`：复用会话上下文（从之前的输出中复制）
- `--new-session`：强制创建新会话（即使传了session-id）
- `--mode`：stream（流式）或 final（完整，默认）
- `--timeout`：超时时间（秒，默认300）
- `--json-output`：输出完整JSON而非纯文本
- `--base-url`：覆盖API地址

---

## 常见错误

### 错误 1：chat 缺少必填参数

```bash
# ❌ 错误：缺少 --from-agent
copaw agents chat --to-agent default --text "你好"

# ❌ 错误：缺少 --to-agent
copaw agents chat --from-agent bot_a --text "你好"

# ❌ 错误：缺少 --text
copaw agents chat --from-agent bot_a --to-agent default

# ✅ 正确：三个参数都提供
copaw agents chat \
  --from-agent bot_a \
  --to-agent default \
  --text "你好"
```

**问题**：`--from-agent`、`--to-agent`、`--text` 三个参数全部必填！

### 错误 2：想续聊但没传 session-id

```bash
# 第一次对话
copaw agents chat --from-agent bot_a --to-agent bot_b \
  --text "[Agent bot_a requesting] 请分析数据"
# 输出：[SESSION: bot_a:to:bot_b:1773998835:abc123]

# ❌ 错误：想继续对话但没传 session-id
copaw agents chat --from-agent bot_a --to-agent bot_b \
  --text "[Agent bot_a requesting] 展开第2点"
# 问题：生成了新session，bot_b 不知道"第2点"是什么！

# ✅ 正确：复用 session-id
copaw agents chat \
  --from-agent bot_a \
  --to-agent bot_b \
  --session-id "bot_a:to:bot_b:1773998835:abc123" \
  --text "[Agent bot_a requesting] 展开第2点"
```

**问题**：不传 `--session-id` 就是新对话，对方没有上下文。  
**正确做法**：手动复制首次输出的 `[SESSION: xxx]`，用 `--session-id` 传入。

### 错误 3：收到 Agent B 的消息后又调用 Agent B

会造成循环调用：A 调用 B → B 调用 A → A 又调用 B → ...

**正确做法**：改为调用第三方 agent，或直接回复用户。

---

## 工作流程图

```
┌─────────────────────────────────────────────────────────┐
│  1. 查询可用 agents                                     │
│     copaw agents list                                    │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  2. (可选) 查询现有会话以复用上下文                     │
│     copaw chats list --agent-id <your_agent> |          │
│       jq '[.[] | select(.session_id | contains(":to:"))]'│
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  3. 发起对话                                            │
│     copaw agents chat \                                  │
│       --from-agent <your_agent> \                        │
│       --to-agent <target_agent> \                        │
│       --text "[Agent <your_agent> requesting] ..."       │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  4. 获取回复和session_id                                │
│     [SESSION: your_agent:to:target:timestamp:uuid]       │
│     Response content...                                  │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  5. 续聊（可选，传入session-id）                        │
│     copaw agents chat \                                  │
│       --from-agent <your_agent> \                        │
│       --to-agent <target_agent> \                        │
│       --session-id "..." \                               │
│       --text "[Agent <your_agent> requesting] ..."       │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Reference (EN)

**🔥 Top 3 Most Important**:
1. **`chat` requires 3 params**: `--from-agent`, `--to-agent`, `--text` (all mandatory!)
2. **To continue conversation, must pass `--session-id`**: Copy from `[SESSION: xxx]` output
3. **Don't call back source agent**: Avoid A→B→A infinite loops

---

- `copaw agents list` = List all available agents
- `copaw agents chat` = Two-way dialogue with another agent, **has reply**
  - **Required**: `--from-agent`, `--to-agent`, `--text` (3 params, all mandatory!)
  - **Optional**: `--session-id` (for conversation context reuse)
- Before `chat`, optionally run:
  ```bash
  copaw chats list --agent-id <your_agent>
  ```
  to find existing inter-agent sessions
- **Session ID reuse example**:
  ```bash
  # 1st call: auto-generate session
  copaw agents chat --from-agent bot_a --to-agent bot_b \
    --text "[Agent bot_a requesting] Analyze"
  # Output: [SESSION: bot_a:to:bot_b:1773998835:abc123]  ← Copy this!
  
  # 2nd call: reuse session (has context)
  copaw agents chat \
    --from-agent bot_a \
    --to-agent bot_b \
    --session-id "bot_a:to:bot_b:1773998835:abc123" \
    --text "[Agent bot_a requesting] Expand point 2"
  ```
- **Do not call back the source agent** that just messaged you
- Use `-h` for command help:
  ```bash
  copaw agents chat -h
  ```

---

## 协作模式

### 模式 1：一次性咨询

Agent A 需要Agent B的专业意见，不需要续聊：

```bash
copaw agents chat \
  --from-agent scheduler \
  --to-agent weather_expert \
  --text "[Agent scheduler requesting] 明天天气如何？"
```

### 模式 2：多轮协作

Agent A 和 Agent B 进行多轮深度讨论：

```bash
# Round 1
copaw agents chat --from-agent researcher --to-agent analyst \
  --text "[Agent researcher requesting] 分析这份报告"
# 获取 session_id

# Round 2
copaw agents chat --from-agent researcher --to-agent analyst \
  --session-id "..." \
  --text "[Agent researcher requesting] 详细说明第3点"

# Round 3
copaw agents chat --from-agent researcher --to-agent analyst \
  --session-id "..." \
  --text "[Agent researcher requesting] 给出具体建议"
```

### 模式 3：多方协作

Agent A 咨询多个不同的agents：

```bash
# 咨询财务专家
copaw agents chat --from-agent manager --to-agent finance \
  --text "[Agent manager requesting] 预算还剩多少？"

# 咨询技术专家
copaw agents chat --from-agent manager --to-agent tech_lead \
  --text "[Agent manager requesting] 项目进度如何？"

# 咨询数据分析师
copaw agents chat --from-agent manager --to-agent data_analyst \
  --text "[Agent manager requesting] 生成月度报表"
```

---

## 使用 copaw chats list 查询会话

如果需要查看某个agent的所有对话历史（包括agent间会话）：

```bash
# 查询所有会话
copaw chats list --agent-id my_bot

# 只看agent间会话（session_id包含 ":to:"）
copaw chats list --agent-id my_bot | \
  jq '[.[] | select(.session_id | contains(":to:"))]'

# 找特定的对话伙伴
copaw chats list --agent-id my_bot | \
  jq '[.[] | select(.session_id | contains(":to:finance_bot"))]'
```

**从输出中获取**：
- `session_id`：用于 `--session-id` 参数续聊
- `updated_at`：查看最后活跃时间

---

## 注意事项

### ⚠️ 并发安全

默认情况下，每次调用都会生成新的唯一session ID（带时间戳+UUID），避免并发冲突。

如果手动指定 `--session-id` 复用会话，**不要并发请求同一个session**，可能会失败。

### ⚠️ 循环调用检测

系统不会自动检测循环调用，需要agent自己注意：

- 如果收到来自 Agent B 的消息，不要再调用 Agent B
- 建议在agent逻辑中记录调用链，避免循环

### ⚠️ Session格式

Agent间session格式固定：

```
{from_agent}:to:{to_agent}:{timestamp_ms}:{uuid_short}
```

例如：

```
bot_a:to:bot_b:1710912345678:a1b2c3d4
```

不要手动构造session ID，让系统自动生成。

---

## 帮助信息

随时使用 `-h` 查看详细帮助：

```bash
copaw agents -h
copaw agents list -h
copaw agents chat -h
```
