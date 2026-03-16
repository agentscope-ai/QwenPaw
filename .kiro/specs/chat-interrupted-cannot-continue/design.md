# 聊天中断后无法继续 Bugfix 设计

## 概述

在 Web 聊天界面中，当 LLM 正在执行工具调用时用户点击"中断"按钮，聊天会话进入不可恢复状态。根本原因是三层缺陷的叠加：(1) 前端 `api.cancel` 回调是空操作（仅 `console.log`），未向后端发送取消请求；(2) 前端通过 `AbortController` 中断了 SSE 流，但后端 asyncio task 未被显式取消，agent 进程继续执行；(3) 中断后前端将消息状态设为 `'interrupted'`，但 `@agentscope-ai/chat` 库的内部状态管理因上一轮请求未正确完成而阻止新消息提交。

修复策略：实现 `api.cancel` 回调向后端发送取消请求，后端新增取消端点以显式取消对应 session 的 asyncio task，并确保取消后会话状态正确保存以允许后续对话继续。

## 术语表

- **Bug_Condition (C)**: 触发 bug 的条件 — 用户在 LLM 执行工具调用期间点击中断按钮，`api.cancel` 仅执行 `console.log` 而未通知后端，导致会话状态不一致
- **Property (P)**: 期望行为 — 中断操作应向后端发送取消请求，终止 agent 进程，保存会话状态，并允许用户继续发送新消息
- **Preservation**: 不应被修改影响的现有行为 — 正常完成的响应、非工具调用期间的对话、会话切换、并发请求去重
- **AgentRunner.query_handler**: `src/copaw/app/runner/runner.py` 中的异步生成器方法，处理 agent 查询并通过 SSE 流式返回结果
- **CoPawAgent.interrupt()**: `src/copaw/agents/react_agent.py` 中的方法，取消 agent 的 `_reply_task` 并等待清理完成
- **AgentApp**: `agentscope_runtime` 库中的类，管理 `/agent/process` 端点和 `_local_tasks` 任务映射
- **customFetch**: `console/src/pages/Chat/index.tsx` 中的回调函数，负责向后端发送 SSE 请求，支持 `AbortSignal`
- **api.cancel**: `@agentscope-ai/chat` 库在用户点击中断按钮时调用的回调，接收 `{ session_id: string }` 参数
- **msgStatus**: 消息状态字段，可选值为 `'finished'` | `'interrupted'` | `'generating'` | `'error'`

## Bug 详情

### Bug 条件

当用户在 LLM 正在执行工具调用（如 `execute_shell_command`）时点击中断按钮，`@agentscope-ai/chat` 库调用 `api.cancel({ session_id })` 回调。当前实现中该回调仅执行 `console.log(data)` 而未向后端发送任何请求。前端虽然通过 `AbortController.abort()` 中断了 SSE HTTP 连接，但后端的 asyncio task 不一定会因 HTTP 连接断开而被取消（特别是在执行长时间工具调用时）。中断后，`@agentscope-ai/chat` 库将最后一条响应消息的 `msgStatus` 设为 `'interrupted'`，但库的内部状态管理因上一轮请求未正确完成而阻止新消息的提交。

**形式化规约：**

```
FUNCTION isBugCondition(input)
  INPUT: input of type { action: string, sessionId: string, agentState: string }
  OUTPUT: boolean

  RETURN input.action === 'cancel_button_clicked'
         AND input.agentState IN ['executing_tool', 'streaming_response']
         AND api.cancel IS noop (only console.log)
         AND backend_task_for(input.sessionId) IS still_running
END FUNCTION
```

### 示例

- **示例 1**: 用户发送"列出当前目录文件"，LLM 调用 `execute_shell_command("ls -la")`，用户在工具执行期间点击中断 → 期望：后端 agent 进程被终止，用户可继续发送新消息；实际：后端继续执行，前端显示"Answers have stopped"，无法发送新消息
- **示例 2**: 用户发送复杂任务，LLM 进入多轮工具调用循环，用户在第 3 轮工具调用时点击中断 → 期望：agent 停止当前迭代，保存已有对话状态；实际：agent 继续执行剩余迭代，前端会话卡死
- **示例 3**: 用户在 LLM 普通文本流式输出期间点击中断 → 期望：SSE 流被中断，用户可继续对话；实际：前端 `AbortController` 中断了 HTTP 连接，但后端可能未感知，会话状态可能不一致
- **边界情况**: 用户在 LLM 刚开始响应（尚未进入工具调用）时点击中断 → 前端 `AbortController` 可能足以中断，但 `api.cancel` 仍应通知后端以确保一致性

