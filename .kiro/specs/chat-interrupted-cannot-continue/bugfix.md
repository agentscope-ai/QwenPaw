# Bugfix 需求文档

## 简介

在 Web 聊天界面中，当 LLM 正在执行工具调用（如 `execute_shell_command`）时，用户点击"中断"（Stop）按钮后，聊天会话进入不可恢复的状态：界面显示"Answers have stopped"，且用户无法再发送新消息继续对话。此 bug 严重影响用户体验，因为用户必须刷新页面或创建新会话才能继续使用聊天功能。

根本原因涉及前后端两侧：

1. **`api.cancel` 回调是空操作**：在 `console/src/pages/Chat/index.tsx` 中，`api.cancel` 仅执行 `console.log(data)` 而未向后端发送取消请求。当 `@agentscope-ai/chat` 库的中断逻辑调用此回调时，后端 agent 进程不会收到任何取消信号，继续执行工具调用并向 SSE 流写入数据。

2. **前端 SSE 流中断但后端未同步**：虽然 `customFetch` 正确地将 `data.signal`（AbortSignal）传递给了 `fetch` 请求，前端可以通过 `AbortController.abort()` 中断 HTTP 连接。但后端的 `AgentRunner.query_handler` 只有在 asyncio task 被显式取消时才会触发 `CancelledError` 处理逻辑（调用 `agent.interrupt()`）。仅关闭 HTTP 连接可能不足以立即取消后端的 asyncio task，特别是当 agent 正在执行长时间运行的工具（如 shell 命令）时。

3. **中断后会话状态不一致**：前端将最后一条响应消息的 `msgStatus` 设为 `'interrupted'`，但后端不知道这一状态变化。当用户尝试发送新消息时，`@agentscope-ai/chat` 库内部的状态管理可能因为上一轮未正确完成的请求而阻止新消息的提交，导致持续显示"Answers have stopped"。

## Bug 分析

### 当前行为（缺陷）

1.1 WHEN 用户在 LLM 正在执行工具调用（如 execute_shell_command）时点击中断按钮 THEN 系统仅在前端将响应标记为 'interrupted' 并显示"Answers have stopped"，但 `api.cancel` 回调仅执行 `console.log` 而未向后端发送取消请求，后端 agent 进程继续执行

1.2 WHEN 用户在中断后尝试发送新消息 THEN 系统无法正常提交新消息，界面持续显示"Answers have stopped"错误，聊天会话处于不可用状态

1.3 WHEN 后端 agent 正在执行长时间运行的工具调用且前端中断了 SSE 连接 THEN 系统的后端 agent 进程未被及时终止，继续占用资源执行已被用户取消的任务

### 期望行为（正确）

2.1 WHEN 用户在 LLM 正在执行工具调用时点击中断按钮 THEN 系统 SHALL 通过 `api.cancel` 回调向后端发送取消请求（取消对应 session_id 的 agent 处理任务），同时中断前端的 SSE 流读取

2.2 WHEN 用户在中断后尝试发送新消息 THEN 系统 SHALL 允许用户正常发送新消息并获得 LLM 响应，聊天会话恢复到可用状态

2.3 WHEN 后端收到取消请求或检测到 SSE 连接断开 THEN 系统 SHALL 终止正在执行的 agent 进程（包括正在运行的工具调用），释放相关资源，并正确保存当前会话状态

### 不变行为（回归预防）

3.1 WHEN LLM 正常完成响应（未被中断）THEN 系统 SHALL CONTINUE TO 正确显示完整的响应内容，消息状态为 'finished'

3.2 WHEN 用户在非工具调用期间（如普通文本生成）正常对话 THEN 系统 SHALL CONTINUE TO 正常处理消息的发送和接收

3.3 WHEN 用户切换会话或创建新会话 THEN 系统 SHALL CONTINUE TO 正确加载聊天历史并解析会话 ID

3.4 WHEN 多个并发请求发生时 THEN 系统 SHALL CONTINUE TO 正确去重请求并保留 realId 映射关系

3.5 WHEN 后端 agent 因其他原因（如异常）终止时 THEN 系统 SHALL CONTINUE TO 正确保存会话状态并允许用户继续对话
