# Task 12.4 ACP 关闭与兼容数据验收

验收日期：2026-09-08  
验收实例：`http://127.0.0.1:18089`  
数据库 Schema：`qwenpaw_task21_acceptance` / `0018_automation_authorization`

## 实施结果

- 侧边栏不再注册 `core.acp`，管理员和普通用户均无 ACP 菜单。
- 前端不再注册 `/acp` 和 `/ACP`，直达旧地址不会加载 ACP 产品页面。
- ACP 配置 GET 路由继续提供历史只读兼容；PUT 写路由不再发布，直接请求返回 405。
- Web 应用的新工作区不再注册 `delegate_external_agent`，工具列表及配置、启停接口也不再公开该工具。
- ACP 源码、历史配置、Harness 读取和会话级 MCP 适配保留，不删除兼容数据。

## 自动化验证

- 后端 ACP、工具治理和兼容回归：57 passed。
- Harness、ACP MCP Driver 针对性兼容回归：19 passed。
- 前端内置路由契约：3 passed。
- TypeScript `tsc -b --noEmit`：通过。
- 前端生产构建与 Monaco CSS 校验：通过；仅有既存循环 chunk、动态/静态混合导入和大包提示。
- Python `compileall`：通过。

OpenAPI 结果：

- `/api/config/acp*` 和 `/api/agents/{agentId}/config/acp*` 仅保留 GET。
- `/api/harnesses`、`/api/harnesses/{provider_id}/mcp` 和 `/api/mcp` 的 GET 仍在。

## 浏览器验收

使用一个 Chrome 进程创建管理员与普通用户两个隔离上下文，共通过 10 项检查：

- 两类账号侧边栏均无 ACP，MCP 入口保留。
- 两类账号直达 `/acp` 均无 ACP 产品界面。
- 两类账号各自在自有 Agent 上读取历史 ACP 配置成功，写入均返回 405。
- 普通用户 Harness/MCP 兼容读取成功。
- 普通用户工具列表不再出现 `delegate_external_agent`。

证据：

- `tmp/task124-browser-acceptance.json`
- `tmp/task124-admin-menu.png`
- `tmp/task124-member-menu.png`
- `tmp/task124-admin-direct-acp.png`
- `tmp/task124-member-direct-acp.png`

## 结论

Task 12.4 验收通过，阶段 12 完成。未执行数据库迁移、数据删除或 Git 提交。下一项为 Task 13.1 全角色逐页验收。