## 期望行为

### 保持不变的行为

**不变行为：**

- LLM 正常完成响应（未被中断）时，系统正确显示完整响应内容，消息状态为 `'finished'`
- 用户在非工具调用期间正常对话时，消息的发送和接收流程保持不变
- 用户切换会话或创建新会话时，聊天历史正确加载并解析会话 ID
- 多个并发请求发生时，请求去重和 `realId` 映射关系保持正确
- 后端 agent 因其他原因（如异常）终止时，会话状态正确保存并允许用户继续对话
- `customFetch` 中的 `AbortSignal` 传递机制保持不变

**范围：**
所有不涉及用户主动点击中断按钮的场景应完全不受此修复影响。这包括：

- 正常的消息发送和接收
- LLM 自然完成响应的流程
- 会话管理操作（创建、切换、删除）
- 后端异常导致的错误处理流程

## 假设的根本原因

基于 bug 分析，最可能的原因是：

1. **`api.cancel` 回调是空操作**: 在 `console/src/pages/Chat/index.tsx` 第 252 行，`cancel` 回调仅执行 `console.log(data)`。当 `@agentscope-ai/chat` 库在用户点击中断按钮时调用此回调，后端不会收到任何取消信号。这是最直接的原因。

2. **后端缺少取消端点**: 当前后端 API 没有专门的取消/中断端点。`AgentApp` 的 `_local_tasks` 中维护了正在运行的 asyncio task，但没有暴露通过 session_id 取消特定 task 的 HTTP 接口。即使前端发送取消请求，也没有后端端点可以接收。

3. **HTTP 连接断开不等于 task 取消**: 前端通过 `AbortController.abort()` 中断 SSE 连接后，后端的 `query_handler` 中的 `asyncio.CancelledError` 处理逻辑只有在 asyncio task 被显式 `cancel()` 时才会触发。仅关闭 HTTP 连接可能不足以取消正在执行长时间工具调用的 asyncio task。

4. **`@agentscope-ai/chat` 库的状态管理**: 中断后，库将消息状态设为 `'interrupted'` 并显示"Answers have stopped"。库的内部状态可能因为上一轮请求的 `loading` 状态未被正确重置而阻止新消息的提交。`api.cancel` 回调的正确实现可能是库重置内部状态的前提条件。

## 正确性属性

Property 1: Bug Condition - 中断操作应终止后端 agent 并恢复会话可用性

_For any_ 用户在 LLM 执行工具调用或流式响应期间点击中断按钮的输入（isBugCondition 返回 true），修复后的系统 SHALL 通过 `api.cancel` 回调向后端发送取消请求，后端 SHALL 终止对应 session_id 的 agent 进程（包括正在运行的工具调用），保存当前会话状态，并允许用户在中断后正常发送新消息继续对话。

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - 非中断场景的行为不变

_For any_ 不涉及用户点击中断按钮的输入（isBugCondition 返回 false），修复后的系统 SHALL 产生与原始系统完全相同的行为，保留正常响应完成、会话管理、并发请求处理等所有现有功能。

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## 修复实现

### 所需变更

假设我们的根因分析正确：

**文件 1**: `console/src/pages/Chat/index.tsx`

**函数**: `options` useMemo 中的 `api.cancel` 回调

**具体变更**:

1. **实现 `api.cancel` 回调**: 将空操作的 `console.log(data)` 替换为向后端发送 POST 请求到取消端点 `/api/agent/cancel`，传递 `session_id` 参数。

**变更前代码**:

```typescript
api: {
  ...defaultConfig.api,
  fetch: customFetch,
  cancel(data: { session_id: string }) {
    console.log(data);
  },
},
```

**变更后代码**:

