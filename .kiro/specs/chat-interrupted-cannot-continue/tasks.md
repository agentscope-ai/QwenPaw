# 实施计划

- [x] 1. 编写 Bug 条件探索测试
  - **Property 1: Bug Condition** - 中断操作未通知后端且会话不可恢复
  - **重要**: 此属性测试必须在实施修复之前编写
  - **目标**: 发现能证明 bug 存在的反例
  - **Scoped PBT 方法**: 将属性范围限定到具体的失败场景 — 用户在 LLM 执行工具调用期间点击中断按钮，`api.cancel` 仅执行 `console.log` 而未向后端发送取消请求
  - Bug 条件: `isBugCondition(input)` — `input.action === 'cancel_button_clicked' AND input.agentState IN ['executing_tool', 'streaming_response'] AND api.cancel IS noop`
  - 测试 1（前端）: 调用 `api.cancel({ session_id })` 后，验证是否向后端 `/api/agent/cancel` 发送了 HTTP POST 请求（在未修复代码上将失败 — 仅执行 console.log）
  - 测试 2（后端）: 向 `/api/agent/cancel` 发送 POST 请求，验证端点存在且返回正确响应（在未修复代码上将返回 404）
  - 测试 3（后端）: 模拟一个正在运行的 asyncio task，调用取消端点后验证 task 被 cancel（在未修复代码上无法测试 — 端点不存在）
  - 在未修复代码上运行测试 — 预期测试失败（确认 bug 存在）
  - 记录发现的反例（例如: "`api.cancel` 调用后没有 HTTP 请求发出"、"后端 `/api/agent/cancel` 返回 404"）
  - 任务完成标准: 测试已编写、已运行、失败已记录
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.3_

- [x] 2. 编写 Preservation 属性测试（在实施修复之前）
  - **Property 2: Preservation** - 非中断场景的行为不变
  - **重要**: 遵循观察优先方法论
  - 观察: 在未修复代码上，LLM 正常完成响应时 `customFetch` 正确处理 SSE 流，消息状态为 `'finished'`
  - 观察: 在未修复代码上，`customFetch` 正确将 `data.signal`（AbortSignal）传递给 `fetch` 请求
  - 观察: 在未修复代码上，会话切换时聊天历史正确加载并解析会话 ID
  - 观察: 在未修复代码上，多个并发请求时去重机制和 `realId` 映射正常工作
  - 观察: 在未修复代码上，后端 `query_handler` 在正常完成时正确保存会话状态并通过 `finally` 块执行清理
  - 编写属性测试: 对于所有不满足 bug 条件的输入（非中断场景），验证正常响应完成、会话管理、并发请求处理、异常处理等行为与原始系统一致
  - 在未修复代码上运行测试 — 预期测试通过（确认基线行为）
  - 任务完成标准: 测试已编写、已运行、在未修复代码上通过
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. 修复聊天中断后无法继续对话 bug

  - [x] 3.1 实现前端 `api.cancel` 回调（`console/src/pages/Chat/index.tsx`）
    - 将 `api.cancel` 中的 `console.log(data)` 替换为向后端发送 POST 请求
    - 请求目标: `getApiUrl("/agent/cancel")`，方法: POST
    - 请求体: `{ session_id: data.session_id }`
    - 请求头: 包含 `Content-Type: application/json` 和认证 token（通过 `getApiToken()` 获取）
    - 使用 `.catch()` 捕获请求失败，避免阻塞前端中断流程
    - _Bug_Condition: api.cancel 是空操作，仅执行 console.log 而未通知后端_
    - _Expected_Behavior: api.cancel 调用后向后端 /api/agent/cancel 发送 POST 请求_
    - _Preservation: customFetch 中的 AbortSignal 传递机制保持不变_
    - _Requirements: 2.1_

  - [x] 3.2 新增后端取消端点（`src/copaw/app/routers/agent.py`）
    - 新增 `CancelRequest` Pydantic model，包含 `session_id: str` 字段
    - 新增 `POST /cancel` 端点 `cancel_agent_task`
    - 从 `request.app.state.agent_app` 获取 `AgentApp` 实例
    - 访问 `agent_app._local_tasks` 查找对应 session_id 的 asyncio task
    - 对匹配的未完成 task 调用 `task.cancel()`
    - 返回 `{ cancelled: bool }` 响应
    - _Bug_Condition: 后端缺少取消端点，无法接收前端的取消请求_
    - _Expected_Behavior: 后端收到取消请求后终止对应 session 的 agent 进程_
    - _Preservation: 现有 /agent/process 等端点行为不变_
    - _Requirements: 2.3_

  - [x] 3.3 暴露 agent_app 到 app.state（`src/copaw/app/_app.py`）
    - 在 lifespan 函数中，`yield` 之前添加 `app.state.agent_app = agent_app`
    - 使取消端点可以通过 `request.app.state.agent_app` 访问 `_local_tasks`
    - _Bug_Condition: 取消端点无法访问 AgentApp 实例和 _local_tasks_
    - _Expected_Behavior: agent_app 实例可通过 app.state 访问_
    - _Preservation: 现有 lifespan 逻辑（runner 初始化、清理等）保持不变_
    - _Requirements: 2.3_

  - [x] 3.4 优化 CancelledError 处理（`src/copaw/app/runner/runner.py`）
    - 在 `query_handler` 的 `asyncio.CancelledError` 异常处理中，将 `raise RuntimeError("Task has been cancelled!") from exc` 替换为 `raise`（重新抛出 CancelledError）
    - 确保 `finally` 块中的 `save_session_state` 正常执行
    - 让框架正确识别任务是被取消而非出错
    - _Bug_Condition: CancelledError 被转换为 RuntimeError，可能影响上层框架的取消处理逻辑_
    - _Expected_Behavior: CancelledError 被正确传播，finally 块保存会话状态_
    - _Preservation: 正常完成和其他异常的处理逻辑保持不变_
    - _Requirements: 2.3, 3.5_

  - [x] 3.5 验证 Bug 条件探索测试现在通过
    - **Property 1: Expected Behavior** - 中断操作应终止后端 agent 并恢复会话可用性
    - **重要**: 重新运行任务 1 中的同一测试，不要编写新测试
    - 任务 1 中的测试编码了期望行为：`api.cancel` 向后端发送取消请求，后端终止对应 task
    - 当此测试通过时，确认期望行为已满足
    - 运行 Bug 条件探索测试
    - **预期结果**: 测试通过（确认 bug 已修复）
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.6 验证 Preservation 测试仍然通过
    - **Property 2: Preservation** - 非中断场景的行为不变
    - **重要**: 重新运行任务 2 中的同一测试，不要编写新测试
    - 运行 Preservation 属性测试
    - **预期结果**: 测试通过（确认无回归）
    - 确认修复后所有测试仍然通过

- [x] 4. 检查点 - 确保所有测试通过
  - 确保所有测试通过，如有问题请咨询用户。
