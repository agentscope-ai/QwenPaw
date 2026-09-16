# Task 10.3 私人通知和审批验收记录

## 结果

Task 10.3 已完成实现、自动化验证、单浏览器双用户验收和原环境部署。现有 PostgreSQL schema 已包含通知、回执和审批表，原表为空，因此无需结构迁移或历史数据迁移。

## 已验证行为

- 多用户通知写入 `notifications`，同时为指定 recipient 写入 `notification_receipts`；个人已读和删除状态保存在回执中。
- 收件箱列表、筛选、未读数、全部已读和批量删除均由服务端绑定当前 Actor，不接受客户端指定其他用户。
- 批量删除在一个 API 请求和一个事务内完成，只软删除当前用户回执，不删除通知事实、Trace、Run 或审计依据。
- Trace 读取要求当前用户持有引用对应 Run 的未删除通知；其他用户即使知道 Run ID 也返回 404。
- 审批列表和决定操作绑定 `approval_user_id`；审批人是任务实际使用者，管理员不能代批普通用户的副作用。
- 无明确 recipient 的平台治理结果只进入治理日志，不广播到个人收件箱。
- `QWENPAW_MULTI_USER_ENABLED=false` 时继续使用原 Legacy JSON 行为。

## 自动化验证

- 后端最终相关组合：44 passed。
- 前端收件箱与审批相关组合：24 passed。
- 追加边界复核：31 passed、1 skipped；skip 是未提供独立 PostgreSQL 测试 URL 时的预期行为。
- TypeScript `tsc --noEmit`：通过。
- 前端生产构建：通过；仅保留既有循环分块和 chunk 大小警告。
- Python compileall：通过。
- Ruff 错误级规则 `E9,F63,F7,F82`：通过。
- 旧的 `test_stream_and_approval_isolation.py` 全文件仍有 2 个与本任务无关的陈旧 fixture 失败；本任务审批隔离目标用例通过，未将该全文件记为通过。

## 浏览器与数据库证据

单个 headless Chromium 内使用两个隔离 BrowserContext 模拟管理员 A 与普通用户 B，10 项检查全部通过：

1. 两个用户在一个浏览器进程中隔离登录；
2. 两用户看到不同的私人通知和未读数；
3. 页面不显示对方通知；
4. Trace 访问绑定当前用户通知引用；
5. 全部已读只影响本人；
6. 批量删除只影响本人且不删除 Trace；
7. 页面批量删除调用单一私人操作；
8. 审批列表按 `approval_user_id` 隔离；
9. 管理员代批 B 的任务返回 404，副作用保持待审批；
10. 数据库保留 3 条通知事实，2 条回执软删除，B 的 1 条通知仍可见。

证据目录：`tmp/task103-browser-20260907-213627/`。其中包含 `acceptance.json` 和四张双用户通知/审批页面截图。隔离 schema `qwenpaw_test_1e50ab97de6b27af516e` 已删除，验收前后原 18089 服务均为 PID 61504、HTTP 200。

## 原数据与部署

- 原 PostgreSQL schema 版本保持 `0018_automation_authorization`，现有表足以承载本任务，无新增迁移。
- 原环境 `notifications`、`notification_receipts`、`approval_requests` 均为 0 行，无历史数据需要归属。
- Legacy `inbox_events.json` 中 22 条旧事件均缺少 recipient，无法安全推断用户，保持原文件不变。
- 18089 服务已从 PID 61504 重启为 PID 18228，加载新后端和最新前端构建；HTTP 200，收件箱 API 与“消息/审批”页签只读冒烟检查通过，证据为 `tmp/task103-deployed-smoke.json`。
