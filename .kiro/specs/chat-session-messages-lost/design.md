# 聊天会话消息丢失 Bugfix 设计

## 概述

`SessionApi.updateSession` 方法在第一行执行 `session.messages = []`，在每次更新会话时强制清空传入 session 对象的消息数组。当 UI 组件在 LLM 流式响应期间调用 `updateSession` 保存会话状态时，空消息数组通过展开运算符 `{ ...this.sessionList[index], ...session }` 覆盖了 `sessionList` 中已有的消息数据。用户切换页面后返回，`getSession` 从内存中的 `sessionList` 读取到的是已被清空的消息，导致消息丢失且无法恢复。

修复策略：移除 `updateSession` 中的 `session.messages = []` 赋值语句，并在合并到 `sessionList` 前删除传入 session 对象上的 `messages` 属性，确保 `updateSession` 仅更新会话元数据而不影响消息数据。

## 术语表

- **Bug_Condition (C)**: 触发 bug 的条件 — `updateSession` 被调用时，传入的 session 对象的 `messages` 字段被强制设为空数组，覆盖 `sessionList` 中已有的消息
- **Property (P)**: 期望行为 — `updateSession` 调用后，`sessionList` 中对应会话的 `messages` 应保持不变（保留调用前的值）
- **Preservation**: 不应被修改影响的现有行为 — `realId` 解析流程、会话创建/删除、并发请求去重
- **SessionApi**: `console/src/pages/Chat/sessionApi/index.ts` 中的类，管理聊天会话的 CRUD 操作和内存缓存
- **sessionList**: `SessionApi` 的私有属性，内存中的会话列表缓存，包含每个会话的 `messages` 数据
- **ExtendedSession**: 扩展的会话接口，包含 `realId`、`sessionId`、`userId`、`channel` 等额外字段
- **realId**: 后端分配的真实 UUID，用于替代前端生成的临时时间戳 ID

## Bug 详情

### Bug 条件

当 `updateSession` 被调用时，方法第一行 `session.messages = []` 强制将传入 session 对象的 `messages` 设为空数组。随后通过 `{ ...this.sessionList[index], ...session }` 展开合并时，空的 `messages` 覆盖了 `sessionList` 中已有的消息数据。这在 LLM 流式响应期间尤为严重，因为 UI 组件会频繁调用 `updateSession` 来同步会话状态。

**形式化规约：**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { session: Partial<Session>, sessionList: Session[] }
  OUTPUT: boolean

  existingSession := sessionList.find(s => s.id === input.session.id)

  RETURN existingSession IS NOT NULL
         AND existingSession.messages.length > 0
         AND updateSession(input.session) is called
         // Bug: session.messages 被强制设为 []，覆盖 existingSession.messages
