# Task 10.4 用量事件与三层统计验收记录

## 结果

Task 10.4 已完成实现、自动化验证、单 Chromium 三角色验收、历史逐轮 Token 迁移和原环境部署。多用户模式使用现有 PostgreSQL `usage_records` 保存不可变用量事实；Legacy 模式继续使用原 JSON。

## 已验证行为

- 模型调用记录用户、actor、Agent、会话、Run、自动化计划、Provider、模型和输入/输出 Token；外部渠道可推断为 `external` actor。
- 关键归属无法映射时拒绝写入，不回退到共享 Legacy JSON，避免跨用户混写。
- 个人范围只查询当前用户；owner/collaborator 的 Agent 范围返回匿名总量；纯使用者的 Agent 范围仍过滤为本人；平台范围仅管理员可用。
- Agent 统计中的 Token、会话、消息和工具调用遵循同一角色范围，单 Agent 统计不读取平台全局 Token。
- Token 页面保留日期、Provider、模型、趋势和明细，并增加个人、当前 Agent、平台全局三层切换；平台入口仅管理员显示。
- 内置 Token 查询工具在多用户模式固定使用当前主体的个人范围。

## 自动化验证

- 后端相关单元组合：43 passed。
- 真实 PostgreSQL 隔离测试：6 passed。
- 前端 Token/Agent Stats API：6 passed。
- TypeScript `tsc -b --noEmit`：通过。
- 前端生产构建和 Monaco CSS 校验：通过；仅有项目既存的循环分块和 chunk 大小警告。
- Ruff 错误级规则 `E9,F63,F7,F82` 与 `git diff --check`：通过。
- 较宽的 console metadata 集成组合中有 1 个既存环境失败：测试环境没有 active model，创建 Agent 返回 400；其余 46 项通过，该失败与用量范围无关，未将该组合记为全通过。

## 浏览器与数据库证据

单个 headless Chromium 内使用三个隔离 BrowserContext 模拟 owner/admin、collaborator 和 user，以下 6 项全部通过：

1. 三个角色在同一浏览器进程中保持独立登录；
2. 三人的个人统计互不混入；
3. owner/collaborator 获得匿名 Agent 总量，user 只得到本人数据；
4. 平台全局统计仅管理员可读，collaborator 返回 403；
5. Agent 消息统计与角色范围一致；
6. 页面按角色展示对应范围控件，非管理员看不到平台全局入口。

证据目录：`tmp/task104-browser-20260907-225338/`，包含 `acceptance.json` 和三张角色页面截图。隔离 schema `qwenpaw_test_4a9a3c74c52662ead4ad` 已删除；验收前后原 18089 服务均为 PID 18228、HTTP 200。

## 原数据与部署

- 原 PostgreSQL schema 版本为 `0018_automation_authorization`，现有表已满足实现，无新增迁移。
- 初次部署时 `usage_records` 为 0 行。后续页面复核发现 Legacy 会话文件中的 `qwenpaw_turn_usage` 同时具有用户、Agent、会话、Provider 和模型关联，具备可靠迁移条件；原“无需历史迁移”结论已纠正。
- 经用户明确确认后，幂等迁移写入 57 条逐轮事实：`admin-task21` 36 条、`member-task21` 1 条、`task42-user` 20 条。重复预览显示 57 条全部已存在、0 条待插入、0 条缺失关联。
- `task42-user` 在 2026-08-31 至 2026-09-07、默认 Agent 范围内为 17 次调用、247,450 输入 Token、21,533 输出 Token；用户页面显示 `247.4K`、`21.5K` 和 17 次。
- Legacy `token_usage.json` 仍不具备用户和 Agent 归属，文件保持原字节，SHA-256 为 `E9DD0C2355AE6887D1003FCED3D99EB4857335CFF088DD29C85A67C820B32668`。本次迁移来源是会话逐轮元数据，不是该全局汇总文件。
- 18089 服务已从 PID 18228 重启为 PID 23940；HTTP 200。部署后验证管理员平台范围 200、普通用户平台范围 403、普通用户个人范围 200，Token 与 Agent Stats 页面均返回最新前端。

## 用户复核修正

- 会话列表展示当前全部未归档会话；统计页原卡片实际计算所选日期内产生过消息的去重会话，却标为“总会话数”。页面现已改为“活跃会话”，并在提示中明确两个页面口径不同。
- 截图环境的默认 Agent 有 15 条未删除会话，其中 8 条在所选日期范围内产生过消息，因此统计值 8 正确，原文案不准确。
- 历史迁移和文案修正后，18089 服务 PID 为 11376、HTTP 200。页面复验记录为 `tmp/task104-history-backfill-acceptance.json`，截图为 `tmp/task104-history-backfill-browser.png`。

## 后续

阶段 10 已完成并停在确认门。内部实施细目还剩 14 项：11.1–11.6、12.1–12.4、13.1–13.4；用户确认后进入 Task 11.1「部署环境变量不可回读」。
