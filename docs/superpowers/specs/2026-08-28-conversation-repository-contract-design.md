# Conversation Repository 契约设计

## 目标

为会话元数据、消息、Run、丰富事件、工具调用和附件定义一个与存储无关的异步契约，让 Legacy 文件存储与 PostgreSQL 实现可以被同一组行为测试验证；本阶段不切换生产事实来源。

## 设计

新增 `ConversationRepository` 抽象，使用不可变 Pydantic 记录作为输入/输出。契约分为六组：

1. `conversations`：创建、读取、列表、更新状态/标题、软删除。
2. `messages`：按会话稳定序列写入和读取。
3. `runs`：创建、状态收敛、读取。
4. `run_events`：按 `run_id + sequence` 幂等追加和顺序读取。
5. `tool_calls`：按 `run_id + call_id` 幂等写入、更新和读取。
6. `attachments`：保存内容引用元数据，不在 Repository 内存放大文件正文。

Legacy 适配器将记录保存为单个 JSON 文档，使用原子替换；PostgreSQL 适配器使用现有 `0002_agent_conversation` 表，并在一个数据库事务中完成单个操作。两者都不负责用户授权，调用方继续负责 Actor/RLS 门禁。

## 一致性规则

- 所有序号从 1 开始，同一会话/Run 内唯一。
- 重复写入相同主键和相同内容必须幂等；同主键不同内容返回冲突错误。
- 列表结果按稳定序列升序，元数据按更新时间降序。
- Repository 不改变现有 ChatManager、SSE 或前端事件模型。

## 验收

契约测试使用同一组固定 fixture，分别运行 Legacy 和 PostgreSQL 实现，验证创建、读取、重复写入、事件顺序、工具关联、附件引用和软删除结果等价。
