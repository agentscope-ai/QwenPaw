# Task 12.2 剩余领域迁移验收

## 结论

2026-09-08 已完成 MCP、定时任务、收件箱、Token 汇总和旧 PostgreSQL 五个剩余领域的执行与复跑。结合此前已完成的身份、Agent、会话、消息和技能，Task 12.2 的 10 个领域均已处理完毕。

## 执行结果

| 顺序 | 领域 | 源记录 | 最终目标 | 最终复跑 | 处理结论 |
|---|---:|---:|---:|---:|---|
| 6 | MCP | 9 | 9 Driver / 9 Revision | 0 新增、9 不变 | 完成；均保持禁用，无非空凭据 |
| 7 | 定时任务 | 0 | 0 | 空迁移 | 源 `jobs.json` 均无任务 |
| 8 | 收件箱 | 50 | 50 通知 / 50 回执 | 0 新增、50 不变 | 完成；2 条已读状态保持 |
| 9 | Token 汇总 | 9 | 61 条既有逐轮事实 | 0 写入 | 拒绝全局汇总，避免重复计费 |
| 10 | 旧 PostgreSQL | 0 | 0 | 空迁移 | 未配置独立旧库，无数据源可迁 |

Token 的 9 条 `token_usage.json` 记录只有日期、Provider、模型和汇总数，没有用户、Agent、会话归属；目标中已有从会话逐轮元数据迁入的 61 条事实。迁移器逐条报告 `missing_usage_attribution`，没有把全局汇总重复写入。

旧 PostgreSQL 只接受 `QWENPAW_LEGACY_DATABASE_URL` 明确指定的独立来源。当前未配置该变量，报告 `legacy_postgres_not_configured`，没有把当前目标库误当作旧库。

## 数据安全与完整性

- 迁移前备份：`tmp/task122-remaining-backup-20260908-214525`。
- 完整执行结果：`tmp/task122-remaining-migration-result.json`。
- API 验收结果：`tmp/task122-api-verification.json`。
- `inbox_events.json` 与 `token_usage.json` 的迁移前后 SHA-256 相同。
- MCP Driver 当前修订孤儿数为 0；通知私人回执缺失数为 0。
- MCP 源配置均为禁用；空字符串密钥占位被丢弃，没有生成凭据记录或明文输出。

## 自动化验证

- `tests/integration/test_migration_idempotency.py`：13 passed。
- `tests/integration/test_inbox_repository.py` 与 `tests/integration/test_mcp_oauth_postgres.py`：2 passed。
- `python -m compileall -q src/qwenpaw/migration`：通过。
- `git diff --check`（本次迁移文件）：通过。

Windows 的 pytest 进程在销毁 Proactor 事件循环时仍输出项目已有的 access violation 诊断；两次测试均完成全部断言并以通过状态结束。

## 页面验收

验收实例为 `http://127.0.0.1:18089`。

1. 使用管理员登录，选择“默认智能体”，进入“工作区 → MCP”。页面应显示 `tavily_search`，状态为禁用，可编辑。
2. 使用 `task42-user` 登录，选择“我的智能体”，进入 MCP。应显示同名禁用配置，可编辑。
3. 普通用户选择公共“默认智能体”或仅使用权限的共享 Agent，MCP 配置应只读，工具清单和敏感配置不返回；选择无权访问的私有 Agent 时接口返回 403。
4. 分别用管理员和 `task42-user` 打开“收件箱”。管理员应看到 22 条、其中 20 条未读；`task42-user` 应看到 10 条且均未读。两者的事件接收者只能是当前登录用户。
5. 打开“定时任务”，源环境没有用户定时任务，列表为空是预期结果。日志中出现的记忆维护调度是系统运行任务，不来自 `jobs.json` 用户任务迁移。
6. 打开“Token 消耗”，页面继续显示已迁入的逐轮、可归属用量；不会出现由旧全局汇总造成的重复数值。

## 工程约束

迁移按领域保持单一职责；稳定 UUID 和内容哈希复用公共工具；目标存在不同治理数据时拒绝覆盖。实现只覆盖本次真实来源，不为不存在的定时任务或未配置旧库引入推断逻辑。
