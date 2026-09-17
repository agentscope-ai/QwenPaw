# Task 12.3 逐领域读写切换与回退验收

## 结论

2026-09-08 已将多用户运行时的 9 个可迁移领域通过显式切换门固定到 PostgreSQL：身份、Agent、会话、消息、技能、MCP、定时任务、收件箱和 Token。当前 18089 服务使用 Schema `0018_automation_authorization`，系统状态接口返回 `active_repository=postgres`、`migration_lock_state=locked`。

旧文件和迁移备份均保留。本任务没有删除 Legacy 数据，也没有执行反向迁移。

## 切换门

每个领域分别声明三种状态：

1. `QWENPAW_CUTOVER_VALIDATED_DOMAINS`：Task 12.2 的迁移结果已核验。
2. `QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS`：Legacy 不再作为该领域的权威写入目标。
3. `QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS`：允许 PostgreSQL 新写入。

多用户服务启动时要求 9 个领域同时满足上述条件，并再次只读检查 Alembic head。声明缺失、顺序错误、未知领域或 Schema 未就绪都会阻止启动，不会隐式退回文件存储。

当某领域已经开放 PostgreSQL 新写入后，Legacy 模式回退必须额外声明 `QWENPAW_CUTOVER_REVERSE_MIGRATED_DOMAINS`；没有完成显式反向迁移时，仓库选择器返回 `rollback_requires_reverse_migration`。

## 会话与消息边界

- 会话所有权、成员、共享权限和状态以 PostgreSQL 为事实源。
- 聊天历史接口已从 PostgreSQL `messages` 表重建前端消息，兼容迁移的 `legacy_snapshot` 和新丰富消息类型。
- 实际浏览器读取聊天详情后，新增日志中的 Legacy `Get session state dict` 次数为 0。
- `chats.json` 和会话文件仍保留运行时路由、第三方 Harness 恢复及 AgentScope 上下文投影；它们不再作为多用户权限或已切换消息历史的事实源。Task 13.2 会在完整回归后清理可删除的兼容写入口。

## 自动化验证

- 领域门、启动校验、状态接口、消息投影和等价性组合：29 passed。
- 持久化、MCP、Cron、Inbox、Token 相关回归：104 passed。
- 身份相关回归：5 passed，3 项依赖外部 fixture 的用例按原条件 skipped。
- 聊天相关组合：133 passed，8 skipped；另 2 项旧用例因个人资料库数据库依赖未隔离而失败，堆栈发生在本次历史读取路径之前，未作为通过项。
- 前端状态页：3 passed。
- TypeScript 和生产构建通过；Monaco CSS 校验通过。构建仍有既有循环 chunk 和大 chunk 警告。
- Python `compileall` 通过。

## 真实环境数据与页面验收

PostgreSQL 当前保留 59 个会话、376 条消息、57 个 Run、64,180 条 Run Event，事件类型 11 种。

单个无头 Chromium 使用管理员和 `task42-user` 两个隔离上下文完成 6 项检查：

1. 两个用户均登录成功，不启动多个桌面浏览器。
2. 管理员状态 API 显示 9 个领域读写均为 PostgreSQL。
3. 管理员“系统状态”页面显示 9 张领域卡和 `0018` Schema。
4. 普通用户直接访问状态页面显示 403，直接调用状态 API 也返回 403。
5. 普通用户仍能读取 15 个会话；抽样历史由 PostgreSQL 返回 29 条消息。
6. 普通用户聊天页面正常加载。

证据：

- `tmp/task123-browser-acceptance.json`
- `tmp/task123-system-status.png`
- `tests/parity/test_cutover_equivalence.py`

## 工程原则

切换策略集中在单一仓库选择模块，领域使用同一顺序校验，避免各业务模块重复实现门禁。选择器每次只返回一个仓库；读切换和写切换分开判定，未满足条件时失败关闭。实现没有引入长期双写协调器，也没有为当前不存在的自动回退增加复杂状态机。
