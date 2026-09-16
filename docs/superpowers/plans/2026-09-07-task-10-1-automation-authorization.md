# Task 10.1 自动化计划、所有者和长期授权实施计划

> **执行要求：** 按 TDD 顺序逐项执行；每项先看到目标测试因缺少行为而失败，再写最小实现。当前会话使用 executing-plans，不创建工作树、不提交 Git。

**目标：** 让多用户自动化由创建者持有并自行批准已有权限范围，运行时使用受限自动化主体，不再通过 Tool Guard OFF 绕过治理。

**架构：** 多用户模式以 PostgreSQL 的 `automation_schedules`、`automation_grants`、`automation_executions` 为唯一事实源，`AutomationAuthorizationService` 集中处理对象权限、摘要和执行前校验，CronManager 只维护 APScheduler 投影。单用户模式继续使用 JsonJobRepository。

**技术栈：** Python 3.11、FastAPI、Pydantic、SQLAlchemy async、PostgreSQL、Alembic、APScheduler、React、TypeScript、Vitest、Playwright。

## 全局约束

- 创建者就是 automation owner；身份字段只能取 ActorContext。
- owner 只批准自己当前已有权限，批准不扩大权限。
- 影响范围的配置变化撤销旧授权；每次执行重新校验实时权限。
- Agent owner/管理员只能查看和暂停他人任务，不能修改、批准、恢复或代运行。
- 自动化不使用 Tool Guard OFF；范围外调用直接阻断。
- 单用户模式和原 Cron/once/repeat/timezone/template/stream/final/silent 行为保持兼容。
- 原数据库迁移和 18089 重启仅在隔离验收通过并再次获得确认后执行。

---

### Task 1：领域模型、PostgreSQL Repository 与 0018 约束