```typescript
api: {
  ...defaultConfig.api,
  fetch: customFetch,
  cancel(data: { session_id: string }) {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const token = getApiToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    fetch(getApiUrl("/agent/cancel"), {
      method: "POST",
      headers,
      body: JSON.stringify({
        session_id: data.session_id,
      }),
    }).catch((err) => {
      console.warn("Failed to cancel agent task:", err);
    });
  },
},
```

---

**文件 2**: `src/copaw/app/routers/agent.py`

**新增端点**: `POST /agent/cancel`

**具体变更**:

2. **新增取消端点**: 在 agent router 中添加 `/cancel` POST 端点，接收 `session_id` 参数，查找 `AgentApp._local_tasks` 中对应的 asyncio task 并调用 `task.cancel()`。

```python
class CancelRequest(BaseModel):
    """Cancel request body."""
    session_id: str = Field(..., description="Session ID to cancel")


@router.post(
    "/cancel",
    response_model=dict,
    summary="Cancel an active agent task",
    description="Cancel the running agent task for a given session",
)
async def cancel_agent_task(
    request: Request,
    body: CancelRequest,
) -> dict:
    """Cancel an active agent task by session_id."""
    agent_app = getattr(request.app.state, "agent_app", None)
    # AgentApp stores tasks in _local_tasks dict
    local_tasks = getattr(agent_app, "_local_tasks", None) if agent_app else None
    if not local_tasks:
        return {"cancelled": False, "reason": "no active tasks"}

    # Find and cancel the task for this session
    cancelled = False
    for task_key, task in list(local_tasks.items()):
        if body.session_id in str(task_key) and not task.done():
            task.cancel()
            cancelled = True
            break

    return {"cancelled": cancelled}
```

注意：由于 `AgentApp` 是 `agentscope_runtime` 库的类，`_local_tasks` 的键格式需要在实际调试中确认。可能需要通过 `request.app.state.runner` 或直接访问模块级 `agent_app` 实例来获取 task 映射。

---

**文件 3**: `src/copaw/app/_app.py`

**具体变更**:

3. **暴露 agent_app 到 app.state**: 在 lifespan 函数中将 `agent_app` 实例添加到 `app.state`，使取消端点可以访问 `_local_tasks`。

```python
# 在 lifespan 函数中，yield 之前添加：
app.state.agent_app = agent_app
```

---

**文件 4**: `src/copaw/app/runner/runner.py`

**函数**: `AgentRunner.query_handler`

**具体变更**:

4. **确保取消后会话状态正确保存**: 当前 `query_handler` 在 `asyncio.CancelledError` 异常处理中调用 `agent.interrupt()` 后抛出 `RuntimeError`。`finally` 块中的 `save_session_state` 会被执行，但需要确认 `RuntimeError` 不会阻止状态保存。当前实现看起来 `finally` 块会正确执行，但需要验证 `agent.interrupt()` 完成后 agent 的内存状态是否完整可保存。

5. **优化取消异常处理**: 考虑在 `CancelledError` 处理中不抛出 `RuntimeError`，而是让 `finally` 块正常保存状态后优雅退出，避免上层框架将取消视为错误。

**变更前代码**:

```python
except asyncio.CancelledError as exc:
    logger.info(f"query_handler: {session_id} cancelled!")
    if agent is not None:
        await agent.interrupt()
    raise RuntimeError("Task has been cancelled!") from exc
```

**变更后代码**:

```python
except asyncio.CancelledError as exc:
    logger.info(f"query_handler: {session_id} cancelled!")
    if agent is not None:
        await agent.interrupt()
    # Let finally block save session state, then re-raise as CancelledError
    # so the framework knows the task was cancelled (not errored)
    raise
```

## 测试策略

### 验证方法

测试策略遵循两阶段方法：首先在未修复代码上发现反例以确认 bug，然后验证修复后的代码行为正确且保留了现有功能。

### 探索性 Bug 条件检查

**目标**: 在实施修复前，发现能证明 bug 存在的反例。确认或否定根因分析。如果否定，需要重新假设。

