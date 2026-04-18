---
name: multi_agent_collaboration
description: 当需要其他 agent 的专长、上下文或协作支持，或用户明确要求调用其他 agent 时，使用本 skill。先查询可用 agents，再用 qwenpaw agents chat 进行双向沟通。
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "🤝"
---

# 多智能体协作

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
qwenpaw agents list
```

### 2) 发起新对话（实时模式）

```bash
qwenpaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --text "[Agent <your_agent> requesting] ..."
```

### 3) 发起复杂任务（后台模式）

**复杂任务**包括：数据分析、报告生成、批量处理、外部API调用等。

```bash
qwenpaw agents chat --background \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --text "[Agent <your_agent> requesting] ..."
```

**输出**：
```
[TASK_ID: xxx-xxx-xxx]
[SESSION: ...]
```

### 4) 查询后台任务状态

```bash
qwenpaw agents chat --background --task-id <task_id>
```

**重要**：不要频繁查询！提交任务后：
1. **不要硬等** - 继续处理其他任务或工作
2. **等待合理时间后再查** - 根据任务复杂度选择：
   - 简单分析：10-20 秒后查询
   - 复杂分析：30-60 秒后查询
   - 批量处理：1-3 分钟后查询
3. **在等待期间** - 可以回复用户、处理其他请求、或执行其他任务

### 5) 继续已有对话

```bash
qwenpaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --session-id "<session_id>" \
  --text "[Agent <your_agent> requesting] ..."
```

**重点**:
- 不传 `--session-id` = 新对话
- 传 `--session-id` = 续聊（保留上下文）
- 复杂任务用 `--background`，提交后记录 task_id

---

## 任务模式选择

### 实时模式 vs 后台模式

| 任务类型 | 使用模式 | 命令 |
|---------|---------|------|
| 简单快速查询 | 实时模式 | `qwenpaw agents chat` |
| 复杂任务（数据分析、批量处理等） | 后台模式 | `qwenpaw agents chat --background` |

**复杂任务示例**：
- 分析大量数据或日志文件
- 生成详细报告
- 批量处理文件（10+ 个文件）
- 调用慢速外部 API
- 需要并行执行的独立任务

**判断标准**：如果不确定任务会花多长时间，或者任务很复杂，优先使用后台模式。

---

## 最小工作流

### 实时模式工作流

```
1. 判断是否需要其他 agent，或用户是否明确要求调用
2. qwenpaw agents list
3. qwenpaw agents chat 发起对话
4. 从输出中记录 [SESSION: ...]
5. 后续需要上下文时带上 --session-id
```

### 后台模式工作流

```
1. 判断任务是否复杂（数据分析、报告生成等）
2. qwenpaw agents list
3. qwenpaw agents chat --background 提交任务
4. 从输出中记录 [TASK_ID: ...]
5. 继续处理其他工作
6. 等待合理时间（30-60秒）后查询状态
7. 使用 --background --task-id 查询结果
```

---

## 关键规则

### 必填参数

`qwenpaw agents chat` 必须同时提供：
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
qwenpaw agents list

qwenpaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agent scheduler_bot requesting] User explicitly asked to consult finance_bot. 请回答当前待处理的财务任务。"
```

### 新对话

```bash
qwenpaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agent scheduler_bot requesting] 今天有哪些待处理的财务任务？"
```

### 续聊

```bash
qwenpaw agents chat \
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
qwenpaw agents list
```

### 错误 2：想续聊但没传 session-id

这会创建新对话，丢失上下文。

### 错误 3：回调来源 agent

如果你刚收到 Agent B 的消息，不要再调用 Agent B。

---

## 可选命令

### 查看已有会话

```bash
qwenpaw chats list --agent-id <your_agent>
```

### 流式输出

```bash
qwenpaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --mode stream \
  --text "[Agent <your_agent> requesting] ..."
```

### JSON 输出

```bash
qwenpaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --json-output \
  --text "[Agent <your_agent> requesting] ..."
```

---

## 完整参数说明

### qwenpaw agents list

**参数**：
- `--base-url`（可选）：覆盖API地址

**无必填参数**，直接运行即可。

### qwenpaw agents chat

**必填参数**（实时模式）：
- `--from-agent`：发起方agent ID
- `--to-agent`：目标agent ID
- `--text`：消息内容

**后台任务参数**（新增）：
- `--background`：后台任务模式
- `--task-id`：查询任务状态（与 --background 一起使用）

**可选参数**：
- `--session-id`：复用会话上下文（从之前的输出中复制）
- `--new-session`：强制创建新会话（即使传了session-id）
- `--mode`：stream（流式）或 final（完整，默认）
- `--timeout`：超时时间（秒，默认300）
- `--json-output`：输出完整JSON而非纯文本
- `--base-url`：覆盖API地址

---

## 后台任务模式详解（Background Task）

