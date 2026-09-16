# Task 10.4 用量事件与三层统计实施计划

## Task 1：固定三层权限契约

- [x] 新增 `tests/isolation/test_usage_scopes.py`。
- [x] 验证个人、Agent、平台三层查询和管理员权限。
- [x] 验证纯使用者只能看到本人 Agent 用量。

## Task 2：接入 PostgreSQL 用量事实

- [x] 新增最小 Usage Repository，覆盖写入、映射和聚合。
- [x] 扩展用量事件的可信运行上下文。
- [x] 多用户写入失败时禁止回退 Legacy 全局 JSON。

## Task 3：收紧 API 与 Agent 统计

- [x] Token API 绑定当前 Actor 和明确 scope。
- [x] Agent 统计使用当前用户有权查看的 PostgreSQL 聚合。
- [x] 内置 Token 查询工具只返回当前主体范围。

## Task 4：前端三层视图

- [x] Token 页面展示个人/Agent/平台范围切换及权限。
- [x] Agent 统计标识匿名聚合或个人范围。
- [x] 保留日期、Provider、模型、趋势和数据表。

## Task 5：验收与部署

- [x] 后端、前端、TypeScript 和构建通过。
- [x] 隔离 PostgreSQL Repository/API 验收通过。
- [x] 单 Chromium 三 BrowserContext 验证角色差异。
- [x] 核验原环境后部署并停在阶段 10 确认门。
