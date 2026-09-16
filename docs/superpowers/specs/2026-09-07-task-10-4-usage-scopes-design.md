# Task 10.4 用量事件与三层统计设计

## 目标

把多用户模型调用用量写入现有 PostgreSQL `usage_records`，提供个人、Agent 匿名聚合、平台全局三层统计，同时保持 Legacy 的 `token_usage.json` 和原页面契约。

## 数据写入

- 模型响应产生 Token 后，从服务端 ContextVar 捕获 `user_id`、主体类型、Agent、会话/Conversation、Run 和自动化计划。
- 写入路径仍为非阻塞队列；Legacy 消费者聚合 JSON，多用户 PostgreSQL 消费者追加不可变 `usage_records`。
- Agent 使用稳定 `agent_database_id()` 映射；Provider 和模型通过治理元数据的 `name + model_key` 精确解析。
- Conversation、Run、自动化标识仅在可解析且数据库存在时写入，否则保持空，不伪造关联。
- 多用户上下文缺少用户、Agent、Provider 或模型映射时拒绝写入并记录脱敏告警，禁止降级写入全局 JSON。

## 查询与权限

- `personal`：当前用户自己的全部用量；管理员也是普通用户时默认仍看自己。
- `agent`：目标 Agent 的聚合。owner/collaborator 看全 Agent 匿名聚合，纯 user 只看本人在该 Agent 的聚合。
- `platform`：仅管理员可看平台全局聚合；普通成员返回 403。
- 所有响应只包含日期、Provider/模型和 Token/调用数，不返回用户 ID、会话标题、消息或逐用户排行。
- Legacy 模式继续使用现有 JSON 汇总，并保持旧 API 参数兼容。

## Agent 统计

- 多用户 Agent 统计从 PostgreSQL 读取当前授权范围的 Token，不再叠加部署级全局 JSON。
- 消息、会话、工具与频道统计继续保持现有页面功能；本任务先消除 Token 串账，后续最终迁移任务再统一所有历史文件数据源。
- 页面明确展示当前范围：个人、Agent 聚合或平台全局。

## 验收

- 两个用户在两个 Agent 下写入不同 Provider/模型用量，验证个人互不可见。
- owner/collaborator 看到共享 Agent 的相同匿名聚合，user 只看到本人份额。
- 管理员平台视图看到总和，但默认个人视图不包含其他用户。
- 单个 headless Chromium 使用三个隔离 BrowserContext 展示三种角色差异。
- 隔离 schema 执行，不修改原服务与原数据；完成后再部署，无新数据库迁移。
