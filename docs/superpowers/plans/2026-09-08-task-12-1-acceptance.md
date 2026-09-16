# Task 12.1 只读扫描与迁移预览验收记录

## 结论

Task 12.1 已完成技术验收，等待用户确认。管理员可在“设置 → 迁移预览”查看十个遗留数据领域的只读扫描结果；本阶段没有迁移写入接口，也没有修改目标业务数据。

## 实现范围

- 扫描 `auth.json`、Agent 根清单和各 workspace `agent.json`、会话、Session 消息、技能、MCP、Cron、Inbox、Token 用量，以及显式配置的旧 PostgreSQL。
- 每个领域输出候选数量、SHA-256 源哈希、目标映射、冲突与拒绝项；扫描前后对已知迁移来源重新计算完整性哈希。
- 旧 PostgreSQL 使用独立 `QWENPAW_LEGACY_DATABASE_URL` 配置，在 5 秒超时的只读事务中探测表和估算记录数；响应不包含 DSN、用户名、密码或驱动异常。
- Secret 只输出逻辑引用和 `fernet-v1`、`plaintext`、`unknown` 版本状态；空值不生成引用，报告模型没有 Secret 原值字段。
- 迁移预览 API 和菜单仅开放给平台管理员。普通用户直接访问页面显示 403，后端权限测试返回 403。

## 验证证据

- 后端迁移预览及既有迁移组合：`4 passed, 3 skipped`；新增预览测试单独复验 `4 passed`。
- 前端迁移预览、系统状态、路由权限与 OS 路由组合：`16 passed`。
- Python `compileall`、TypeScript 编译、Vite 生产构建和 Monaco CSS 校验通过。
- 真实管理员页面显示 10 个领域、51 条候选记录、0 冲突、0 拒绝项、0 个非空 Secret 引用，并显示“源数据未改变”。旧 PostgreSQL 未配置时明确显示 `unavailable`。
- 真实普通用户 `task42-user` 的设置菜单没有迁移预览入口；直接打开 `/migration-preview` 显示 403“无权访问”。
- 管理员截图：`task-12-1-migration-preview-admin.png`。

## 数据影响

- 未执行 Task 12.2 迁移器，未写入迁移目标表。
- 未配置旧 PostgreSQL 独立来源，因此该领域只报告 `unavailable`，不会误把当前目标数据库当作旧来源扫描。
- 本地多用户验收服务已恢复到 `qwenpaw_test_migrations / qwenpaw_task21_acceptance`，18089 当前 PID `70540`。

## 下一确认门

用户确认 Task 12.1 后，下一项是 Task 12.2“幂等分领域迁移器”。该任务会写入 PostgreSQL 目标数据，开始前必须再次取得数据库批量写入的危险操作授权；随后每迁移一个领域都停止并展示报告。