**测试计划**: 编写测试验证 `api.cancel` 回调是否向后端发送了取消请求，以及后端是否正确取消了对应的 asyncio task。在未修复代码上运行以观察失败。

**测试用例**:

1. **cancel 回调空操作测试**: 调用 `api.cancel({ session_id: "test-session" })`，验证是否向后端发送了 HTTP 请求（将在未修复代码上失败 — 仅执行 console.log）
2. **后端取消端点不存在测试**: 向 `/api/agent/cancel` 发送 POST 请求，验证端点是否存在（将在未修复代码上返回 404）
3. **中断后发送新消息测试**: 模拟中断流程后尝试发送新消息，验证消息是否能正常提交（将在未修复代码上失败）
4. **后端 task 未取消测试**: 在前端中断 SSE 连接后，检查后端 asyncio task 是否仍在运行（将在未修复代码上观察到 task 继续执行）

**预期反例**:

- `api.cancel` 调用后没有 HTTP 请求发出
- 后端 agent 进程在前端中断后继续执行工具调用
- 可能原因：`api.cancel` 是空操作、后端缺少取消端点、HTTP 断开不触发 task 取消

### Fix 检查

**目标**: 验证对于所有满足 bug 条件的输入，修复后的系统产生期望行为。

**伪代码:**

```
FOR ALL input WHERE isBugCondition(input) DO
  // 用户点击中断按钮
  api.cancel({ session_id: input.sessionId })

  // 验证前端行为
  ASSERT http_request_sent_to("/api/agent/cancel", { session_id: input.sessionId })

  // 验证后端行为
  ASSERT backend_task_for(input.sessionId).is_cancelled() == true
  ASSERT session_state_saved(input.sessionId) == true

  // 验证会话恢复
  result := send_new_message(input.sessionId, "继续对话")
  ASSERT result.status == 'success'
  ASSERT result.response IS NOT NULL
END FOR
```

### Preservation 检查

**目标**: 验证对于所有不满足 bug 条件的输入，修复后的系统产生与原始系统相同的行为。

**伪代码:**

```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT system_original(input) = system_fixed(input)
END FOR
```

**测试方法**: 推荐使用属性测试（Property-Based Testing）进行 preservation 检查，因为：

- 它能自动生成大量测试用例覆盖输入域
- 它能捕获手动单元测试可能遗漏的边界情况
- 它能提供强有力的保证：所有非中断输入的行为不变

**测试计划**: 先在未修复代码上观察正常对话、会话管理等行为，然后编写属性测试捕获这些行为。

**测试用例**:

1. **正常响应完成保留**: 验证 LLM 正常完成响应时，消息状态为 `'finished'`，响应内容完整（修复前后行为一致）
2. **会话切换保留**: 验证切换会话时，聊天历史正确加载，会话 ID 正确解析
3. **并发请求保留**: 验证多个并发请求时，去重机制和 `realId` 映射正常工作
4. **异常处理保留**: 验证后端 agent 因异常终止时，会话状态正确保存并允许继续对话

### 单元测试

- 测试 `api.cancel` 回调向后端发送正确的 HTTP 请求（包含 session_id 和认证 token）
- 测试后端 `/api/agent/cancel` 端点正确查找并取消对应的 asyncio task
- 测试 `query_handler` 在 `CancelledError` 后正确保存会话状态
- 测试 `CoPawAgent.interrupt()` 正确取消 `_reply_task` 并等待清理
- 测试取消不存在的 session_id 时返回适当的响应

### 属性测试

- 生成随机的 session_id 和 agent 状态，验证取消操作后会话状态被正确保存
- 生成随机的非中断输入（正常消息、会话操作），验证修复后行为与修复前完全一致
- 生成随机的并发场景（多个会话同时活跃），验证取消一个会话不影响其他会话

### 集成测试

- 测试完整的中断流程：发送消息 → LLM 开始工具调用 → 点击中断 → 验证后端 task 被取消 → 发送新消息 → 验证响应正常
- 测试中断后会话状态恢复：中断 → 刷新页面 → 验证聊天历史正确加载 → 继续对话
- 测试多会话场景：会话 A 正在执行 → 中断会话 A → 切换到会话 B → 验证会话 B 不受影响
