# Task 10.1 自动化计划、所有者和长期授权设计

## 1. 目标与范围

Task 10.1 把多用户模式下仍保存在 Agent `jobs.json`、以目标用户身份运行并可进入 Tool Guard OFF 的 Cron，收口为有明确创建者、任务所有者、授权快照和运行审计的自动化。

本任务保留 Cron、单次执行、按日重复、时区、模板、stream/final、silent、手动运行、暂停、恢复和历史记录。本任务处理自动化计划及长期授权；Heartbeat 专用主体和目标解析属于 Task 10.2，私人通知和审批页面属于 Task 10.3。

## 2. 已确认的产品规则

- 创建自动化的登录用户就是 `created_by_user_id` 和 `automation_owner_user_id`，客户端不能提交或覆盖这两个身份。
- 自动化 owner 审批自己的任务，无需等待 Agent owner 在线。
- 用户只能批准自己当前已有的 Agent、工具、资源和投递目标权限，自动化不能扩大创建者权限。
- 经批准的固定范围内允许无人值守运行，不在每次执行时等待交互审批。
- 任务内容、Agent、工具能力、资源范围或投递目标发生变化时，旧授权失效，任务进入 `pending_authorization`。
- 创建者账号停用、失去 Agent 使用权或底层资源权限被撤销时，执行前检查失败并自动暂停。
- Agent owner 可以查看和暂停该 Agent 下的自动化，但不能修改任务内容、恢复任务或替任务 owner 扩大授权。
- 管理员可以治理查看和紧急暂停，不能静默替用户生成更宽的长期授权。

## 3. 架构选型

多用户模式复用 0003 已有的 `automation_schedules`、`automation_grants` 和 `automation_executions`：PostgreSQL 是计划、授权及执行记录的唯一事实源，APScheduler 是可重建的运行投影。单用户 legacy 模式继续使用 `jobs.json`，保持现有部署兼容。

不采用 JSON 计划加 PostgreSQL 授权的双事实源，因为计划更新与授权撤销无法原子提交。不采用每次执行交互审批，因为计划任务可能在无人在线时运行。

新增边界：

- `PostgresAutomationRepository`：计划、版本、grant 和 execution 的事务读写。
- `AutomationAuthorizationService`：身份、Agent 访问、授权摘要、配置指纹、管理权限和执行前检查。
- `CronManager`：只负责调度、状态和执行协调，不自行推导用户权限。
- 工具治理适配器：识别可信 `automation_authorization`，只允许授权快照内的调用；范围外调用直接拒绝，不创建等待中的交互审批。

## 4. 数据模型

`automation_schedules` 继续保存既有列，并规范以下语义：

- `agent_id`：稳定 `agent_database_id(agent_key)`；
- `created_by_user_id`、`automation_owner_user_id`：创建时均取 ActorContext；
- `type`：`cron` 或 `once`；
- `schedule`：完整 ScheduleSpec JSON；
- `task`：任务类型、文本或 Agent request 以及 runtime；
- `dispatch`：投递模式和目标；
- `status`：`pending_authorization`、`active`、`paused`、`authorization_revoked`、`failed`；
- `config_version`：每次影响授权范围的修改递增。

`automation_grants` 每条记录绑定 schedule、授权人、能力、资源范围、目标范围、有效期和撤销时间。本任务使用稳定能力：

- `automation.execute`：允许执行该版本任务；
- `tool:<canonical_tool_name>`：允许指定工具及其资源范围；
- `dispatch:<channel>`：允许投递到固定用户、会话和频道。

grant 的 `resource_scope` 和 `target_scope` 保存规范化 JSON。每次批准时撤销旧版本 grant，并写入当前 `config_version`、配置 SHA-256 和批准时 Agent 角色。授权指纹由影响执行的 `agent_id + schedule + task + dispatch` 规范 JSON 计算；展示字段和运行状态不进入指纹。

`automation_executions` 保存 scheduled/manual 触发、开始/结束状态、投递状态和清理后的错误摘要。0018 增量迁移只增加约束、索引和缺失的版本/指纹表达字段；不删除已有表。

## 5. 权限矩阵

| 操作 | 任务 owner | Agent owner | 平台管理员 | 其他可使用者 |
|---|---:|---:|---:|---:|
| 创建自己的任务 | 是 | 是 | 是 | 是 |
| 查看自己的任务 | 是 | 是 | 是 | 是 |
| 查看该 Agent 全部任务 | 自己的 | 是 | 是 | 否 |
| 修改、删除、批准、恢复 | 是 | 否 | 否 | 否 |
| 暂停 | 是 | 是 | 是 | 否 |
| 手动运行 | 是且授权有效 | 否 | 否 | 否 |

