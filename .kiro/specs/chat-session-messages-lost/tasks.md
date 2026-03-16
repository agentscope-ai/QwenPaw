# 实施计划

- [x] 1. 编写 Bug 条件探索测试
  - **Property 1: Bug Condition** - updateSession 清空已有消息
  - **重要**: 此属性测试必须在实施修复之前编写
  - **目标**: 发现能证明 bug 存在的反例
  - **Scoped PBT 方法**: 将属性范围限定到具体的失败场景 — `sessionList` 中存在带有非空 `messages` 的会话，调用 `updateSession` 传入该会话的部分更新
  - Bug 条件: `isBugCondition(input)` — `sessionList` 中存在 `id === session.id` 的会话，且该会话 `messages.length > 0`，此时调用 `updateSession`
  - 构造 `sessionList` 中有多条消息的会话，调用 `updateSession({ id, name: "新名称" })` 仅更新元数据
  - 断言 `sessionList` 中该会话的 `messages` 应保持不变（与调用前相同）
  - 在未修复代码上运行测试 — 预期测试失败（确认 bug 存在）
  - 记录发现的反例（例如: "调用 `updateSession({ id, name })` 后，`sessionList` 中的 messages 从 3 条变为 0 条"）
  - 任务完成标准: 测试已编写、已运行、失败已记录
  - _Requirements: 1.1, 1.2, 2.1, 2.2_

- [x] 2. 编写 Preservation 属性测试（在实施修复之前）
  - **Property 2: Preservation** - 元数据更新和 realId 解析行为不变
  - **重要**: 遵循观察优先方法论
  - 观察: 在未修复代码上，`updateSession({ id, name: "新名称" })` 正确更新 `sessionList` 中的 `name` 字段
  - 观察: 在未修复代码上，对 `isLocalTimestamp(id)` 且无 `realId` 的会话，`updateSession` 触发 `getSessionList` + `resolveRealId` 流程
  - 观察: 在未修复代码上，`updateSession({ id: "不存在的ID" })` 走 else 分支刷新 sessionList
  - 观察: 在未修复代码上，`updateSession` 返回 `sessionList` 的浅拷贝
  - 编写属性测试: 对于所有不满足 bug 条件的输入（会话不在 `sessionList` 中，或会话 `messages` 为空），验证元数据更新、realId 解析、fallback 刷新等行为与原始函数一致
  - 在未修复代码上运行测试 — 预期测试通过（确认基线行为）
  - 任务完成标准: 测试已编写、已运行、在未修复代码上通过
  - _Requirements: 3.1, 3.2, 3.4, 3.5_

- [x] 3. 修复 updateSession 消息丢失 bug

  - [x] 3.1 实施修复
    - 移除 `session.messages = []` 赋值语句
    - 使用解构 `const { messages, ...metadataUpdate } = session as any` 从传入的 session 对象中排除 `messages` 字段
    - 将展开合并中的 `session` 替换为 `metadataUpdate`：`{ ...this.sessionList[index], ...metadataUpdate }`
    - 更新 `findIndex` 使用 `metadataUpdate.id` 替代 `session.id`
    - 保持 `realId` 解析流程、else 分支 fallback 逻辑、返回值等其余逻辑不变
    - _Bug_Condition: isBugCondition(input) — sessionList 中存在 id === session.id 的会话且 messages.length > 0 时调用 updateSession_
    - _Expected_Behavior: updateSession 调用后 sessionList 中对应会话的 messages 保持不变_
    - _Preservation: 元数据更新、realId 解析流程、onSessionIdResolved 回调、fallback 刷新逻辑保持不变_
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.4, 3.5_

  - [x] 3.2 验证 Bug 条件探索测试现在通过
    - **Property 1: Expected Behavior** - updateSession 不应清空已有消息
    - **重要**: 重新运行任务 1 中的同一测试，不要编写新测试
    - 任务 1 中的测试编码了期望行为：`updateSession` 调用后 messages 保持不变
    - 当此测试通过时，确认期望行为已满足
    - 运行 Bug 条件探索测试
    - **预期结果**: 测试通过（确认 bug 已修复）
    - _Requirements: 2.1, 2.2_

  - [x] 3.3 验证 Preservation 测试仍然通过
    - **Property 2: Preservation** - 元数据更新和 realId 解析行为不变
    - **重要**: 重新运行任务 2 中的同一测试，不要编写新测试
    - 运行 Preservation 属性测试
    - **预期结果**: 测试通过（确认无回归）
    - 确认修复后所有测试仍然通过

- [x] 4. 检查点 - 确保所有测试通过
  - 确保所有测试通过，如有问题请咨询用户。