**文件：**
- Modify: `src/qwenpaw/app/crons/models.py`
- Create: `src/qwenpaw/app/crons/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/crons/repo/__init__.py`
- Create: `migrations/versions/0018_automation_authorization.py`
- Modify: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_automation_repository.py`

**接口：**
- `PostgresJobRepository(agent_key: str, schema: str, session_factory=database_session)` 实现 `BaseJobRepository`。
- Repository 额外提供 `create_for_actor`、`replace_for_owner`、`list_for_actor`、`authorize`、`revoke_authorization`、`record_execution`。
- `AutomationStatus`、`AuthorizationSummary` 和 owner/version/digest 字段进入 API view，不接受客户端身份覆盖。

- [ ] 写迁移链、状态约束、owner 查询与原子授权的失败测试。
- [ ] 运行目标测试，确认因 0018 和 Repository 缺失而失败。
- [ ] 实现规范 JSON 映射、事务写入、执行历史和索引/约束。
- [ ] 运行 Repository、迁移 upgrade/repeat/downgrade 测试至通过。

### Task 2：创建者授权服务和权限矩阵

**文件：**
- Create: `src/qwenpaw/automation/__init__.py`
- Create: `src/qwenpaw/automation/grants.py`
- Create: `tests/isolation/test_automation_grants.py`

**接口：**
- `AutomationAuthorizationService.create(actor, agent_key, spec)` 强制 owner/target 身份。
- `preview/authorize/revoke/require_view/require_modify/require_pause/validate_execution` 返回稳定结果或原因码。
- `authorization_digest` 使用规范化的 Agent、schedule、task、runtime、dispatch 和服务端能力范围。

- [ ] 写 owner 自批、他人拒绝、Agent owner 只暂停、伪造身份、修改失效和权限撤销测试。
- [ ] 运行测试并确认缺少服务行为导致失败。
- [ ] 实现最小授权服务和能力/资源范围规范化。
- [ ] 运行隔离测试至通过并删除重复权限判断。

### Task 3：CronManager 投影和受限执行主体

**文件：**
- Modify: `src/qwenpaw/app/crons/manager.py`
- Modify: `src/qwenpaw/app/crons/executor.py`
- Modify: `src/qwenpaw/app/workspace/workspace.py`
- Modify: `src/qwenpaw/hooks/request_setup/contextvars_hook.py`
- Modify: `src/qwenpaw/governance/tool_adapter.py`
- Modify: `tests/unit/app/crons/test_manager.py`
- Modify: `tests/unit/app/crons/test_executor.py`
- Create: `tests/isolation/test_automation_runtime.py`

**接口：**
- 多用户 workspace 注入 PostgresJobRepository 和 AutomationAuthorizationService。
- `CronExecutor.execute(job, authorization)` 写入可信 `actor_type=automation` 上下文。
- 工具适配器验证 schedule/version/digest/能力范围，禁止自动化进入交互 ASK 或 OFF。

- [ ] 写 active-only 调度、执行前撤权、范围外工具阻断和请求上下文不可覆盖测试。
- [ ] 运行测试，确认现有 OFF 路径和无校验调度失败。
- [ ] 实现执行前校验、自动暂停、受限上下文和执行记录。
- [ ] 运行 CronManager/Executor 既有回归及新增运行时测试。

### Task 4：对象级 API 与兼容 DTO

**文件：**
- Modify: `src/qwenpaw/app/crons/api.py`
- Modify: `src/qwenpaw/app/crons/models.py`
- Create: `tests/isolation/test_automation_api.py`
- Modify: `tests/integration/test_cron.py`
- Modify: `tests/integration/test_cron_execution.py`

**接口：**
- 保留现有 jobs CRUD/state/history/run/pause/resume。
- 新增 `GET authorization`、`POST authorize`、`POST revoke` 和 `scope=mine|agent`。
- 创建/修改只接受任务内容；owner、状态、版本、摘要由服务端返回。

- [ ] 写四身份 CRUD、查看、暂停、批准、运行以及 404/403/409 映射测试。
- [ ] 运行测试确认旧路由缺少对象级权限。
- [ ] 注入 ActorContext 和授权服务，保持旧 payload 可解析但忽略 tool_safety 的 OFF 语义。
- [ ] 运行 API 与原 Cron 集成测试至通过。

### Task 5：前端任务 owner 与授权确认

**文件：**
- Modify: `console/src/api/types/cronjob.ts`
- Modify: `console/src/api/modules/cronjob.ts`
- Modify: `console/src/pages/Control/CronJobs/useCronJobs.ts`
- Modify: `console/src/pages/Control/CronJobs/index.tsx`
- Modify: `console/src/pages/Control/CronJobs/components/JobDrawer.tsx`
- Modify: `console/src/pages/Control/CronJobs/components/constants.ts`
- Modify: `console/src/pages/Control/CronJobs/components/columns.tsx`
- Modify: `console/src/pages/Control/CronJobs/useCronJobs.test.ts`
- Create: `console/src/pages/Control/CronJobs/authorization.test.tsx`

**接口：**
- API 类型返回 owner、status、config_version 和 authorization summary。
- 保存影响范围的任务后展示服务端摘要并调用 authorize。
- 默认“我的任务”；Agent owner/管理员可查看 Agent 全部并只能暂停他人任务。

- [ ] 写隐藏工具安全开关、owner 授权确认、他人只读/暂停和变更后重新授权测试。
- [ ] 运行 Vitest 确认当前页面暴露 OFF 开关且无授权状态。
- [ ] 实现最小 API 与页面交互，保留所有原调度表单能力。
- [ ] 运行 CronJobs Vitest、TypeScript 和生产构建。

### Task 6：隔离数据库和真实浏览器验收

**文件：**
- Create: `docs/superpowers/plans/2026-09-07-task-10-1-acceptance.md`
- Modify: `.superpowers/sdd/2026-09-07-task-10-1-automation-authorization/progress.md`
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`

- [ ] 运行目标 Ruff、pytest、Vitest、TypeScript 和构建。
- [ ] 在隔离 PostgreSQL schema 完成 0018 upgrade/repeat/downgrade 和真实 Repository 验证。
- [ ] 单个 headless Chrome 使用管理员、Agent owner、collaborator、user 四个独立 context 验收自批、越权、暂停、失效和原表单能力。
- [ ] 删除隔离 schema，证明 18089 和原 schema 未变化。
- [ ] 记录迁移影响、备份/回滚方案并请求原数据库迁移确认。
