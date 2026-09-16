# Task 5.2 PostgreSQL 消息与丰富事件持久化设计

## 目标

在多用户模式下，将 Console 对话的 Conversation、Run、Message、RunEvent 与 ToolCall 写入 PostgreSQL，同时保持现有 SSE 字符串、TaskTracker 断线继续执行和前端渲染行为不变。

## 接入位置

持久化必须包裹 `TaskTracker.attach_or_start()` 实际启动的后台事件源，不能包裹 HTTP 响应生成器。浏览器断开只会取消响应订阅，TaskTracker 的生产任务仍继续消费 Agent 事件，因此持久化也能继续到 Run 终态。

调用链：

`Console -> ChatManager.persisting_stream_source() -> 原 console_channel.stream_one() -> PostgreSQL -> TaskTracker buffer/queues -> SSE 客户端`

原始 SSE 帧在落库后原样 yield，不修改 wire envelope。

## ID 与顺序

- Conversation ID：沿用 `ChatSpec.id` UUID。
- Agent ID：沿用 `agent_database_id(agent_key)`。
- Run ID：每个新 Run 生成 UUID。
- RunEvent sequence：每个 Run 从 1 单调递增。
- Message sequence：读取当前会话最大序号后递增；同一 Chat 由 TaskTracker 保证单 Run。
- 非 UUID 的 wire message/tool/approval/event ID 使用带命名空间的 UUIDv5 稳定映射，原始 ID仍完整保存在 JSON payload 中。

## 事件映射

每个可解析的 `data:` SSE 帧保存为一个 RunEvent，payload 保存完整 wire JSON。Message wire 同时保存 Message；工具开始/输出/审批事件同时 upsert ToolCall。`turn_usage`、`replay_end` 等现有控制事件仍可保存为 RunEvent，但不改变前端行为。

超大工具输出、图片和文件不复制二进制正文；现有 URL、路径或内容引用保留在 JSON payload / `output_ref` 中。

## 事务与失败策略

- 每个 SSE 帧的 Event、Message、ToolCall 在一个数据库事务内写入。
- `final`、`error`、取消或异常在相应最后事务中收敛 Run 状态。
- 持久化失败采用 fail-closed：该 Run 终止并由现有 TaskTracker 生成通用错误帧，避免前端显示了无法回放的“幽灵事件”。
- Legacy 模式不创建 PostgreSQL 持久化服务，继续走原有文件/Session 路径。

## 验收

1. Task 0.2 的全部 15 类丰富事件写入真实 PostgreSQL 后按序读取，wire JSON 零丢失。
2. final/error/cancelled 状态正确收敛。
3. 模拟客户端只消费首帧后断开，后台事件源仍完整写入。
4. 既有 ChatManager、TaskTracker、Console 与事件契约回归通过。
