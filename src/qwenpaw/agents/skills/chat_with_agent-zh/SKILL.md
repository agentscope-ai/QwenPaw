---
name: chat_with_agent
description: 当你需要咨询其他 agent、寻求帮助，或用户明确要求某个 agent 参与时，使用本 skill。
metadata:
  builtin_skill_version: "1.1"
  qwenpaw:
    emoji: "💬"
---

# 与 Agent 对话

## 什么时候用

当你需要**向另一个 agent 询问问题、寻求帮助、请求方案、请求复核、请求决策支持，或者进行任何形式的交流**时，使用本 skill。  
如果**用户明确要求与某个 agent 对话**，也应使用本 skill。

### 应该使用

- 需要另一个 agent 的专长、判断或第二意见
- 需要向某个 agent 请求方案、复核或建议
- 用户明确要求某个 agent 参与、协助或回答
- 需要继续某个已有的 agent 会话，并保留上下文

### 不应使用

- 你自己可以直接完成，且用户没有明确要求调用其他 agent
- 只是普通问答，不需要专门 agent
- 目标 agent 不明确，应该先追问或先查可用 agents
- 刚收到某个 agent 的消息，又立刻回调同一个 agent，可能造成循环

## 决策规则

1. **如果用户明确要求某个 agent，优先按要求执行，但仍要先查 agent，不要猜 ID**
2. **如果你自己能完成，就不要调用其他 agent**
3. **需要保留上下文续聊时，必须传 `session_id`**
4. **默认优先使用 `list_agents()` 和 `chat_with_agent(...)` 进行前台对话，不要绕到别的方式**
5. **如果任务需要后台执行，使用 `submit_to_agent(...)` 提交，再用 `check_agent_task(...)` 查询状态**

## 使用流程

请严格按照以下流程顺序使用本 skill：

1) 确保你的工具列表中包含 `list_agents()` 和 `chat_with_agent(...)` 两个内建工具

  - 这两个工具是与其他 agent 对话的基础，不要删除或禁用它们
  - 如果你没有这两个工具，请告诉用户你需要它们来与其他 agent 对话，并请求用户添加

2) 使用 `list_agents()` 工具查看当前可用的 Agent，并从中选择一个 agent 提取其 id

  - 请根据用户的需求和对应 Agent 的描述来选择最合适的 Agent
  - 如果找不到合适的 Agent 且你不是 Default Agent，就使用 Default Agent
  - 否则告诉用户没有合适的 Agent 可用，并建议他们创建一个新的 Agent 或调整现有 Agent 的描述以便更好地匹配需求

3) 调用 `chat_with_agent(...)` 发起前台求助，其中需要传递的关键参数包括
  - `to_agent`: 对话目标 Agent 的 ID，注意是 ID 不是名字
  - `text`: 你要对目标 Agent 说的内容
  - `session_id`: （可选）如果你需要与同一个 Agent 进行多轮对话，从第二轮开始传递相同的 `session_id` 来保持上下文连续
  - `timeout`: （可选）预估任务需要的前台等待时间，避免过早超时

4) 如果任务适合后台执行，请使用新的后台工具路径
  - `submit_to_agent(...)`：提交后台任务，参数只需要 `to_agent`、`text` 和可选 `session_id`
  - `check_agent_task(...)`：通过 `task_id` 查询任务状态，完成时返回最终结果

## 最小调用示例

### 新对话

```text
list_agents()

chat_with_agent(
  to_agent="<target_agent_id>",
  text="[Agent <your_agent_id> requesting] 我需要你帮我判断这个问题的处理方向。",
)
```

### 续接已有对话

```text
chat_with_agent(
  to_agent="<target_agent_id>",
  text="[Agent <your_agent_id> requesting] 请基于刚才的结论继续展开第 2 点。",
  session_id="<previous_session_id>",
)
```

### 后台提交与查询

```text
submit_to_agent(
  to_agent="<target_agent_id>",
  text="[Agent <your_agent_id> requesting] 请在后台完成这个较长任务。",
)

check_agent_task(
  task_id="<task_id>",
)
```


## 注意事项

- **添加对话标识符**：建议对话内容以如下内容开头

```text
[Agent <your_agent_id> requesting]
```
这样可以让对方 Agent 更清楚地知道是谁在跟它说话，有助于提高沟通效率和准确性。


- **合理复用会话**：如果你需要与同一个 Agent 进行多轮对话，务必传递相同的 `session_id` 来保持上下文连续。否则每次调用都会被视为新的对话，可能导致对方 Agent 无法正确理解你的需求。`session_id` 可以从第一轮对话的返回结果中获取，例如

  ```text
  [SESSION: xxx]
  ```

  其中 `xxx` 就是 `session_id` 的值，该值一般由系统生成，长度一般较长，具有唯一性。你需要把这个 `session_id` 存下来，在后续与同一个 Agent 的对话中继续使用它。
