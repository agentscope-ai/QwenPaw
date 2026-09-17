# Task 5.2 PostgreSQL Chat Events Implementation Plan

**Goal:** 在不改变 SSE wire envelope 的前提下，把多用户 Console Run 的完整事件流写入 PostgreSQL，并保证断线继续和终态一致。

### Task 1：RED 集成契约

- [x] 创建 `tests/integration/test_postgres_chat_events.py`。
- [x] 用 Task 0.2 fixture 验证 Conversation、Run、Message、RunEvent、ToolCall。
- [x] 验证 final/error/cancelled 与断线后台继续。

### Task 2：事件持久化服务

- [x] 新增稳定 ID、SSE 解析和 wire 映射。
- [x] PostgreSQL 单帧事务写入 Event/Message/ToolCall。
- [x] Run 开始与终态收敛。

### Task 3：运行链路接入

- [x] ChatManager 可选注入持久化服务。
- [x] Console 前台和后台任务均通过持久化事件源。
- [x] Legacy 模式保持原路径。

### Task 4：回归和验收

- [x] fixture 零丢失。
- [x] 运行聊天、迁移、TaskTracker 与 Console 回归。
- [x] 生成 Task 5.2 验收报告并停在用户确认门。