END FUNCTION
```

### 示例

- **示例 1**: 用户发送消息，LLM 正在流式响应（已返回部分内容），UI 调用 `updateSession({ id: "abc", name: "新对话" })` 更新会话名称 → 期望：`sessionList` 中 id="abc" 的会话 messages 保持不变；实际：messages 被清空为 `[]`
- **示例 2**: 用户在工具调用期间切换到模型配置页面，组件卸载前调用 `updateSession` → 期望：消息保留；实际：消息被清空，返回后看到空对话
- **示例 3**: 用户刷新页面后，`getSession` 从后端获取聊天历史 → 期望：显示所有已持久化的消息；实际：如果流式响应被中断，后端可能也未完整保存该轮对话
- **边界情况**: `updateSession` 被调用时 session 不在 `sessionList` 中（index === -1）→ 走 else 分支，调用 `getSessionList` 刷新列表，不涉及消息覆盖问题

## 期望行为

### 保持不变的行为

**不变行为：**
- 鼠标点击切换会话时，`getSession` 从后端获取聊天历史的行为必须保持不变
- `updateSession` 中的 `realId` 解析流程（`isLocalTimestamp` 检查 + `resolveRealId` 调用）必须保持不变
- `createSession` 创建新会话并分配临时时间戳 ID 的行为必须保持不变
- `removeSession` 删除会话并通知消费者的行为必须保持不变
- 并发 `getSessionList` / `getSession` 请求的去重机制必须保持不变
- `updateSession` 更新会话元数据（如 `name`）到 `sessionList` 的行为必须保持不变

**范围：**
所有不涉及 `session.messages` 字段的 `updateSession` 行为应完全不受此修复影响。这包括：
- 会话元数据更新（name、meta 等）
- `realId` 解析和 `onSessionIdResolved` 回调触发
- `sessionList` 中找不到会话时的 fallback 刷新逻辑
- 返回 `sessionList` 副本的行为

## 假设的根本原因

基于 bug 分析，最可能的原因是：

1. **不必要的消息清空**: `updateSession` 方法第 444 行的 `session.messages = []` 是一个错误的防御性编码。开发者可能意图在更新会话元数据时不传递大量消息数据到后端，但实际上 `updateSession` 并不调用后端 API，它只是更新内存中的 `sessionList`。因此这行代码没有任何正面作用，只会破坏已有的消息数据。

2. **展开运算符的覆盖效应**: `{ ...this.sessionList[index], ...session }` 中，`session` 上的 `messages: []` 会覆盖 `this.sessionList[index]` 上已有的 `messages` 数组。这是 JavaScript 展开运算符的正常行为，但在这里产生了非预期的副作用。

3. **缺少消息字段的隔离**: `updateSession` 没有区分"元数据更新"和"消息更新"两种场景。理想情况下，`updateSession` 应该只处理元数据，消息的管理应由 `getSession`（从后端获取）负责。

## 正确性属性

Property 1: Bug Condition - updateSession 不应清空已有消息

_For any_ 调用 `updateSession(session)` 的输入，其中 `sessionList` 中存在 `id === session.id` 的会话且该会话的 `messages` 非空，修复后的 `updateSession` SHALL 保留 `sessionList` 中该会话的 `messages` 不变，不对其进行任何修改或清空。

**Validates: Requirements 2.1, 2.2**

Property 2: Preservation - 元数据更新和 realId 解析行为不变

_For any_ 调用 `updateSession(session)` 的输入，其中 bug 条件不成立（即会话不存在于 `sessionList` 中，或会话的 `messages` 为空），修复后的 `updateSession` SHALL 产生与原始函数完全相同的结果，保留元数据更新、`realId` 解析流程、`onSessionIdResolved` 回调触发等所有现有行为。

**Validates: Requirements 3.1, 3.2, 3.4, 3.5**

## 修复实现

### 所需变更

假设我们的根因分析正确：

**文件**: `console/src/pages/Chat/sessionApi/index.ts`

**函数**: `SessionApi.updateSession`

**具体变更**:
1. **移除消息清空语句**: 删除第 444 行的 `session.messages = []`
2. **排除 messages 字段参与合并**: 在展开合并前，从传入的 `session` 对象中删除 `messages` 属性，确保即使调用方传入了 `messages` 字段，也不会覆盖 `sessionList` 中已有的消息数据。具体做法：
   ```typescript
   const { messages, ...sessionWithoutMessages } = session as any;
   ```
   然后使用 `sessionWithoutMessages` 替代 `session` 进行展开合并。
3. **保持其余逻辑不变**: `realId` 解析流程、`sessionList` 查找和更新逻辑、`onSessionIdResolved` 回调等全部保持原样。

**变更前代码**:
```typescript
async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.messages = [];
    const index = this.sessionList.findIndex((s) => s.id === session.id);

    if (index > -1) {
      this.sessionList[index] = { ...this.sessionList[index], ...session };
      // ...
```

**变更后代码**:
```typescript
async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    const { messages, ...metadataUpdate } = session as any;
    const index = this.sessionList.findIndex((s) => s.id === metadataUpdate.id);

    if (index > -1) {
      this.sessionList[index] = { ...this.sessionList[index], ...metadataUpdate };
      // ...
```

## 测试策略

### 验证方法

测试策略遵循两阶段方法：首先在未修复代码上发现反例以确认 bug，然后验证修复后的代码行为正确且保留了现有功能。

### 探索性 Bug 条件检查

**目标**: 在实施修复前，发现能证明 bug 存在的反例。确认或否定根因分析。如果否定，需要重新假设。

**测试计划**: 编写测试，构造一个带有非空 `messages` 的会话并添加到 `sessionList`，然后调用 `updateSession` 传入该会话的部分更新（如 name 变更），检查 `sessionList` 中该会话的 `messages` 是否被清空。在未修复代码上运行以观察失败。

**测试用例**:
1. **消息清空测试**: 构造 sessionList 中有 3 条消息的会话，调用 `updateSession({ id, name: "新名称" })`，断言 messages 仍有 3 条（将在未修复代码上失败）
2. **流式响应期间更新测试**: 模拟流式响应期间的 `updateSession` 调用，断言消息保留（将在未修复代码上失败）
3. **带 messages 字段的更新测试**: 调用 `updateSession({ id, messages: [...newMsgs] })`，断言 sessionList 中的 messages 不被调用方传入的值覆盖（将在未修复代码上失败）
4. **会话不存在测试**: 调用 `updateSession({ id: "不存在的ID" })`，验证走 else 分支的行为（可能在未修复代码上通过）

**预期反例**:
- `sessionList` 中对应会话的 `messages` 在 `updateSession` 调用后变为空数组 `[]`
- 原因：`session.messages = []` 赋值 + 展开运算符覆盖

### Fix 检查

**目标**: 验证对于所有满足 bug 条件的输入，修复后的函数产生期望行为。

**伪代码:**
```
FOR ALL input WHERE isBugCondition(input) DO
  messagesBefore := copy(sessionList[input.session.id].messages)
  result := updateSession_fixed(input.session)
  messagesAfter := sessionList[input.session.id].messages
  ASSERT messagesAfter EQUALS messagesBefore
END FOR
```

### Preservation 检查

**目标**: 验证对于所有不满足 bug 条件的输入，修复后的函数产生与原始函数相同的结果。

**伪代码:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT updateSession_original(input) = updateSession_fixed(input)
END FOR
```

**测试方法**: 推荐使用属性测试（Property-Based Testing）进行 preservation 检查，因为：
- 它能自动生成大量测试用例覆盖输入域
- 它能捕获手动单元测试可能遗漏的边界情况
- 它能提供强有力的保证：所有非 bug 输入的行为不变

**测试计划**: 先在未修复代码上观察元数据更新、realId 解析等行为，然后编写属性测试捕获这些行为。

**测试用例**:
1. **元数据更新保留**: 验证 `updateSession({ id, name: "新名称" })` 后，sessionList 中的 name 被正确更新（修复前后行为一致）
2. **realId 解析保留**: 验证对于 `isLocalTimestamp(id)` 且无 `realId` 的会话，`updateSession` 仍触发 `getSessionList` + `resolveRealId` 流程
3. **不存在会话的 fallback 保留**: 验证 `updateSession({ id: "不存在" })` 仍走 else 分支刷新 sessionList
4. **返回值保留**: 验证 `updateSession` 返回 `sessionList` 的浅拷贝

### 单元测试

- 测试 `updateSession` 调用后 `sessionList` 中会话的 `messages` 保持不变
- 测试 `updateSession` 正确更新会话元数据（name、meta 等）
- 测试 `updateSession` 对不存在的会话 ID 的处理
- 测试 `updateSession` 对 `isLocalTimestamp` 会话的 `realId` 解析触发

### 属性测试

- 生成随机的 session 对象和 sessionList 状态，验证 `updateSession` 后 messages 不被修改
- 生成随机的元数据更新，验证 `updateSession` 正确合并元数据且不影响 messages
- 生成随机的会话 ID（包括时间戳 ID 和 UUID），验证 `realId` 解析逻辑在修复前后行为一致

### 集成测试

- 测试完整的聊天流程：发送消息 → 流式响应期间调用 updateSession → 验证消息保留
- 测试页面切换流程：发送消息 → 切换页面 → 返回 → 验证 getSession 返回完整消息
- 测试新会话流程：创建会话 → 发送消息 → updateSession 触发 realId 解析 → 验证消息和 realId 都正确