创建任务要求用户当前对 Agent 至少具有 `user` 使用权。`collaborator` 和普通 `user` 均能创建自己的任务；是否可调用具体工具由其自身能力和资源权限决定。

dispatch target 在多用户模式固定为创建者本人。用户可以选择自己的频道和会话，但不能把任务伪装成其他用户执行或向其他用户私人会话投递。跨用户/外部目标必须在授权摘要中显式表示，并且只有创建者当前本来就有该投递能力时才能批准。

## 6. 创建、修改与批准流程

1. API 从认证状态取得 ActorContext，从可信 Agent header/state 取得 `agent_key`。
2. 服务校验用户当前可使用该 Agent，并覆盖任务中的用户身份字段。
3. 服务规范化任务和投递目标，分析声明的能力与范围，计算配置指纹。
4. 创建任务时写入 `pending_authorization`；纯文本且只向本人现有会话投递的任务也走同一确认，保持规则一致。
5. `POST /api/cron/jobs/{id}/authorize` 返回并确认服务端生成的摘要；服务再次验证当前权限，写 grant 并将状态改为 `active`。
6. 修改 name、enabled 等不影响范围的字段时保留授权；修改 schedule、task、runtime、dispatch 或 Agent 时递增版本、撤销旧 grant并回到 `pending_authorization`。

批准接口不接受任意能力列表，只接受客户端回传的 `config_version` 和 `authorization_digest`，防止前端删减服务端识别出的风险范围。

## 7. 运行时授权

APScheduler 只注册 `active` 且授权有效的任务。手动运行和定时触发使用同一执行前检查：

1. schedule 仍 active，配置版本和授权摘要一致；
2. automation owner 账号 active；
3. owner 仍拥有目标 Agent 使用权；
4. 当前声明的工具、资源和投递范围仍在 owner 的实时权限内；
5. grants 未撤销且未过期。

通过后构造 `ActorContext(actor_type=AUTOMATION, user_id=automation_owner_user_id)`，并在可信 request_context 中附加只读的 schedule ID、版本、摘要和授权范围。执行不再设置 `approval_level=OFF`。

工具治理层遇到自动化主体时：授权范围内继续执行既有安全策略；需要交互确认或超出长期授权的调用直接拒绝，写入执行错误并暂停任务。任务不能通过 prompt、请求体或工具参数覆盖 owner、Agent、授权摘要和投递目标。

## 8. API 与页面

既有 `/api/cron` 路由保留，并增加：

```text
GET  /api/cron/jobs?scope=mine|agent
GET  /api/cron/jobs/{id}/authorization
POST /api/cron/jobs/{id}/authorize
POST /api/cron/jobs/{id}/revoke
```

创建、列表、详情、更新、删除、暂停、恢复、运行和历史接口全部接收可信 ActorContext 并执行对象级权限检查。未获查看权统一返回 404，明确管理冲突返回 403/409。

定时任务页面默认显示“我的任务”，Agent owner 和管理员可切换“Agent 全部任务”。抽屉显示任务所有者、状态和授权摘要；保存影响范围的变更后打开确认面板。普通用户不再看到可关闭的“工具安全”开关；页面固定显示“按任务授权范围执行”。Agent owner/管理员查看他人任务时只有暂停操作。

## 9. 兼容与迁移

- 单用户模式继续由 `JsonJobRepository` 工作，并保留当前 CLI 行为。
- 多用户模式切换为 PostgreSQL Repository；不再同时写 `jobs.json`。
- 原环境 6 个 `jobs.json` 的任务总数为 0，因此本次没有存量任务导入。若其他部署检测到旧任务，启动时只生成迁移预览并保持禁用，不自动指定 owner 或批准权限。
- 对历史 API payload 中的 `tool_safety` 只做兼容读取，不再据此生成 OFF；响应中以授权状态替代该开关。

## 10. 失败处理与验收

数据库写入和 APScheduler 更新失败时，以数据库事务为准：未成功持久化的任务不进入调度器；持久化成功但投影失败时将任务标为 `failed` 并在重建时恢复。授权校验失败使用稳定原因码，不暴露其他用户身份或任务内容。

自动化测试覆盖任务 owner 自批、他人无法批准、Agent owner 只能查看/暂停、身份字段不可伪造、配置变化撤销授权、权限撤销自动暂停、工具超范围阻断、OFF 不再出现，以及 Cron/once/repeat/timezone/template/stream/final/silent 回归。

浏览器验收使用管理员、Agent owner、collaborator 和普通 user 独立上下文，演示各自创建并批准自己的任务、他人不可修改、Agent owner 可暂停、修改目标后重新授权。隔离数据库验收完成后，原数据库 0018 迁移和服务重启继续使用单独危险操作确认门。