### 什么时候用后台模式？

当任务是**复杂任务**时，使用 `--background` 提交到后台：

✅ **应该使用后台模式**：
- 数据分析（分析日志、统计数据）
- 报告生成（生成长篇报告、文档）
- 批量处理（处理多个文件）
- 外部 API 调用（调用慢速服务）
- 不确定任务时长的复杂任务

❌ **不需要后台模式**：
- 简单快速查询
- 明确知道很快完成的任务

### 后台任务示例

#### 提交复杂任务

```bash
qwenpaw agents chat --background \
  --from-agent scheduler \
  --to-agent data_analyst \
  --text "[Agent scheduler requesting] 分析 /data/logs/2026-03-26.log 中的用户行为，生成详细报告"
```

**输出**：
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[SESSION: scheduler:to:data_analyst:1774516703206:ec02e542]

✅ Task submitted successfully

Check status with:
  qwenpaw agents chat --background --task-id 20802ea3-...
```

#### 查询任务状态

**重要**：提交后不要硬等！

1. **继续处理其他工作** - 回复用户其他问题、执行其他任务
2. **在合适时机查询** - 处理完其他工作后，或用户询问进度时
3. **如果必须等待** - 使用合理间隔（10-60秒），不要立即查询

```bash
# 方式 1：处理其他任务后再查（推荐）
# 提交任务后，继续完成用户的其他请求
# 在适当时机查询：
qwenpaw agents chat --background \
  --task-id 20802ea3-832d-4fb4-86f0-666ad79fcc80

# 方式 2：如果必须等待，使用合理间隔
sleep 30 && qwenpaw agents chat --background \
  --task-id 20802ea3-832d-4fb4-86f0-666ad79fcc80
```

**状态说明**：

任务状态分为两层：
- **外层状态**（API 返回）：`submitted` → `pending` → `running` → `finished`
- **内层状态**（仅当外层是 `finished` 时）：`completed`（成功）或 `failed`（失败）

**可能的输出**：

1. **已提交**（刚提交后立即查询可能看到）：
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: submitted]

📤 Task submitted, waiting to start...

💡 Don't wait - continue with other work!
   Check again in a few seconds:
  qwenpaw agents chat --background --task-id 20802ea3-...
```

2. **等待执行**：
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: pending]

⏸️  Task is pending in queue...

💡 Don't wait - handle other work first!
   Check again in a few seconds:
  qwenpaw agents chat --background --task-id 20802ea3-...
```

4. **正在执行**：
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: running]

⏳ Task is still running...
   Started at: 1774516703

💡 Don't wait - continue with other tasks first!
   Check again later (10-30s):
  qwenpaw agents chat --background --task-id 20802ea3-...
```

5. **成功完成**：
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: finished]

✅ Task completed

（任务结果内容...）
```

6. **执行失败**：
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: finished]

❌ Task failed

Error: （错误信息...）
```

### 查询间隔策略

**不要频繁查询！** 提交任务后应该：

1. **继续处理其他工作** - 不要硬等，去完成其他任务
2. **等待合理时间后再查** - 根据任务复杂度选择间隔
3. **避免阻塞当前流程** - 这是后台任务的核心价值

| 任务类型 | 建议首次查询 | 后续间隔 | 等待期间做什么 |
|---------|------------|---------|--------------|
| 简单分析 | 10 秒后 | 5-10 秒 | 处理其他用户请求 |
| 复杂分析 | 30 秒后 | 10-20 秒 | 完成当前对话其他部分 |
| 批量处理 | 1 分钟后 | 20-30 秒 | 执行其他独立任务 |
| 超大任务 | 2 分钟后 | 30-60 秒 | 继续用户的其他工作 |

#### ✅ 推荐做法

**方式 1：处理其他任务后再查**（推荐）
```bash
# 1. 提交任务，记录 task_id
qwenpaw agents chat --background ... 
# 返回 task_id

# 2. 继续处理用户的其他请求或任务
# （比如回答其他问题、执行其他操作）

# 3. 在适当时机查询结果
# （比如处理完当前任务后，或用户询问进度时）
qwenpaw agents chat --background --task-id <id>
```

**方式 2：定时轮询**（如果必须等待）
```bash
# 递增间隔，先快后慢
sleep 10 && qwenpaw agents chat --background --task-id <id>
sleep 20 && qwenpaw agents chat --background --task-id <id>
sleep 30 && qwenpaw agents chat --background --task-id <id>
```

#### ❌ 不要这样做

```bash
# 错误：查询太频繁
while true; do
    qwenpaw agents chat --background --task-id <id>
    sleep 1  # 太频繁了！
done
```

---

## 帮助信息

随时使用 `-h` 查看详细帮助：

```bash
qwenpaw agents -h
qwenpaw agents list -h
qwenpaw agents chat -h
```
