---
name: multi_agent_collaboration
description: Use this skill when another agent's expertise/context is needed, or when the user explicitly asks to involve another agent. First list agents, then use copaw agents chat for two-way communication with replies. | 当需要其他 agent 的专长/上下文，或用户明确要求调用其他 agent 时使用；先查 agent，再用 copaw agents chat 双向通信（有回复）
metadata: { "builtin_skill_version": "1.0", "copaw": { "emoji": "🤝" } }
---

# Multi-Agent Collaboration（多智能体协作）

## 什么时候用

当你**需要其他 agent 的专业能力、上下文、workspace 内容或协作支持**时，使用本 skill。  
如果**用户明确要求某个 agent 参与/协助/回答**，也应使用本 skill。

### 应该使用
- 当前任务明显更适合某个专用 agent
- 需要另一个 agent 的 workspace / 文件 / 上下文
- 需要第二意见或专业复核
- 用户明确要求某个 agent 参与或调用其他 agent

### 不应使用
- 你自己可以直接完成，且用户没有明确要求调用其他 agent
- 只是普通问答，不需要专门 agent
- 信息不足，应先追问用户
- 刚收到 Agent B 的消息，**不要再调用 Agent B**，避免循环

## 决策规则

1. **如果用户明确要求调用其他 agent，优先按要求执行**
2. **否则，能自己做，就不要调用**
3. **调用前先查 agent，不要猜 ID**
4. **需要上下文续聊时，必须传 `--session-id`**
5. **不要回调消息来源 agent**

---

## 最常用命令

### 1) 先查询可用 agents

```bash
copaw agents list
```

### 2) 发起新对话

```bash
copaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --text "[Agent <your_agent> requesting] ..."
```

### 3) 继续已有对话

```bash
copaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --session-id "<session_id>" \
  --text "[Agent <your_agent> requesting] ..."
```

**重点**:
- 不传 `--session-id` = 新对话
- 传 `--session-id` = 续聊（保留上下文）

---

## 最小工作流

```
1. 判断是否需要其他 agent，或用户是否明确要求调用
2. copaw agents list
3. copaw agents chat 发起对话
4. 从输出中记录 [SESSION: ...]
5. 后续需要上下文时带上 --session-id
```

---

## 关键规则

### 必填参数

`copaw agents chat` 必须同时提供：
- `--from-agent`
- `--to-agent`
- `--text`

### 身份前缀

消息建议以以下前缀开头：

```text
[Agent my_agent requesting] ...
```

### 会话复用

首次调用会返回：

```text
[SESSION: your_agent:to:target_agent:...]
```

后续续聊必须复制这个 session_id 传入 `--session-id`。

---

## 简短示例

### 用户明确要求调用其他 agent

```bash
copaw agents list

copaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agent scheduler_bot requesting] User explicitly asked to consult finance_bot. 请回答当前待处理的财务任务。"
```

### 新对话

```bash
copaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agent scheduler_bot requesting] 今天有哪些待处理的财务任务？"
```

### 续聊

```bash
copaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --session-id "scheduler_bot:to:finance_bot:1710912345:a1b2c3d4" \
  --text "[Agent scheduler_bot requesting] 展开第2项"
```

---

## 常见错误

### 错误 1：没先查 agent

不要猜 agent ID，先执行：

```bash
copaw agents list
```

### 错误 2：想续聊但没传 session-id

这会创建新对话，丢失上下文。

### 错误 3：回调来源 agent

如果你刚收到 Agent B 的消息，不要再调用 Agent B。

---

## 可选命令

### 查看已有会话

```bash
copaw chats list --agent-id <your_agent>
```

### 流式输出

```bash
copaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --mode stream \
  --text "[Agent <your_agent> requesting] ..."
```

### JSON 输出

```bash
copaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --json-output \
  --text "[Agent <your_agent> requesting] ..."
```

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

## 帮助信息

随时使用 `-h` 查看详细帮助：

```bash
copaw agents -h
copaw agents list -h
copaw agents chat -h
```
