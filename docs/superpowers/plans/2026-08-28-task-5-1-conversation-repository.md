# Task 5.1 Conversation Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 定义并实现 Legacy 与 PostgreSQL 可互换的 Conversation Repository 契约，不切换当前生产事实来源。

**Architecture:** 新增独立领域记录和异步抽象；JSON 适配器用于 Legacy；PostgreSQL 适配器复用现有 `0002_agent_conversation` 表。ChatManager 和聊天路由继续使用现有路径，直到后续 Task 5.2 明确切换。

**Tech Stack:** Python 3.11、Pydantic、SQLAlchemy AsyncSession、PostgreSQL、pytest、Alembic。

## Global Constraints

- 不修改 AgentScope Runtime、工具卡片或 SSE wire envelope。
- 不切换 18089 的生产事实来源。
- 不执行 Git 提交、分支切换或数据库删除。
- 所有新测试必须先 RED 再 GREEN。

### Task 1：领域记录与抽象契约

**Files:**
- Create: `src/qwenpaw/app/chats/repo/conversation.py`
- Create: `tests/parity/test_conversation_repository_contract.py`

- [x] 定义 `ConversationRecord`、`MessageRecord`、`RunRecord`、`RunEventRecord`、`ToolCallRecord`、`AttachmentRecord`。
- [x] 定义 `ConversationRepository` 异步方法：`create_conversation`、`get_conversation`、`list_conversations`、`save_message`、`list_messages`、`create_run`、`finish_run`、`append_event`、`list_events`、`upsert_tool_call`、`add_attachment`。
- [x] 先运行契约测试，确认两个适配器尚未实现而失败。

### Task 2：Legacy JSON 适配器

**Files:**
- Create: `src/qwenpaw/app/chats/repo/json_conversation_repo.py`
- Modify: `src/qwenpaw/app/chats/repo/__init__.py`

- [x] 使用单文件 JSON 和原子替换保存六类记录。
- [x] 对事件和消息按唯一键幂等处理；冲突抛出稳定异常。
- [x] 运行契约测试，确认 Legacy 实现通过。

### Task 3：PostgreSQL 适配器

**Files:**
- Create: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/chats/repo/__init__.py`

- [x] 使用注入的异步 session factory 和 schema 白名单。
- [x] 映射现有 conversations/messages/runs/run_events/tool_calls/attachments 表。
- [x] 保持 UUID、JSON、时间和状态字段的稳定转换。
- [x] 在真实 PostgreSQL schema 中运行同一契约测试。

### Task 4：回归与报告

**Files:**
- Create: `docs/project-audit/41-任务5.1-Conversation-Repository验收报告.md`
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`

- [x] 运行契约、既有聊天 Repository、迁移和后端相关回归。
- [x] 运行 Python 编译检查和 `git diff --check`。
- [x] 报告明确两种实现等价结果和“未切生产源”边界。
- [x] 停在 Task 5.1 用户验收门，不自动进入 Task 5.2。
