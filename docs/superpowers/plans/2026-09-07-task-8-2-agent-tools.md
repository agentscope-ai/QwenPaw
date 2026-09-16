# Task 8.2 Agent 工具配置与运行实施计划

**Goal:** 让 Agent 工具配置满足成员权限与 Secret 隔离，并使 Browser 在多用户环境受平台许可、隔离模式和并发配额约束。

**Architecture:** 保留 Agent 文件中的非敏感工具配置；密码字段写入既有 PostgreSQL Credential Binding，通过异步装载的进程内缓存兼容插件同步读取；Browser 使用平台策略计算有效可用性。

**Tech Stack:** 仓库既有 Python、FastAPI、SQLAlchemy async/PostgreSQL、React/TypeScript、pytest、Vitest、Playwright；不新增依赖。

## 全局约束

- 已确认设计：`docs/superpowers/specs/2026-09-07-task-8-2-agent-tools-design.md`。
- 不执行 git commit、push、分支或 worktree；不删除文件、历史数据或备份。
- 原 18089 服务、原 MCP、工具配置和 Secret 保持不变；使用独立 schema、合成 Agent 与隔离端口验证。
- 先固定失败测试，再做最小实现；任何 Secret 迁移和原环境平台策略切换另行确认。

## Task 1：固定权限、安全 DTO 与配置服务边界

**Files:** 修改 `src/qwenpaw/app/routers/tools.py`；新增局部工具配置服务；修改/新增 `tests/isolation/test_tool_permissions.py`、`e2e/tests/test_tools.py`。

- [x] 记录目标文件与原数据基线。
- [x] 写失败测试：owner/collaborator 可写，user 的 toggle/async/config 均 403，跨 Agent 访问拒绝。
- [x] 定义 `ToolInfo` 权限/策略/凭据状态和 keep/replace/delete DTO；GET 不返回 password 值或 `***`。
- [x] 清单驱动过滤工具名、字段名和非敏感类型，Browser 全局字段不能经 Agent 路由写入。
- [x] 保持列表、逐项启停、异步和热重载响应兼容。

## Task 2：Credential Binding 与插件运行解析

**Files:** 新增 `src/qwenpaw/app/tools/` 服务与运行缓存；修改 `src/qwenpaw/drivers/credentials/postgres_store.py`、`src/qwenpaw/plugins/registry.py`、必要的 Agent 启动/重载接线；新增 `tests/parity/test_tool_credential_bindings.py`。

- [x] 写失败测试：replace/keep/delete、跨 Agent 拒绝、撤销后缓存失效、重启重新装载、数据库失败不回退明文。
- [x] 实现稳定 consumer、逐字段 binding 状态、创建/替换/撤销和只限内部解析。
- [x] Agent 文件仅保存非敏感字段；历史 password 值只进入迁移预览，不由新 API 回读或复制。
- [x] 实现进程内运行缓存与启动/预载/重载异步装载，插件同步 API 合并配置；卸载和撤销清缓存。
- [x] 覆盖补偿失败与安全日志，运行 Credential/MCP 既有回归，确认共享 Store 无退化。

## Task 3：多用户 Browser 平台策略与配额

**Files:** 修改 `src/qwenpaw/config/config.py`、`src/qwenpaw/app/routers/tools.py`、`src/qwenpaw/browser/tool_entrypoint.py`、`src/qwenpaw/browser/execution/` 必要局部模块；新增 Browser 策略/配额测试。

- [x] 写失败测试：多用户默认锁定；允许后强制 guest/incognito/headless/managed；真实 Chrome、profile 和外部 CDP 拒绝。
- [x] 增加平台开关、全局/单用户上限和有限等待配置，保持单用户默认行为。
- [x] 在实际调用主体进入 Browser 执行前取得配额，全部结束与异常路径可靠释放。
- [x] API 返回配置态和有效态；历史 Agent `enabled=true` 在平台禁用时不能注册或调用 Browser。
- [x] 验证空闲回收、会话关闭、服务关闭与并发恢复，不改变 ToolCards/后台命令协议。

## Task 4：Tools 前端完整交互

**Files:** 修改 `console/src/api/modules/tools.ts`、`console/src/pages/Agent/Tools/index.tsx`、`useTools.ts`、样式与 i18n；修改 `useTools.test.ts` 和必要组件测试。

- [x] 密码表单改为状态 + keep/replace/delete，不把 `***` 放入表单或请求。
- [x] user 页面只读；owner/collaborator 保留启停、异步、全开/全关和非敏感配置。
- [x] 多用户 Browser 显示平台锁定、有效模式和原因；移除 Agent 对全局实验模式的写操作，单用户入口保持。
- [x] 防止切 Agent/关弹窗后的迟到配置响应污染当前表单。
- [x] 运行 Vitest、类型检查和构建。

## Task 5：整合、隔离浏览器验收与原数据保真

**Files:** 验收文档、隔离环境脚本和必要 fixture；不修改原业务数据。

- [x] 运行后端权限/Credential/Browser/后台任务/ToolCards 目标回归和 Legacy 合同。
- [x] 独立 PostgreSQL 与隔离服务，用 owner/collaborator/user 验证启停、异步、非敏感配置、Secret 动作和跨用户拒绝。
- [x] 验证 Browser 默认锁定；单元契约覆盖许可后的访客模式、并发拒绝与释放恢复，原环境保持关闭。
- [x] 运行原 Tools 页面关键浏览器流程、前端测试/构建，并检查 API/日志/文件无合成 Secret。
- [x] 复核原文件/表/服务哈希，形成验收报告和前端验收步骤；原环境 Secret 迁移或策略切换保持单独确认门。

## 计划自检

任务按 API 边界、凭据运行链、Browser 资源策略、前端交互和整体验收拆分，依赖顺序明确。没有引入新的工具配置数据库表或插件 API 破坏性升级；所有原数据写入均被隔离在后续确认门之外。
